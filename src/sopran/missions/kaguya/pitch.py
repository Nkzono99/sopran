from __future__ import annotations

import importlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Literal, cast

import numpy as np

from sopran.core.data import SopranArray
from sopran.core.errors import FrameTransformError
from sopran.core.schema import VariableSchema
from sopran.core.time import TimeRange
from sopran.frames import FrameContext, normalize_frame
from sopran.missions.kaguya.er_geometry import GEOMETRY_POLICY, interpolate_vectors
from sopran.missions.kaguya.esa_quality import (
    ESA_PITCH_RECORD_POLICY,
    PACE_ION_CHECK_MODES,
    esa_pitch_rejection_reason,
)
from sopran.missions.kaguya.pace import PaceCalibration, PaceData, PaceRecord

PitchBins = Literal["native"] | int | Any
CountCorrection = Literal["none", "event", "trash", "event_trash"]
# Historical name retained for old analysis scripts; these are NOT ESA exclusions.
PACE_CALIBRATION_DATA_MODES = PACE_ION_CHECK_MODES
PACE_PITCH_DATA_MODE_POLICY = ESA_PITCH_RECORD_POLICY


@dataclass(frozen=True)
class PitchAngleSpectrumOptions:
    """Pitch-spectrum construction options.

    ``cadence_seconds`` selects one native record nearest each cadence-bucket
    center. It is decimation, not temporal count accumulation.
    """

    value: str = "counts"
    pitch_bins: PitchBins = "native"
    look_frame: str = "SELENE_M_SPACECRAFT"
    magnetic_frame: str | None = None
    min_look_bins: int = 1
    cadence_seconds: float | None = None
    count_correction: CountCorrection = "none"

    def __post_init__(self) -> None:
        if self.cadence_seconds is not None and (
            not np.isfinite(self.cadence_seconds) or self.cadence_seconds <= 0.0
        ):
            raise ValueError("cadence_seconds must be finite and positive")
        if self.count_correction not in {"none", "event", "trash", "event_trash"}:
            raise ValueError("count_correction must be 'none', 'event', 'trash', or 'event_trash'")


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
    records = _sample_records(records, cadence_seconds=options.cadence_seconds)
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
    exposure_rows = []
    detector_sample_rows = []
    integration_time_rows = []
    data_mode_rows = []
    data_type_rows = []
    record_metadata = {key: [] for key in (
        "pace_submode", "pace_svs_tbl", "pace_data_quality", "record_duration_seconds"
    )}
    exposure_modes = []
    used_times = []
    geometry_rejected = times_unix[
        ~np.all(np.isfinite(magnetic), axis=1) | (np.linalg.norm(magnetic, axis=1) == 0)
    ].tolist()
    for row_index, (record, header) in enumerate(records):
        magnetic_row = magnetic[row_index]
        if not np.all(np.isfinite(magnetic_row)) or np.linalg.norm(magnetic_row) == 0.0:
            continue
        try:
            angular = _record_angular_data(
                record,
                header,
                pace.sensor,
                calibration,
                value=options.value,
                count_correction=options.count_correction,
            )
        except _CountCorrectionTelemetryError:
            raise
        except ValueError:
            continue
        pitch = pitch_angles_deg(angular.theta, angular.phi, magnetic_row)
        spectrum = _bin_energy_pitch(
            values=angular.values,
            pitch_deg=pitch,
            detector_bins=angular.detector_bins,
            weights=angular.weights,
            edges=edges,
            value=options.value,
            min_look_bins=options.min_look_bins,
        )
        exposure = _bin_energy_pitch_exposure(
            values=angular.values,
            exposure=angular.exposure,
            pitch_deg=pitch,
            detector_bins=angular.detector_bins,
            edges=edges,
            min_look_bins=options.min_look_bins,
        )
        detector_samples = _bin_energy_pitch_detector_samples(
            values=angular.values,
            exposure=angular.exposure,
            pitch_deg=pitch,
            detector_bins=angular.detector_bins,
            edges=edges,
            min_look_bins=options.min_look_bins,
        )
        rows.append(spectrum)
        energy_rows.append(_energy_row(angular.energy))
        exposure_rows.append(exposure)
        detector_sample_rows.append(detector_samples)
        integration_time_rows.append(angular.integration_time_seconds)
        data_mode_rows.append(int(header["mode"]) if "mode" in header else -1)
        data_type_rows.append(int(header.get("type", record.type)))
        for coord, field in (("pace_submode", "mode2"), ("pace_svs_tbl", "svs_tbl"),
                             ("pace_data_quality", "data_quality")):
            record_metadata[coord].append(int(header.get(field, -1)))
        record_metadata["record_duration_seconds"].append(
            float(header.get("time_resolution", 0)) / 1000.0
        )
        exposure_modes.append(angular.exposure_mode)
        used_times.append(_datetime64_from_unix(float(header["time"])))

    if not rows:
        return _empty_pitch_spectrum(
            time, files, options, edges=edges, geometry_rejected_times_unix=geometry_rejected
        )

    return _pitch_spectrum_array(
        values=np.stack(rows),
        time_values=np.asarray(used_times, dtype="datetime64[ns]"),
        energy_values=np.stack(energy_rows),
        exposure_values=np.stack(exposure_rows),
        detector_sample_values=np.stack(detector_sample_rows),
        integration_time_values=np.asarray(integration_time_rows, dtype=float),
        data_mode_values=np.asarray(data_mode_rows, dtype=np.int32),
        data_type_values=np.asarray(data_type_rows, dtype=np.int32),
        record_metadata_values={k: np.asarray(v) for k, v in record_metadata.items()},
        exposure_mode=_combined_exposure_mode(exposure_modes),
        pitch_centers=centers,
        pitch_edges=edges,
        time=time,
        files=files,
        options=options,
        geometry_rejected_times_unix=geometry_rejected,
    )


