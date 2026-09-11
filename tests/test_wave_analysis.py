from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from sopran import Store
from sopran.experimental.waves import (
    BBN_ESW_CANDIDATE,
    FPE_LOW_RIDGE_CANDIDATE,
    INSTRUMENT_RFI_CANDIDATE,
    PLASMA_LINE_RIDGE_CANDIDATE,
    RADIO_AKR_CANDIDATE,
    TRACKED_HIGH_PLASMA_RIDGE_CANDIDATE,
    TRACKED_LOW_FPE_RIDGE_CANDIDATE,
    FixedLine,
    FrequencyBand,
    LineDetectionRule,
    PeakRule,
    RidgeTrackerConfig,
    WaveDetectorConfig,
    WindowConfig,
    WindowedSpectra,
    build_candidate_intervals,
    detect_wave_candidates,
    extract_wave_features,
    feature_spec_hash,
    fixed_line_keep_mask,
    log_frequency_grid,
    merge_half_open_intervals,
    robust_center_scale,
    track_spectral_ridge,
)


def test_log_grid_and_median_mad_normalization_are_robust() -> None:
    window = WindowConfig(
        frequency_minimum_khz=0.5,
        frequency_maximum_khz=500.0,
        frequency_bins=7,
        minimum_frequency_bins=3,
    )
    grid = log_frequency_grid(window)
    np.testing.assert_allclose(grid[[0, -1]], [0.5, 500.0])
    np.testing.assert_allclose(np.diff(np.log10(grid)), np.full(6, 0.5))

    center, scale = robust_center_scale(
        np.asarray([[0.0, 10.0], [1.0, 11.0], [2.0, 1000.0]]),
        axis=0,
        minimum_scale=0.1,
    )
    np.testing.assert_allclose(center, [1.0, 11.0])
    np.testing.assert_allclose(scale, [1.4826, 1.4826])


def test_fixed_line_masks_and_multi_label_features_are_independent() -> None:
    frequency = np.geomspace(0.1, 1000.0, 128)
    line_200 = FixedLine("200_khz", 200.0, 12.0)
    keep = fixed_line_keep_mask(np.asarray([180.0, 200.0, 213.0]), (line_200,))
    np.testing.assert_array_equal(keep, [True, False, True])

    config = _feature_test_config(line_200)
    normalized = np.zeros((2, frequency.size), dtype=float)
    bbn = (frequency >= 0.1) & (frequency < 10.0)
    radio = (frequency >= 100.0) & (frequency < 500.0)
    normalized[0, bbn] = 2.2
    normalized[0, _nearest(frequency, 5.0)] = 4.5
    normalized[0, _nearest(frequency, 50.0)] = 4.5
    normalized[0, radio] = 1.6
    normalized[0, _nearest(frequency, 300.0)] = 4.5

    normalized[1, radio] = 1.6
    normalized[1, _nearest(frequency, 300.0)] = 4.5
    normalized[1, _nearest(frequency, 200.0)] = 5.0
    features = extract_wave_features(_windows(frequency, normalized), config)

    assert features.bbn_candidate[0]
    assert features.low_ridge_candidate[0]
    assert features.high_ridge_candidate[0]
    assert features.radio_candidate[0]
    assert features.instrument_rfi_candidate[1]
    assert not features.radio_candidate[1]


def test_low_and_high_viterbi_tracks_are_separate_and_split_at_gaps() -> None:
    time = np.asarray([0.0, 60.0, 120.0, 300.0, 360.0])
    frequency = np.geomspace(2.0, 100.0, 96)
    matrix = np.zeros((time.size, frequency.size), dtype=float)
    for row in range(time.size):
        matrix[row, _nearest(frequency, 5.0 + 0.2 * row)] = 4.0
        matrix[row, _nearest(frequency, 55.0 + 0.5 * row)] = 5.0
    line_30 = FixedLine("30_khz", 30.0, 2.0)
    matrix[:, np.abs(frequency - line_30.frequency_khz) <= line_30.half_width_khz] = 20.0

    low = track_spectral_ridge(
        time,
        frequency,
        matrix,
        RidgeTrackerConfig(
            "low",
            FrequencyBand("low", 2.0, 30.0),
            mask_lines=(line_30,),
        ),
    )
    high = track_spectral_ridge(
        time,
        frequency,
        matrix,
        RidgeTrackerConfig(
            "high",
            FrequencyBand("high", 30.0, 100.0),
            mask_lines=(line_30,),
        ),
    )

    assert np.all(low.frequency_khz < 10.0)
    assert np.all(high.frequency_khz > 40.0)
    np.testing.assert_array_equal(low.segment_index, [0, 0, 0, 1, 1])
    np.testing.assert_array_equal(high.segment_index, [0, 0, 0, 1, 1])
    assert np.all(low.candidate)
    assert np.all(high.candidate)


