from __future__ import annotations

import numpy as np

from sopran.experimental.waves.intervals import (
    build_candidate_intervals,
    stable_detector_run_id,
    stable_window_id,
)
from sopran.experimental.waves.model import (
    CandidateInterval,
    InputScale,
    LineFeatures,
    PeakFeatures,
    PeakRule,
    WaveDetectionResult,
    WaveDetectorConfig,
    detector_config_id,
    feature_spec_hash,
    feature_spec_id,
)
from sopran.experimental.waves.ridge import track_spectral_ridge
from sopran.experimental.waves.spectral import (
    extract_wave_features,
    prepare_windowed_spectra,
    time_to_seconds,
)

BBN_ESW_CANDIDATE = "bbn_esw_candidate"
FPE_LOW_RIDGE_CANDIDATE = "fpe_low_ridge_candidate"
PLASMA_LINE_RIDGE_CANDIDATE = "plasma_line_ridge_candidate"
RADIO_AKR_CANDIDATE = "radio_akr_candidate"
INSTRUMENT_RFI_CANDIDATE = "instrument_rfi_candidate"
TRACKED_LOW_FPE_RIDGE_CANDIDATE = "tracked_low_fpe_ridge_candidate"
TRACKED_HIGH_PLASMA_RIDGE_CANDIDATE = "tracked_high_plasma_ridge_candidate"

WAVE_CANDIDATE_PHENOMENA = (
    BBN_ESW_CANDIDATE,
    FPE_LOW_RIDGE_CANDIDATE,
    PLASMA_LINE_RIDGE_CANDIDATE,
    RADIO_AKR_CANDIDATE,
    INSTRUMENT_RFI_CANDIDATE,
    TRACKED_LOW_FPE_RIDGE_CANDIDATE,
    TRACKED_HIGH_PLASMA_RIDGE_CANDIDATE,
)