def build_combined_pitch_angle_spectrum(
    *,
    paces: Sequence[PaceData | None],
    time: TimeRange,
    calibration: PaceCalibration | None,
    magnetic_field: Any,
    files: tuple[Any, ...] = (),
    options: PitchAngleSpectrumOptions | None = None,
    frame_context: FrameContext | None = None,
    energy_bins: int = 24,
    max_time_offset_seconds: float = 16.0,
) -> SopranArray:
    """Combine complementary PACE sensors on a common energy-pitch grid.

    Each sensor is pitch-binned with its own angle and sensitivity calibration.
    Integer counts and exposures are then accumulated into common log-energy
    bins over the sensors' shared energy range. This is intended for the
    opposing ESA-S1/ESA-S2 hemispherical fields of view.
    """

    options = options or PitchAngleSpectrumOptions()
    if options.value != "counts":
        raise ValueError("combined pitch-angle spectra currently require value='counts'")
    if energy_bins < 2:
        raise ValueError("energy_bins must be at least 2")
    if not np.isfinite(max_time_offset_seconds) or max_time_offset_seconds < 0.0:
        raise ValueError("max_time_offset_seconds must be finite and non-negative")
    available = [pace for pace in paces if pace is not None]
    sensor_ids = [pace.sensor for pace in available]
    if len(available) < 2:
        raise ValueError("at least two PACE sensors are required")
    if len(set(sensor_ids)) != len(sensor_ids):
        raise ValueError("PACE sensors must be unique")

    aligned = _aligned_sampled_paces(
        available,
        time,
        cadence_seconds=options.cadence_seconds,
        max_time_offset_seconds=max_time_offset_seconds,
    )
    sensor_options = replace(options, cadence_seconds=None)
    spectra = [
        build_pitch_angle_spectrum(
            pace=pace,
            time=time,
            calibration=calibration,
            magnetic_field=magnetic_field,
            files=pace.source_files,
            options=sensor_options,
            frame_context=frame_context,
        )
        for pace in aligned
    ]
    arrays = [spectrum.to_xarray() for spectrum in spectra]
    if any(array.sizes.get("time", 0) == 0 for array in arrays):
        return _empty_pitch_spectrum(time, files, options)
    pitch = np.asarray(arrays[0].coords["pitch_angle"].values, dtype=float)
    for array in arrays[1:]:
        candidate = np.asarray(array.coords["pitch_angle"].values, dtype=float)
        if candidate.shape != pitch.shape or not np.allclose(candidate, pitch):
            raise ValueError("combined PACE spectra must use identical pitch bins")

    matches = _match_spectrum_times(arrays, max_time_offset_seconds)
    if not matches:
        return _empty_pitch_spectrum(time, files, options)
    rows: list[np.ndarray] = []
    energy_rows: list[np.ndarray] = []
    exposure_rows: list[np.ndarray] = []
    time_rows: list[np.datetime64] = []
    sensor_mode_rows = {pace.sensor_name: [] for pace in available}
    sensor_type_rows = {pace.sensor_name: [] for pace in available}
    for indices in matches:
        combined = _combine_spectrum_rows(arrays, indices, energy_bins=energy_bins)
        if combined is None:
            continue
        counts, energy_eV, exposure = combined
        rows.append(counts)
        energy_rows.append(energy_eV)
        exposure_rows.append(exposure)
        time_rows.append(
            np.asarray(arrays[0].coords["time"].values, dtype="datetime64[ns]")[indices[0]]
        )
        for pace, array, index in zip(available, arrays, indices, strict=True):
            sensor_mode_rows[pace.sensor_name].append(
                int(array.coords["pace_data_mode"].values[index])
            )
            sensor_type_rows[pace.sensor_name].append(
                int(array.coords["pace_data_type"].values[index])
            )
    if not rows:
        return _empty_pitch_spectrum(time, files, options)

    sensor_names = tuple(pace.sensor_name for pace in available)
    pitch_edges = np.asarray(arrays[0].attrs["pitch_edges"], dtype=float)
    exposure_modes = [
        str(array.coords["exposure"].attrs.get("mode", "unknown")) for array in arrays
    ]
    return _pitch_spectrum_array(
        values=np.stack(rows),
        time_values=np.asarray(time_rows, dtype="datetime64[ns]"),
        energy_values=np.stack(energy_rows),
        exposure_values=np.stack(exposure_rows),
        exposure_mode=f"combined_{_combined_exposure_mode(exposure_modes)}",
        pitch_centers=pitch,
        pitch_edges=pitch_edges,
        time=time,
        files=files or tuple(path for pace in available for path in pace.source_files),
        options=options,
        source_sensors=sensor_names,
        sensor_data_mode_values={
            sensor: np.asarray(values, dtype=np.int32)
            for sensor, values in sensor_mode_rows.items()
        },
        sensor_data_type_values={
            sensor: np.asarray(values, dtype=np.int32)
            for sensor, values in sensor_type_rows.items()
        },
        energy_alignment="log_energy_count_rebin_common_range",
    )