def test_half_open_merge_and_interval_ids_are_deterministic() -> None:
    starts = np.asarray([0.0, 60.0, 180.0])
    stops = np.asarray([60.0, 120.0, 240.0])
    candidate = np.asarray([True, True, True])
    assert merge_half_open_intervals(starts, stops, candidate) == (
        (0.0, 120.0),
        (180.0, 240.0),
    )

    common = {
        "time_start_seconds": starts,
        "time_stop_seconds": stops,
        "candidate": np.asarray([True, True, False]),
        "score": np.asarray([2.0, 3.0, 0.0]),
        "confidence": np.asarray([0.6, 0.8, 0.0]),
        "peak_frequency_khz": np.asarray([5.0, 6.0, np.nan]),
        "data_quality_warning": np.asarray([False, False, False]),
        "component": "Ey",
        "source_dataset": "synthetic:wfc",
        "detector": "test.detector",
        "detector_version": "1",
        "detector_run_id": "waverun-test",
        "detector_config_id": "wavecfg-test",
        "feature_spec_id": "wavefs-test",
        "feature_spec_hash": "a" * 64,
        "merge_gap_seconds": 0.0,
    }
    bbn = build_candidate_intervals(phenomenon=BBN_ESW_CANDIDATE, **common)
    low = build_candidate_intervals(phenomenon=FPE_LOW_RIDGE_CANDIDATE, **common)
    assert len(bbn) == len(low) == 1
    assert bbn[0].interval_id == low[0].interval_id
    assert bbn[0].event_id != low[0].event_id
    assert bbn[0].score == pytest.approx(3.0)
    assert bbn[0].detector_run_id == "waverun-test"


def test_detector_tracks_provenance_and_non_overlapping_exposure() -> None:
    time = np.arange(130.0)
    frequency = np.geomspace(0.1, 1000.0, 64)
    spectrum = np.zeros((time.size, frequency.size), dtype=float)
    config = WaveDetectorConfig(
        window=WindowConfig(
            duration_seconds=120.0,
            step_seconds=60.0,
            minimum_points=8,
            minimum_frequency_bins=8,
            minimum_finite_fraction=0.65,
            frequency_minimum_khz=0.1,
            frequency_maximum_khz=1000.0,
            frequency_bins=64,
        )
    )
    result = detect_wave_candidates(
        time,
        frequency,
        spectrum,
        config=config,
        component="Ey",
        source_dataset="synthetic:wfc",
    )
    repeated = detect_wave_candidates(
        time,
        frequency,
        spectrum,
        config=config,
        component="Ey",
        source_dataset="synthetic:wfc",
    )
    spectrally_sparse = spectrum.copy()
    spectrally_sparse[:, 4:] = np.nan
    insufficient = detect_wave_candidates(
        time,
        frequency,
        spectrally_sparse,
        config=config,
        component="Ey",
        source_dataset="synthetic:wfc:sparse",
    )

    np.testing.assert_allclose(result.windows.time_start_seconds, [0.0, 60.0, 120.0])
    np.testing.assert_allclose(result.windows.time_stop_seconds, [120.0, 130.0, 130.0])
    np.testing.assert_array_equal(result.is_observed, [True, True, True])
    np.testing.assert_array_equal(result.is_eligible, [True, True, True])
    np.testing.assert_allclose(result.exposure_seconds, [60.0, 60.0, 10.0])
    assert result.exposure_seconds.sum() == pytest.approx(130.0)
    assert len(set(result.window_id.tolist())) == 3
    np.testing.assert_array_equal(result.window_id, repeated.window_id)
    assert result.detector_run_id == repeated.detector_run_id
    assert result.detector_config_id == repeated.detector_config_id
    assert result.feature_spec_id == repeated.feature_spec_id
    assert len(result.feature_spec_hash) == 64
    assert result.feature_spec_hash == feature_spec_hash(config)
    assert feature_spec_hash(replace(config, detector_version="2")) != result.feature_spec_hash
    np.testing.assert_array_equal(insufficient.is_observed, [True, True, True])
    np.testing.assert_array_equal(insufficient.is_eligible, [False, False, False])
    np.testing.assert_allclose(insufficient.exposure_seconds, 0.0)

    try:
        import polars as pl
    except ImportError:  # pragma: no cover - optional materialization dependency
        return
    from sopran.core.time import _filter_polars_time, period

    frame = result.features_to_polars()
    assert frame.schema["time_start"] == pl.String
    assert frame.schema["time_stop"] == pl.String
    assert frame.schema["time_mid"] == pl.String
    assert frame.get_column("time_start").to_list() == [
        "1970-01-01T00:00:00Z",
        "1970-01-01T00:01:00Z",
        "1970-01-01T00:02:00Z",
    ]
    filtered = _filter_polars_time(
        frame,
        period("1970-01-01T00:00:59Z", "1970-01-01T00:02:01Z"),
        column="time_start",
    )
    assert filtered.height == 2