def detect_wave_candidates(
    time: np.ndarray,
    frequency_khz: np.ndarray,
    spectrum: np.ndarray,
    *,
    input_scale: InputScale = "db",
    config: WaveDetectorConfig | None = None,
    valid_time: np.ndarray | None = None,
    component: str = "unknown",
    source_dataset: str = "unknown",
) -> WaveDetectionResult:
    """Extract robust spectral features, smooth ridges, and candidate intervals.

    Input spectra use ``(time, frequency)`` orientation.  All internal work is
    NumPy-only; Polars is imported only by the result materialization methods.
    Candidate labels are deliberately multi-label and mean "send to review",
    not a confirmed physical identification.
    """

    detector_config = config if config is not None else WaveDetectorConfig()
    if not component:
        raise ValueError("component must not be empty")
    if not source_dataset:
        raise ValueError("source_dataset must not be empty")

    source_start, source_stop = _source_bounds(time)
    windows = prepare_windowed_spectra(
        time,
        frequency_khz,
        spectrum,
        input_scale=input_scale,
        config=detector_config.window,
        valid_time=valid_time,
    )
    features = extract_wave_features(windows, detector_config)
    low_track = track_spectral_ridge(
        windows.time_mid_seconds,
        windows.frequency_khz,
        windows.normalized_z,
        detector_config.low_tracker,
    )
    high_track = track_spectral_ridge(
        windows.time_mid_seconds,
        windows.frequency_khz,
        windows.normalized_z,
        detector_config.high_tracker,
    )

    full_feature_hash = feature_spec_hash(detector_config)
    current_feature_spec_id = feature_spec_id(detector_config)
    current_config_id = detector_config_id(detector_config)
    detector_run_id = stable_detector_run_id(
        source_dataset=source_dataset,
        component=component,
        detector_config_id=current_config_id,
        source_start_seconds=source_start,
        source_stop_seconds=source_stop,
    )
    window_ids = np.asarray(
        [
            stable_window_id(
                source_dataset=source_dataset,
                component=component,
                time_start_seconds=start,
                time_stop_seconds=stop,
                feature_spec_id=current_feature_spec_id,
            )
            for start, stop in zip(
                windows.time_start_seconds,
                windows.time_stop_seconds,
                strict=True,
            )
        ],
        dtype=str,
    )
    is_observed = windows.n_points > 0
    is_eligible = (
        is_observed
        & (windows.n_points >= detector_config.window.minimum_points)
        & np.isfinite(windows.finite_fraction)
        & (windows.finite_fraction >= detector_config.window.minimum_finite_fraction)
    )
    exposure = _window_exposure_seconds(
        windows.time_start_seconds,
        is_eligible,
        source_start_seconds=source_start,
        source_stop_seconds=source_stop,
        step_seconds=detector_config.window.step_seconds,
    )

    bbn_confidence = _minimum_confidence(
        _threshold_confidence(features.bbn_p90_z, detector_config.bbn_minimum_p90_z),
        _threshold_confidence(
            features.bbn_broad_fraction,
            detector_config.bbn_minimum_broad_fraction,
        ),
    )
    low_confidence = _peak_confidence(features.low_ridge, detector_config.low_ridge_rule)
    high_confidence = _peak_confidence(
        features.high_ridge,
        detector_config.high_ridge_rule,
    )
    radio_confidence = _minimum_confidence(
        _peak_confidence(features.radio, detector_config.radio_rule),
        _threshold_confidence(
            features.radio_broad_fraction,
            detector_config.radio_minimum_broad_fraction,
        ),
    )
    rfi_score, rfi_confidence, rfi_frequency = _rfi_summary(
        features.lines,
        detector_config,
        windows.n_windows,
    )
    low_track_confidence = _threshold_confidence(
        low_track.score,
        detector_config.low_tracker.candidate_threshold,
    )
    high_track_confidence = _threshold_confidence(
        high_track.score,
        detector_config.high_tracker.candidate_threshold,
    )

    interval_groups = (
        _interval_group(
            BBN_ESW_CANDIDATE,
            features.bbn_candidate,
            features.bbn_p90_z,
            bbn_confidence,
            features.low_ridge.peak_frequency_khz,
        ),
        _interval_group(
            FPE_LOW_RIDGE_CANDIDATE,
            features.low_ridge_candidate,
            features.low_ridge.peak_z,
            low_confidence,
            features.low_ridge.peak_frequency_khz,
        ),
        _interval_group(
            PLASMA_LINE_RIDGE_CANDIDATE,
            features.high_ridge_candidate,
            features.high_ridge.peak_z,
            high_confidence,
            features.high_ridge.peak_frequency_khz,
        ),
        _interval_group(
            RADIO_AKR_CANDIDATE,
            features.radio_candidate,
            features.radio.peak_z,
            radio_confidence,
            features.radio.peak_frequency_khz,
        ),
        _interval_group(
            INSTRUMENT_RFI_CANDIDATE,
            features.instrument_rfi_candidate,
            rfi_score,
            rfi_confidence,
            rfi_frequency,
        ),
        _interval_group(
            TRACKED_LOW_FPE_RIDGE_CANDIDATE,
            low_track.candidate,
            low_track.score,
            low_track_confidence,
            low_track.frequency_khz,
        ),
        _interval_group(
            TRACKED_HIGH_PLASMA_RIDGE_CANDIDATE,
            high_track.candidate,
            high_track.score,
            high_track_confidence,
            high_track.frequency_khz,
        ),
    )
    intervals: list[CandidateInterval] = []
    for phenomenon, candidate, score, confidence, peak_frequency in interval_groups:
        intervals.extend(
            build_candidate_intervals(
                time_start_seconds=windows.time_start_seconds,
                time_stop_seconds=windows.time_stop_seconds,
                candidate=np.asarray(candidate, dtype=bool) & is_eligible,
                phenomenon=phenomenon,
                score=score,
                confidence=confidence,
                peak_frequency_khz=peak_frequency,
                data_quality_warning=features.data_quality_warning,
                component=component,
                source_dataset=source_dataset,
                detector=detector_config.detector,
                detector_version=detector_config.detector_version,
                detector_run_id=detector_run_id,
                detector_config_id=current_config_id,
                feature_spec_id=current_feature_spec_id,
                feature_spec_hash=full_feature_hash,
                merge_gap_seconds=detector_config.interval_merge_gap_seconds,
            )
        )
    intervals.sort(
        key=lambda interval: (
            interval.time_start_seconds,
            interval.time_stop_seconds,
            interval.phenomenon,
            interval.event_id,
        )
    )
    return WaveDetectionResult(
        component=component,
        source_dataset=source_dataset,
        detector_run_id=detector_run_id,
        detector_config_id=current_config_id,
        feature_spec_id=current_feature_spec_id,
        feature_spec_hash=full_feature_hash,
        config=detector_config,
        windows=windows,
        features=features,
        low_track=low_track,
        high_track=high_track,
        intervals=tuple(intervals),
        window_id=window_ids,
        is_observed=is_observed.astype(bool),
        is_eligible=is_eligible.astype(bool),
        exposure_seconds=exposure,
    )