def build_aligned_pitch_angle_spectra(
    *,
    paces: Sequence[PaceData | None],
    time: TimeRange,
    calibration: PaceCalibration | None,
    magnetic_field: Any,
    files: tuple[Any, ...] = (),
    options: PitchAngleSpectrumOptions | None = None,
    frame_context: FrameContext | None = None,
    max_time_offset_seconds: float = 16.0,
    align: bool = True,
) -> dict[str, SopranArray]:
    """Build time-aligned sensor spectra without merging their count surfaces.

    Each returned array retains its sensor's native energy grid, counts, and
    exposure. With ``align=True``, only records with a counterpart in every
    sensor are retained. ``align=False`` keeps independent native sensor times
    for subsequent windowed likelihoods; no matching tolerance is applied.
    """

    options = options or PitchAngleSpectrumOptions()
    if options.value != "counts":
        raise ValueError("aligned PACE spectra currently require value='counts'")
    if not np.isfinite(max_time_offset_seconds) or max_time_offset_seconds < 0.0:
        raise ValueError("max_time_offset_seconds must be finite and non-negative")
    available = [pace for pace in paces if pace is not None]
    sensor_ids = [pace.sensor for pace in available]
    if len(available) < 2:
        raise ValueError("at least two PACE sensors are required")
    if len(set(sensor_ids)) != len(sensor_ids):
        raise ValueError("PACE sensors must be unique")

    aligned = _aligned_sampled_paces(
        available,
        time,
        cadence_seconds=options.cadence_seconds,
        max_time_offset_seconds=max_time_offset_seconds,
    ) if align else available
    sensor_options = replace(options, cadence_seconds=None) if align else options
    spectra = [
        build_pitch_angle_spectrum(
            pace=pace,
            time=time,
            calibration=calibration,
            magnetic_field=magnetic_field,
            files=pace.source_files or files,
            options=sensor_options,
            frame_context=frame_context,
        )
        for pace in aligned
    ]
    arrays = [spectrum.to_xarray() for spectrum in spectra]
    selection = []
    start, stop = time.start.timestamp(), time.stop.timestamp()
    for pace, paired, array in zip(available, aligned, arrays, strict=True):
        records = [
            r
            for r in pace.record_order
            if pace.headers[r.index].get("time") is not None
            and start <= float(pace.headers[r.index]["time"]) < stop
        ]
        reasons = Counter(
            reason for r in records
            if (reason := esa_pitch_rejection_reason(pace.headers[r.index], data_type=r.type))
        )
        excluded = sum(reasons.values())
        selection.append(
            dict(
                records_in_range=len(records),
                rejected_records=excluded,
                rejection_reasons=dict(reasons),
                ion_check_esa_records=sum(
                    pace.headers[r.index].get("mode") in PACE_ION_CHECK_MODES
                    and esa_pitch_rejection_reason(pace.headers[r.index], data_type=r.type) is None
                    for r in records
                ),
                eligible_records=len(records) - excluded,
                matched_records=len(paired.record_order) if align else None,
                pitch_records=array.sizes.get("time", 0),
                geometry_rejected_records=len(array.attrs.get("geometry_rejected_times_unix", ())),
            )
        )
    if any(s["records_in_range"] == 0 for s in selection):
        status = "no_records"
    elif any(s["eligible_records"] == 0 for s in selection):
        status = "excluded_by_record_policy"
    elif any(s["matched_records"] == 0 for s in selection):
        status = "no_matched_records"
    elif any(s["pitch_records"] == 0 for s in selection):
        status = "no_valid_pitch_records"
    else:
        status = "usable"
    matches = (
        _match_spectrum_times(arrays, max_time_offset_seconds)
        if align and status == "usable" else []
    )
    if align and status == "usable" and not matches:
        status = "no_matched_records"

    output: dict[str, SopranArray] = {}
    sensor_names = [pace.sensor_name for pace in available]
    for sensor_index, (pace, spectrum, array) in enumerate(
        zip(available, spectra, arrays, strict=True)
    ):
        indices = slice(None)
        if align:
            indices = [match[sensor_index] for match in matches] if matches else slice(0, 0)
        selected_array = array.isel(time=indices).assign_attrs(
            joint_input_status=status,
            record_selection=selection[sensor_index],
            sensor_time_policy="matched_native" if align else "independent_native",
        )
        output[pace.sensor_name] = spectrum._with_xarray(
            selected_array,
            operation={
                "operation": "align_pitch_angle_spectra" if align else "native_pitch_angle_spectra",
                "parameters": {
                    "sensors": sensor_names,
                    "max_time_offset_seconds": max_time_offset_seconds,
                },
            },
        )
    return output


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
    exposure: np.ndarray
    integration_time_seconds: float
    exposure_mode: str