def test_public_candidate_vocabulary_is_stable() -> None:
    assert {
        BBN_ESW_CANDIDATE,
        FPE_LOW_RIDGE_CANDIDATE,
        PLASMA_LINE_RIDGE_CANDIDATE,
        RADIO_AKR_CANDIDATE,
        INSTRUMENT_RFI_CANDIDATE,
        TRACKED_LOW_FPE_RIDGE_CANDIDATE,
        TRACKED_HIGH_PLASMA_RIDGE_CANDIDATE,
    } == {
        "bbn_esw_candidate",
        "fpe_low_ridge_candidate",
        "plasma_line_ridge_candidate",
        "radio_akr_candidate",
        "instrument_rfi_candidate",
        "tracked_low_fpe_ridge_candidate",
        "tracked_high_plasma_ridge_candidate",
    }


def test_detector_emits_traceable_raw_score_events(tmp_path) -> None:
    time = np.arange(360.0)
    frequency = np.geomspace(0.1, 1000.0, 64)
    spectrum = np.zeros((time.size, frequency.size), dtype=float)
    bbn = frequency < 10.0
    spectrum[60:180, bbn] += 4.0
    config = WaveDetectorConfig(
        window=WindowConfig(
            duration_seconds=120.0,
            step_seconds=60.0,
            minimum_points=8,
            minimum_frequency_bins=8,
            frequency_minimum_khz=0.1,
            frequency_maximum_khz=1000.0,
            frequency_bins=64,
        ),
        bbn_minimum_p90_z=1.0,
        bbn_broad_threshold_z=1.0,
        bbn_minimum_broad_fraction=0.5,
    )
    result = detect_wave_candidates(
        time,
        frequency,
        spectrum,
        config=config,
        component="Ex",
        source_dataset="synthetic:bbn",
    )

    events = [
        interval
        for interval in result.intervals
        if interval.phenomenon == BBN_ESW_CANDIDATE
    ]
    assert events
    event = events[0]
    assert event.score >= config.bbn_minimum_p90_z
    assert event.component == "Ex"
    assert event.source_dataset == "synthetic:bbn"
    assert event.detector_run_id == result.detector_run_id
    assert event.detector_config_id == result.detector_config_id
    assert event.feature_spec_id == result.feature_spec_id
    assert event.feature_spec_hash == result.feature_spec_hash

    event_frame = result.events_to_polars(mission="kaguya", instrument="lrs_wfc_h")
    assert event_frame.height >= 1
    assert {
        "event_id",
        "interval_id",
        "detector_run_id",
        "detector_config_id",
        "feature_spec_id",
        "source_dataset",
        "score",
    }.issubset(event_frame.columns)
    assert event_frame.get_column("detector_run_id").unique().to_list() == [
        result.detector_run_id
    ]

    from sopran.core.time import period

    catalog = Store(tmp_path / "store").event_catalog("wave_candidates", create=True)
    catalog.write_events(
        event_frame,
        time_coverage=period("1970-01-01", "1970-01-02"),
        overwrite=True,
    )
    assert catalog.scan().collect().get_column("event_id").to_list() == event_frame.get_column(
        "event_id"
    ).to_list()


def _feature_test_config(line_200: FixedLine) -> WaveDetectorConfig:
    return WaveDetectorConfig(
        window=WindowConfig(
            minimum_points=4,
            minimum_frequency_bins=8,
            frequency_bins=128,
        ),
        low_ridge_rule=PeakRule(
            "low",
            FrequencyBand("low", 2.0, 30.0),
            minimum_peak_z=1.5,
            minimum_quality=0.08,
            support_drop_z=0.75,
            maximum_log10_half_width=0.35,
        ),
        high_ridge_rule=PeakRule(
            "high",
            FrequencyBand("high", 10.0, 100.0),
            minimum_peak_z=2.5,
            minimum_quality=0.15,
            support_drop_z=1.0,
        ),
        radio_rule=PeakRule(
            "radio",
            FrequencyBand("radio", 100.0, 500.0),
            minimum_peak_z=3.0,
            minimum_quality=0.0,
            support_drop_z=1.0,
            mask_lines=(line_200,),
        ),
        line_rules=(
            LineDetectionRule(
                "line200",
                FrequencyBand("line200", 180.0, 220.0),
                FrequencyBand("side200", 150.0, 260.0),
                minimum_peak_z=3.0,
                minimum_prominence_z=2.0,
                veto_radio=True,
            ),
        ),
    )


def _windows(frequency: np.ndarray, normalized: np.ndarray) -> WindowedSpectra:
    n_rows = normalized.shape[0]
    starts = np.arange(n_rows, dtype=float) * 60.0
    return WindowedSpectra(
        time_start_seconds=starts,
        time_stop_seconds=starts + 120.0,
        time_mid_seconds=starts + 60.0,
        frequency_khz=frequency,
        raw_db=normalized.copy(),
        normalized_z=normalized,
        background_center_db=np.zeros(frequency.size),
        background_scale_db=np.ones(frequency.size),
        n_points=np.full(n_rows, 10, dtype=int),
        finite_fraction=np.ones(n_rows),
    )


def _nearest(values: np.ndarray, target: float) -> int:
    return int(np.argmin(np.abs(np.asarray(values, dtype=float) - target)))
