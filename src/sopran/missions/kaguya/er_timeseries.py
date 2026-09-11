from __future__ import annotations

import hashlib
import json
import time as time_module
from collections.abc import Callable, Mapping
from concurrent.futures import (
    ALL_COMPLETED,
    FIRST_COMPLETED,
    Future,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    wait,
)
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import pandas as pd

from sopran.analysis.electron_reflection import (
    GlobalJointFitSettings,
    GlobalPitchCountObservation,
    fit_global_joint_effective_field,
)
from sopran.missions.kaguya.er_geometry import GEOMETRY_POLICY, geometry_support, load_lmag_for_er
from sopran.missions.kaguya.geometry import lmag_position
from sopran.missions.kaguya.pitch import CountCorrection, _datetime64_from_unix
from sopran.missions.kaguya.schema import KAGUYA_ER_SCHEMA

if TYPE_CHECKING:
    from sopran.core.time import TimeRange
    from sopran.frames import FrameContext
    from sopran.missions.kaguya.er import EffectiveFieldEndpoint, KaguyaEffectiveFieldData

CacheMode = Literal["use", "refresh", "never"]
DownloadMode = Literal["never", "missing", "always"]
ParallelExecutor = Literal["thread", "process"]


@dataclass(frozen=True)
class _FitTask:
    base: dict[str, object]
    observations: Mapping[str, GlobalPitchCountObservation]
    settings: GlobalJointFitSettings


