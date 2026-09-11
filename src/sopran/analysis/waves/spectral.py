from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from sopran.analysis.waves.model import (
    FixedLine,
    FrequencyBand,
    LineDetectionRule,
    LineFeatures,
    PeakFeatures,
    PeakRule,
    WaveDetectorConfig,
    WaveFeatureSet,
    WindowConfig,
    WindowedSpectra,
    frequency_to_density_cm3,
    frequency_to_required_b_nt,
)


@dataclass(frozen=True)
class _BandStatistics:
    median: np.ndarray
    p90: np.ndarray
    maximum: np.ndarray
    broad_fraction: np.ndarray
    strong_fraction: np.ndarray


def time_to_seconds(values: np.ndarray) -> np.ndarray:
    """Convert numeric or datetime-like UTC values to floating Unix seconds."""

    raw = np.asarray(values)
    if raw.ndim != 1:
        raise ValueError("time must be one-dimensional")
    if np.issubdtype(raw.dtype, np.datetime64):
        micros = raw.astype("datetime64[us]").astype(np.int64)
        seconds = micros.astype(float) / 1.0e6
        seconds[np.isnat(raw)] = np.nan
        return seconds
    if np.issubdtype(raw.dtype, np.number):
        return raw.astype(float)
    try:
        datetimes = raw.astype("datetime64[us]")
    except (TypeError, ValueError) as exc:
        raise TypeError("time must contain numeric seconds or datetime-like values") from exc
    micros = datetimes.astype(np.int64)
    seconds = micros.astype(float) / 1.0e6
    seconds[np.isnat(datetimes)] = np.nan
    return seconds


def log_frequency_grid(config: WindowConfig) -> np.ndarray:
    return np.geomspace(
        config.frequency_minimum_khz,
        config.frequency_maximum_khz,
        config.frequency_bins,
    ).astype(float)


