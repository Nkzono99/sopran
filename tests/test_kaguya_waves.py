from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from sopran.analysis.waves import WaveDetectorConfig, feature_spec_hash
from sopran.missions.kaguya.waves import (
    KAGUYA_WFC_FIXED_LINES,
    KAGUYA_WFC_V1,
    build_kaguya_wfc_quality_mask,
    kaguya_wfc_fixed_lines,
)

DATA_DIR = Path(__file__).with_name("fixtures")


def test_kaguya_wfc_v1_is_a_versioned_generic_detector_preset() -> None:
    assert isinstance(KAGUYA_WFC_V1, WaveDetectorConfig)
    assert KAGUYA_WFC_V1.detector == "sopran.kaguya.lrs.wfc_h.wave_candidates"
    assert KAGUYA_WFC_V1.detector_version == "1"
    assert KAGUYA_WFC_V1.feature_spec_version == "kaguya-wfc-wave-features-v1"
    assert KAGUYA_WFC_V1.window.duration_seconds == pytest.approx(120.0)
    assert KAGUYA_WFC_V1.window.step_seconds == pytest.approx(60.0)
    assert (
        KAGUYA_WFC_V1.bbn_band.minimum_khz,
        KAGUYA_WFC_V1.bbn_band.maximum_khz,
    ) == pytest.approx((0.1, 10.0))
    assert (
        KAGUYA_WFC_V1.high_ridge_rule.band.minimum_khz,
        KAGUYA_WFC_V1.high_ridge_rule.band.maximum_khz,
    ) == pytest.approx((10.0, 100.0))
    assert len(feature_spec_hash(KAGUYA_WFC_V1)) == 64


def test_kaguya_fixed_lines_are_purpose_specific() -> None:
    assert [line.frequency_khz for line in KAGUYA_WFC_FIXED_LINES] == [
        30.0,
        200.0,
        957.0,
    ]
    assert [line.frequency_khz for line in kaguya_wfc_fixed_lines("ridge")] == [
        30.0
    ]
    assert [line.half_width_khz for line in kaguya_wfc_fixed_lines("ridge")] == [
        2.0
    ]
    assert kaguya_wfc_fixed_lines("tracker") == kaguya_wfc_fixed_lines("ridge")
    assert [line.half_width_khz for line in kaguya_wfc_fixed_lines("radio")] == [
        12.0
    ]
    assert [line.frequency_khz for line in kaguya_wfc_fixed_lines("high")] == [
        957.0
    ]
    assert kaguya_wfc_fixed_lines("low_fpe") == ()
    assert kaguya_wfc_fixed_lines("clustering") == KAGUYA_WFC_FIXED_LINES
    assert [line.half_width_khz for line in KAGUYA_WFC_FIXED_LINES] == [
        3.0,
        3.0,
        3.0,
    ]
    assert [line.frequency_khz for line in kaguya_wfc_fixed_lines("rfi_diagnostic")] == [
        200.0,
        957.0,
    ]
    with pytest.raises(ValueError, match="unknown KAGUYA WFC fixed-line purpose"):
        kaguya_wfc_fixed_lines("typo")


def test_kaguya_preset_masks_lines_without_losing_rfi_diagnostics() -> None:
    assert KAGUYA_WFC_V1.low_ridge_rule.mask_lines == ()
    assert [line.frequency_khz for line in KAGUYA_WFC_V1.high_ridge_rule.mask_lines] == [
        30.0
    ]
    assert KAGUYA_WFC_V1.high_ridge_rule.mask_lines[0].half_width_khz == pytest.approx(
        2.0
    )
    assert [line.frequency_khz for line in KAGUYA_WFC_V1.radio_rule.mask_lines] == [
        200.0
    ]
    assert [rule.name for rule in KAGUYA_WFC_V1.line_rules] == [
        "kaguya_wfc_200_khz_rfi",
        "kaguya_wfc_957_khz_rfi",
    ]
    assert KAGUYA_WFC_V1.line_rules[0].veto_radio is True
    assert KAGUYA_WFC_V1.line_rules[1].minimum_prominence_z == pytest.approx(1.5)


