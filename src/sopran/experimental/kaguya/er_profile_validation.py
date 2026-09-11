from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from sopran.core.store import Store
from sopran.core.time import day
from sopran.experimental.electron_reflection import (
    EffectiveFieldFitSettings,
    EffectiveFieldQualitySettings,
    fit_effective_field,
)
from sopran.experimental.kaguya.er import (
    ResolvedSide,
    _energy_values,
    _exposure_array,
    _paired_event,
    _symmetric_pitch_pairs,
    _vectors_at,
    affected_side_from_geometry,
)
from sopran.frames import FrameContext
from sopran.missions.kaguya.geometry import lmag_position
from sopran.missions.kaguya.mission import Kaguya
from sopran.missions.kaguya.pitch import (
    PitchAngleSpectrumOptions,
    build_pitch_angle_spectrum,
)

ProgressCallback = Callable[[int, int, str], None]
ACCEPTED_GRADES = ("good", "review")


@dataclass(frozen=True)
class EffectiveFieldProfileValidation:
    """Resumable profile-likelihood refit result for a selected archive subset."""

    output_path: Path
    summary: dict[str, Any]
    failed_days: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.failed_days and bool(self.summary.get("complete"))


@dataclass(frozen=True)
class _ProfileTask:
    day_label: str
    source_rows: tuple[dict[str, Any], ...]


_WORKER_MISSION: Kaguya | None = None
_WORKER_CONTEXT: FrameContext | None = None
_WORKER_CALIBRATION: Any = None
_WORKER_SETTINGS: EffectiveFieldFitSettings | None = None


def build_effective_field_profile_validation(
    variant_path: Path | str,
    output_path: Path | str,
    *,
    store_path: Path | str,
    fallback_roots: tuple[Path | str, ...] = (),
    frame_context: FrameContext,
    grades: tuple[str, ...] = ACCEPTED_GRADES,
    day_labels: tuple[str, ...] | None = None,
    workers: int | None = None,
    resume: bool = True,
    strict: bool = True,
    progress: ProgressCallback | None = None,
) -> EffectiveFieldProfileValidation:
    """Refit selected rows with profile likelihood while preserving source estimates."""

    variant = Path(variant_path).resolve()
    output = Path(output_path).resolve()
    selected_workers = workers or min(8, os.cpu_count() or 1)
    if selected_workers <= 0:
        raise ValueError("workers must be positive")
    if not grades:
        raise ValueError("grades must not be empty")
    dataset = _read_json(variant / "dataset.json")
    settings = _profile_settings(dataset)
    source = _selected_source_rows(variant, grades=grades)
    if day_labels is not None:
        requested_days = set(day_labels)
        source = source.loc[source["source_day"].astype(str).isin(requested_days)].copy()
        found_days = set(source["source_day"].astype(str))
        if found_days != requested_days:
            missing = ", ".join(sorted(requested_days - found_days))
            raise ValueError(f"requested profile days have no selected rows: {missing}")
    tasks = _profile_tasks(source)
    manifest = {
        "schema_version": 1,
        "kind": "kaguya_er_effective_field_profile_validation",
        "source_variant": str(variant),
        "source_dataset_sha256": _sha256(variant / "dataset.json"),
        "source_catalog_sha256": _sha256(variant / "catalog.parquet"),
        "selected_grades": list(grades),
        "selected_days": None if day_labels is None else list(day_labels),
        "source_rows": len(source),
        "settings": asdict(settings),
        "store_path": str(Path(store_path).resolve()),
        "fallback_roots": [str(Path(path).resolve()) for path in fallback_roots],
        "spice_kernels": [str(Path(path).resolve()) for path in frame_context.spice_kernels],
    }
    output.mkdir(parents=True, exist_ok=True)
    _verify_or_write_manifest(output / "manifest.json", manifest)
    state_path = output / "state.json"
    state = _read_json(state_path) if state_path.exists() else {"days": {}}
    state_days = cast(dict[str, Any], state.setdefault("days", {}))

    pending: list[_ProfileTask] = []
    for task in tasks:
        shard = _profile_shard(output, task.day_label)
        if resume and shard.exists():
            state_days[task.day_label] = {
                "status": "complete",
                "rows": len(pd.read_parquet(shard, columns=["time"])),
            }
        else:
            pending.append(task)
    _write_json_atomic(state_path, state)

    failures: dict[str, str] = {}
    completed = len(tasks) - len(pending)
    if progress is not None:
        progress(completed, len(tasks), "resume")
    if pending:
        with ProcessPoolExecutor(
            max_workers=selected_workers,
            initializer=_initialize_profile_worker,
            initargs=(
                str(Path(store_path).resolve()),
                tuple(str(Path(path).resolve()) for path in fallback_roots),
                tuple(str(Path(path).resolve()) for path in frame_context.spice_kernels),
                asdict(settings),
            ),
        ) as pool:
            future_tasks = {pool.submit(_profile_day, task): task for task in pending}
            for future in as_completed(future_tasks):
                task = future_tasks[future]
                try:
                    records, timing = future.result()
                    frame = pd.DataFrame.from_records(records).sort_values("time")
                    if len(frame) != len(task.source_rows):
                        raise ValueError(
                            "profile row mismatch: "
                            f"expected {len(task.source_rows)}, got {len(frame)}"
                        )
                    _write_parquet_atomic(_profile_shard(output, task.day_label), frame)
                    state_days[task.day_label] = {
                        "status": "complete",
                        "rows": len(frame),
                        **timing,
                    }
                except Exception as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    failures[task.day_label] = message
                    state_days[task.day_label] = {"status": "failed", "message": message}
                completed += 1
                _write_json_atomic(state_path, state)
                if progress is not None:
                    progress(completed, len(tasks), task.day_label)

    catalog = _read_profile_shards(output)
    summary = _profile_summary(
        catalog,
        source_rows=len(source),
        expected_days=len(tasks),
        state_days=state_days,
        failures=failures,
    )
    _write_parquet_atomic(output / "catalog.parquet", catalog)
    _write_json_atomic(output / "summary.json", summary)
    result = EffectiveFieldProfileValidation(
        output_path=output,
        summary=summary,
        failed_days=tuple(sorted(failures)),
    )
    if strict and not result.complete:
        raise RuntimeError(
            "KAGUYA ER profile validation is incomplete: "
            + ", ".join(result.failed_days or ("row coverage mismatch",))
        )
    return result


