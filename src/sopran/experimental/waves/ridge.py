from __future__ import annotations

import warnings

import numpy as np

from sopran.experimental.waves.model import (
    FixedLine,
    RidgeTrack,
    RidgeTrackerConfig,
    frequency_to_density_cm3,
)
from sopran.experimental.waves.spectral import fixed_line_keep_mask


def frequency_local_contrast(
    frequency_khz: np.ndarray,
    matrix: np.ndarray,
    *,
    baseline_window_bins: int = 25,
    mask_lines: tuple[FixedLine, ...] = (),
) -> np.ndarray:
    """Subtract a broad frequency-local median from every spectrum."""

    frequency = np.asarray(frequency_khz, dtype=float)
    values = np.asarray(matrix, dtype=float)
    if frequency.ndim != 1:
        raise ValueError("frequency_khz must be one-dimensional")
    if values.ndim != 2 or values.shape[1] != frequency.size:
        raise ValueError("matrix must have shape (time, frequency)")
    baseline = _rolling_frequency_median(values, baseline_window_bins)
    contrast: np.ndarray = values - baseline
    contrast[:, ~fixed_line_keep_mask(frequency, tuple(mask_lines))] = np.nan
    return contrast


def track_spectral_ridge(
    time_seconds: np.ndarray,
    frequency_khz: np.ndarray,
    normalized_matrix: np.ndarray,
    config: RidgeTrackerConfig,
) -> RidgeTrack:
    """Track one smooth ridge, splitting paths at missing rows and time gaps."""

    time = np.asarray(time_seconds, dtype=float)
    frequency = np.asarray(frequency_khz, dtype=float)
    matrix = np.asarray(normalized_matrix, dtype=float)
    if time.ndim != 1:
        raise ValueError("time_seconds must be one-dimensional")
    if frequency.ndim != 1:
        raise ValueError("frequency_khz must be one-dimensional")
    if matrix.shape != (time.size, frequency.size):
        raise ValueError("normalized_matrix must have shape (time, frequency)")
    if time.size and (not np.isfinite(time).all() or np.any(np.diff(time) < 0.0)):
        raise ValueError("time_seconds must be finite and sorted")

    contrast = frequency_local_contrast(
        frequency,
        matrix,
        baseline_window_bins=config.baseline_window_bins,
        mask_lines=config.mask_lines,
    )
    band = (
        np.isfinite(frequency)
        & (frequency >= config.band.minimum_khz)
        & (frequency <= config.band.maximum_khz)
    )
    contrast[:, ~band] = np.nan
    return viterbi_ridge_track(time, frequency, contrast, config)


def viterbi_ridge_track(
    time_seconds: np.ndarray,
    frequency_khz: np.ndarray,
    score_matrix: np.ndarray,
    config: RidgeTrackerConfig,
) -> RidgeTrack:
    time = np.asarray(time_seconds, dtype=float)
    frequency = np.asarray(frequency_khz, dtype=float)
    scores = np.asarray(score_matrix, dtype=float)
    if time.ndim != 1 or frequency.ndim != 1:
        raise ValueError("time_seconds and frequency_khz must be one-dimensional")
    if scores.shape != (time.size, frequency.size):
        raise ValueError("score_matrix must have shape (time, frequency)")
    if time.size and (not np.isfinite(time).all() or np.any(np.diff(time) < 0.0)):
        raise ValueError("time_seconds must be finite and sorted")

    n_time = time.size
    tracked_frequency = np.full(n_time, np.nan, dtype=float)
    tracked_score = np.full(n_time, np.nan, dtype=float)
    state_index = np.full(n_time, -1, dtype=int)
    segment_index = np.full(n_time, -1, dtype=int)
    if n_time == 0:
        return RidgeTrack(
            name=config.name,
            time_seconds=time,
            frequency_khz=tracked_frequency,
            density_cm3=tracked_frequency.copy(),
            score=tracked_score,
            candidate=np.empty(0, dtype=bool),
            state_index=state_index,
            segment_index=segment_index,
        )

    valid_frequency = np.isfinite(frequency) & (frequency > 0.0)
    row_valid = np.any(np.isfinite(scores) & valid_frequency[None, :], axis=1)
    segments = _valid_time_segments(
        time,
        row_valid,
        maximum_gap_seconds=config.maximum_gap_seconds,
    )
    for segment_number, (start, stop) in enumerate(segments):
        local_state = _viterbi_segment(
            frequency,
            scores[start:stop, :],
            smoothness=config.smoothness,
            maximum_jump_dex=config.maximum_jump_dex,
        )
        local_rows = np.arange(start, stop)
        local_valid = local_state >= 0
        chosen_rows = local_rows[local_valid]
        chosen_states = local_state[local_valid]
        state_index[chosen_rows] = chosen_states
        segment_index[chosen_rows] = segment_number
        tracked_frequency[chosen_rows] = frequency[chosen_states]
        tracked_score[chosen_rows] = scores[chosen_rows, chosen_states]
    candidate = np.isfinite(tracked_score) & (tracked_score >= config.candidate_threshold)
    return RidgeTrack(
        name=config.name,
        time_seconds=time,
        frequency_khz=tracked_frequency,
        density_cm3=np.asarray(frequency_to_density_cm3(tracked_frequency), dtype=float),
        score=tracked_score,
        candidate=candidate.astype(bool),
        state_index=state_index,
        segment_index=segment_index,
    )