def fit_effective_field_timeseries(
    endpoint: EffectiveFieldEndpoint,
    time: TimeRange,
    *,
    integration: str | float = "16s",
    pitch_bins: int = 16,
    min_window_coverage: float = 0.5,
    settings: GlobalJointFitSettings | None = None,
    count_correction: CountCorrection = "event_trash",
    workers: int | None = None,
    executor: ParallelExecutor = "process",
    download: DownloadMode | None = None,
    frame_context: FrameContext | None = None,
    max_time_offset_seconds: float = 1.0,
    native_cadence_seconds: float = 2.0,
    cache: CacheMode = "use",
    dataset_id: str = "kaguya.er.global_joint_effective_field",
    layer: str = "features",
    progress: Callable[[int, int], None] | None = None,
) -> KaguyaEffectiveFieldData:
    """Fit one S1/S2 global ER model per fixed UTC integration window.

    Native records remain separate negative-binomial likelihood terms while
    sharing physical and per-sensor parameters within each window. This keeps
    the half-step offset between increasing and decreasing PACE energy sweeps.
    Empty windows and windows mixing PACE modes remain in the result with an
    explicit skip reason. Sparse or irregularly sampled windows are passed to
    the count likelihood; their support is assessed from the available cells.
    """

    from sopran.missions.kaguya.er import (
        KaguyaEffectiveFieldData,
        _read_cached_effective_field,
        _vectors_at,
    )

    integration_seconds = _duration_seconds(integration)
    if not 0.0 < min_window_coverage <= 1.0:
        raise ValueError("min_window_coverage must be in (0, 1]")
    if max_time_offset_seconds < 0.0:
        raise ValueError("max_time_offset_seconds must be non-negative")
    if not np.isfinite(native_cadence_seconds) or native_cadence_seconds <= 0.0:
        raise ValueError("native_cadence_seconds must be finite and positive")
    if cache not in {"use", "refresh", "never"}:
        raise ValueError("cache must be 'use', 'refresh', or 'never'")
    if executor not in {"thread", "process"}:
        raise ValueError("executor must be 'thread' or 'process'")
    resolved_workers = workers if workers is not None else 1
    if resolved_workers <= 0:
        raise ValueError("workers must be positive")
    settings = settings or GlobalJointFitSettings(edge_transition="hard")
    mission = endpoint.instrument.mission
    resolved_download = getattr(mission, "download", "never") if download is None else download
    resolved_frame_context = frame_context
    if resolved_frame_context is None and hasattr(mission, "source"):
        from sopran.frames import FrameContext
        from sopran.missions.kaguya.spice import selene_spice_kernels

        resolved_frame_context = FrameContext(
            spice_kernels=selene_spice_kernels(
                mission.store,
                time,
                download=resolved_download,
            ),
            default_backend="spiceypy",
        )
    calibration_files: tuple[Path, ...] = tuple(
        dict.fromkeys(
            path
            for instrument_name in ("esa1", "esa2")
            for path in _calibration_files(
                getattr(mission, instrument_name, None),
                download=resolved_download,
            )
        )
    )
    spectra = endpoint.instrument.pitch_angle_spectra(
        time,
        cadence_seconds=None,
        pitch_bins=pitch_bins,
        count_correction=count_correction,
        download=download,
        frame_context=resolved_frame_context,
        max_time_offset_seconds=max_time_offset_seconds,
        align=False,
    )
    if len(spectra) < 2:
        raise ValueError("16-second global ER fitting requires both ESA-S1 and ESA-S2")
    arrays = _native_record_arrays(
        {name: spectrum.to_xarray() for name, spectrum in spectra.items()}
    )
    reference = next(iter(arrays.values()))
    record_times = np.asarray(reference.coords["time"].values, dtype="datetime64[ns]")
    geometry_series = None
    if record_times.size:
        lmag = load_lmag_for_er(mission.lmag, time, download=download)
        magnetic = _vectors_at(lmag.magnetic_field, record_times, "magnetic_field")
        position = _vectors_at(lmag_position(lmag), record_times, "position")
        _, sides, _ = geometry_support(magnetic, position)
        b_sc = np.linalg.norm(magnetic, axis=1)
        lmag_files = tuple(getattr(lmag, "files", ()))
        geometry_series = lmag.magnetic_field.to_xarray()
    else:
        magnetic = np.empty((0, 3), dtype=float)
        position = np.empty((0, 3), dtype=float)
        sides = np.asarray([], dtype=str)
        b_sc = np.asarray([], dtype=float)
        lmag_files = ()
    arrays = _attach_geometry(arrays, magnetic, position)
    files = tuple(
        dict.fromkeys(
            path
            for source_files in (
                *(spectrum.files for spectrum in spectra.values()),
                lmag_files,
                calibration_files,
                tuple(getattr(resolved_frame_context, "spice_kernels", ())),
            )
            for path in source_files
        )
    )
    input_fingerprint = _input_fingerprint(
        files=files,
        arrays=arrays,
        magnetic=magnetic,
        position=position,
        frame_context=resolved_frame_context,
    )
    variant_id = _variant_id(
        integration_seconds=integration_seconds,
        pitch_bins=pitch_bins,
        min_window_coverage=min_window_coverage,
        max_time_offset_seconds=max_time_offset_seconds,
        native_cadence_seconds=native_cadence_seconds,
        count_correction=count_correction,
        settings=settings,
        time=time,
        input_fingerprint=input_fingerprint,
    )
    if cache == "use":
        cached = _read_cached_effective_field(
            mission.store,
            dataset_id=dataset_id,
            layer=layer,
            variant_id=variant_id,
            time=time,
        )
        if cached is not None and not cached.frame.empty:
            return replace(cached, files=tuple(Path(path) for path in files))
    expected_records = max(1, int(round(integration_seconds / native_cadence_seconds)))
    minimum_records = max(1, int(np.ceil(expected_records * min_window_coverage)))

    rows: list[dict[str, object]] = []
    groups = _window_groups(record_times, integration_seconds, time=time)
    total_windows = len(groups)
    completed = 0
    pool = None
    pending: dict[Future[dict[str, object]], None] = {}

    def record_completed(row: dict[str, object]) -> None:
        nonlocal completed
        rows.append(row)
        completed += 1
        if progress is not None:
            progress(completed, total_windows)

    def drain(*, all_pending: bool) -> None:
        if not pending:
            return
        done, _ = wait(
            tuple(pending),
            return_when=(FIRST_COMPLETED if not all_pending else ALL_COMPLETED),
        )
        for future in done:
            del pending[future]
            record_completed(future.result())

    if resolved_workers > 1:
        executor_class = ThreadPoolExecutor if executor == "thread" else ProcessPoolExecutor
        pool = executor_class(max_workers=resolved_workers)
    try:
        for window_id, indices in groups:
            base = _window_record(
                window_id,
                indices,
                record_times=record_times,
                integration_seconds=integration_seconds,
                native_cadence_seconds=native_cadence_seconds,
                expected_records=expected_records,
                minimum_records=minimum_records,
                min_window_coverage=min_window_coverage,
                b_sc=b_sc,
                sides=sides,
                arrays=arrays,
                count_correction=count_correction,
                geometry_series=geometry_series,
            )
            skip_reason = _window_skip_reason(
                indices,
                arrays=arrays,
            )
            if skip_reason is not None:
                record_completed({**base, **_empty_fit_record("skipped", skip_reason)})
                continue
            observations: dict[str, GlobalPitchCountObservation] = {}
            for sensor_name, spectrum in arrays.items():
                for record_index in _usable_record_indices(spectrum, indices):
                    key = f"{sensor_name}:{int(record_index)}"
                    observations[key] = replace(
                        GlobalPitchCountObservation.from_spectrum(
                            spectrum,
                            index=int(record_index),
                            b_sc_nT=float(b_sc[record_index]),
                            affected_side=str(sides[record_index]),
                        ),
                        sensor_group=sensor_name,
                    )
            for observation in observations.values():
                exposure_mode = (observation.metadata or {}).get("exposure_mode")
                if exposure_mode != "calibrated":
                    raise RuntimeError(
                        "ER time-series fitting requires calibrated exposure; "
                        f"received {exposure_mode!r}"
                    )
            task = _FitTask(base=base, observations=observations, settings=settings)
            if pool is None:
                record_completed(_fit_task(task))
            else:
                pending[pool.submit(_fit_task, task)] = None
                if len(pending) >= 2 * resolved_workers:
                    drain(all_pending=False)
        while pending:
            drain(all_pending=True)
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=False)

    frame = pd.DataFrame(rows).sort_values("time", ignore_index=True)
    result = KaguyaEffectiveFieldData(
        frame=frame,
        time=time,
        files=files,
        variant_id=variant_id,
    )
    if cache != "never" and not frame.empty:
        _write_timeseries(
            result,
            mission.store,
            dataset_id=dataset_id,
            layer=layer,
            variant_id=variant_id,
            integration_seconds=integration_seconds,
            min_window_coverage=min_window_coverage,
            pitch_bins=pitch_bins,
            count_correction=count_correction,
            settings=settings,
            overwrite=True,
        )
    return result


