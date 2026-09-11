from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.error import HTTPError

import numpy as np
import pandas as pd

from sopran.core.errors import DatasetNotFoundError
from sopran.core.store import DatasetRecord
from sopran.core.time import TimeRange, day, period
from sopran.experimental.electron_reflection import EffectiveFieldFitSettings
from sopran.experimental.kaguya.schema import KAGUYA_ER_SCHEMA
from sopran.frames import FrameContext
from sopran.missions.kaguya.geometry import (
    lmag_position,
    spice_sun_vectors_moon_me,
)
from sopran.missions.kaguya.pace import PaceCalibration
from sopran.missions.kaguya.pitch import (
    PitchAngleSpectrumOptions,
    build_combined_pitch_angle_spectrum,
)
from sopran.missions.kaguya.spice import selene_spice_kernels

if TYPE_CHECKING:
    import polars as pl

    from sopran.experimental.kaguya.er import EffectiveFieldEndpoint

DownloadMode = Literal["never", "missing", "always"]
ParallelExecutor = Literal["thread", "process"]

KAGUYA_ESA1_ARCHIVE_TIME = period("2007-11-07", "2009-06-11")


@dataclass(frozen=True)
class EffectiveFieldCatalogBuildResult:
    """Summary and lazy access for a resumable effective-field catalog build."""

    time: TimeRange
    dataset_id: str
    variant_id: str
    state_path: Path
    record: DatasetRecord | None
    processed_days: tuple[str, ...]
    skipped_days: tuple[str, ...]
    missing_days: tuple[str, ...]
    failed_days: tuple[str, ...]
    row_count: int

    def scan(self) -> pl.LazyFrame:
        if self.record is None:
            raise DatasetNotFoundError(
                f"No completed shards for {self.dataset_id} variant {self.variant_id}"
            )
        return cast("pl.LazyFrame", self.record.scan(dataset_id=self.dataset_id))