def _initialize_profile_worker(
    store_path: str,
    fallback_roots: tuple[str, ...],
    spice_kernels: tuple[str, ...],
    settings: dict[str, Any],
) -> None:
    global _WORKER_CALIBRATION, _WORKER_CONTEXT, _WORKER_MISSION, _WORKER_SETTINGS
    _WORKER_MISSION = Kaguya(
        store=Store(store_path),
        fallback_roots=tuple(Path(path) for path in fallback_roots),
        download="never",
    )
    _WORKER_CONTEXT = FrameContext(
        spice_kernels=tuple(Path(path) for path in spice_kernels),
        default_backend="spiceypy",
    )
    _WORKER_CALIBRATION = _WORKER_MISSION.esa1.load_calibration(download="never")
    _WORKER_SETTINGS = _settings_from_payload(settings)


def _profile_day(task: _ProfileTask) -> tuple[list[dict[str, Any]], dict[str, float]]:
    from time import perf_counter

    if (
        _WORKER_MISSION is None
        or _WORKER_CONTEXT is None
        or _WORKER_SETTINGS is None
        or _WORKER_CALIBRATION is None
    ):
        raise RuntimeError("profile worker was not initialized")
    started = perf_counter()
    selected_time = day(task.day_label)
    pace = _WORKER_MISSION.esa1.load(
        selected_time,
        calibration=_WORKER_CALIBRATION,
        download="never",
        missing="error",
    )
    lmag = _WORKER_MISSION.lmag.load(selected_time, download="never", missing="error")
    spectrum = build_pitch_angle_spectrum(
        pace=pace.pace,
        time=selected_time,
        calibration=_WORKER_CALIBRATION,
        magnetic_field=lmag.magnetic_field,
        files=pace.files,
        options=PitchAngleSpectrumOptions(
            value="counts",
            pitch_bins=16,
            look_frame="SELENE_M_SPACECRAFT",
            min_look_bins=1,
            cadence_seconds=600.0,
        ),
        frame_context=_WORKER_CONTEXT,
    )
    array = spectrum.to_xarray()
    times = np.asarray(array.coords["time"].values, dtype="datetime64[ns]")
    time_index = {int(value.astype(np.int64)): index for index, value in enumerate(times)}
    magnetic = _vectors_at(lmag.magnetic_field, times, "magnetic_field")
    position = _vectors_at(lmag_position(lmag), times, "position")
    sides = affected_side_from_geometry(magnetic, position)
    pitch = np.asarray(array.coords["pitch_angle"].values, dtype=float)
    low, high, folded = _symmetric_pitch_pairs(pitch)
    energy = _energy_values(array)
    counts = np.asarray(array.values, dtype=float)
    exposure, exposure_mode = _exposure_array(array, None, counts)
    reconstructed_seconds = perf_counter() - started

    records: list[dict[str, Any]] = []
    fit_started = perf_counter()
    for source in task.source_rows:
        timestamp = pd.Timestamp(source["time"])
        key = int(timestamp.value)
        if key not in time_index:
            raise KeyError(f"source time is absent from rebuilt spectrum: {timestamp.isoformat()}")
        index = time_index[key]
        event = _paired_event(
            energy_eV=energy[index],
            folded_pitch=folded,
            counts=counts[index],
            exposure=exposure[index],
            low_indices=low,
            high_indices=high,
            b_sc_nT=float(np.linalg.norm(magnetic[index])),
            affected_side=cast(ResolvedSide, str(sides[index])),
            time_value=times[index],
            exposure_assumed_equal=exposure_mode == "assumed_equal",
            exposure_mode=exposure_mode,
        )
        estimate = fit_effective_field(event, settings=_WORKER_SETTINGS)
        record = {f"refit_{name}": value for name, value in estimate.to_record().items()}
        record.update(
            {
                "time": timestamp,
                "source_day": task.day_label,
                "source_quality_grade": source["quality_grade"],
                "source_selected_model": source["selected_model"],
                "source_reason": source["reason"],
                "source_affected_side": source["affected_side"],
                "source_mirror_ratio": source["mirror_ratio"],
                "source_effective_field": source["effective_field"],
                "source_b_sc_nT": source["b_sc_nT"],
                "refit_affected_side": str(sides[index]),
                "refit_b_sc_nT": float(np.linalg.norm(magnetic[index])),
            }
        )
        records.append(record)
    return records, {
        "reconstruction_seconds": reconstructed_seconds,
        "fit_seconds": perf_counter() - fit_started,
    }