class _CountCorrectionTelemetryError(ValueError):
    """Requested PACE count-correction telemetry is absent or malformed."""


def _selected_records(pace: PaceData, time: TimeRange) -> list[tuple[PaceRecord, dict[str, Any]]]:
    rows = []
    for record in pace.record_order:
        header = pace.headers[record.index]
        if esa_pitch_rejection_reason(header, data_type=record.type) is not None:
            continue
        value = header.get("time")
        if value is None:
            continue
        instant = datetime.fromtimestamp(float(value), tz=UTC)
        if time.start <= instant < time.stop:
            rows.append((record, header))
    return rows


def _sample_records(
    records: list[tuple[PaceRecord, dict[str, Any]]],
    *,
    cadence_seconds: float | None,
) -> list[tuple[PaceRecord, dict[str, Any]]]:
    if cadence_seconds is None or len(records) < 2:
        return records
    selected: dict[int, tuple[float, tuple[PaceRecord, dict[str, Any]]]] = {}
    for item in records:
        value = item[1].get("time")
        if value is None or not np.isfinite(float(value)):
            continue
        instant = float(value)
        bucket = int(np.floor(instant / cadence_seconds))
        center = (bucket + 0.5) * cadence_seconds
        distance = abs(instant - center)
        current = selected.get(bucket)
        if current is None or distance < current[0]:
            selected[bucket] = (distance, item)
    return [selected[bucket][1] for bucket in sorted(selected)]


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
    count_correction: CountCorrection = "none",
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
    correction_factor = _pace_count_correction_factor(record, raw_counts, count_correction)
    if calibration is not None and sensor in calibration.info:
        raw_counts = _assign_by_sequence(shape, enesq, polsq, raw_counts)
        correction_factor = _assign_by_sequence(shape, enesq, polsq, correction_factor)
    sampl_time = float(header.get("sampl_time", 0.0))
    integration_time = 1.0 if sampl_time <= 0.0 else 16.0 / sampl_time
    nominal_exposure = integration_time * gfactor * 0.6
    if value == "counts":
        exposure = np.divide(
            nominal_exposure,
            correction_factor,
            out=np.full_like(nominal_exposure, np.nan, dtype=float),
            where=np.isfinite(correction_factor) & (correction_factor > 0.0),
        )
    else:
        exposure = nominal_exposure
    exposure_mode = (
        "calibrated"
        if calibration is not None and sensor in calibration.info and sampl_time > 0.0
        else "relative"
    )
    if value == "counts":
        values = raw_counts
    else:
        with np.errstate(divide="ignore", invalid="ignore"):
            values = raw_counts * correction_factor / nominal_exposure
    weights = _domega(theta, shape)
    return _AngularRecord(
        values=_flatten_angular(values),
        energy=_flatten_angular(energy),
        theta=_flatten_angular(theta),
        phi=_flatten_angular(phi),
        detector_bins=_flatten_angular(detector_bins).astype(int),
        weights=_flatten_angular(weights),
        exposure=_flatten_angular(exposure),
        integration_time_seconds=integration_time,
        exposure_mode=exposure_mode,
    )