def build_effective_field_catalog(
    endpoint: EffectiveFieldEndpoint,
    time: TimeRange,
    *,
    cadence: str | float | None = None,
    pitch_bins: int = 16,
    settings: EffectiveFieldFitSettings | None = None,
    workers: int | None = None,
    download: DownloadMode | None = None,
    frame_context: FrameContext | None = None,
    include_sza: bool = True,
    resume: bool = True,
    retry_missing: bool = False,
    dataset_id: str | None = None,
    variant_id: str | None = None,
    layer: str = "features",
    max_days: int | None = None,
    executor: ParallelExecutor = "process",
) -> EffectiveFieldCatalogBuildResult:
    """Build day-partitioned ER fits without retaining the full period in memory."""

    if pitch_bins < 6 or pitch_bins % 2:
        raise ValueError("pitch_bins must be an even integer of at least 6")
    if max_days is not None and max_days <= 0:
        raise ValueError("max_days must be positive")
    cadence_seconds = _cadence_seconds(cadence)
    settings = settings or EffectiveFieldFitSettings(profile_likelihood=False)
    workers = workers or min(8, os.cpu_count() or 1)
    if workers <= 0:
        raise ValueError("workers must be positive")
    if executor not in {"thread", "process"}:
        raise ValueError("executor must be 'thread' or 'process'")

    mission = endpoint.instrument.mission
    resolved_download = mission.download if download is None else download
    if resolved_download not in {"never", "missing", "always"}:
        raise ValueError("download must be 'never', 'missing', or 'always'")
    resolved_dataset_id = dataset_id or endpoint.dataset_id
    resolved_variant_id = variant_id or _catalog_variant_id(
        settings=settings,
        cadence_seconds=cadence_seconds,
        pitch_bins=pitch_bins,
        include_sza=include_sza,
    )
    root = mission.store.dataset_path(
        resolved_dataset_id,
        layer=layer,
        variant_id=resolved_variant_id,
    )
    state_path = root / "build-state.json"
    state = _read_state(state_path)
    state.update(
        {
            "version": 1,
            "dataset_id": resolved_dataset_id,
            "variant_id": resolved_variant_id,
            "requested_time": {
                "start": time.start_iso,
                "stop": time.stop_iso,
            },
            "parameters": {
                "cadence_seconds": cadence_seconds,
                "pitch_bins": pitch_bins,
                "workers": workers,
                "executor": executor,
                "include_sza": include_sza,
                "source_sensors": ["ESA1", "ESA2"],
                "settings": asdict(settings),
            },
        }
    )
    state_days = state.setdefault("days", {})
    if not isinstance(state_days, dict):
        raise ValueError(f"Invalid ER build state: {state_path}")

    record = _catalog_record(
        mission.store,
        dataset_id=resolved_dataset_id,
        layer=layer,
        variant_id=resolved_variant_id,
    )
    complete_shards = (
        {
            str(shard.get("path")): shard
            for shard in record.shards(status="complete")
            if shard.get("path")
        }
        if record is not None
        else {}
    )
    processed: list[str] = []
    skipped: list[str] = []
    missing: list[str] = []
    failed: list[str] = []
    esa1_calibration = mission.esa1.load_calibration(download=resolved_download)
    esa2_calibration = mission.esa2.load_calibration(download=resolved_download)
    calibration = PaceCalibration(
        fov={**esa1_calibration.fov, **esa2_calibration.fov},
        info={**esa1_calibration.info, **esa2_calibration.info},
    )

    labels = time.days()
    if max_days is not None:
        labels = labels[:max_days]
    for label in labels:
        shard_path = f"shards/date={label}/part-000.parquet"
        prior = state_days.get(label)
        prior_status = prior.get("status") if isinstance(prior, dict) else None
        if resume and shard_path in complete_shards:
            if prior_status != "complete":
                _reconcile_completed_day_state(
                    state,
                    state_path,
                    root=root,
                    label=label,
                    shard_path=shard_path,
                    shard=complete_shards[shard_path],
                    prior=prior,
                )
            skipped.append(label)
            continue
        if resume and prior_status in {"missing", "no_data"} and not retry_missing:
            missing.append(label)
            continue

        day_time = _intersect_day(time, label)
        started_at = _utc_now_iso()
        try:
            esa1_data = mission.esa1.load(
                day_time,
                calibration=calibration,
                download=resolved_download,
                missing="empty",
            )
            esa2_data = mission.esa2.load(
                day_time,
                calibration=calibration,
                download=resolved_download,
                missing="empty",
            )
            if (
                not esa1_data.files
                or esa1_data.pace is None
                or not esa2_data.files
                or esa2_data.pace is None
            ):
                reason = esa1_data.missing_reason or esa2_data.missing_reason
                _update_day_state(
                    state,
                    state_path,
                    label,
                    status="missing",
                    started_at=started_at,
                    message=reason or "PACE ESA1/ESA2 files are unavailable",
                )
                missing.append(label)
                continue
            lmag_data = mission.lmag.load(
                day_time,
                download=resolved_download,
                missing="empty",
            )
            if lmag_data.frame.empty:
                _update_day_state(
                    state,
                    state_path,
                    label,
                    status="missing",
                    started_at=started_at,
                    message=lmag_data.missing_reason or "LMAG data are unavailable",
                )
                missing.append(label)
                continue

            kernels: tuple[Path, ...]
            if frame_context is None:
                kernels = selene_spice_kernels(
                    mission.store,
                    day_time,
                    download=resolved_download,
                )
                day_context = FrameContext(
                    spice_kernels=kernels,
                    default_backend="spiceypy",
                )
            else:
                day_context = frame_context
                kernels = tuple(Path(path) for path in day_context.spice_kernels)

            magnetic_field = lmag_data.magnetic_field
            position = lmag_position(lmag_data)
            spectrum = build_combined_pitch_angle_spectrum(
                paces=(esa1_data.pace, esa2_data.pace),
                time=day_time,
                calibration=calibration,
                magnetic_field=magnetic_field,
                files=esa1_data.files + esa2_data.files,
                options=PitchAngleSpectrumOptions(
                    value="counts",
                    pitch_bins=pitch_bins,
                    look_frame="SELENE_M_SPACECRAFT",
                    min_look_bins=1,
                    cadence_seconds=cadence_seconds,
                ),
                frame_context=day_context,
            )
            if spectrum.to_xarray().sizes["time"] == 0:
                _update_day_state(
                    state,
                    state_path,
                    label,
                    status="no_data",
                    started_at=started_at,
                    message="No pitch-angle spectra survived decoding and calibration",
                )
                missing.append(label)
                continue

            fitted = endpoint.fit(
                spectrum,
                magnetic_field=magnetic_field,
                position=position,
                affected_side="auto",
                settings=settings,
                cache="never",
                workers=workers,
                executor=executor,
            )
            frame = fitted.to_pandas()
            frame["source_day"] = label
            frame["sampling_cadence_seconds"] = cadence_seconds
            if include_sza:
                frame["sza"] = _sza_at_fit_times(frame, kernels=kernels)
            source_files = tuple(
                dict.fromkeys(
                    str(path)
                    for path in (
                        *esa1_data.files,
                        *esa2_data.files,
                        *lmag_data.files,
                        *kernels,
                    )
                )
            )
            day_result = fitted.__class__(
                frame=frame,
                time=day_time,
                files=tuple(Path(path) for path in source_files),
                variant_id=resolved_variant_id,
            )
            record = mission.store.write_parquet_dataset(
                dataset_id=resolved_dataset_id,
                layer=layer,
                variant_id=resolved_variant_id,
                variant={
                    "model_family": "robust_counts",
                    "model_version": 4,
                    "source_sensors": ["ESA1", "ESA2"],
                    "cadence_seconds": cadence_seconds,
                    "pitch_bins": pitch_bins,
                    "include_sza": include_sza,
                    "settings": asdict(settings),
                },
                mission="kaguya",
                instrument="er",
                product="effective_field",
                schema=KAGUYA_ER_SCHEMA,
                time_coverage=day_time,
                frame=day_result.to_polars(),
                source_files=source_files,
                source_datasets=(
                    "kaguya.esa1.counts_pitch_angle_spectrum",
                    "kaguya.esa2.counts_pitch_angle_spectrum",
                    "kaguya.lmag.magnetic_field",
                    "kaguya.orbit.position",
                    "kaguya.orbit.sza",
                ),
                shard_path=shard_path,
                append=record is not None,
                producer="sopran.experimental.kaguya.er.catalog",
                parameters={
                    "effective_field_fit": asdict(settings),
                    "sampling_cadence_seconds": cadence_seconds,
                    "pitch_bins": pitch_bins,
                    "source_sensors": ["ESA1", "ESA2"],
                },
                status="candidate",
                partitioning=("date",),
            )
            complete_shards[shard_path] = {
                "path": shard_path,
                "row_count": len(frame),
                "status": "complete",
            }
            _update_day_state(
                state,
                state_path,
                label,
                status="complete",
                started_at=started_at,
                row_count=len(frame),
                quality_counts={
                    str(key): int(value)
                    for key, value in frame["quality_grade"].value_counts().items()
                },
            )
            processed.append(label)
        except HTTPError as exc:
            if exc.code != 404:
                _update_day_state(
                    state,
                    state_path,
                    label,
                    status="failed",
                    started_at=started_at,
                    message=f"{type(exc).__name__}: {exc}",
                )
                failed.append(label)
                continue
            _update_day_state(
                state,
                state_path,
                label,
                status="missing",
                started_at=started_at,
                message=str(exc),
            )
            missing.append(label)
        except Exception as exc:
            _update_day_state(
                state,
                state_path,
                label,
                status="failed",
                started_at=started_at,
                message=f"{type(exc).__name__}: {exc}",
            )
            failed.append(label)

    record = _catalog_record(
        mission.store,
        dataset_id=resolved_dataset_id,
        layer=layer,
        variant_id=resolved_variant_id,
    )
    row_count = (
        sum(int(shard.get("row_count") or 0) for shard in record.shards(status="complete"))
        if record is not None
        else 0
    )
    return EffectiveFieldCatalogBuildResult(
        time=time,
        dataset_id=resolved_dataset_id,
        variant_id=resolved_variant_id,
        state_path=state_path,
        record=record,
        processed_days=tuple(processed),
        skipped_days=tuple(skipped),
        missing_days=tuple(missing),
        failed_days=tuple(failed),
        row_count=row_count,
    )


