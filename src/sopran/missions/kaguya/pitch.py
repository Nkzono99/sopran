from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Literal, cast

import numpy as np

from sopran.core.data import SopranArray
from sopran.core.errors import FrameTransformError
from sopran.core.schema import VariableSchema
from sopran.core.time import TimeRange
from sopran.frames import FrameContext, normalize_frame
from sopran.missions.kaguya.pace import PaceCalibration, PaceData, PaceRecord

PitchBins = Literal["native"] | int | Any


@dataclass(frozen=True)
class PitchAngleSpectrumOptions:
    value: str = "counts"
    pitch_bins: PitchBins = "native"
    look_frame: str = "SELENE_M_SPACECRAFT"
    magnetic_frame: str | None = None
    min_look_bins: int = 1


def build_pitch_angle_spectrum(
    *,
    pace: PaceData | None,
    time: TimeRange,
    calibration: PaceCalibration | None,
    magnetic_field: Any,
    files: tuple[Any, ...] = (),
    options: PitchAngleSpectrumOptions | None = None,
    frame_context: FrameContext | None = None,
) -> SopranArray:
    options = options or PitchAngleSpectrumOptions()
    if options.value not in {"counts", "energy_flux"}:
        raise ValueError("value must be 'counts' or 'energy_flux'")
    if options.min_look_bins <= 0:
        raise ValueError("min_look_bins must be positive")
    if pace is None:
        return _empty_pitch_spectrum(time, files, options)
    records = _selected_records(pace, time)
    if not records:
        return _empty_pitch_spectrum(time, files, options)
    if not _has_angle_calibration(calibration, pace.sensor):
        raise ValueError(
            "pitch_angle_spectrum requires PACE angle calibration. "
            "Load it with kg.esa1.load_calibration() and pass calibration=..."
        )
    if options.value == "energy_flux" and not _has_info_calibration(calibration, pace.sensor):
        raise ValueError(
            "KAGUYA ESA1 energy_flux requires PACE INFO calibration tables "
            "for pitch_angle_spectrum."
        )

    edges = _pitch_edges(options.pitch_bins, records)
    centers = (edges[:-1] + edges[1:]) * 0.5
    times_unix = np.asarray([float(header["time"]) for _record, header in records], dtype=float)
    magnetic = _magnetic_vectors_at(
        magnetic_field,
        times_unix,
        look_frame=options.look_frame,
        magnetic_frame=options.magnetic_frame,
        frame_context=frame_context,
    )

    rows = []
    energy_rows = []
    used_times = []
    for row_index, (record, header) in enumerate(records):
        try:
            angular = _record_angular_data(
                record,
                header,
                pace.sensor,
                calibration,
                value=options.value,
            )
        except ValueError:
            continue
        pitch = pitch_angles_deg(angular.theta, angular.phi, magnetic[row_index])
        spectrum = _bin_energy_pitch(
            values=angular.values,
            pitch_deg=pitch,
            detector_bins=angular.detector_bins,
            weights=angular.weights,
            edges=edges,
            value=options.value,
            min_look_bins=options.min_look_bins,
        )
        rows.append(spectrum)
        energy_rows.append(_energy_row(angular.energy))
        used_times.append(_datetime64_from_unix(float(header["time"])))

    if not rows:
        return _empty_pitch_spectrum(time, files, options, edges=edges)

    return _pitch_spectrum_array(
        values=np.stack(rows),
        time_values=np.asarray(used_times, dtype="datetime64[ns]"),
        energy_values=np.stack(energy_rows),
        pitch_centers=centers,
        pitch_edges=edges,
        time=time,
        files=files,
        options=options,
    )


def pitch_angles_deg(theta_deg: Any, phi_deg: Any, magnetic_field: Any) -> np.ndarray:
    bvec = np.asarray(magnetic_field, dtype=float)
    bnorm = float(np.linalg.norm(bvec))
    if not np.isfinite(bnorm) or bnorm == 0.0:
        raise ValueError("magnetic_field must be a finite non-zero vector")
    theta_array = np.asarray(theta_deg, dtype=float)
    phi_array = np.asarray(phi_deg, dtype=float)
    native = _native_module()
    if native is not None and theta_array.ndim == 2 and phi_array.ndim == 2:
        try:
            return cast(np.ndarray, native.pitch_angles_deg(theta_array, phi_array, bvec))
        except AttributeError:
            pass
    theta = np.deg2rad(theta_array)
    phi = np.deg2rad(phi_array)
    vx = np.cos(phi) * np.cos(theta)
    vy = np.sin(phi) * np.cos(theta)
    vz = np.sin(theta)
    dot = (vx * bvec[0] + vy * bvec[1] + vz * bvec[2]) / bnorm
    return cast(np.ndarray, np.rad2deg(np.arccos(np.clip(dot, -1.0, 1.0))))


