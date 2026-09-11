from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal

import numpy as np

InputScale = Literal["db", "linear_power"]
WindowAnchor = Literal["first_sample", "epoch"]

FPE_KHZ_PER_SQRT_CM3 = 8.98
FCE_KHZ_PER_NT = 0.02802495


@dataclass(frozen=True)
class FrequencyBand:
    name: str
    minimum_khz: float
    maximum_khz: float

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("frequency band name must not be empty")
        if not np.isfinite(self.minimum_khz) or self.minimum_khz <= 0.0:
            raise ValueError("frequency band minimum_khz must be positive and finite")
        if not np.isfinite(self.maximum_khz) or self.maximum_khz <= self.minimum_khz:
            raise ValueError("frequency band maximum_khz must exceed minimum_khz")


@dataclass(frozen=True)
class FixedLine:
    name: str
    frequency_khz: float
    half_width_khz: float

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("fixed-line name must not be empty")
        if not np.isfinite(self.frequency_khz) or self.frequency_khz <= 0.0:
            raise ValueError("fixed-line frequency_khz must be positive and finite")
        if not np.isfinite(self.half_width_khz) or self.half_width_khz < 0.0:
            raise ValueError("fixed-line half_width_khz must be non-negative and finite")


@dataclass(frozen=True)
class LineDetectionRule:
    name: str
    line_band: FrequencyBand
    side_band: FrequencyBand
    minimum_peak_z: float = 3.0
    minimum_prominence_z: float = 2.0
    veto_radio: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("line-detection rule name must not be empty")
        if not np.isfinite(self.minimum_peak_z):
            raise ValueError("minimum_peak_z must be finite")
        if not np.isfinite(self.minimum_prominence_z):
            raise ValueError("minimum_prominence_z must be finite")