def _rolling_frequency_median(matrix: np.ndarray, window_bins: int) -> np.ndarray:
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2:
        raise ValueError("matrix must be two-dimensional")
    width = max(3, int(window_bins))
    if width % 2 == 0:
        width += 1
    half = width // 2
    baseline = np.full(values.shape, np.nan, dtype=float)
    for column in range(values.shape[1]):
        lower = max(0, column - half)
        upper = min(values.shape[1], column + half + 1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            baseline[:, column] = np.nanmedian(values[:, lower:upper], axis=1)
    return baseline


def _valid_time_segments(
    time_seconds: np.ndarray,
    row_valid: np.ndarray,
    *,
    maximum_gap_seconds: float,
) -> list[tuple[int, int]]:
    time = np.asarray(time_seconds, dtype=float)
    valid = np.asarray(row_valid, dtype=bool)
    segments: list[tuple[int, int]] = []
    start: int | None = None
    for index in range(time.size):
        continues = (
            start is not None
            and valid[index]
            and valid[index - 1]
            and time[index] - time[index - 1] <= maximum_gap_seconds
        )
        if valid[index] and start is None:
            start = index
        elif valid[index] and continues:
            continue
        elif valid[index]:
            if start is not None:
                segments.append((start, index))
            start = index
        elif start is not None:
            segments.append((start, index))
            start = None
    if start is not None:
        segments.append((start, time.size))
    return segments


def _viterbi_segment(
    frequency_khz: np.ndarray,
    score_matrix: np.ndarray,
    *,
    smoothness: float,
    maximum_jump_dex: float,
) -> np.ndarray:
    frequency = np.asarray(frequency_khz, dtype=float)
    scores = np.asarray(score_matrix, dtype=float)
    n_time, n_frequency = scores.shape
    if n_time == 0:
        return np.empty(0, dtype=int)
    valid_frequency = np.isfinite(frequency) & (frequency > 0.0)
    log_frequency = np.full(frequency.shape, np.nan, dtype=float)
    log_frequency[valid_frequency] = np.log10(frequency[valid_frequency])
    finite_score = np.isfinite(scores) & valid_frequency[None, :]
    emission = np.where(finite_score, scores, -np.inf)
    differences = log_frequency[:, None] - log_frequency[None, :]
    transition = -smoothness * differences**2
    transition[np.abs(differences) > maximum_jump_dex] = -np.inf
    transition[~np.isfinite(transition)] = -np.inf

    dynamic = np.full((n_time, n_frequency), -np.inf, dtype=float)
    back = np.full((n_time, n_frequency), -1, dtype=int)
    dynamic[0] = emission[0]
    for time_index in range(1, n_time):
        candidates = dynamic[time_index - 1][:, None] + transition
        best_previous = np.argmax(candidates, axis=0)
        best_values = candidates[best_previous, np.arange(n_frequency)]
        dynamic[time_index] = emission[time_index] + best_values
        back[time_index] = best_previous
        if not np.any(np.isfinite(dynamic[time_index])):
            dynamic[time_index] = emission[time_index]
            back[time_index] = -1

    state = np.full(n_time, -1, dtype=int)
    state[-1] = int(np.argmax(dynamic[-1]))
    for time_index in range(n_time - 1, 0, -1):
        previous = back[time_index, state[time_index]] if state[time_index] >= 0 else -1
        if previous < 0:
            previous = int(np.argmax(dynamic[time_index - 1]))
        state[time_index - 1] = previous
    state[~np.any(finite_score, axis=1)] = -1
    return state