@dataclass(frozen=True)
class _AngularRecord:
    values: np.ndarray
    energy: np.ndarray
    theta: np.ndarray
    phi: np.ndarray
    detector_bins: np.ndarray
    weights: np.ndarray


def _selected_records(pace: PaceData, time: TimeRange) -> list[tuple[PaceRecord, dict[str, Any]]]:
    rows = []
    for record in pace.record_order:
        header = pace.headers[record.index]
        value = header.get("time")
        if value is None:
            continue
        instant = datetime.fromtimestamp(float(value), tz=UTC)
        if time.start <= instant < time.stop:
            rows.append((record, header))
    return rows


def _has_angle_calibration(calibration: PaceCalibration | None, sensor: int) -> bool:
    if calibration is None:
        return False
    return sensor in calibration.info or sensor in calibration.fov


def _has_info_calibration(calibration: PaceCalibration | None, sensor: int) -> bool:
    return calibration is not None and sensor in calibration.info


def _pitch_edges(
    pitch_bins: PitchBins,
    records: list[tuple[PaceRecord, dict[str, Any]]],
) -> np.ndarray:
    if isinstance(pitch_bins, str):
        if pitch_bins != "native":
            raise ValueError("pitch_bins must be 'native', an integer, or an array of bin edges")
        count = max(_native_pitch_bin_count(record) for record, _header in records)
        return np.linspace(0.0, 180.0, count + 1)
    if isinstance(pitch_bins, int):
        if pitch_bins <= 0:
            raise ValueError("pitch_bins must be positive")
        return np.linspace(0.0, 180.0, int(pitch_bins) + 1)
    edges = np.asarray(pitch_bins, dtype=float)
    if edges.ndim != 1 or edges.size < 2:
        raise ValueError("pitch_bins array must contain at least two bin edges")
    if not np.all(np.diff(edges) > 0):
        raise ValueError("pitch_bins edges must be strictly increasing")
    if edges[0] < 0.0 or edges[-1] > 180.0:
        raise ValueError("pitch_bins edges must be within 0..180 degrees")
    return edges


def _native_pitch_bin_count(record: PaceRecord) -> int:
    counts = record.arrays.get("cnt")
    if counts is None or counts.ndim < 3:
        return 16
    shape = tuple(int(value) for value in counts.shape[-2:])
    if shape == (16, 64):
        return 32
    if shape == (4, 16):
        return 16
    return max(16, min(32, int(np.sqrt(np.prod(shape)))))


def _record_angular_data(
    record: PaceRecord,
    header: dict[str, Any],
    sensor: int,
    calibration: PaceCalibration | None,
    *,
    value: str,
) -> _AngularRecord:
    counts = record.arrays.get("cnt")
    if counts is None or counts.ndim != 3 or counts.shape[0] != 32:
        raise ValueError(
            f"PACE count record shape cannot be pitch-binned: {getattr(counts, 'shape', None)}"
        )
    shape = (int(counts.shape[0]), int(counts.shape[1]), int(counts.shape[2]))
    key = _angular_key(shape[1], shape[2])
    if key is None:
        raise ValueError(f"Unsupported PACE angular shape for pitch binning: {shape}")
    energy, theta, phi, gfactor, detector_bins, enesq, polsq = _calibration_grid(
        header,
        shape,
        sensor,
        calibration,
    )
    raw_counts = counts.astype(float, copy=True)
    raw_counts[raw_counts == 65535] = np.nan
    if calibration is not None and sensor in calibration.info:
        raw_counts = _assign_by_sequence(shape, enesq, polsq, raw_counts)
    if value == "counts":
        values = raw_counts
    else:
        sampl_time = float(header.get("sampl_time", 0.0))
        integ_t = np.nan if sampl_time == 0.0 else 16.0 / sampl_time
        with np.errstate(divide="ignore", invalid="ignore"):
            values = raw_counts / (integ_t * gfactor * 0.6)
    weights = _domega(theta, shape)
    return _AngularRecord(
        values=_flatten_angular(values),
        energy=_flatten_angular(energy),
        theta=_flatten_angular(theta),
        phi=_flatten_angular(phi),
        detector_bins=_flatten_angular(detector_bins).astype(int),
        weights=_flatten_angular(weights),
    )