def _profile_settings(dataset: dict[str, Any]) -> EffectiveFieldFitSettings:
    payload = dataset.get("parameters", {}).get("effective_field_fit")
    if not isinstance(payload, dict):
        raise ValueError("source dataset does not record effective_field_fit settings")
    settings = _settings_from_payload(payload)
    return EffectiveFieldFitSettings(
        **{
            **asdict(settings),
            "profile_likelihood": True,
            "quality": settings.quality,
        }
    )


def _settings_from_payload(payload: dict[str, Any]) -> EffectiveFieldFitSettings:
    values = dict(payload)
    quality_payload = values.pop("quality", {})
    quality = (
        quality_payload
        if isinstance(quality_payload, EffectiveFieldQualitySettings)
        else EffectiveFieldQualitySettings(**quality_payload)
    )
    return EffectiveFieldFitSettings(**values, quality=quality)


def _selected_source_rows(variant: Path, *, grades: tuple[str, ...]) -> pd.DataFrame:
    columns = [
        "time",
        "source_day",
        "quality_grade",
        "selected_model",
        "reason",
        "affected_side",
        "mirror_ratio",
        "effective_field",
        "b_sc_nT",
    ]
    frames = [
        pd.read_parquet(path, columns=columns)
        for path in sorted((variant / "shards").rglob("*.parquet"))
    ]
    if not frames:
        raise ValueError(f"source variant contains no shards: {variant}")
    frame = pd.concat(frames, ignore_index=True)
    frame = frame.loc[frame["quality_grade"].astype(str).isin(grades)].copy()
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.sort_values("time", ignore_index=True)


def _profile_tasks(source: pd.DataFrame) -> list[_ProfileTask]:
    tasks: list[_ProfileTask] = []
    for label, frame in source.groupby("source_day", sort=True):
        records = tuple(cast(list[dict[str, Any]], frame.to_dict("records")))
        tasks.append(_ProfileTask(str(label), records))
    return tasks