def _pace_count_correction_factor(
    record: PaceRecord,
    raw_counts: np.ndarray,
    correction: CountCorrection,
) -> np.ndarray:
    """Return the SPEDAS ``/cntcorr`` multiplier for each raw count cell.

    SPEDAS first redistributes the two trash counters over azimuth, then scales
    each adjacent energy pair to its event counter. The multiplier is kept
    separate so raw integer counts can remain the likelihood observations.
    """

    counts = np.asarray(raw_counts, dtype=float)
    if counts.ndim != 3 or counts.shape[0] != 32:
        raise ValueError("PACE count correction requires a (32, polar, azimuth) count array")
    factor = np.ones(counts.shape, dtype=float)
    corrected = counts.copy()

    if correction in {"trash", "event_trash"}:
        trash_array = record.arrays.get("trash")
        if trash_array is None:
            raise _CountCorrectionTelemetryError(
                "trash count correction requires PACE trash telemetry"
            )
        trash = _pace_telemetry_values(trash_array)
        expected_shape = counts.shape[:2] + (2,)
        if trash.shape != expected_shape:
            raise _CountCorrectionTelemetryError(
                f"PACE trash telemetry must have shape {expected_shape}, received {trash.shape}"
            )
        observed = np.nansum(counts, axis=2)
        discarded = np.nansum(trash, axis=2)
        valid = observed > 0.0
        trash_factor = np.ones(observed.shape, dtype=float)
        trash_factor[valid] = (observed[valid] + discarded[valid]) / observed[valid]
        factor *= trash_factor[:, :, None]
        corrected *= trash_factor[:, :, None]

    if correction in {"event", "event_trash"}:
        event_array = record.arrays.get("event")
        if event_array is None:
            raise _CountCorrectionTelemetryError(
                "event count correction requires PACE event telemetry"
            )
        event = np.squeeze(_pace_telemetry_values(event_array))
        if event.shape != (16,):
            raise _CountCorrectionTelemetryError(
                "PACE event correction currently requires one 16-bin event vector "
                f"per record, received {event.shape}"
            )
        pair_total = np.nansum(corrected[0::2] + corrected[1::2], axis=(1, 2))
        valid = (pair_total > 0.0) & np.isfinite(event)
        event_factor = np.ones(16, dtype=float)
        event_factor[valid] = event[valid] / pair_total[valid]
        event_factor[(pair_total > 0.0) & ~np.isfinite(event)] = np.nan
        factor[0::2] *= event_factor[:, None, None]
        factor[1::2] *= event_factor[:, None, None]

    return factor


def _pace_telemetry_values(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values)
    output = array.astype(float, copy=True)
    if np.issubdtype(array.dtype, np.integer):
        output[array == np.iinfo(array.dtype).max] = np.nan
    output[array == 65535] = np.nan
    return output


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
                np.broadcast_to(-fov[pol_name][ram_index, :, :, None], shape).astype(float).copy()
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


def _bin_energy_pitch_exposure(
    *,
    values: np.ndarray,
    exposure: np.ndarray,
    pitch_deg: np.ndarray,
    detector_bins: np.ndarray,
    edges: np.ndarray,
    min_look_bins: int,
) -> np.ndarray:
    out = np.full((values.shape[0], edges.size - 1), np.nan, dtype=float)
    valid_base = detector_bins == 1
    for bin_index in range(edges.size - 1):
        lower = edges[bin_index]
        upper = edges[bin_index + 1]
        if bin_index == edges.size - 2:
            in_pitch = (pitch_deg >= lower) & (pitch_deg <= upper)
        else:
            in_pitch = (pitch_deg >= lower) & (pitch_deg < upper)
        finite = (
            valid_base & in_pitch & np.isfinite(values) & np.isfinite(exposure) & (exposure > 0.0)
        )
        finite_hits = np.sum(finite, axis=1)
        good = finite_hits >= min_look_bins
        summed = np.nansum(np.where(finite, exposure, np.nan), axis=1)
        out[good, bin_index] = summed[good]
    return out


def _bin_energy_pitch_detector_samples(
    *,
    values: np.ndarray,
    exposure: np.ndarray,
    pitch_deg: np.ndarray,
    detector_bins: np.ndarray,
    edges: np.ndarray,
    min_look_bins: int,
) -> np.ndarray:
    out = np.full((values.shape[0], edges.size - 1), np.nan, dtype=float)
    valid_base = (
        (detector_bins == 1) & np.isfinite(values) & np.isfinite(exposure) & (exposure > 0.0)
    )
    for bin_index in range(edges.size - 1):
        lower = edges[bin_index]
        upper = edges[bin_index + 1]
        if bin_index == edges.size - 2:
            in_pitch = (pitch_deg >= lower) & (pitch_deg <= upper)
        else:
            in_pitch = (pitch_deg >= lower) & (pitch_deg < upper)
        hits = np.sum(valid_base & in_pitch, axis=1)
        good = hits >= min_look_bins
        out[good, bin_index] = hits[good]
    return out