def power_to_db(values: np.ndarray) -> np.ndarray:
    data = np.asarray(values, dtype=float)
    db = np.full(data.shape, np.nan, dtype=float)
    valid = np.isfinite(data) & (data > 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        db[valid] = 10.0 * np.log10(data[valid])
    return db


def robust_center_scale(
    matrix: np.ndarray,
    *,
    axis: int,
    minimum_scale: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    data = np.asarray(matrix, dtype=float)
    if data.ndim != 2:
        raise ValueError("matrix must be two-dimensional")
    if axis not in (0, 1):
        raise ValueError("axis must be 0 or 1")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        center = np.nanmedian(data, axis=axis)
        expanded = center[None, :] if axis == 0 else center[:, None]
        mad = np.nanmedian(np.abs(data - expanded), axis=axis)
        fallback = np.nanstd(data, axis=axis)
    scale = 1.4826 * mad
    scale = np.where(np.isfinite(scale) & (scale >= minimum_scale), scale, fallback)
    scale = np.where(np.isfinite(scale) & (scale >= minimum_scale), scale, 1.0)
    return np.asarray(center, dtype=float), np.asarray(scale, dtype=float)


def normalize_window_spectra(
    raw_db: np.ndarray,
    config: WindowConfig,
    *,
    reference_rows: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    raw = np.asarray(raw_db, dtype=float)
    if raw.ndim != 2:
        raise ValueError("raw_db must be two-dimensional")
    if raw.shape[0] == 0:
        empty_frequency = np.full(raw.shape[1], np.nan, dtype=float)
        return raw.copy(), empty_frequency, empty_frequency.copy()
    if reference_rows is None:
        reference = raw
    else:
        reference_mask = np.asarray(reference_rows, dtype=bool)
        if reference_mask.shape != (raw.shape[0],):
            raise ValueError("reference_rows must have one value per spectrum")
        reference = raw[reference_mask, :]
        if reference.shape[0] == 0:
            reference = raw
    center, scale = robust_center_scale(
        reference,
        axis=0,
        minimum_scale=config.robust_minimum_scale_db,
    )
    normalized = (raw - center[None, :]) / scale[None, :]
    if config.shape_normalize:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            row_center = np.nanmedian(normalized, axis=1)
        normalized = normalized - row_center[:, None]
    normalized = np.clip(normalized, -config.z_clip, config.z_clip)
    return normalized.astype(float), center, scale


def prepare_windowed_spectra(
    time: np.ndarray,
    frequency_khz: np.ndarray,
    spectrum: np.ndarray,
    *,
    input_scale: str,
    config: WindowConfig,
    valid_time: np.ndarray | None = None,
) -> WindowedSpectra:
    """Build median spectra on deterministic half-open time windows."""

    time_seconds = time_to_seconds(np.asarray(time))
    frequency = np.asarray(frequency_khz, dtype=float)
    values = np.asarray(spectrum, dtype=float)
    if frequency.ndim != 1:
        raise ValueError("frequency_khz must be one-dimensional")
    if values.ndim != 2:
        raise ValueError("spectrum must be two-dimensional with shape (time, frequency)")
    if values.shape != (time_seconds.size, frequency.size):
        raise ValueError(
            "spectrum shape must match time and frequency lengths: "
            f"{values.shape} != ({time_seconds.size}, {frequency.size})"
        )
    if input_scale == "linear_power":
        db = power_to_db(values)
    elif input_scale == "db":
        db = values.copy()
        db[~np.isfinite(db)] = np.nan
    else:
        raise ValueError("input_scale must be 'db' or 'linear_power'")

    if valid_time is not None:
        valid = np.asarray(valid_time, dtype=bool)
        if valid.shape != (time_seconds.size,):
            raise ValueError("valid_time must have the same length as time")
        db[~valid, :] = np.nan

    finite_time = np.isfinite(time_seconds)
    positive_frequency = np.isfinite(frequency) & (frequency > 0.0)
    if not np.any(finite_time) or not np.any(positive_frequency):
        return _empty_windowed(config)

    time_seconds = time_seconds[finite_time]
    db = db[finite_time, :][:, positive_frequency]
    frequency = frequency[positive_frequency]
    time_order = np.argsort(time_seconds, kind="mergesort")
    frequency_order = np.argsort(frequency, kind="mergesort")
    time_seconds = time_seconds[time_order]
    db = db[time_order, :][:, frequency_order]
    frequency = frequency[frequency_order]

    frequency, unique_indices = np.unique(frequency, return_index=True)
    db = db[:, unique_indices]
    target_frequency = log_frequency_grid(config)
    if time_seconds.size == 0 or frequency.size < config.minimum_frequency_bins:
        return _empty_windowed(config)

    cadence = _median_positive_difference(time_seconds)
    effective_stop = (
        float(time_seconds[-1] + cadence)
        if np.isfinite(cadence)
        else float(time_seconds[-1])
    )
    first_time = float(time_seconds[0])
    if config.anchor == "epoch":
        first_start = float(np.floor(first_time / config.step_seconds) * config.step_seconds)
    else:
        first_start = first_time
    if effective_stop <= first_start:
        return _empty_windowed(config)
    n_starts = int(np.ceil((effective_stop - first_start) / config.step_seconds))
    starts = first_start + np.arange(n_starts, dtype=float) * config.step_seconds
    starts = starts[starts < effective_stop]
    raw_rows: list[np.ndarray] = []
    kept_starts: list[float] = []
    point_counts: list[int] = []
    finite_fractions: list[float] = []
    record_has_data = np.any(np.isfinite(db), axis=1)
    for start in starts:
        stop = start + config.duration_seconds
        time_mask = (time_seconds >= start) & (time_seconds < stop)
        n_points = int(np.count_nonzero(time_mask & record_has_data))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            median_spectrum = np.nanmedian(db[time_mask, :], axis=0)
        interpolated = interpolate_log_spectrum(
            frequency,
            median_spectrum,
            target_frequency,
            minimum_bins=config.minimum_frequency_bins,
        )
        raw_rows.append(interpolated)
        kept_starts.append(float(start))
        point_counts.append(n_points)
        finite_fractions.append(float(np.isfinite(interpolated).mean()))

    if not raw_rows:
        return _empty_windowed(config)
    raw_matrix = np.vstack(raw_rows).astype(float)
    start_array = np.asarray(kept_starts, dtype=float)
    point_count_array = np.asarray(point_counts, dtype=int)
    finite_fraction_array = np.asarray(finite_fractions, dtype=float)
    reference_rows = (
        (point_count_array >= config.minimum_points)
        & (finite_fraction_array >= config.minimum_finite_fraction)
    )
    normalized, center, scale = normalize_window_spectra(
        raw_matrix,
        config,
        reference_rows=reference_rows,
    )
    stop_array = np.minimum(start_array + config.duration_seconds, effective_stop)
    return WindowedSpectra(
        time_start_seconds=start_array,
        time_stop_seconds=stop_array,
        time_mid_seconds=0.5 * (start_array + stop_array),
        frequency_khz=target_frequency,
        raw_db=raw_matrix,
        normalized_z=normalized,
        background_center_db=center,
        background_scale_db=scale,
        n_points=point_count_array,
        finite_fraction=finite_fraction_array,
    )


def interpolate_log_spectrum(
    frequency_khz: np.ndarray,
    spectrum: np.ndarray,
    target_frequency_khz: np.ndarray,
    *,
    minimum_bins: int = 8,
) -> np.ndarray:
    frequency = np.asarray(frequency_khz, dtype=float)
    values = np.asarray(spectrum, dtype=float)
    target = np.asarray(target_frequency_khz, dtype=float)
    finite = np.isfinite(frequency) & np.isfinite(values) & (frequency > 0.0)
    if np.count_nonzero(finite) < minimum_bins:
        return np.full(target.shape, np.nan, dtype=float)
    x = np.log10(frequency[finite])
    y = values[finite]
    order = np.argsort(x, kind="mergesort")
    unique_x, unique_indices = np.unique(x[order], return_index=True)
    if unique_x.size < minimum_bins:
        return np.full(target.shape, np.nan, dtype=float)
    unique_y = y[order][unique_indices]
    interpolated: np.ndarray = np.interp(
        np.log10(target),
        unique_x,
        unique_y,
        left=np.nan,
        right=np.nan,
    ).astype(float)
    return interpolated


def fixed_line_keep_mask(
    frequency_khz: np.ndarray,
    lines: tuple[FixedLine, ...],
) -> np.ndarray:
    frequency = np.asarray(frequency_khz, dtype=float)
    keep: np.ndarray = np.isfinite(frequency) & (frequency > 0.0)
    for line in lines:
        keep &= np.abs(frequency - line.frequency_khz) > line.half_width_khz
    return keep


def extract_wave_features(
    windows: WindowedSpectra,
    config: WaveDetectorConfig,
) -> WaveFeatureSet:
    frequency = np.asarray(windows.frequency_khz, dtype=float)
    normalized = np.asarray(windows.normalized_z, dtype=float)
    if normalized.ndim != 2 or normalized.shape[1] != frequency.size:
        raise ValueError("window normalized_z must have shape (window, frequency)")

    bbn = _band_statistics(
        frequency,
        normalized,
        config.bbn_band,
        broad_threshold=config.bbn_broad_threshold_z,
    )
    bbn_core = _band_statistics(
        frequency,
        normalized,
        config.bbn_core_band,
        broad_threshold=config.bbn_broad_threshold_z,
    )
    radio_stats = _band_statistics(
        frequency,
        normalized,
        config.radio_rule.band,
        broad_threshold=config.radio_broad_threshold_z,
        mask_lines=config.radio_rule.mask_lines,
    )
    high_stats = _band_statistics(
        frequency,
        normalized,
        config.high_band,
        broad_threshold=config.radio_broad_threshold_z,
    )
    low_peak = local_peak_features(frequency, normalized, config.low_ridge_rule)
    high_peak = local_peak_features(frequency, normalized, config.high_ridge_rule)
    radio_peak = local_peak_features(frequency, normalized, config.radio_rule)
    lines = tuple(
        line_detection_features(frequency, normalized, rule) for rule in config.line_rules
    )

    bbn_candidate = (
        np.isfinite(bbn.p90)
        & (bbn.p90 >= config.bbn_minimum_p90_z)
        & np.isfinite(bbn.broad_fraction)
        & (bbn.broad_fraction >= config.bbn_minimum_broad_fraction)
    )
    low_candidate = _peak_candidate(low_peak, config.low_ridge_rule)
    high_candidate = _peak_candidate(high_peak, config.high_ridge_rule)
    radio_candidate = (
        _peak_candidate(radio_peak, config.radio_rule)
        & np.isfinite(radio_stats.broad_fraction)
        & (radio_stats.broad_fraction >= config.radio_minimum_broad_fraction)
    )
    if lines:
        line_candidates = np.vstack([line.candidate for line in lines])
        instrument_candidate = np.any(line_candidates, axis=0)
        radio_veto = np.any(
            np.vstack([line.candidate for line in lines if line.veto_radio]),
            axis=0,
        ) if any(line.veto_radio for line in lines) else np.zeros(normalized.shape[0], dtype=bool)
        radio_candidate &= ~radio_veto
    else:
        instrument_candidate = np.zeros(normalized.shape[0], dtype=bool)

    data_warning = (
        (windows.finite_fraction < config.window.minimum_finite_fraction)
        | (windows.n_points < config.data_warning_minimum_points)
    )
    return WaveFeatureSet(
        bbn_median_z=bbn.median,
        bbn_p90_z=bbn.p90,
        bbn_peak_z=bbn.maximum,
        bbn_broad_fraction=bbn.broad_fraction,
        bbn_core_p90_z=bbn_core.p90,
        radio_median_z=radio_stats.median,
        radio_peak_z=radio_stats.maximum,
        radio_broad_fraction=radio_stats.broad_fraction,
        high_median_z=high_stats.median,
        low_ridge=low_peak,
        high_ridge=high_peak,
        radio=radio_peak,
        lines=lines,
        bbn_candidate=bbn_candidate.astype(bool),
        low_ridge_candidate=low_candidate.astype(bool),
        high_ridge_candidate=high_candidate.astype(bool),
        radio_candidate=radio_candidate.astype(bool),
        instrument_rfi_candidate=instrument_candidate.astype(bool),
        data_quality_warning=data_warning.astype(bool),
    )


def local_peak_features(
    frequency_khz: np.ndarray,
    matrix: np.ndarray,
    rule: PeakRule,
) -> PeakFeatures:
    frequency = np.asarray(frequency_khz, dtype=float)
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2 or values.shape[1] != frequency.size:
        raise ValueError("matrix must have shape (window, frequency)")
    n_rows = values.shape[0]
    outputs = [np.full(n_rows, np.nan, dtype=float) for _ in range(11)]
    (
        peak_frequency,
        peak_z,
        prominence,
        frequency_low,
        frequency_high,
        log_width,
        density,
        density_low,
        density_high,
        required_b,
        quality,
    ) = outputs
    base_mask = (
        np.isfinite(frequency)
        & (frequency >= rule.band.minimum_khz)
        & (frequency < rule.band.maximum_khz)
        & fixed_line_keep_mask(frequency, rule.mask_lines)
    )
    for row_index, row in enumerate(values):
        valid = base_mask & np.isfinite(row)
        if np.count_nonzero(valid) < 3:
            continue
        valid_indices = np.flatnonzero(valid)
        peak_index = int(valid_indices[int(np.argmax(row[valid_indices]))])
        current_peak = float(row[peak_index])
        support = valid & (row >= current_peak - rule.support_drop_z)
        low_index = peak_index
        high_index = peak_index
        while low_index > 0 and support[low_index - 1]:
            low_index -= 1
        while high_index + 1 < support.size and support[high_index + 1]:
            high_index += 1
        low_edge, high_edge = frequency_edge_bounds(frequency, low_index, high_index)
        outside = row[valid & ~support]
        current_prominence = current_peak - float(np.max(outside)) if outside.size else current_peak
        current_frequency = float(frequency[peak_index])
        if low_edge > 0.0 and high_edge > 0.0:
            current_width = float(
                max(
                    abs(np.log10(current_frequency / low_edge)),
                    abs(np.log10(high_edge / current_frequency)),
                )
            )
        else:
            current_width = np.nan
        delta_score = float(np.clip((current_peak - 2.0) / 4.0, 0.0, 1.0))
        prominence_score = float(np.clip(current_prominence, 0.0, 1.0))
        width_score = (
            float(np.clip(1.0 - current_width / 0.50, 0.0, 1.0))
            if np.isfinite(current_width)
            else 0.0
        )

        peak_frequency[row_index] = current_frequency
        peak_z[row_index] = current_peak
        prominence[row_index] = current_prominence
        frequency_low[row_index] = low_edge
        frequency_high[row_index] = high_edge
        log_width[row_index] = current_width
        density[row_index] = float(frequency_to_density_cm3(current_frequency))
        density_low[row_index] = float(frequency_to_density_cm3(low_edge))
        density_high[row_index] = float(frequency_to_density_cm3(high_edge))
        required_b[row_index] = float(frequency_to_required_b_nt(current_frequency))
        quality[row_index] = delta_score * prominence_score * width_score
    return PeakFeatures(
        peak_frequency_khz=peak_frequency,
        peak_z=peak_z,
        prominence_z=prominence,
        frequency_low_khz=frequency_low,
        frequency_high_khz=frequency_high,
        log10_half_width=log_width,
        density_if_fpe_cm3=density,
        density_if_fpe_low_cm3=density_low,
        density_if_fpe_high_cm3=density_high,
        required_b_if_fce_nt=required_b,
        quality_score=quality,
    )


def line_detection_features(
    frequency_khz: np.ndarray,
    matrix: np.ndarray,
    rule: LineDetectionRule,
) -> LineFeatures:
    frequency = np.asarray(frequency_khz, dtype=float)
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2 or values.shape[1] != frequency.size:
        raise ValueError("matrix must have shape (window, frequency)")
    n_rows = values.shape[0]
    peak_frequency = np.full(n_rows, np.nan, dtype=float)
    peak_z = np.full(n_rows, np.nan, dtype=float)
    prominence = np.full(n_rows, np.nan, dtype=float)
    line_mask = _band_mask(frequency, rule.line_band)
    side_mask = _band_mask(frequency, rule.side_band) & ~line_mask
    for row_index, row in enumerate(values):
        valid_line = line_mask & np.isfinite(row)
        if not np.any(valid_line):
            continue
        indices = np.flatnonzero(valid_line)
        peak_index = int(indices[int(np.argmax(row[indices]))])
        valid_side = side_mask & np.isfinite(row)
        side_p90 = _finite_percentile(row[valid_side], 90.0, default=0.0)
        peak_frequency[row_index] = frequency[peak_index]
        peak_z[row_index] = row[peak_index]
        prominence[row_index] = row[peak_index] - side_p90
    candidate = (
        np.isfinite(peak_z)
        & (peak_z >= rule.minimum_peak_z)
        & np.isfinite(prominence)
        & (prominence >= rule.minimum_prominence_z)
    )
    return LineFeatures(
        name=rule.name,
        peak_frequency_khz=peak_frequency,
        peak_z=peak_z,
        prominence_z=prominence,
        candidate=candidate.astype(bool),
        veto_radio=rule.veto_radio,
    )


def frequency_edge_bounds(
    frequency_khz: np.ndarray,
    low_index: int,
    high_index: int,
) -> tuple[float, float]:
    frequency = np.asarray(frequency_khz, dtype=float)
    if frequency.size == 0:
        return np.nan, np.nan
    low_index = int(np.clip(low_index, 0, frequency.size - 1))
    high_index = int(np.clip(high_index, low_index, frequency.size - 1))
    if low_index > 0 and frequency[low_index - 1] > 0.0:
        low = float(np.sqrt(frequency[low_index - 1] * frequency[low_index]))
    else:
        low = float(frequency[low_index])
    if high_index + 1 < frequency.size and frequency[high_index + 1] > 0.0:
        high = float(np.sqrt(frequency[high_index] * frequency[high_index + 1]))
    else:
        high = float(frequency[high_index])
    return low, high


def _peak_candidate(features: PeakFeatures, rule: PeakRule) -> np.ndarray:
    candidate: np.ndarray = (
        np.isfinite(features.peak_z)
        & (features.peak_z >= rule.minimum_peak_z)
        & np.isfinite(features.quality_score)
        & (features.quality_score >= rule.minimum_quality)
    )
    if rule.maximum_log10_half_width is not None:
        candidate &= (
            np.isfinite(features.log10_half_width)
            & (features.log10_half_width <= rule.maximum_log10_half_width)
        )
    return candidate


def _band_statistics(
    frequency_khz: np.ndarray,
    matrix: np.ndarray,
    band: FrequencyBand,
    *,
    broad_threshold: float,
    mask_lines: tuple[FixedLine, ...] = (),
) -> _BandStatistics:
    frequency = np.asarray(frequency_khz, dtype=float)
    values = np.asarray(matrix, dtype=float)
    mask = _band_mask(frequency, band) & fixed_line_keep_mask(frequency, mask_lines)
    n_rows = values.shape[0]
    median = np.full(n_rows, np.nan, dtype=float)
    p90 = np.full(n_rows, np.nan, dtype=float)
    maximum = np.full(n_rows, np.nan, dtype=float)
    broad_fraction = np.full(n_rows, np.nan, dtype=float)
    strong_fraction = np.full(n_rows, np.nan, dtype=float)
    for index, row in enumerate(values):
        data = row[mask & np.isfinite(row)]
        if data.size == 0:
            continue
        median[index] = float(np.median(data))
        p90[index] = float(np.percentile(data, 90.0))
        maximum[index] = float(np.max(data))
        broad_fraction[index] = float(np.mean(data >= broad_threshold))
        strong_fraction[index] = float(np.mean(data >= 2.0))
    return _BandStatistics(median, p90, maximum, broad_fraction, strong_fraction)


def _band_mask(frequency_khz: np.ndarray, band: FrequencyBand) -> np.ndarray:
    mask: np.ndarray = (
        np.isfinite(frequency_khz)
        & (frequency_khz >= band.minimum_khz)
        & (frequency_khz < band.maximum_khz)
    )
    return mask


def _finite_percentile(values: np.ndarray, percentile: float, *, default: float) -> float:
    data = np.asarray(values, dtype=float)
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return default
    return float(np.percentile(finite, percentile))


def _median_positive_difference(values: np.ndarray) -> float:
    differences = np.diff(np.asarray(values, dtype=float))
    positive = differences[np.isfinite(differences) & (differences > 0.0)]
    return float(np.median(positive)) if positive.size else np.nan


def _empty_windowed(config: WindowConfig) -> WindowedSpectra:
    frequency = log_frequency_grid(config)
    empty = np.empty(0, dtype=float)
    return WindowedSpectra(
        time_start_seconds=empty,
        time_stop_seconds=empty.copy(),
        time_mid_seconds=empty.copy(),
        frequency_khz=frequency,
        raw_db=np.empty((0, frequency.size), dtype=float),
        normalized_z=np.empty((0, frequency.size), dtype=float),
        background_center_db=np.full(frequency.size, np.nan, dtype=float),
        background_scale_db=np.full(frequency.size, np.nan, dtype=float),
        n_points=np.empty(0, dtype=int),
        finite_fraction=empty.copy(),
    )