def _source_bounds(time: np.ndarray) -> tuple[float, float]:
    seconds = time_to_seconds(np.asarray(time))
    finite = np.sort(seconds[np.isfinite(seconds)])
    if finite.size == 0:
        return 0.0, 0.0
    differences = np.diff(finite)
    positive = differences[differences > 0.0]
    cadence = float(np.median(positive)) if positive.size else 0.0
    return float(finite[0]), float(finite[-1] + cadence)


def _window_exposure_seconds(
    window_start_seconds: np.ndarray,
    is_eligible: np.ndarray,
    *,
    source_start_seconds: float,
    source_stop_seconds: float,
    step_seconds: float,
) -> np.ndarray:
    starts = np.asarray(window_start_seconds, dtype=float)
    eligible = np.asarray(is_eligible, dtype=bool)
    if starts.shape != eligible.shape:
        raise ValueError("window_start_seconds and is_eligible must be aligned")
    allocation_start = np.maximum(starts, source_start_seconds)
    allocation_stop = np.minimum(starts + step_seconds, source_stop_seconds)
    allocated = np.clip(allocation_stop - allocation_start, 0.0, step_seconds)
    return np.where(eligible, allocated, 0.0).astype(float)


def _interval_group(
    phenomenon: str,
    candidate: np.ndarray,
    score: np.ndarray,
    confidence: np.ndarray,
    peak_frequency_khz: np.ndarray,
) -> tuple[str, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    return phenomenon, candidate, score, confidence, peak_frequency_khz


def _threshold_confidence(values: np.ndarray, threshold: float) -> np.ndarray:
    data = np.asarray(values, dtype=float)
    scale = max(abs(float(threshold)), 1.0e-12)
    confidence = 0.5 + 0.5 * (data - threshold) / scale
    confidence = np.where(np.isfinite(data), np.clip(confidence, 0.0, 1.0), 0.0)
    return confidence.astype(float)


def _minimum_confidence(*values: np.ndarray) -> np.ndarray:
    if not values:
        return np.empty(0, dtype=float)
    arrays = tuple(np.asarray(value, dtype=float) for value in values)
    minimum: np.ndarray = arrays[0].copy()
    for array in arrays[1:]:
        minimum = np.minimum(minimum, array)
    return minimum.astype(float)


def _peak_confidence(features: PeakFeatures, rule: PeakRule) -> np.ndarray:
    minimum_peak_z = float(rule.minimum_peak_z)
    minimum_quality = float(rule.minimum_quality)
    parts = [_threshold_confidence(features.peak_z, minimum_peak_z)]
    if minimum_quality > 0.0:
        parts.append(_threshold_confidence(features.quality_score, minimum_quality))
    maximum_width = rule.maximum_log10_half_width
    if maximum_width is not None:
        width = np.asarray(features.log10_half_width, dtype=float)
        width_confidence = np.where(
            np.isfinite(width),
            np.clip(0.5 + 0.5 * (float(maximum_width) - width) / float(maximum_width), 0.0, 1.0),
            0.0,
        )
        parts.append(width_confidence)
    return _minimum_confidence(*parts)


def _rfi_summary(
    lines: tuple[LineFeatures, ...],
    config: WaveDetectorConfig,
    n_windows: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    score = np.full(n_windows, np.nan, dtype=float)
    confidence = np.zeros(n_windows, dtype=float)
    frequency = np.full(n_windows, np.nan, dtype=float)
    rules_by_name = {rule.name: rule for rule in config.line_rules}
    for line in lines:
        name = line.name
        rule = rules_by_name[name]
        line_candidate = np.asarray(line.candidate, dtype=bool)
        line_score = np.asarray(line.peak_z, dtype=float)
        line_prominence = np.asarray(line.prominence_z, dtype=float)
        line_frequency = np.asarray(line.peak_frequency_khz, dtype=float)
        line_confidence = _minimum_confidence(
            _threshold_confidence(line_score, rule.minimum_peak_z),
            _threshold_confidence(line_prominence, rule.minimum_prominence_z),
        )
        replace = line_candidate & (~np.isfinite(score) | (line_score > score))
        score[replace] = line_score[replace]
        confidence[replace] = line_confidence[replace]
        frequency[replace] = line_frequency[replace]
    return score, confidence, frequency