def _fit_task(task: _FitTask) -> dict[str, object]:
    started = time_module.perf_counter()
    try:
        estimate = fit_global_joint_effective_field(
            task.observations,
            settings=task.settings,
        )
    except Exception as exc:
        return {
            **task.base,
            **_empty_fit_record("failed", f"{type(exc).__name__}: {exc}"),
            "fit_seconds": time_module.perf_counter() - started,
        }
    record = estimate.to_record()
    record.update(
        {
            "fit_status": "complete",
            "fit_error": "",
            "fit_seconds": time_module.perf_counter() - started,
            "effective_field": estimate.effective_field_nT,
            "delta_u_eff": estimate.delta_u_eff_eV,
            "b_sc_nT": estimate.representative_b_sc_nT,
            "quality_grade": (
                "good" if estimate.success and estimate.edge_supported else "diagnostic"
            ),
        }
    )
    return {**task.base, **record}


def _duration_seconds(value: str | float) -> float:
    seconds = (
        float(value)
        if isinstance(value, int | float)
        else pd.Timedelta(value).total_seconds()
    )
    if not np.isfinite(seconds) or seconds <= 0.0:
        raise ValueError("integration must be a finite positive duration")
    return seconds


def _calibration_files(
    instrument: Any,
    *,
    download: DownloadMode,
) -> tuple[Path, ...]:
    resolver = getattr(instrument, "calibration_files", None)
    if not callable(resolver):
        return ()
    return tuple(Path(path) for path in resolver(download=download))