def _catalog_variant_id(
    *,
    settings: EffectiveFieldFitSettings,
    cadence_seconds: float | None,
    pitch_bins: int,
    include_sza: bool,
) -> str:
    payload = {
        "model_version": 4,
        "source_sensors": ["ESA1", "ESA2"],
        "settings": asdict(settings),
        "cadence_seconds": cadence_seconds,
        "pitch_bins": pitch_bins,
        "include_sza": include_sza,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    cadence_token = "native" if cadence_seconds is None else f"{cadence_seconds:g}s"
    return f"robust_counts_v3_esa1_esa2_{cadence_token}_p{pitch_bins}_{digest}"


def _cadence_seconds(cadence: str | float | None) -> float | None:
    if cadence is None:
        return None
    if isinstance(cadence, str):
        value = float(pd.Timedelta(cadence).total_seconds())
    else:
        value = float(cadence)
    if not np.isfinite(value) or value <= 0.0:
        raise ValueError("cadence must resolve to a finite positive duration")
    return value


def _intersect_day(time: TimeRange, label: str) -> TimeRange:
    value = day(label)
    return TimeRange(max(time.start, value.start), min(time.stop, value.stop))


def _sza_at_fit_times(frame: pd.DataFrame, *, kernels: tuple[Path, ...]) -> np.ndarray:
    positions = frame[["position_x", "position_y", "position_z"]].to_numpy(
        dtype=float
    )
    times = pd.to_datetime(frame["time"], utc=True).to_numpy(dtype="datetime64[ns]")
    sun = spice_sun_vectors_moon_me(times, spice_kernels=kernels)
    position_norm = np.linalg.norm(positions, axis=1)
    sun_norm = np.linalg.norm(sun, axis=1)
    denominator = position_norm * sun_norm
    cosine = np.divide(
        np.sum(positions * sun, axis=1),
        denominator,
        out=np.full(position_norm.shape, np.nan),
        where=denominator > 0.0,
    )
    return np.asarray(
        np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))),
        dtype=float,
    )


