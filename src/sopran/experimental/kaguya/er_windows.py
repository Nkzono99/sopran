"""Native ESA records grouped into fixed integration windows for ER inputs.

The pieces follow the full-period Halekas runner (halekas_mission_v1): sensor
records stay on their own native times, geometry comes from bounded LMAG
interpolation at each record, and every calendar window of a day gets a record
with coverage, geometry and data-mode diagnostics. Nothing is interpolated in
counts, energies or exposure.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from sopran.core.time import TimeRange
from sopran.experimental.electron_reflection.maps import PitchCountRecord
from sopran.missions.kaguya.magnetic_geometry import GEOMETRY_POLICY
from sopran.missions.kaguya.pitch import _datetime64_from_unix

if TYPE_CHECKING:
    import xarray as xr

FloatArray = NDArray[np.float64]
# TOF/POS check commands change the ions, not the ESA EC-N response.
_ION_CHECK_MODES = (0x11, 0x12)


@dataclass(frozen=True)
class NativeEsaRecords:
    """ESA sensors on the union of their native record times, with record geometry.

    ``arrays`` maps sensor names to raw-count pitch spectra reindexed onto
    ``times``; ``record_present`` marks real records and ``geometry_valid``
    records with usable field-radial geometry. ``position_km`` and
    ``magnetic_field_nT`` (MOON_ME), ``field_nT`` and ``affected_side`` are per
    union time. ``magnetic_field`` is the LMAG series used for in-window
    direction statistics.
    """

    arrays: Mapping[str, xr.DataArray]
    times: NDArray[np.datetime64]
    position_km: FloatArray
    magnetic_field_nT: FloatArray
    field_nT: FloatArray
    affected_side: NDArray[np.str_]
    magnetic_field: xr.DataArray | None = None
    files: tuple[Path, ...] = field(default_factory=tuple)


def native_record_arrays(arrays: Mapping[str, xr.DataArray]) -> dict[str, xr.DataArray]:
    """Index each sensor on the union of native times without synthesizing data.

    NaN padding is only an index convenience: ``record_present`` says which rows
    are observations and ``pitch_geometry_rejected`` which records the pitch
    builder rejected for geometry.
    """

    rejected = {
        name: np.array(
            [_datetime64_from_unix(t) for t in a.attrs.get("geometry_rejected_times_unix", ())],
            dtype="datetime64[ns]",
        )
        for name, a in arrays.items()
    }
    times = np.unique(
        np.concatenate([*[a.time.values for a in arrays.values()], *rejected.values()])
    )
    result = {}
    for name, array in arrays.items():
        if np.any(np.isnat(array.time.values)) or np.unique(array.time.values).size != array.sizes[
            "time"
        ]:
            raise ValueError(f"{name} native record times must be finite and unique")
        result[name] = (
            array.reindex(time=times)
            .assign_coords(
                record_present=("time", np.isin(times, array.time.values)),
                pitch_geometry_rejected=("time", np.isin(times, rejected[name])),
            )
            .assign_attrs(sensor_time_policy="independent_native", geometry_policy=GEOMETRY_POLICY)
        )
    return result


def field_radial_geometry(
    magnetic_field: Any, position: Any
) -> tuple[NDArray[np.bool_], FloatArray, NDArray[np.str_]]:
    """Return usable rows, the B/r cosine and the affected (outgoing) side per row.

    A row is usable when the cosine is finite and nonzero. Outgoing electrons
    occupy the low-pitch hemisphere when +B points radially outward.
    """

    b = np.asarray(magnetic_field, dtype=float)
    r = np.asarray(position, dtype=float)
    norm = np.linalg.norm(b, axis=1) * np.linalg.norm(r, axis=1)
    cosine = np.divide(np.sum(b * r, axis=1), norm, out=np.full(len(b), np.nan), where=norm > 0)
    valid = np.isfinite(cosine) & (cosine != 0)
    sides = np.where(valid, np.where(cosine > 0, "low", "high"), "unknown")
    return valid, np.clip(cosine, -1, 1), sides


def attach_record_geometry(
    arrays: Mapping[str, xr.DataArray], magnetic_field: Any, position: Any
) -> dict[str, xr.DataArray]:
    """Attach per-record B vectors, B/r cosine and geometry validity to each sensor."""

    magnetic = np.asarray(magnetic_field, dtype=float)
    valid, cosine, _ = field_radial_geometry(magnetic, position)
    coords: dict[str, Any] = {
        "geometry_valid": ("time", valid),
        "field_radial_cosine": ("time", cosine),
    }
    coords.update({f"magnetic_{axis}_nT": ("time", magnetic[:, i]) for i, axis in enumerate("xyz")})
    result = {name: a.assign_coords(coords) for name, a in arrays.items()}
    for array in result.values():
        for name in coords:
            array.coords[name].attrs["units"] = "nT" if name.startswith("magnetic_") else "1"
    return result


def usable_record_indices(array: xr.DataArray, indices: NDArray[np.intp]) -> NDArray[np.intp]:
    """Indices that are real records with valid geometry."""

    valid = np.ones(indices.size, dtype=bool)
    for name in ("record_present", "geometry_valid"):
        if name in array.coords:
            valid &= np.asarray(array.coords[name].values[indices], dtype=bool)
    return indices[valid]


def calendar_windows(
    times: Any, day: TimeRange, *, integration_seconds: int = 16
) -> Iterator[tuple[int, NDArray[np.intp]]]:
    """Yield ``(window_id, record_indices)`` for every window of a UTC day, empty or not.

    ``window_id`` is the window start in Unix seconds divided by the width.
    """

    values = np.asarray(times, dtype="datetime64[ns]").astype(np.int64)
    if np.any(np.diff(values) <= 0):
        raise ValueError("native union timestamps must be strictly increasing")
    if 86400 % integration_seconds:
        raise ValueError("integration_seconds must divide a day")
    start = pd.Timestamp(day.start).value
    width = integration_seconds * 1_000_000_000
    edges = start + np.arange(86400 // integration_seconds + 1, dtype=np.int64) * width
    bounds = np.searchsorted(values, edges)
    for index in range(len(edges) - 1):
        yield int(edges[index] // width), np.arange(bounds[index], bounds[index + 1])


def window_sample_id(window_id: int, integration_seconds: int = 16) -> str:
    """``YYYYMMDD-HHMMSS`` of the window center."""

    center = pd.Timestamp(window_id * integration_seconds, unit="s", tz="UTC") + pd.Timedelta(
        seconds=integration_seconds / 2
    )
    return center.strftime("%Y%m%d-%H%M%S")


def window_record(
    window_id: int,
    indices: NDArray[np.intp],
    records: NativeEsaRecords,
    *,
    integration_seconds: int = 16,
    native_cadence_seconds: float = 2.0,
    count_correction: str = "event_trash",
) -> dict[str, Any]:
    """Coverage, field, side, geometry and mode summary of one window.

    ``magnetic_direction_max_deviation_deg`` and ``magnetic_magnitude_cv`` use
    the LMAG samples inside the window when ``records.magnetic_field`` is set,
    otherwise the field at the ESA record centers. The expected record count
    follows the slower sensor's median record duration when available.
    """

    arrays = records.arrays
    width_ns = int(round(integration_seconds * 1.0e9))
    start = pd.Timestamp(window_id * width_ns, unit="ns", tz="UTC")
    stop = start + pd.Timedelta(seconds=integration_seconds)
    sensor_indices = {name: usable_record_indices(a, indices) for name, a in arrays.items()}
    usable = np.unique(np.concatenate(list(sensor_indices.values()))) if arrays else indices
    modes = {
        f"{name.lower().replace('-', '_')}_pace_data_mode": (
            _single_value(array.coords["pace_data_mode"].values[sensor_indices[name]])
            if sensor_indices[name].size
            else None
        )
        for name, array in arrays.items()
        if "pace_data_mode" in array.coords
    }
    times = records.times
    gaps = np.diff(times[usable].astype("datetime64[ns]").astype("int64")) / 1.0e9
    expected_records = max(1, int(integration_seconds // native_cadence_seconds))
    durations = [
        np.asarray(a.coords["record_duration_seconds"].values[sensor_indices[name]], dtype=float)
        for name, a in arrays.items()
        if "record_duration_seconds" in a.coords and sensor_indices[name].size
    ]
    if indices.size and durations and len(durations) == len(arrays):
        all_durations = np.concatenate(durations)
        if np.all(np.isfinite(all_durations) & (all_durations > 0)):
            native_cadence_seconds = max(float(np.median(d)) for d in durations)
            expected_records = max(1, int(np.ceil(integration_seconds / native_cadence_seconds)))
    field_values = records.field_nT[usable]
    sides = records.affected_side[usable]
    return {
        "sample_id": window_sample_id(window_id, integration_seconds),
        "time": start + (stop - start) / 2,
        "window_start": start,
        "window_stop": stop,
        "integration_seconds": integration_seconds,
        "native_cadence_seconds": native_cadence_seconds,
        "records_integrated": int(usable.size),
        "input_record_timestamps": int(indices.size),
        "expected_records": expected_records,
        "minimum_records": 1,
        "window_coverage": float(
            min((i.size for i in sensor_indices.values()), default=0) / expected_records
        ),
        "first_record_time": _utc(times[usable[0]]) if usable.size else None,
        "last_record_time": _utc(times[usable[-1]]) if usable.size else None,
        "affected_side": _single_value(sides) if usable.size else None,
        "affected_side_changed": bool(usable.size and np.unique(sides).size > 1),
        "max_record_gap_seconds": float(np.max(gaps)) if gaps.size else None,
        "b_sc_nT": float(np.median(field_values)) if usable.size else None,
        "record_time_median_b_sc_nT": float(np.median(field_values)) if usable.size else None,
        "b_sc_std_nT": float(np.std(field_values)) if usable.size else None,
        "count_correction": count_correction,
        **_record_geometry_diagnostics(arrays, indices, sensor_indices),
        **_magnetic_window_diagnostics(records.magnetic_field, start, stop),
        **modes,
    }


def window_input_diagnostic(
    indices: NDArray[np.intp], arrays: Mapping[str, xr.DataArray]
) -> str | None:
    """Why a window's records do not form one homogeneous joint input, or None.

    Calibrated native records can still be combined; the runner stores this as
    ``joint_input_diagnostic`` rather than as a skip reason.
    """

    if indices.size == 0:
        return "no_records"
    for name, array in arrays.items():
        selected = usable_record_indices(array, indices)
        if selected.size == 0:
            present = "record_present" in array.coords and np.any(
                array.record_present.values[indices]
            )
            rejected = "pitch_geometry_rejected" in array.coords and np.any(
                array.pitch_geometry_rejected.values[indices]
            )
            return f"{name}_geometry_unavailable" if present or rejected else f"{name}_no_records"
        for coordinate in ("pace_data_type", "pace_submode", "pace_svs_tbl"):
            if (
                coordinate in array.coords
                and np.unique(array.coords[coordinate].values[selected]).size > 1
            ):
                return f"{name}_{coordinate}_changed"
        if "pace_data_mode" in array.coords:
            modes = np.asarray(array.coords["pace_data_mode"].values[selected])
            if np.unique(modes).size != 1 and not np.all(np.isin(modes, _ION_CHECK_MODES)):
                return f"{name}_pace_data_mode_changed"
    return None


def window_pitch_records(
    records: NativeEsaRecords, indices: NDArray[np.intp]
) -> list[PitchCountRecord]:
    """One oriented-ready count record per usable sensor record in the window."""

    return [
        PitchCountRecord.from_spectrum(
            spectrum,
            index=int(i),
            affected_side=cast(Literal["low", "high"], str(records.affected_side[i])),
        )
        for spectrum in records.arrays.values()
        for i in usable_record_indices(spectrum, indices)
    ]


def _record_geometry_diagnostics(
    arrays: Mapping[str, xr.DataArray],
    indices: NDArray[np.intp],
    sensor_indices: Mapping[str, NDArray[np.intp]],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "sensor_records": {name: int(idx.size) for name, idx in sensor_indices.items()},
        "geometry_rejected_records": {
            name: int(
                np.count_nonzero(a.record_present.values[indices])
                - sensor_indices[name].size
                + (
                    np.count_nonzero(a.pitch_geometry_rejected.values[indices])
                    if "pitch_geometry_rejected" in a.coords
                    else 0
                )
            )
            for name, a in arrays.items()
            if "record_present" in a.coords
        },
        "field_connection_status": "not_evaluated",
    }
    if not arrays:
        return result
    nonempty = [
        a.time.values[sensor_indices[n]].astype("datetime64[ns]").astype("int64") / 1e9
        for n, a in arrays.items()
        if sensor_indices[n].size
    ]
    if len(nonempty) == 2:
        distances = np.abs(nonempty[0][:, None] - nonempty[1][None, :])
        result["sensor_nearest_time_offset_max_seconds"] = float(
            max(np.max(np.min(distances, axis=0)), np.max(np.min(distances, axis=1)))
        )
    reference = next(iter(arrays.values()))
    usable = np.unique(np.concatenate(list(sensor_indices.values())))
    if not usable.size or "field_radial_cosine" not in reference.coords:
        return result
    b = np.column_stack([reference.coords[f"magnetic_{axis}_nT"].values[usable] for axis in "xyz"])
    cosine = reference.field_radial_cosine.values[usable]
    result.update(
        geometry_policy=GEOMETRY_POLICY,
        geometry_sampling="esa_record_centers",
        **_direction_statistics(b),
        field_radial_abs_cosine_min=float(np.min(np.abs(cosine))),
        affected_side_changed=bool(np.any(cosine > 0) and np.any(cosine < 0)),
    )
    return result


def _magnetic_window_diagnostics(
    source: xr.DataArray | None, start: pd.Timestamp, stop: pd.Timestamp
) -> dict[str, Any]:
    if source is None:
        return {}
    times = source.time.values.astype("datetime64[ns]").astype("int64")
    left, right = np.searchsorted(times, [start.value, stop.value])
    values = np.asarray(source.values[left:right], dtype=float)
    norms = np.linalg.norm(values, axis=1)
    valid = np.all(np.isfinite(values), axis=1) & (norms > 0)
    result: dict[str, Any] = dict(
        geometry_sampling="lmag_samples",
        magnetic_samples=int(np.count_nonzero(valid)),
        magnetic_invalid_samples=int(np.count_nonzero(~valid)),
        magnetic_direction_resultant=None,
        magnetic_direction_max_deviation_deg=None,
        magnetic_magnitude_cv=None,
    )
    if np.any(valid):
        result.update(_direction_statistics(values[valid]))
    return result


def _direction_statistics(vectors: FloatArray) -> dict[str, Any]:
    magnitude = np.linalg.norm(vectors, axis=1)
    unit = vectors / magnitude[:, None]
    mean = np.mean(unit, axis=0)
    norm = np.linalg.norm(mean)
    angles = np.degrees(np.arccos(np.clip(unit @ (mean / norm), -1, 1))) if norm > 1e-12 else None
    return dict(
        magnetic_direction_resultant=float(norm),
        magnetic_direction_max_deviation_deg=float(np.max(angles)) if angles is not None else None,
        magnetic_magnitude_cv=float(np.std(magnitude) / np.mean(magnitude)),
    )


def _utc(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).tz_localize("UTC")


def _single_value(values: Any) -> object:
    unique = np.unique(np.asarray(values))
    return unique[0].item() if unique.size == 1 else None


__all__ = [
    "NativeEsaRecords",
    "attach_record_geometry",
    "calendar_windows",
    "field_radial_geometry",
    "native_record_arrays",
    "usable_record_indices",
    "window_input_diagnostic",
    "window_pitch_records",
    "window_record",
    "window_sample_id",
]