def _window_groups(
    times: np.ndarray,
    integration_seconds: float,
    *,
    time: TimeRange,
) -> list[tuple[int, np.ndarray]]:
    width_ns = int(round(integration_seconds * 1.0e9))
    window_ids = times.astype("datetime64[ns]").astype("int64") // width_ns
    start_ns = pd.Timestamp(time.start).value
    stop_ns = pd.Timestamp(time.stop).value
    first_window = start_ns // width_ns
    final_window = (stop_ns - 1) // width_ns
    return [
        (int(window_id), np.flatnonzero(window_ids == window_id))
        for window_id in range(first_window, final_window + 1)
        if start_ns <= window_id * width_ns + width_ns // 2 < stop_ns
    ]


def _window_record(
    window_id: int,
    indices: np.ndarray,
    *,
    record_times: np.ndarray,
    integration_seconds: float,
    native_cadence_seconds: float,
    expected_records: int,
    minimum_records: int,
    b_sc: np.ndarray,
    sides: np.ndarray,
    arrays: Mapping[str, Any],
    count_correction: CountCorrection,
    min_window_coverage: float | None = None,
    geometry_series: Any | None = None,
) -> dict[str, object]:
    width_ns = int(round(integration_seconds * 1.0e9))
    start = pd.Timestamp(window_id * width_ns, unit="ns", tz="UTC")
    stop = start + pd.Timedelta(seconds=integration_seconds)
    sensor_indices = {name: _usable_record_indices(a, indices) for name, a in arrays.items()}
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
    first_record_time = (
        pd.Timestamp(record_times[usable[0]]).tz_localize("UTC")
        if usable.size
        else None
    )
    last_record_time = (
        pd.Timestamp(record_times[usable[-1]]).tz_localize("UTC")
        if usable.size
        else None
    )
    gaps = (
        np.diff(record_times[usable].astype("datetime64[ns]").astype("int64"))
        / 1.0e9
    )
    durations = [
        np.asarray(a.coords["record_duration_seconds"].values[sensor_indices[name]], dtype=float)
        for name, a in arrays.items()
        if "record_duration_seconds" in a.coords and sensor_indices[name].size
    ]
    if indices.size and len(durations) == len(arrays) and durations:
        all_durations = np.concatenate(durations)
        if np.all(np.isfinite(all_durations) & (all_durations > 0)):
            # Coverage is diagnostic; retain the slower sensor as the reference.
            native_cadence_seconds = max(float(np.median(d)) for d in durations)
            expected_records = max(1, int(np.ceil(integration_seconds / native_cadence_seconds)))
            if min_window_coverage is not None:
                minimum_records = max(1, int(np.ceil(expected_records * min_window_coverage)))
    return {
        "time": start + (stop - start) / 2,
        "window_start": start,
        "window_stop": stop,
        "integration_seconds": integration_seconds,
        "native_cadence_seconds": native_cadence_seconds,
        "records_integrated": int(usable.size),
        "input_record_timestamps": int(indices.size),
        "expected_records": expected_records,
        "minimum_records": minimum_records,
        "window_coverage": float(
            min((i.size for i in sensor_indices.values()), default=0) / expected_records
        ),
        "first_record_time": first_record_time,
        "last_record_time": last_record_time,
        "affected_side": _single_value(sides[usable]) if usable.size else None,
        "affected_side_changed": bool(
            usable.size and np.unique(sides[usable]).size > 1
        ),
        "max_record_gap_seconds": float(np.max(gaps)) if gaps.size else None,
        "b_sc_nT": float(np.median(b_sc[usable])) if usable.size else None,
        "record_time_median_b_sc_nT": float(np.median(b_sc[usable])) if usable.size else None,
        "b_sc_std_nT": float(np.std(b_sc[usable])) if usable.size else None,
        "count_correction": count_correction,
        **_window_geometry_diagnostics(arrays, indices, sensor_indices),
        **_magnetic_window_diagnostics(geometry_series, start, stop),
        **modes,
    }