def _combined_exposure_mode(modes: list[str]) -> str:
    return modes[0] if len(set(modes)) == 1 else "mixed"


def _aligned_sampled_paces(
    paces: Sequence[PaceData],
    time: TimeRange,
    *,
    cadence_seconds: float | None,
    max_time_offset_seconds: float,
) -> tuple[PaceData, ...]:
    selected = [_selected_records(pace, time) for pace in paces]
    if any(not records for records in selected):
        return tuple(
            PaceData(
                sensor=pace.sensor,
                headers=pace.headers,
                records={},
                source_files=pace.source_files,
                record_order=(),
            )
            for pace in paces
        )
    times = [
        np.asarray([float(header["time"]) for _record, header in records]) for records in selected
    ]
    used = [set() for _pace in paces]
    pairs: list[tuple[int, ...]] = []
    for reference_index, instant in enumerate(times[0]):
        indices = [reference_index]
        valid = True
        for sensor_index, candidates in enumerate(times[1:], start=1):
            insertion = int(np.searchsorted(candidates, instant))
            possible = [
                index
                for index in (insertion - 1, insertion)
                if 0 <= index < candidates.size and index not in used[sensor_index]
            ]
            if not possible:
                valid = False
                break
            nearest = min(possible, key=lambda index: abs(candidates[index] - instant))
            if abs(float(candidates[nearest] - instant)) > max_time_offset_seconds:
                valid = False
                break
            indices.append(nearest)
        if valid:
            for sensor_index, index in enumerate(indices):
                used[sensor_index].add(index)
            pairs.append(tuple(indices))
    if cadence_seconds is not None:
        sampled: dict[int, tuple[float, tuple[int, ...]]] = {}
        for indices in pairs:
            instant = float(times[0][indices[0]])
            bucket = int(np.floor(instant / cadence_seconds))
            center = (bucket + 0.5) * cadence_seconds
            distance = abs(instant - center)
            current = sampled.get(bucket)
            if current is None or distance < current[0]:
                sampled[bucket] = (distance, indices)
        pairs = [sampled[bucket][1] for bucket in sorted(sampled)]
    out = []
    for sensor_index, pace in enumerate(paces):
        record_order = tuple(selected[sensor_index][indices[sensor_index]][0] for indices in pairs)
        records_by_type: dict[int, list[PaceRecord]] = {}
        for record in record_order:
            records_by_type.setdefault(record.type, []).append(record)
        out.append(
            PaceData(
                sensor=pace.sensor,
                headers=pace.headers,
                records={
                    record_type: tuple(records) for record_type, records in records_by_type.items()
                },
                source_files=pace.source_files,
                record_order=record_order,
            )
        )
    return tuple(out)


def _match_spectrum_times(
    arrays: Sequence[Any],
    max_time_offset_seconds: float,
) -> list[tuple[int, ...]]:
    times = [
        np.asarray(array.coords["time"].values, dtype="datetime64[ns]").astype(np.int64)
        for array in arrays
    ]
    tolerance_ns = int(round(max_time_offset_seconds * 1_000_000_000.0))
    matches: list[tuple[int, ...]] = []
    used = [set() for _array in arrays]
    for reference_index, instant in enumerate(times[0]):
        indices = [reference_index]
        valid = True
        for sensor_index, candidates in enumerate(times[1:], start=1):
            insertion = int(np.searchsorted(candidates, instant))
            possible = [
                index
                for index in (insertion - 1, insertion)
                if 0 <= index < candidates.size and index not in used[sensor_index]
            ]
            if not possible:
                valid = False
                break
            nearest = min(possible, key=lambda index: abs(int(candidates[index] - instant)))
            if abs(int(candidates[nearest] - instant)) > tolerance_ns:
                valid = False
                break
            indices.append(nearest)
        if not valid:
            continue
        for sensor_index, index in enumerate(indices):
            used[sensor_index].add(index)
        matches.append(tuple(indices))
    return matches


