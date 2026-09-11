from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

import numpy as np

from sopran.analysis.waves.model import CandidateInterval


@dataclass(frozen=True)
class _MergedSpan:
    start_seconds: float
    stop_seconds: float
    source_indices: np.ndarray


def merge_half_open_intervals(
    time_start_seconds: np.ndarray,
    time_stop_seconds: np.ndarray,
    candidate: np.ndarray,
    *,
    merge_gap_seconds: float = 0.0,
) -> tuple[tuple[float, float], ...]:
    """Merge selected half-open intervals, including adjacent intervals."""

    return tuple(
        (span.start_seconds, span.stop_seconds)
        for span in _merged_spans(
            time_start_seconds,
            time_stop_seconds,
            candidate,
            merge_gap_seconds=merge_gap_seconds,
        )
    )


def build_candidate_intervals(
    *,
    time_start_seconds: np.ndarray,
    time_stop_seconds: np.ndarray,
    candidate: np.ndarray,
    phenomenon: str,
    score: np.ndarray,
    confidence: np.ndarray,
    peak_frequency_khz: np.ndarray,
    data_quality_warning: np.ndarray,
    component: str,
    source_dataset: str,
    detector: str,
    detector_version: str,
    detector_run_id: str,
    detector_config_id: str,
    feature_spec_id: str,
    feature_spec_hash: str,
    merge_gap_seconds: float,
) -> tuple[CandidateInterval, ...]:
    if not phenomenon:
        raise ValueError("phenomenon must not be empty")
    starts = np.asarray(time_start_seconds, dtype=float)
    stops = np.asarray(time_stop_seconds, dtype=float)
    scores = _validated_row_array(score, starts.size, "score", dtype=float)
    confidences = _validated_row_array(confidence, starts.size, "confidence", dtype=float)
    frequencies = _validated_row_array(
        peak_frequency_khz,
        starts.size,
        "peak_frequency_khz",
        dtype=float,
    )
    warnings = _validated_row_array(
        data_quality_warning,
        starts.size,
        "data_quality_warning",
        dtype=bool,
    )
    intervals: list[CandidateInterval] = []
    for span in _merged_spans(
        starts,
        stops,
        candidate,
        merge_gap_seconds=merge_gap_seconds,
    ):
        indices = span.source_indices
        finite_scores = np.isfinite(scores[indices])
        if np.any(finite_scores):
            eligible_indices = indices[finite_scores]
            peak_index = int(eligible_indices[int(np.argmax(scores[eligible_indices]))])
            peak_score = float(scores[peak_index])
        else:
            peak_index = int(indices[0])
            peak_score = np.nan
        finite_confidence = confidences[indices][np.isfinite(confidences[indices])]
        interval_confidence = (
            float(np.clip(np.max(finite_confidence), 0.0, 1.0))
            if finite_confidence.size
            else 0.0
        )
        interval_id = stable_interval_id(
            source_dataset=source_dataset,
            component=component,
            time_start_seconds=span.start_seconds,
            time_stop_seconds=span.stop_seconds,
            detector_config_id=detector_config_id,
        )
        event_id = _stable_id("waveevt", interval_id, phenomenon)
        quality_flags = ("data_quality_warning",) if np.any(warnings[indices]) else ()
        intervals.append(
            CandidateInterval(
                event_id=event_id,
                interval_id=interval_id,
                time_start_seconds=span.start_seconds,
                time_stop_seconds=span.stop_seconds,
                phenomenon=phenomenon,
                confidence=interval_confidence,
                score=peak_score,
                peak_time_seconds=float(0.5 * (starts[peak_index] + stops[peak_index])),
                peak_frequency_khz=float(frequencies[peak_index]),
                n_windows=int(indices.size),
                component=component,
                source_dataset=source_dataset,
                detector=detector,
                detector_version=detector_version,
                detector_run_id=detector_run_id,
                detector_config_id=detector_config_id,
                feature_spec_id=feature_spec_id,
                feature_spec_hash=feature_spec_hash,
                quality_flags=quality_flags,
            )
        )
    return tuple(intervals)


def stable_window_id(
    *,
    source_dataset: str,
    component: str,
    time_start_seconds: float,
    time_stop_seconds: float,
    feature_spec_id: str,
) -> str:
    return _stable_id(
        "wavewin",
        source_dataset,
        component,
        _canonical_time(time_start_seconds),
        _canonical_time(time_stop_seconds),
        feature_spec_id,
    )


def stable_interval_id(
    *,
    source_dataset: str,
    component: str,
    time_start_seconds: float,
    time_stop_seconds: float,
    detector_config_id: str,
) -> str:
    return _stable_id(
        "waveint",
        source_dataset,
        component,
        _canonical_time(time_start_seconds),
        _canonical_time(time_stop_seconds),
        detector_config_id,
    )


def stable_detector_run_id(
    *,
    source_dataset: str,
    component: str,
    detector_config_id: str,
    source_start_seconds: float,
    source_stop_seconds: float,
) -> str:
    return _stable_id(
        "waverun",
        source_dataset,
        component,
        detector_config_id,
        _canonical_time(source_start_seconds),
        _canonical_time(source_stop_seconds),
    )


def _merged_spans(
    time_start_seconds: np.ndarray,
    time_stop_seconds: np.ndarray,
    candidate: np.ndarray,
    *,
    merge_gap_seconds: float,
) -> tuple[_MergedSpan, ...]:
    starts = np.asarray(time_start_seconds, dtype=float)
    stops = np.asarray(time_stop_seconds, dtype=float)
    selected = np.asarray(candidate, dtype=bool)
    if starts.ndim != 1 or stops.shape != starts.shape or selected.shape != starts.shape:
        raise ValueError("start, stop, and candidate arrays must be one-dimensional and aligned")
    if not np.isfinite(merge_gap_seconds) or merge_gap_seconds < 0.0:
        raise ValueError("merge_gap_seconds must be non-negative and finite")
    finite = np.isfinite(starts) & np.isfinite(stops)
    if np.any(stops[finite] <= starts[finite]):
        raise ValueError("every finite interval stop must exceed its start")
    indices = np.flatnonzero(selected & finite)
    if indices.size == 0:
        return ()
    order = np.argsort(starts[indices], kind="mergesort")
    indices = indices[order]

    output: list[_MergedSpan] = []
    current_indices = [int(indices[0])]
    current_start = float(starts[indices[0]])
    current_stop = float(stops[indices[0]])
    for raw_index in indices[1:]:
        index = int(raw_index)
        next_start = float(starts[index])
        next_stop = float(stops[index])
        if next_start <= current_stop + merge_gap_seconds:
            current_stop = max(current_stop, next_stop)
            current_indices.append(index)
        else:
            output.append(
                _MergedSpan(
                    current_start,
                    current_stop,
                    np.asarray(current_indices, dtype=int),
                )
            )
            current_start = next_start
            current_stop = next_stop
            current_indices = [index]
    output.append(
        _MergedSpan(current_start, current_stop, np.asarray(current_indices, dtype=int))
    )
    return tuple(output)


def _validated_row_array(
    values: np.ndarray,
    rows: int,
    name: str,
    *,
    dtype: type,
) -> np.ndarray:
    array: np.ndarray = np.asarray(values, dtype=dtype)
    if array.shape != (rows,):
        raise ValueError(f"{name} must have one value per window")
    return array


def _canonical_time(seconds: float) -> str:
    return str(int(round(float(seconds) * 1.0e6)))


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}-{sha256(payload).hexdigest()[:20]}"