def _angular_key(polar_count: int, azimuth_count: int) -> str | None:
    if (polar_count, azimuth_count) == (16, 64):
        return "16x64"
    if (polar_count, azimuth_count) == (4, 16):
        return "4x16"
    return None


def _calibration_grid(
    header: dict[str, Any],
    shape: tuple[int, int, int],
    sensor: int,
    calibration: PaceCalibration | None,
) -> Any:
    ram = int(header.get("svs_tbl", 0))
    key = _angular_key(shape[1], shape[2])
    fov = calibration.fov.get(sensor) if calibration is not None else None
    info = calibration.info.get(sensor) if calibration is not None else None
    energy, theta, phi = _fallback_fov_grid(fov, ram, shape)
    gfactor = np.ones(shape, dtype=float)
    detector_bins = np.ones(shape, dtype=int)
    enesq = np.arange(32)
    polsq = np.arange(shape[1])
    if info is None or key is None:
        return energy, theta, phi, gfactor, detector_bins, enesq, polsq
    ram_index = min(ram, info[f"gfactor_{key}"].shape[0] - 1)
    enesq, polsq = _seq_or_default(info, key, ram_index, shape[1])
    gfactor = _assign_by_sequence(
        shape,
        enesq,
        polsq,
        info[f"gfactor_{key}"][ram_index],
        default=0.0,
    )
    detector_bins[~np.isfinite(gfactor) | (gfactor == 0.0)] = 0
    energy = _assign_by_sequence(shape, enesq, polsq, info[f"ene_{key}"][ram_index] * 1000.0)
    theta = _assign_by_sequence(shape, enesq, polsq, info[f"pol_{key}"][ram_index])
    phi = _assign_by_sequence(shape, enesq, polsq, info[f"az_{key}"][ram_index])
    return energy, theta, phi, gfactor, detector_bins, enesq, polsq