def _window_skip_reason(
    indices: np.ndarray,
    *,
    arrays: Mapping[str, Any],
) -> str | None:
    if indices.size == 0:
        return "no_records"
    for name, array in arrays.items():
        selected = _usable_record_indices(array, indices)
        if selected.size == 0:
            if (
                ("record_present" in array.coords and np.any(array.record_present.values[indices]))
                or ("pitch_geometry_rejected" in array.coords
                    and np.any(array.pitch_geometry_rejected.values[indices]))
            ):
                return f"{name}_geometry_unavailable"
            return f"{name}_no_records"
        for coordinate in ("pace_data_type", "pace_submode", "pace_svs_tbl"):
            if (
                coordinate in array.coords
                and np.unique(array.coords[coordinate].values[selected]).size > 1
            ):
                return f"{name}_{coordinate}_changed"
        if "pace_data_mode" in array.coords:
            modes = np.asarray(array.coords["pace_data_mode"].values[selected])
            # TOF/POS check commands change the ions, not the ESA EC-N response.
            ion_checks_only = np.all(np.isin(modes, (0x11, 0x12)))
            if np.unique(modes).size != 1 and not ion_checks_only:
                return f"{name}_pace_data_mode_changed"
    return None


def _native_record_arrays(arrays: Mapping[str, Any]) -> dict[str, Any]:
    """Index native sensor records on the union of times without synthesizing data.

    NaN padding is only an index convenience; record_present controls which
    rows are observations. Counts, energies and exposure are never interpolated.
    """
    rejected = {
        name: np.array([_datetime64_from_unix(t)
                        for t in a.attrs.get("geometry_rejected_times_unix", ())],
                       dtype="datetime64[ns]")
        for name, a in arrays.items()
    }
    times = np.unique(np.concatenate([
        *[a.time.values for a in arrays.values()], *rejected.values()
    ]))
    result = {}
    for name, array in arrays.items():
        if (
            np.any(np.isnat(array.time.values))
            or np.unique(array.time.values).size != array.sizes["time"]
        ):
            raise ValueError(f"{name} native record times must be finite and unique")
        result[name] = array.reindex(time=times).assign_coords(
            record_present=("time", np.isin(times, array.time.values)),
            pitch_geometry_rejected=("time", np.isin(times, rejected[name])),
        ).assign_attrs(sensor_time_policy="independent_native", geometry_policy=GEOMETRY_POLICY)
    return result


def _attach_geometry(
    arrays: Mapping[str, Any], magnetic: np.ndarray, position: np.ndarray,
) -> dict[str, Any]:
    valid, _, cosine = geometry_support(magnetic, position)
    coords = {"geometry_valid": ("time", valid), "field_radial_cosine": ("time", cosine)}
    coords.update({f"magnetic_{axis}_nT": ("time", magnetic[:, i]) for i, axis in enumerate("xyz")})
    result = {name: a.assign_coords(coords) for name, a in arrays.items()}
    for array in result.values():
        for name in coords:
            array.coords[name].attrs["units"] = "nT" if name.startswith("magnetic_") else "1"
    return result


def _usable_record_indices(array: Any, indices: np.ndarray) -> np.ndarray:
    valid = np.ones(indices.size, dtype=bool)
    for name in ("record_present", "geometry_valid"):
        if name in array.coords:
            valid &= np.asarray(array.coords[name].values[indices], dtype=bool)
    return indices[valid]