def test_quality_mask_makes_nan_and_pad_hard_invalid() -> None:
    spectrum = np.asarray(
        [
            [1.0, 2.0, 3.0],
            [np.nan, 2.0, 3.0],
            [65534.0, np.nan, np.inf],
            [1.0, 2.0, 3.0],
            [1.0, 2.0, 3.0],
        ]
    )
    quality = build_kaguya_wfc_quality_mask(
        spectrum,
        mode=np.asarray([2.0, 2.0, 2.0, 254.0, np.nan]),
    )

    np.testing.assert_array_equal(
        quality.sample_valid,
        [
            [True, True, True],
            [False, True, True],
            [False, False, False],
            [True, True, True],
            [True, True, True],
        ],
    )
    np.testing.assert_array_equal(
        quality.record_valid,
        [True, True, False, False, False],
    )
    np.testing.assert_array_equal(quality.valid_time, quality.record_valid)
    np.testing.assert_allclose(quality.finite_fraction, [1.0, 2.0 / 3.0, 0.0, 1.0, 1.0])


def test_quality_mask_keeps_finite_state_transitions_as_warnings() -> None:
    spectrum = np.ones((4, 3), dtype=float)
    quality = build_kaguya_wfc_quality_mask(
        spectrum,
        mode=[2, 2, 3, 3],
        gain=[20, 40, 40, 40],
        fband=[3, 3, 3, 3],
        postgap=[64, 64, 32, 32],
    )

    np.testing.assert_array_equal(quality.record_valid, [True, True, True, True])
    np.testing.assert_array_equal(quality.mode_warning, [False, False, True, False])
    np.testing.assert_array_equal(quality.gain_warning, [False, True, False, False])
    np.testing.assert_array_equal(quality.fband_warning, [False, False, False, False])
    np.testing.assert_array_equal(quality.postgap_warning, [False, False, True, False])
    np.testing.assert_array_equal(quality.warning, [False, True, True, False])
    assert quality.to_metadata() == {
        "record_count": 4,
        "valid_record_count": 4,
        "invalid_record_count": 0,
        "warning_record_count": 2,
        "mode_transition_count": 1,
        "gain_transition_count": 1,
        "fband_transition_count": 0,
        "postgap_transition_count": 1,
    }
    assert set(quality.warning_flags) == {
        "mode_transition",
        "gain_transition",
        "fband_transition",
        "postgap_transition",
    }


def test_quality_mask_rejects_ambiguous_shapes() -> None:
    with pytest.raises(ValueError, match="two-dimensional"):
        build_kaguya_wfc_quality_mask(np.ones(4))
    with pytest.raises(ValueError, match=r"gain must have shape \(3,\)"):
        build_kaguya_wfc_quality_mask(np.ones((3, 2)), gain=[20, 20])


def test_gold_manifest_has_ordered_utc_strict_and_review_intervals() -> None:
    manifest = json.loads(
        (DATA_DIR / "kaguya_wfc_wave_gold.json").read_text(encoding="utf-8")
    )
    assert manifest["schema"] == "sopran.kaguya.wfc-wave-gold/v1"
    assert manifest["preset"] == "KAGUYA_WFC_V1"
    assert manifest["interval_semantics"] == "half_open_[start,stop)"
    assert manifest["strict_intervals"]
    assert manifest["review_intervals"]

    for tier in ("strict_intervals", "review_intervals"):
        ids = [row["id"] for row in manifest[tier]]
        assert len(ids) == len(set(ids))
        for row in manifest[tier]:
            start = _utc(row["start"])
            stop = _utc(row["stop"])
            assert start.tzinfo is UTC
            assert stop.tzinfo is UTC
            assert start < stop

    strict = manifest["strict_intervals"][0]
    assert strict["start"] == "2008-01-10T00:17:08Z"
    assert strict["stop"] == "2008-01-10T00:18:36Z"
    assert "esw_confirmed_without_wfc_l_waveform" in strict["must_not_claim"]

    strict_by_id = {row["id"]: row for row in manifest["strict_intervals"]}
    assert strict_by_id["wfc-ey-20080614-quiet-negative"][
        "expected_candidate_types"
    ] == []
    assert strict_by_id["wfc-ey-20080618-957-khz-rfi"][
        "expected_fixed_line_khz"
    ] == pytest.approx(957.03)
    assert strict_by_id["wfc-ey-20080618-957-khz-rfi"][
        "expected_candidate_types"
    ] == []
    review_ids = {row["id"] for row in manifest["review_intervals"]}
    assert "wfc-ey-20080110-200-khz-legacy-label-review" in review_ids


def test_wave_documentation_records_exposure_and_wfc_product_boundaries() -> None:
    text = (
        Path(__file__).parents[1] / "docs" / "missions" / "kaguya" / "wfc-waves.md"
    ).read_text(encoding="utf-8")
    assert "exposure_seconds" in text
    assert "二重計上" in text
    assert "WFC-H" in text
    assert "WFC-L" in text
    assert "ESW confirmed" in text


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