def _catalog_record(
    store: Any,
    *,
    dataset_id: str,
    layer: str,
    variant_id: str,
) -> DatasetRecord | None:
    try:
        return cast(
            DatasetRecord,
            store.dataset(dataset_id, layer=layer, variant_id=variant_id),
        )
    except DatasetNotFoundError:
        return None


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"days": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid ER build state: {path}")
    return payload


def _update_day_state(
    state: dict[str, Any],
    path: Path,
    label: str,
    *,
    status: str,
    started_at: str,
    message: str | None = None,
    row_count: int | None = None,
    quality_counts: dict[str, int] | None = None,
) -> None:
    day_state: dict[str, Any] = {
        "status": status,
        "started_at": started_at,
        "finished_at": _utc_now_iso(),
    }
    if message is not None:
        day_state["message"] = message
    if row_count is not None:
        day_state["row_count"] = row_count
    if quality_counts is not None:
        day_state["quality_counts"] = quality_counts
    days = state.setdefault("days", {})
    if not isinstance(days, dict):
        raise ValueError(f"Invalid ER build state: {path}")
    days[label] = day_state
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp")
    temp.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _reconcile_completed_day_state(
    state: dict[str, Any],
    state_path: Path,
    *,
    root: Path,
    label: str,
    shard_path: str,
    shard: dict[str, Any],
    prior: Any,
) -> None:
    """Restore build state when a committed Store shard is authoritative."""

    frame = pd.read_parquet(root / shard_path, columns=["quality_grade"])
    started_at = (
        str(prior.get("started_at"))
        if isinstance(prior, dict) and prior.get("started_at")
        else _utc_now_iso()
    )
    manifest_row_count = shard.get("row_count")
    row_count = int(manifest_row_count) if manifest_row_count is not None else len(frame)
    if row_count != len(frame):
        raise ValueError(
            f"ER shard row count mismatch for {label}: "
            f"manifest={row_count}, parquet={len(frame)}"
        )
    _update_day_state(
        state,
        state_path,
        label,
        status="complete",
        started_at=started_at,
        row_count=row_count,
        quality_counts={
            str(key): int(value)
            for key, value in frame["quality_grade"].value_counts().items()
        },
    )


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "EffectiveFieldCatalogBuildResult",
    "KAGUYA_ESA1_ARCHIVE_TIME",
    "build_effective_field_catalog",
]