@dataclass(frozen=True)
class PeakRule:
    name: str
    band: FrequencyBand
    minimum_peak_z: float
    minimum_quality: float
    support_drop_z: float
    maximum_log10_half_width: float | None = None
    mask_lines: tuple[FixedLine, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("peak-rule name must not be empty")
        for field_name, value in (
            ("minimum_peak_z", self.minimum_peak_z),
            ("minimum_quality", self.minimum_quality),
            ("support_drop_z", self.support_drop_z),
        ):
            if not np.isfinite(value):
                raise ValueError(f"{field_name} must be finite")
        if self.support_drop_z <= 0.0:
            raise ValueError("support_drop_z must be positive")
        if self.maximum_log10_half_width is not None and (
            not np.isfinite(self.maximum_log10_half_width)
            or self.maximum_log10_half_width <= 0.0
        ):
            raise ValueError("maximum_log10_half_width must be positive and finite")


@dataclass(frozen=True)
class WindowConfig:
    duration_seconds: float = 120.0
    step_seconds: float = 60.0
    minimum_points: int = 8
    minimum_frequency_bins: int = 8
    minimum_finite_fraction: float = 0.65
    frequency_minimum_khz: float = 0.1
    frequency_maximum_khz: float = 1000.0
    frequency_bins: int = 128
    robust_minimum_scale_db: float = 0.5
    z_clip: float = 8.0
    shape_normalize: bool = False
    anchor: WindowAnchor = "first_sample"

    def __post_init__(self) -> None:
        if not np.isfinite(self.duration_seconds) or self.duration_seconds <= 0.0:
            raise ValueError("duration_seconds must be positive and finite")
        if not np.isfinite(self.step_seconds) or self.step_seconds <= 0.0:
            raise ValueError("step_seconds must be positive and finite")
        if self.minimum_points < 1:
            raise ValueError("minimum_points must be at least one")
        if self.minimum_frequency_bins < 2:
            raise ValueError("minimum_frequency_bins must be at least two")
        if not 0.0 <= self.minimum_finite_fraction <= 1.0:
            raise ValueError("minimum_finite_fraction must be in [0, 1]")
        if self.frequency_minimum_khz <= 0.0:
            raise ValueError("frequency_minimum_khz must be positive")
        if self.frequency_maximum_khz <= self.frequency_minimum_khz:
            raise ValueError("frequency_maximum_khz must exceed frequency_minimum_khz")
        if self.frequency_bins < self.minimum_frequency_bins:
            raise ValueError("frequency_bins must cover minimum_frequency_bins")
        if self.robust_minimum_scale_db <= 0.0:
            raise ValueError("robust_minimum_scale_db must be positive")
        if self.z_clip <= 0.0:
            raise ValueError("z_clip must be positive")
        if self.anchor not in ("first_sample", "epoch"):
            raise ValueError("anchor must be 'first_sample' or 'epoch'")


@dataclass(frozen=True)
class RidgeTrackerConfig:
    name: str
    band: FrequencyBand
    baseline_window_bins: int = 25
    smoothness: float = 12.0
    maximum_jump_dex: float = 0.08
    candidate_threshold: float = 0.45
    maximum_gap_seconds: float = 90.0
    mask_lines: tuple[FixedLine, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ridge tracker name must not be empty")
        if self.baseline_window_bins < 3:
            raise ValueError("baseline_window_bins must be at least three")
        if not np.isfinite(self.smoothness) or self.smoothness < 0.0:
            raise ValueError("smoothness must be non-negative and finite")
        if not np.isfinite(self.maximum_jump_dex) or self.maximum_jump_dex <= 0.0:
            raise ValueError("maximum_jump_dex must be positive and finite")
        if not np.isfinite(self.candidate_threshold):
            raise ValueError("candidate_threshold must be finite")
        if not np.isfinite(self.maximum_gap_seconds) or self.maximum_gap_seconds <= 0.0:
            raise ValueError("maximum_gap_seconds must be positive and finite")


def _default_low_peak_rule() -> PeakRule:
    return PeakRule(
        name="fpe_low_ridge",
        band=FrequencyBand("low_fpe", 2.0, 30.0),
        minimum_peak_z=1.5,
        minimum_quality=0.08,
        support_drop_z=0.75,
        maximum_log10_half_width=0.35,
    )


def _default_high_peak_rule() -> PeakRule:
    return PeakRule(
        name="plasma_line_ridge",
        band=FrequencyBand("plasma_line", 10.0, 100.0),
        minimum_peak_z=2.5,
        minimum_quality=0.15,
        support_drop_z=1.0,
    )


def _default_radio_peak_rule() -> PeakRule:
    return PeakRule(
        name="radio_akr",
        band=FrequencyBand("radio", 100.0, 500.0),
        minimum_peak_z=3.0,
        minimum_quality=0.0,
        support_drop_z=1.0,
    )


def _default_low_tracker() -> RidgeTrackerConfig:
    return RidgeTrackerConfig(
        name="tracked_low_fpe_ridge",
        band=FrequencyBand("tracked_low_fpe", 2.0, 30.0),
    )


def _default_high_tracker() -> RidgeTrackerConfig:
    return RidgeTrackerConfig(
        name="tracked_high_plasma_ridge",
        band=FrequencyBand("tracked_high_plasma", 30.0, 100.0),
    )


@dataclass(frozen=True)
class WaveDetectorConfig:
    detector: str = "sopran.wave.multi_label"
    detector_version: str = "1"
    feature_spec_version: str = "wave-features-v1"
    window: WindowConfig = field(default_factory=WindowConfig)
    bbn_band: FrequencyBand = field(
        default_factory=lambda: FrequencyBand("bbn", 0.1, 10.0)
    )
    bbn_core_band: FrequencyBand = field(
        default_factory=lambda: FrequencyBand("bbn_core", 0.1, 3.0)
    )
    bbn_minimum_p90_z: float = 2.0
    bbn_broad_threshold_z: float = 1.5
    bbn_minimum_broad_fraction: float = 0.15
    low_ridge_rule: PeakRule = field(default_factory=_default_low_peak_rule)
    high_ridge_rule: PeakRule = field(default_factory=_default_high_peak_rule)
    radio_rule: PeakRule = field(default_factory=_default_radio_peak_rule)
    radio_broad_threshold_z: float = 1.5
    radio_minimum_broad_fraction: float = 0.08
    high_band: FrequencyBand = field(
        default_factory=lambda: FrequencyBand("high", 500.0, 1000.0)
    )
    line_rules: tuple[LineDetectionRule, ...] = ()
    low_tracker: RidgeTrackerConfig = field(default_factory=_default_low_tracker)
    high_tracker: RidgeTrackerConfig = field(default_factory=_default_high_tracker)
    data_warning_minimum_points: int = 4
    interval_merge_gap_seconds: float = 1.0

    def __post_init__(self) -> None:
        if not self.detector:
            raise ValueError("detector must not be empty")
        if not self.detector_version:
            raise ValueError("detector_version must not be empty")
        if not self.feature_spec_version:
            raise ValueError("feature_spec_version must not be empty")
        for field_name, value in (
            ("bbn_minimum_p90_z", self.bbn_minimum_p90_z),
            ("bbn_broad_threshold_z", self.bbn_broad_threshold_z),
            ("bbn_minimum_broad_fraction", self.bbn_minimum_broad_fraction),
            ("radio_broad_threshold_z", self.radio_broad_threshold_z),
            ("radio_minimum_broad_fraction", self.radio_minimum_broad_fraction),
            ("interval_merge_gap_seconds", self.interval_merge_gap_seconds),
        ):
            if not np.isfinite(value):
                raise ValueError(f"{field_name} must be finite")
        if not 0.0 <= self.bbn_minimum_broad_fraction <= 1.0:
            raise ValueError("bbn_minimum_broad_fraction must be in [0, 1]")
        if not 0.0 <= self.radio_minimum_broad_fraction <= 1.0:
            raise ValueError("radio_minimum_broad_fraction must be in [0, 1]")
        if self.data_warning_minimum_points < 1:
            raise ValueError("data_warning_minimum_points must be at least one")
        if self.interval_merge_gap_seconds < 0.0:
            raise ValueError("interval_merge_gap_seconds must be non-negative")


@dataclass(frozen=True)
class WindowedSpectra:
    time_start_seconds: np.ndarray
    time_stop_seconds: np.ndarray
    time_mid_seconds: np.ndarray
    frequency_khz: np.ndarray
    raw_db: np.ndarray
    normalized_z: np.ndarray
    background_center_db: np.ndarray
    background_scale_db: np.ndarray
    n_points: np.ndarray
    finite_fraction: np.ndarray

    @property
    def n_windows(self) -> int:
        return int(self.time_start_seconds.size)


@dataclass(frozen=True)
class PeakFeatures:
    peak_frequency_khz: np.ndarray
    peak_z: np.ndarray
    prominence_z: np.ndarray
    frequency_low_khz: np.ndarray
    frequency_high_khz: np.ndarray
    log10_half_width: np.ndarray
    density_if_fpe_cm3: np.ndarray
    density_if_fpe_low_cm3: np.ndarray
    density_if_fpe_high_cm3: np.ndarray
    required_b_if_fce_nt: np.ndarray
    quality_score: np.ndarray


@dataclass(frozen=True)
class LineFeatures:
    name: str
    peak_frequency_khz: np.ndarray
    peak_z: np.ndarray
    prominence_z: np.ndarray
    candidate: np.ndarray
    veto_radio: bool


@dataclass(frozen=True)
class WaveFeatureSet:
    bbn_median_z: np.ndarray
    bbn_p90_z: np.ndarray
    bbn_peak_z: np.ndarray
    bbn_broad_fraction: np.ndarray
    bbn_core_p90_z: np.ndarray
    radio_median_z: np.ndarray
    radio_peak_z: np.ndarray
    radio_broad_fraction: np.ndarray
    high_median_z: np.ndarray
    low_ridge: PeakFeatures
    high_ridge: PeakFeatures
    radio: PeakFeatures
    lines: tuple[LineFeatures, ...]
    bbn_candidate: np.ndarray
    low_ridge_candidate: np.ndarray
    high_ridge_candidate: np.ndarray
    radio_candidate: np.ndarray
    instrument_rfi_candidate: np.ndarray
    data_quality_warning: np.ndarray


@dataclass(frozen=True)
class RidgeTrack:
    name: str
    time_seconds: np.ndarray
    frequency_khz: np.ndarray
    density_cm3: np.ndarray
    score: np.ndarray
    candidate: np.ndarray
    state_index: np.ndarray
    segment_index: np.ndarray


@dataclass(frozen=True)
class CandidateInterval:
    event_id: str
    interval_id: str
    time_start_seconds: float
    time_stop_seconds: float
    phenomenon: str
    confidence: float
    score: float
    peak_time_seconds: float
    peak_frequency_khz: float
    n_windows: int
    component: str
    source_dataset: str
    detector: str
    detector_version: str
    detector_run_id: str
    detector_config_id: str
    feature_spec_id: str
    feature_spec_hash: str
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class WaveDetectionResult:
    component: str
    source_dataset: str
    detector_run_id: str
    detector_config_id: str
    feature_spec_id: str
    feature_spec_hash: str
    config: WaveDetectorConfig
    windows: WindowedSpectra
    features: WaveFeatureSet
    low_track: RidgeTrack
    high_track: RidgeTrack
    intervals: tuple[CandidateInterval, ...]
    window_id: np.ndarray
    is_observed: np.ndarray
    is_eligible: np.ndarray
    exposure_seconds: np.ndarray

    def feature_columns(self) -> dict[str, Any]:
        columns: dict[str, Any] = {
            "window_id": self.window_id,
            "time_start": self.windows.time_start_seconds,
            "time_stop": self.windows.time_stop_seconds,
            "time_mid": self.windows.time_mid_seconds,
            "n_points": self.windows.n_points,
            "finite_fraction": self.windows.finite_fraction,
            "is_observed": self.is_observed,
            "is_eligible": self.is_eligible,
            "exposure_seconds": self.exposure_seconds,
            "bbn_median_z": self.features.bbn_median_z,
            "bbn_p90_z": self.features.bbn_p90_z,
            "bbn_peak_z": self.features.bbn_peak_z,
            "bbn_broad_fraction": self.features.bbn_broad_fraction,
            "bbn_core_p90_z": self.features.bbn_core_p90_z,
            "radio_median_z": self.features.radio_median_z,
            "radio_broad_fraction": self.features.radio_broad_fraction,
            "high_median_z": self.features.high_median_z,
            "low_ridge_peak_frequency_khz": self.features.low_ridge.peak_frequency_khz,
            "low_ridge_peak_z": self.features.low_ridge.peak_z,
            "low_ridge_prominence_z": self.features.low_ridge.prominence_z,
            "low_ridge_frequency_low_khz": self.features.low_ridge.frequency_low_khz,
            "low_ridge_frequency_high_khz": self.features.low_ridge.frequency_high_khz,
            "low_ridge_log10_half_width": self.features.low_ridge.log10_half_width,
            "low_ridge_density_if_fpe_cm3": self.features.low_ridge.density_if_fpe_cm3,
            "low_ridge_density_if_fpe_low_cm3": (
                self.features.low_ridge.density_if_fpe_low_cm3
            ),
            "low_ridge_density_if_fpe_high_cm3": (
                self.features.low_ridge.density_if_fpe_high_cm3
            ),
            "low_ridge_required_b_if_fce_nt": self.features.low_ridge.required_b_if_fce_nt,
            "low_ridge_quality_score": self.features.low_ridge.quality_score,
            "high_ridge_peak_frequency_khz": self.features.high_ridge.peak_frequency_khz,
            "high_ridge_peak_z": self.features.high_ridge.peak_z,
            "high_ridge_prominence_z": self.features.high_ridge.prominence_z,
            "high_ridge_frequency_low_khz": self.features.high_ridge.frequency_low_khz,
            "high_ridge_frequency_high_khz": self.features.high_ridge.frequency_high_khz,
            "high_ridge_log10_half_width": self.features.high_ridge.log10_half_width,
            "high_ridge_density_if_fpe_cm3": self.features.high_ridge.density_if_fpe_cm3,
            "high_ridge_density_if_fpe_low_cm3": (
                self.features.high_ridge.density_if_fpe_low_cm3
            ),
            "high_ridge_density_if_fpe_high_cm3": (
                self.features.high_ridge.density_if_fpe_high_cm3
            ),
            "high_ridge_required_b_if_fce_nt": (
                self.features.high_ridge.required_b_if_fce_nt
            ),
            "high_ridge_quality_score": self.features.high_ridge.quality_score,
            "radio_peak_frequency_khz": self.features.radio.peak_frequency_khz,
            "radio_peak_z": self.features.radio.peak_z,
            "radio_prominence_z": self.features.radio.prominence_z,
            "radio_frequency_low_khz": self.features.radio.frequency_low_khz,
            "radio_frequency_high_khz": self.features.radio.frequency_high_khz,
            "radio_log10_half_width": self.features.radio.log10_half_width,
            "radio_required_b_if_fce_nt": self.features.radio.required_b_if_fce_nt,
            "radio_quality_score": self.features.radio.quality_score,
            "bbn_candidate": self.features.bbn_candidate,
            "low_ridge_candidate": self.features.low_ridge_candidate,
            "high_ridge_candidate": self.features.high_ridge_candidate,
            "radio_candidate": self.features.radio_candidate,
            "instrument_rfi_candidate": self.features.instrument_rfi_candidate,
            "data_quality_warning": self.features.data_quality_warning,
            "tracked_low_frequency_khz": self.low_track.frequency_khz,
            "tracked_low_score": self.low_track.score,
            "tracked_low_candidate": self.low_track.candidate,
            "tracked_low_density_cm3": self.low_track.density_cm3,
            "tracked_low_state_index": self.low_track.state_index,
            "tracked_low_segment_index": self.low_track.segment_index,
            "tracked_high_frequency_khz": self.high_track.frequency_khz,
            "tracked_high_score": self.high_track.score,
            "tracked_high_candidate": self.high_track.candidate,
            "tracked_high_density_cm3": self.high_track.density_cm3,
            "tracked_high_state_index": self.high_track.state_index,
            "tracked_high_segment_index": self.high_track.segment_index,
        }
        for line in self.features.lines:
            prefix = f"line_{line.name}"
            columns[f"{prefix}_peak_frequency_khz"] = line.peak_frequency_khz
            columns[f"{prefix}_peak_z"] = line.peak_z
            columns[f"{prefix}_prominence_z"] = line.prominence_z
            columns[f"{prefix}_candidate"] = line.candidate
        return columns

    def features_to_polars(self) -> Any:
        try:
            import polars as pl
        except ImportError as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("polars is required to materialize wave feature frames") from exc
        columns = self.feature_columns()
        for name in ("time_start", "time_stop", "time_mid"):
            columns[name] = pl.Series(
                name,
                [_utc_iso(value) for value in np.asarray(columns[name], dtype=float)],
                dtype=pl.String,
            )
        frame = pl.DataFrame(columns)
        return frame.with_columns(
            pl.lit(self.component).alias("component"),
            pl.lit(self.source_dataset).alias("source_dataset"),
            pl.lit(self.detector_run_id).alias("detector_run_id"),
            pl.lit(self.detector_config_id).alias("detector_config_id"),
            pl.lit(self.feature_spec_id).alias("feature_spec_id"),
            pl.lit(self.feature_spec_hash).alias("feature_spec_hash"),
        )

    def events_to_polars(
        self,
        *,
        mission: str,
        instrument: str,
        component: str | None = None,
    ) -> Any:
        try:
            import polars as pl
        except ImportError as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("polars is required to materialize wave event frames") from exc
        rows = [
            {
                "event_id": interval.event_id,
                "interval_id": interval.interval_id,
                "time_start": _utc_iso(interval.time_start_seconds),
                "time_stop": _utc_iso(interval.time_stop_seconds),
                "mission": mission,
                "instrument": instrument,
                "component": component or interval.component,
                "phenomenon": interval.phenomenon,
                "confidence": interval.confidence,
                "detector": interval.detector,
                "detector_version": interval.detector_version,
                "detector_run_id": interval.detector_run_id,
                "detector_config_id": interval.detector_config_id,
                "feature_spec_id": interval.feature_spec_id,
                "feature_spec_hash": interval.feature_spec_hash,
                "source_dataset": interval.source_dataset,
                "score": interval.score,
                "peak_time": _utc_iso(interval.peak_time_seconds),
                "peak_frequency_khz": interval.peak_frequency_khz,
                "n_windows": interval.n_windows,
                "quality_flags": ",".join(interval.quality_flags),
            }
            for interval in self.intervals
        ]
        if rows:
            return pl.DataFrame(rows)
        return pl.DataFrame(
            schema={
                "event_id": pl.String,
                "interval_id": pl.String,
                "time_start": pl.String,
                "time_stop": pl.String,
                "mission": pl.String,
                "instrument": pl.String,
                "component": pl.String,
                "phenomenon": pl.String,
                "confidence": pl.Float64,
                "detector": pl.String,
                "detector_version": pl.String,
                "detector_run_id": pl.String,
                "detector_config_id": pl.String,
                "feature_spec_id": pl.String,
                "feature_spec_hash": pl.String,
                "source_dataset": pl.String,
                "score": pl.Float64,
                "peak_time": pl.String,
                "peak_frequency_khz": pl.Float64,
                "n_windows": pl.Int64,
                "quality_flags": pl.String,
            }
        )


def feature_spec(config: WaveDetectorConfig) -> dict[str, Any]:
    return {
        "schema": "sopran.wave.feature-spec.v1",
        "configuration": asdict(config),
    }


def feature_spec_hash(config: WaveDetectorConfig) -> str:
    payload = json.dumps(
        feature_spec(config),
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def feature_spec_id(config: WaveDetectorConfig) -> str:
    return f"wavefs-{feature_spec_hash(config)[:16]}"


def detector_config_id(config: WaveDetectorConfig) -> str:
    payload = json.dumps(
        asdict(config),
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"wavecfg-{sha256(payload).hexdigest()[:16]}"


def frequency_to_density_cm3(frequency_khz: np.ndarray | float) -> np.ndarray | float:
    frequency = np.asarray(frequency_khz, dtype=float)
    density = np.where(frequency > 0.0, (frequency / FPE_KHZ_PER_SQRT_CM3) ** 2, np.nan)
    return float(density) if np.ndim(frequency_khz) == 0 else density


def frequency_to_required_b_nt(frequency_khz: np.ndarray | float) -> np.ndarray | float:
    frequency = np.asarray(frequency_khz, dtype=float)
    field_nt = np.where(frequency > 0.0, frequency / FCE_KHZ_PER_NT, np.nan)
    return float(field_nt) if np.ndim(frequency_khz) == 0 else field_nt


def _utc_iso(seconds: float) -> str:
    return datetime.fromtimestamp(float(seconds), tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ").replace(
        ".000000Z", "Z"
    )