def _combine_spectrum_rows(
    arrays: Sequence[Any],
    indices: tuple[int, ...],
    *,
    energy_bins: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    energy_rows = [
        np.asarray(array.coords["energy_eV"].values[index], dtype=float)
        for array, index in zip(arrays, indices, strict=True)
    ]
    finite_ranges = []
    for energy in energy_rows:
        finite = energy[np.isfinite(energy) & (energy > 0.0)]
        if finite.size < 2:
            return None
        finite_ranges.append((float(np.min(finite)), float(np.max(finite))))
    lower = max(bounds[0] for bounds in finite_ranges)
    upper = min(bounds[1] for bounds in finite_ranges)
    if not lower < upper:
        return None
    epsilon = np.finfo(float).eps * 16.0
    energy_edges = np.geomspace(lower * (1.0 - epsilon), upper * (1.0 + epsilon), energy_bins + 1)
    target_energy = np.sqrt(energy_edges[:-1] * energy_edges[1:])
    pitch_bins = int(arrays[0].sizes["pitch_angle"])
    combined_counts = np.zeros((energy_bins, pitch_bins), dtype=float)
    combined_exposure = np.zeros_like(combined_counts)
    supported = np.zeros(combined_counts.shape, dtype=bool)
    for array, row_index, energy in zip(arrays, indices, energy_rows, strict=True):
        counts = np.asarray(array.values[row_index], dtype=float)
        exposure = np.asarray(array.coords["exposure"].values[row_index], dtype=float)
        assignments = np.searchsorted(energy_edges, energy, side="right") - 1
        assignments[energy == energy_edges[-1]] = energy_bins - 1
        for source_index, target_index in enumerate(assignments):
            if target_index < 0 or target_index >= energy_bins:
                continue
            valid = (
                np.isfinite(counts[source_index])
                & (counts[source_index] >= 0.0)
                & np.isfinite(exposure[source_index])
                & (exposure[source_index] > 0.0)
            )
            combined_counts[target_index, valid] += counts[source_index, valid]
            combined_exposure[target_index, valid] += exposure[source_index, valid]
            supported[target_index, valid] = True
    supported &= combined_exposure > 0.0
    combined_counts[~supported] = np.nan
    combined_exposure[~supported] = np.nan
    return combined_counts, target_energy, combined_exposure


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
                missing="nan",
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
        vectors = interpolate_vectors(source_times, values, times_unix).values
        frame = (
            magnetic_frame
            or magnetic_field.schema.frame
            or getattr(array, "attrs", {}).get("frame")
        )
        return vectors, str(frame) if frame is not None else None
    arr = np.asarray(magnetic_field, dtype=float)
    if arr.shape == (3,):
        return (
            np.broadcast_to(arr[None, :], (times_unix.size, 3)).astype(float).copy(),
            magnetic_frame,
        )
    if arr.ndim == 2 and arr.shape[1] >= 4:
        vectors = interpolate_vectors(arr[:, 0], arr[:, 1:4], times_unix).values
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
    exposure_values: np.ndarray,
    exposure_mode: str,
    pitch_centers: np.ndarray,
    pitch_edges: np.ndarray,
    time: TimeRange,
    files: tuple[Any, ...],
    options: PitchAngleSpectrumOptions,
    detector_sample_values: np.ndarray | None = None,
    integration_time_values: np.ndarray | None = None,
    data_mode_values: np.ndarray | None = None,
    data_type_values: np.ndarray | None = None,
    record_metadata_values: dict[str, np.ndarray] | None = None,
    sensor_data_mode_values: dict[str, np.ndarray] | None = None,
    sensor_data_type_values: dict[str, np.ndarray] | None = None,
    source_sensors: tuple[str, ...] = (),
    energy_alignment: str | None = None,
    geometry_rejected_times_unix: Sequence[float] = (),
) -> SopranArray:
    try:
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError("xarray is required for pitch_angle_spectrum()") from exc

    units = "count" if options.value == "counts" else "eV/(cm^2 s sr eV)"
    attrs: dict[str, Any] = {
        "units": units,
        "value": options.value,
        "pitch_edges": pitch_edges.tolist(),
        "look_frame": normalize_frame(options.look_frame),
        "cadence_seconds": options.cadence_seconds,
        "count_correction": options.count_correction,
        "count_correction_order": "trash_then_event",
        "pace_data_mode_policy": PACE_PITCH_DATA_MODE_POLICY,
        "geometry_policy": GEOMETRY_POLICY,
        "excluded_pace_data_modes": [],
    }
    if geometry_rejected_times_unix:
        attrs["geometry_rejected_times_unix"] = list(geometry_rejected_times_unix)
    if source_sensors:
        attrs["source_sensors"] = list(source_sensors)
    if energy_alignment is not None:
        attrs["energy_alignment"] = energy_alignment
    coords: dict[str, Any] = {
        "time": time_values,
        "energy": np.arange(values.shape[1]),
        "pitch_angle": pitch_centers,
        "energy_eV": (("time", "energy"), energy_values),
        "exposure": (("time", "energy", "pitch_angle"), exposure_values),
    }
    if detector_sample_values is not None:
        coords["detector_samples"] = (
            ("time", "energy", "pitch_angle"),
            detector_sample_values,
        )
    if integration_time_values is not None:
        coords["integration_time_seconds"] = ("time", integration_time_values)
    if data_mode_values is not None:
        coords["pace_data_mode"] = ("time", data_mode_values)
    if data_type_values is not None:
        coords["pace_data_type"] = ("time", data_type_values)
    for name, metadata in (record_metadata_values or {}).items():
        coords[name] = ("time", metadata)
    for sensor, sensor_values in (sensor_data_mode_values or {}).items():
        coords[f"pace_data_mode_{_sensor_coord_token(sensor)}"] = ("time", sensor_values)
    for sensor, sensor_values in (sensor_data_type_values or {}).items():
        coords[f"pace_data_type_{_sensor_coord_token(sensor)}"] = ("time", sensor_values)
    array = xr.DataArray(
        values,
        dims=("time", "energy", "pitch_angle"),
        coords=coords,
        name="pitch_angle_spectrum",
        attrs=attrs,
    )
    array.coords["energy_eV"].attrs.update({"units": "eV", "long_name": "energy"})
    array.coords["exposure"].attrs.update(
        {
            "units": "relative",
            "long_name": "effective count exposure",
            "mode": exposure_mode,
        }
    )
    if "detector_samples" in array.coords:
        array.coords["detector_samples"].attrs.update(
            {
                "units": "count",
                "long_name": "number of calibrated detector looks in pitch cell",
            }
        )
    if "integration_time_seconds" in array.coords:
        array.coords["integration_time_seconds"].attrs.update(
            {"units": "s", "long_name": "PACE integration time per detector look"}
        )
    for name in array.coords:
        if name.startswith("pace_data_mode"):
            array.coords[name].attrs.update({"long_name": "PACE data mode command"})
        elif name.startswith("pace_data_type"):
            array.coords[name].attrs.update({"long_name": "PACE record data type"})
    for name, label in (
        ("pace_submode", "PACE sensor sub-data mode"),
        ("pace_svs_tbl", "PACE energy sweep RAM table"),
        ("pace_data_quality", "PACE raw data quality field (not decoded)"),
        ("record_duration_seconds", "PACE record acquisition duration"),
    ):
        if name in array.coords:
            array.coords[name].attrs.update(
                units="s" if name == "record_duration_seconds" else "1", long_name=label
            )
    sensor_label = "+".join(source_sensors) if source_sensors else "ESA1"
    schema = VariableSchema(
        name="pitch_angle_spectrum",
        aliases=("pas",),
        dims=("time", "energy", "pitch_angle"),
        units=units,
        frame=normalize_frame(options.look_frame),
        description=f"KAGUYA PACE {sensor_label} energy spectrum binned by pitch angle.",
    )
    parameters: dict[str, Any] = {
        "value": options.value,
        "pitch_edges": pitch_edges.tolist(),
        "look_frame": normalize_frame(options.look_frame),
        "magnetic_frame": (
            normalize_frame(options.magnetic_frame) if options.magnetic_frame is not None else None
        ),
        "min_look_bins": options.min_look_bins,
        "cadence_seconds": options.cadence_seconds,
        "count_correction": options.count_correction,
        "count_correction_order": "trash_then_event",
        "exposure_mode": exposure_mode,
        "pace_data_mode_policy": PACE_PITCH_DATA_MODE_POLICY,
        "geometry_policy": GEOMETRY_POLICY,
        "excluded_pace_data_modes": [],
    }
    if geometry_rejected_times_unix:
        parameters["geometry_rejected_times_unix"] = list(geometry_rejected_times_unix)
    if source_sensors:
        parameters["source_sensors"] = list(source_sensors)
    if energy_alignment is not None:
        parameters["energy_alignment"] = energy_alignment
    return SopranArray(
        name=schema.name,
        time=time,
        schema=schema,
        files=files,
        operations=(
            {
                "operation": (
                    "combined_pitch_angle_spectrum" if source_sensors else "pitch_angle_spectrum"
                ),
                "parameters": parameters,
            },
        ),
        xr=array,
    )


def _sensor_coord_token(sensor: str) -> str:
    return sensor.lower().replace("-", "_")


def _empty_pitch_spectrum(
    time: TimeRange,
    files: tuple[Any, ...],
    options: PitchAngleSpectrumOptions,
    *,
    edges: np.ndarray | None = None,
    geometry_rejected_times_unix: Sequence[float] = (),
) -> SopranArray:
    edges = np.linspace(0.0, 180.0, 17) if edges is None else edges
    return _pitch_spectrum_array(
        values=np.empty((0, 32, edges.size - 1), dtype=float),
        time_values=np.array([], dtype="datetime64[ns]"),
        energy_values=np.empty((0, 32), dtype=float),
        exposure_values=np.empty((0, 32, edges.size - 1), dtype=float),
        exposure_mode="unavailable",
        pitch_centers=(edges[:-1] + edges[1:]) * 0.5,
        pitch_edges=edges,
        time=time,
        files=files,
        options=options,
        geometry_rejected_times_unix=geometry_rejected_times_unix,
    )
