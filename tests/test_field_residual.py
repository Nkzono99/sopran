from __future__ import annotations

import numpy as np
import pytest

from sopran.experimental.kaguya.field_residual import quiet_field_baseline, residual_decomposition


def test_residual_splits_parallel_and_perpendicular_parts() -> None:
    result = residual_decomposition([[3.0, 4.0, 0.0]], [[1.0, 1.0, 0.0]], [[1.0, 0.0, 0.0]])
    np.testing.assert_allclose(result.residual_nT, [[2.0, 3.0, 0.0]])
    assert result.parallel_nT[0] == pytest.approx(2.0)
    assert result.perpendicular_abs_nT[0] == pytest.approx(3.0)
    assert result.residual_abs_nT[0] == pytest.approx(np.sqrt(13.0))
    assert result.fractional_abs[0] == pytest.approx(np.sqrt(13.0) / np.sqrt(2.0))
    assert result.direction_source == "supplied_with_observed_fallback"
    frame = result.to_pandas()
    assert list(frame.columns)[:3] == ["residual_x_nT", "residual_y_nT", "residual_z_nT"]


def test_residual_falls_back_to_observed_direction_and_handles_zero_base() -> None:
    result = residual_decomposition([[0.0, 2.0, 0.0]], [[0.0, 0.0, 0.0]], [[0.0, 0.0, 0.0]])
    assert result.parallel_nT[0] == pytest.approx(2.0)
    assert result.perpendicular_abs_nT[0] == pytest.approx(0.0)
    assert np.isnan(result.fractional_abs[0])
    with pytest.raises(ValueError):
        residual_decomposition([[1.0, 0.0, 0.0]], [[1.0, 0.0]])


def test_quiet_baseline_uses_cell_medians_then_global_median() -> None:
    lon = np.array([0.0, 1.0, 2.0, 100.0, 100.0, 100.0, -170.0])
    lat = np.array([0.0, 0.0, 0.0, 10.0, 10.0, 10.0, 50.0])
    value = np.array([1.0, 3.0, 2.0, 10.0, 11.0, 12.0, 100.0])
    quiet = np.array([True, True, True, True, False, True, False])
    baseline = quiet_field_baseline(lon, lat, value, quiet, grid_deg=10.0, min_events=3)
    np.testing.assert_allclose(baseline.value[:3], 2.0)
    assert baseline.source[0] == "quiet_grid_median"
    assert baseline.cell_count[0] == 3
    assert baseline.source[3] == "global_quiet_median"
    assert baseline.value[3] == pytest.approx(np.median([1.0, 3.0, 2.0, 10.0, 12.0]))
    assert baseline.value[6] == pytest.approx(baseline.global_median)
    none_quiet = quiet_field_baseline(lon, lat, value, np.zeros(7, bool), fallback=np.full(7, 7.0))
    assert np.all(none_quiet.value == 7.0) and none_quiet.source[0] == "fallback"
    with pytest.raises(ValueError):
        quiet_field_baseline(lon, lat, value, quiet, grid_deg=7.0)