def _window_geometry_diagnostics(
    arrays: Mapping[str, Any], indices: np.ndarray, sensor_indices: Mapping[str, np.ndarray],
) -> dict[str, object]:
    result: dict[str, object] = {
        "sensor_records": {name: int(idx.size) for name, idx in sensor_indices.items()},
        "geometry_rejected_records": {
            name: int(
                np.count_nonzero(a.record_present.values[indices]) - sensor_indices[name].size
                + (np.count_nonzero(a.pitch_geometry_rejected.values[indices])
                   if "pitch_geometry_rejected" in a.coords else 0)
            )
            for name, a in arrays.items() if "record_present" in a.coords
        },
        "field_connection_status": "not_evaluated",
    }
    if not arrays:
        return result
    nonempty = [a.time.values[sensor_indices[n]].astype("datetime64[ns]").astype("int64") / 1e9
                for n, a in arrays.items() if sensor_indices[n].size]
    if len(nonempty) == 2:
        distances = np.abs(nonempty[0][:, None] - nonempty[1][None, :])
        result["sensor_nearest_time_offset_max_seconds"] = float(max(
            np.max(np.min(distances, axis=0)), np.max(np.min(distances, axis=1))
        ))
    reference = next(iter(arrays.values()))
    usable = np.unique(np.concatenate(list(sensor_indices.values())))
    if not usable.size or "field_radial_cosine" not in reference.coords:
        return result
    b = np.column_stack([reference.coords[f"magnetic_{axis}_nT"].values[usable] for axis in "xyz"])
    magnitude = np.linalg.norm(b, axis=1)
    unit = b / magnitude[:, None]
    mean = np.mean(unit, axis=0)
    norm = np.linalg.norm(mean)
    angles = np.degrees(np.arccos(np.clip(unit @ (mean / norm), -1, 1))) if norm > 1e-12 else None
    cosine = reference.field_radial_cosine.values[usable]
    result.update(
        geometry_policy=GEOMETRY_POLICY,
        geometry_sampling="esa_record_centers",
        magnetic_direction_resultant=float(norm),
        magnetic_direction_max_deviation_deg=float(np.max(angles)) if angles is not None else None,
        magnetic_magnitude_cv=float(np.std(magnitude) / np.mean(magnitude)),
        field_radial_abs_cosine_min=float(np.min(np.abs(cosine))),
        affected_side_changed=bool(np.any(cosine > 0) and np.any(cosine < 0)),
    )
    return result


def _magnetic_window_diagnostics(
    source: Any | None, start: pd.Timestamp, stop: pd.Timestamp,
) -> dict[str, object]:
    if source is None:
        return {}
    times = source.time.values.astype("datetime64[ns]").astype("int64")
    left, right = np.searchsorted(times, [start.value, stop.value])
    values = np.asarray(source.values[left:right], dtype=float)
    norms = np.linalg.norm(values, axis=1)
    valid = np.all(np.isfinite(values), axis=1) & (norms > 0)
    result: dict[str, object] = dict(
        geometry_sampling="lmag_samples",
        magnetic_samples=int(np.count_nonzero(valid)),
        magnetic_invalid_samples=int(np.count_nonzero(~valid)),
        magnetic_direction_resultant=None,
        magnetic_direction_max_deviation_deg=None,
        magnetic_magnitude_cv=None,
    )
    if np.any(valid):
        unit = values[valid] / norms[valid, None]
        mean = np.mean(unit, axis=0)
        norm = np.linalg.norm(mean)
        angles = (
            np.degrees(np.arccos(np.clip(unit @ (mean / norm), -1, 1)))
            if norm > 1e-12 else None
        )
        result.update(
            magnetic_direction_resultant=float(norm),
            magnetic_direction_max_deviation_deg=(
                float(np.max(angles)) if angles is not None else None
            ),
            magnetic_magnitude_cv=float(np.std(norms[valid]) / np.mean(norms[valid])),
        )
    return result


def _single_value(values: Any) -> object:
    unique = np.unique(np.asarray(values))
    return unique[0].item() if unique.size == 1 else None


def _empty_fit_record(status: str, error: str) -> dict[str, object]:
    return {
        "fit_status": status,
        "fit_error": error,
        "fit_seconds": 0.0,
        "success": False,
        "reason": error,
        "selected_model": None,
        "edge_supported": False,
        "mirror_ratio": None,
        "effective_field_nT": None,
        "effective_field": None,
        "delta_u_eff_eV": None,
        "delta_u_eff": None,
        "quality_grade": "not_fitted",
    }