def _profile_summary(
    frame: pd.DataFrame,
    *,
    source_rows: int,
    expected_days: int,
    state_days: dict[str, Any],
    failures: dict[str, str],
) -> dict[str, Any]:
    completed_days = sum(
        1
        for value in state_days.values()
        if isinstance(value, dict) and value.get("status") == "complete"
    )
    interval = np.isfinite(
        frame["refit_mirror_ratio_ci95_low"].to_numpy(dtype=float)
    ) & np.isfinite(frame["refit_mirror_ratio_ci95_high"].to_numpy(dtype=float))
    mirror = frame["refit_mirror_ratio"].to_numpy(dtype=float)
    lower = frame["refit_mirror_ratio_ci95_low"].to_numpy(dtype=float)
    upper = frame["refit_mirror_ratio_ci95_high"].to_numpy(dtype=float)
    relative_width = np.divide(
        upper - lower,
        mirror,
        out=np.full(mirror.shape, np.nan),
        where=interval & (mirror > 0.0),
    )
    source_mirror = frame["source_mirror_ratio"].to_numpy(dtype=float)
    relative_change = np.divide(
        np.abs(mirror - source_mirror),
        source_mirror,
        out=np.full(mirror.shape, np.nan),
        where=np.isfinite(mirror) & np.isfinite(source_mirror) & (source_mirror > 0.0),
    )
    quality_match = (
        frame["refit_quality_grade"].astype(str).eq(frame["source_quality_grade"].astype(str))
    )
    model_match = (
        frame["refit_selected_model"].astype(str).eq(frame["source_selected_model"].astype(str))
    )
    truncated = frame["refit_profile_truncated"].fillna(False).to_numpy(dtype=bool)
    return {
        "complete": not failures and completed_days == expected_days and len(frame) == source_rows,
        "source_rows": source_rows,
        "rows": len(frame),
        "expected_days": expected_days,
        "completed_days": completed_days,
        "failed_days": failures,
        "refit_quality_counts": _counts(frame["refit_quality_grade"]),
        "quality_grade_matches": int(quality_match.sum()),
        "quality_grade_match_fraction": float(quality_match.mean()) if len(frame) else float("nan"),
        "selected_model_matches": int(model_match.sum()),
        "selected_model_match_fraction": float(model_match.mean()) if len(frame) else float("nan"),
        "profile_interval_rows": int(np.count_nonzero(interval)),
        "profile_interval_fraction": float(np.mean(interval)) if len(frame) else float("nan"),
        "profile_truncated_rows": int(np.count_nonzero(truncated)),
        "profile_truncated_fraction": float(np.mean(truncated)) if len(frame) else float("nan"),
        "profile_relative_width": _distribution(relative_width),
        "source_refit_relative_change": _distribution(relative_change),
        "relative_width_le_0_5": int(np.count_nonzero(relative_width <= 0.5)),
        "relative_width_le_1_0": int(np.count_nonzero(relative_width <= 1.0)),
        "created_utc": datetime.now(UTC).isoformat(),
    }


def _read_profile_shards(output: Path) -> pd.DataFrame:
    paths = sorted((output / "shards").rglob("*.parquet"))
    return pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True).sort_values(
        "time",
        ignore_index=True,
    )


def _profile_shard(output: Path, label: str) -> Path:
    return output / "shards" / f"date={label}" / "part-000.parquet"


def _verify_or_write_manifest(path: Path, expected: dict[str, Any]) -> None:
    if path.exists():
        current = _read_json(path)
        comparable = {key: value for key, value in current.items() if key != "created_utc"}
        if comparable != expected:
            raise ValueError(f"profile validation manifest does not match requested run: {path}")
        return
    _write_json_atomic(path, {**expected, "created_utc": datetime.now(UTC).isoformat()})


def _write_parquet_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _distribution(values: np.ndarray) -> dict[str, Any]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not finite.size:
        return {"n": 0, "p10": None, "median": None, "p90": None, "p99": None}
    return {
        "n": int(finite.size),
        "p10": float(np.percentile(finite, 10.0)),
        "median": float(np.percentile(finite, 50.0)),
        "p90": float(np.percentile(finite, 90.0)),
        "p99": float(np.percentile(finite, 99.0)),
    }


def _counts(values: pd.Series) -> dict[str, int]:
    return {str(key): int(value) for key, value in values.value_counts().sort_index().items()}


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


__all__ = [
    "EffectiveFieldProfileValidation",
    "build_effective_field_profile_validation",
]