def _fallback_fov_grid(
    fov: dict[str, np.ndarray] | None,
    ram: int,
    shape: tuple[int, int, int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    energy_count, polar_count, azimuth_count = shape
    key = _angular_key(polar_count, azimuth_count)
    if fov is not None and key is not None:
        az_name = "az64" if azimuth_count == 64 else "az16"
        pol_name = "pol16" if polar_count == 16 else "pol4"
        if {"ene", az_name, pol_name} <= set(fov):
            ram_index = min(ram, fov["ene"].shape[0] - 1)
            energy = (
                np.broadcast_to(fov["ene"][ram_index, :, None, None] * 1000.0, shape)
                .astype(float)
                .copy()
            )
            theta = (
                np.broadcast_to(-fov[pol_name][ram_index, :, :, None], shape)
                .astype(float)
                .copy()
            )
            phi = np.broadcast_to(fov[az_name][None, None, :], shape).astype(float).copy()
            return energy, theta, phi
    raise ValueError("pitch_angle_spectrum requires PACE angle calibration")


def _seq_or_default(info: dict[str, np.ndarray], key: str, ram: int, polar_count: int) -> Any:
    ene_name = f"ene_sqno_{key}"
    pol_name = f"pol_sqno_{key}"
    if ene_name not in info or pol_name not in info:
        return np.arange(32), np.arange(polar_count)
    enesq = np.asarray(info[ene_name][ram, :, 0, 0], dtype=int)
    polsq = np.asarray(info[pol_name][ram, 0, :, 0], dtype=int)
    if ram == 0:
        enesq = np.arange(32)
    return np.clip(enesq, 0, 31), np.clip(polsq, 0, polar_count - 1)


def _assign_by_sequence(
    shape: tuple[int, int, int],
    enesq: np.ndarray,
    polsq: np.ndarray,
    values: np.ndarray,
    *,
    default: float = np.nan,
) -> np.ndarray:
    out = np.full(shape, default, dtype=float)
    out[np.ix_(enesq, polsq, np.arange(shape[2]))] = values
    return out


def _domega(theta: np.ndarray, shape: tuple[int, int, int]) -> np.ndarray:
    dtheta = 90.0 / float(shape[1])
    dphi = 360.0 / float(shape[2])
    theta_rad = np.deg2rad(theta)
    return cast(
        np.ndarray,
        2.0 * np.deg2rad(dphi) * np.cos(theta_rad) * np.sin(0.5 * np.deg2rad(dtheta)),
    )


def _flatten_angular(values: np.ndarray) -> np.ndarray:
    return values.reshape(values.shape[0], -1)


def _bin_energy_pitch(
    *,
    values: np.ndarray,
    pitch_deg: np.ndarray,
    detector_bins: np.ndarray,
    weights: np.ndarray,
    edges: np.ndarray,
    value: str,
    min_look_bins: int,
) -> np.ndarray:
    native = _native_module()
    if native is not None and values.ndim == pitch_deg.ndim == detector_bins.ndim == 2:
        try:
            return cast(
                np.ndarray,
                native.bin_energy_pitch(
                    values,
                    pitch_deg,
                    detector_bins,
                    weights,
                    edges,
                    value,
                    min_look_bins,
                ),
            )
        except AttributeError:
            pass
    out = np.full((values.shape[0], edges.size - 1), np.nan, dtype=float)
    valid_base = detector_bins == 1
    for bin_index in range(edges.size - 1):
        lower = edges[bin_index]
        upper = edges[bin_index + 1]
        if bin_index == edges.size - 2:
            in_pitch = (pitch_deg >= lower) & (pitch_deg <= upper)
        else:
            in_pitch = (pitch_deg >= lower) & (pitch_deg < upper)
        active = valid_base & in_pitch
        hits = np.sum(active, axis=1)
        enough = hits >= min_look_bins
        if not np.any(enough):
            continue
        if value == "counts":
            finite = active & np.isfinite(values)
            finite_hits = np.sum(finite, axis=1)
            good = enough & (finite_hits >= min_look_bins)
            summed = np.nansum(np.where(finite, values, np.nan), axis=1)
            out[good, bin_index] = summed[good]
        else:
            finite = active & np.isfinite(values) & np.isfinite(weights)
            finite_hits = np.sum(finite, axis=1)
            numerator = np.nansum(np.where(finite, values * weights, np.nan), axis=1)
            denominator = np.nansum(np.where(finite, weights, np.nan), axis=1)
            good = enough & (finite_hits >= min_look_bins) & (denominator != 0.0)
            out[good, bin_index] = numerator[good] / denominator[good]
    return out


@lru_cache(maxsize=1)
def _native_module() -> Any | None:
    for module_name in ("sopran._native", "sopran_native"):
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                raise
    return None


def _energy_row(energy: np.ndarray) -> np.ndarray:
    valid = np.isfinite(energy)
    out = np.full(energy.shape[0], np.nan, dtype=float)
    for index in range(energy.shape[0]):
        if np.any(valid[index]):
            out[index] = float(np.nanmean(energy[index]))
    return out


def _magnetic_vectors_at(
    magnetic_field: Any,
    times_unix: np.ndarray,
    *,
    look_frame: str,
    magnetic_frame: str | None,
    frame_context: FrameContext | None,
) -> np.ndarray:
    vectors, source_frame = _magnetic_source_vectors(magnetic_field, times_unix, magnetic_frame)
    source = normalize_frame(source_frame or look_frame)
    target = normalize_frame(look_frame)
    if source == target:
        return vectors
    context = frame_context or FrameContext()
    try:
        return np.asarray(
            context.transform_vectors(
                vectors,
                times=times_unix,
                source_frame=source,
                target_frame=target,
            ),
            dtype=float,
        )
    except FrameTransformError:
        raise
    except Exception as exc:
        raise FrameTransformError(
            f"Failed to align magnetic field frame {source} -> {target}"
        ) from exc


def _magnetic_source_vectors(
    magnetic_field: Any,
    times_unix: np.ndarray,
    magnetic_frame: str | None,
) -> tuple[np.ndarray, str | None]:
    if isinstance(magnetic_field, SopranArray):
        array = magnetic_field.to_xarray()
        values = np.asarray(array.values, dtype=float)
        if values.ndim != 2 or values.shape[1] != 3:
            raise ValueError("magnetic_field SopranArray must have shape (time, component=3)")
        source_times = _unix_from_datetime64(np.asarray(array.coords["time"].values))
        vectors = np.vstack(
            [np.interp(times_unix, source_times, values[:, component]) for component in range(3)]
        ).T
        frame = magnetic_frame or magnetic_field.schema.frame or getattr(
            array, "attrs", {}
        ).get("frame")
        return vectors, str(frame) if frame is not None else None
    arr = np.asarray(magnetic_field, dtype=float)
    if arr.shape == (3,):
        return (
            np.broadcast_to(arr[None, :], (times_unix.size, 3)).astype(float).copy(),
            magnetic_frame,
        )
    if arr.ndim == 2 and arr.shape[1] >= 4:
        vectors = np.vstack(
            [np.interp(times_unix, arr[:, 0], arr[:, component]) for component in range(1, 4)]
        ).T
        return vectors, magnetic_frame
    raise ValueError("magnetic_field must be a 3-vector, SopranArray, or array with time,bx,by,bz")


def _unix_from_datetime64(values: np.ndarray) -> np.ndarray:
    return values.astype("datetime64[ns]").astype("int64").astype(float) / 1_000_000_000.0


def _datetime64_from_unix(value: float) -> np.datetime64:
    text = datetime.fromtimestamp(value, tz=UTC).replace(tzinfo=None).isoformat()
    return np.datetime64(text, "ns")


def _pitch_spectrum_array(
    *,
    values: np.ndarray,
    time_values: np.ndarray,
    energy_values: np.ndarray,
    pitch_centers: np.ndarray,
    pitch_edges: np.ndarray,
    time: TimeRange,
    files: tuple[Any, ...],
    options: PitchAngleSpectrumOptions,
) -> SopranArray:
    try:
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError("xarray is required for pitch_angle_spectrum()") from exc

    units = "count" if options.value == "counts" else "eV/(cm^2 s sr eV)"
    array = xr.DataArray(
        values,
        dims=("time", "energy", "pitch_angle"),
        coords={
            "time": time_values,
            "energy": np.arange(values.shape[1]),
            "pitch_angle": pitch_centers,
            "energy_eV": (("time", "energy"), energy_values),
        },
        name="pitch_angle_spectrum",
        attrs={
            "units": units,
            "value": options.value,
            "pitch_edges": pitch_edges.tolist(),
            "look_frame": normalize_frame(options.look_frame),
        },
    )
    schema = VariableSchema(
        name="pitch_angle_spectrum",
        aliases=("pas",),
        dims=("time", "energy", "pitch_angle"),
        units=units,
        frame=normalize_frame(options.look_frame),
        description="KAGUYA PACE ESA1 energy spectrum binned by pitch angle.",
    )
    return SopranArray(
        name=schema.name,
        time=time,
        schema=schema,
        files=files,
        operations=(
            {
                "operation": "pitch_angle_spectrum",
                "parameters": {
                    "value": options.value,
                    "pitch_edges": pitch_edges.tolist(),
                    "look_frame": normalize_frame(options.look_frame),
                    "magnetic_frame": (
                        normalize_frame(options.magnetic_frame)
                        if options.magnetic_frame is not None
                        else None
                    ),
                    "min_look_bins": options.min_look_bins,
                },
            },
        ),
        xr=array,
    )


def _empty_pitch_spectrum(
    time: TimeRange,
    files: tuple[Any, ...],
    options: PitchAngleSpectrumOptions,
    *,
    edges: np.ndarray | None = None,
) -> SopranArray:
    edges = np.linspace(0.0, 180.0, 17) if edges is None else edges
    return _pitch_spectrum_array(
        values=np.empty((0, 32, edges.size - 1), dtype=float),
        time_values=np.array([], dtype="datetime64[ns]"),
        energy_values=np.empty((0, 32), dtype=float),
        pitch_centers=(edges[:-1] + edges[1:]) * 0.5,
        pitch_edges=edges,
        time=time,
        files=files,
        options=options,
    )