def _input_fingerprint(
    *,
    files: tuple[Any, ...],
    arrays: Mapping[str, Any],
    magnetic: np.ndarray,
    position: np.ndarray,
    frame_context: FrameContext | None,
) -> str:
    digest = hashlib.sha256()
    file_records: list[dict[str, object]] = []
    for value in files:
        path = Path(value).expanduser().resolve()
        try:
            stat = path.stat()
        except OSError:
            file_records.append({"path": path.as_posix(), "missing": True})
        else:
            file_records.append(
                {
                    "path": path.as_posix(),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
    context = None
    if frame_context is not None:
        context = {
            "time_scale": frame_context.time_scale,
            "default_backend": frame_context.default_backend,
            "spice_kernels": [
                Path(path).expanduser().resolve().as_posix()
                for path in frame_context.spice_kernels
            ],
        }
    digest.update(
        json.dumps(
            {"files": sorted(file_records, key=lambda item: str(item["path"])), "frame": context},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    for name in sorted(arrays):
        array = arrays[name]
        digest.update(name.encode("utf-8"))
        digest.update(
            json.dumps(
                {
                    key: array.attrs.get(key)
                    for key in (
                        "count_correction",
                        "count_correction_order",
                        "excluded_pace_data_modes",
                        "look_frame",
                        "pace_data_mode_policy",
                        "geometry_policy",
                        "sensor_time_policy",
                    )
                }
                | {
                    "exposure_mode": array.coords["exposure"].attrs.get("mode")
                    if "exposure" in array.coords
                    else None
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
        for coordinate in (
            "time",
            "energy_eV",
            "pitch_angle",
            "exposure",
            "pace_data_mode",
            "pace_data_type",
            "pace_submode",
            "pace_svs_tbl",
            "pace_data_quality",
            "record_duration_seconds",
            "integration_time_seconds",
            "detector_samples",
            "record_present",
            "geometry_valid",
            "pitch_geometry_rejected",
        ):
            if coordinate in array.coords:
                _update_array_digest(digest, array.coords[coordinate].values)
        _update_array_digest(digest, array.values)
    _update_array_digest(digest, magnetic)
    _update_array_digest(digest, position)
    return digest.hexdigest()


def _update_array_digest(digest: Any, values: Any) -> None:
    array = np.ascontiguousarray(np.asarray(values))
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(json.dumps(array.shape, separators=(",", ":")).encode("ascii"))
    digest.update(array.tobytes())


def _variant_id(
    *,
    time: TimeRange,
    integration_seconds: float,
    pitch_bins: int,
    min_window_coverage: float,
    max_time_offset_seconds: float,
    native_cadence_seconds: float,
    count_correction: CountCorrection,
    settings: GlobalJointFitSettings,
    input_fingerprint: str,
) -> str:
    payload = {
        "model_family": "global_joint_counts_timeseries",
        "model_version": 7,
        "time_start": time.start_iso,
        "time_stop": time.stop_iso,
        "integration_seconds": integration_seconds,
        "pitch_bins": pitch_bins,
        "min_window_coverage": min_window_coverage,
        "max_time_offset_seconds": max_time_offset_seconds,
        "native_cadence_seconds": native_cadence_seconds,
        "count_correction": count_correction,
        "settings": asdict(settings),
        "input_fingerprint": input_fingerprint,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    return f"global_joint_timeseries_v7_{digest}"


def _write_timeseries(
    data: KaguyaEffectiveFieldData,
    store: Any,
    *,
    dataset_id: str,
    layer: str,
    variant_id: str,
    integration_seconds: float,
    min_window_coverage: float,
    pitch_bins: int,
    count_correction: CountCorrection,
    settings: GlobalJointFitSettings,
    overwrite: bool,
) -> None:
    parameters = {
        "integration_seconds": integration_seconds,
        "min_window_coverage": min_window_coverage,
        "pitch_bins": pitch_bins,
        "count_correction": count_correction,
        "fit_settings": asdict(settings),
    }
    store.write_parquet_dataset(
        dataset_id=dataset_id,
        layer=layer,
        variant_id=variant_id,
        variant={"model_family": "global_joint_counts_timeseries", **parameters},
        mission="kaguya",
        instrument="er",
        product="effective_field",
        schema=KAGUYA_ER_SCHEMA,
        time_coverage=data.time,
        frame=data.to_polars(),
        source_files=tuple(str(Path(path)) for path in data.files),
        source_datasets=(
            "kaguya.pace.pitch_angle_spectrum",
            "kaguya.lmag.magnetic_field",
            "kaguya.orbit.position",
        ),
        overwrite=overwrite,
        append=False,
        producer="sopran.kaguya.er.global_joint_timeseries",
        parameters=parameters,
        status="candidate",
    )
