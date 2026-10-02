from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from scipy.special import ndtr

from sopran.experimental.electron_reflection import (
    ElectronReflectionCounts,
    HalekasFitSettings,
    fit_halekas_distribution,
    mirror_boundary_sin2,
)
from sopran.experimental.electron_reflection.halekas import (
    _boundary_supported,
    _fit_hard_distribution,
    _parameters_at_bounds,
    _prepare_distribution,
)


def test_ratio_bounds_allow_positive_domains() -> None:
    assert HalekasFitSettings().mirror_ratio_bounds == (0.001, 1000.0)
    for bounds in ((0.00001, 0.9), (0.1, 1.0), (1.0, 2.0), (1.001, 1000.0)):
        assert HalekasFitSettings(mirror_ratio_bounds=bounds).mirror_ratio_bounds == bounds
    for bounds in ((0.0, 1.0), (-0.1, 1.0), (1.0, 1.0), (2.0, 1.0), (np.nan, 1.0), (0.1, np.inf)):
        with pytest.raises(ValueError, match="mirror_ratio_bounds"):
            HalekasFitSettings(mirror_ratio_bounds=bounds)


def _counts(ratio: float, sigma: float | None) -> ElectronReflectionCounts:
    energy = np.geomspace(40.0, 1500.0, 24)
    pitch = np.linspace(2.0, 88.0, 32)
    boundary = mirror_boundary_sin2(energy, ratio, -100.0)
    sin2 = np.sin(np.deg2rad(pitch)) ** 2
    outside = (sin2[None, :] >= boundary[:, None]).astype(float)
    if sigma is not None:
        log_boundary = np.full(boundary.shape, -np.inf)
        positive = boundary > 0
        log_boundary[positive] = np.log(boundary[positive])
        outside = ndtr((np.log(sin2)[None, :] - log_boundary[:, None]) / sigma)
    reference = np.full(outside.shape, 100_000.0)
    return ElectronReflectionCounts(
        energy_eV=energy,
        pitch_deg=pitch,
        affected_counts=np.rint(reference * (0.1 + 0.9 * outside)),
        reference_counts=reference,
        b_sc_nT=7.0,
    )


@pytest.mark.parametrize("ratio", [0.6, 0.85, 1.0, 1.35])
@pytest.mark.parametrize("sigma", [None, 0.2])
def test_halekas_recovers_ratios_across_unity(ratio: float, sigma: float | None) -> None:
    result = fit_halekas_distribution(
        _counts(ratio, sigma),
        settings=HalekasFitSettings(
            edge_transition="hard" if sigma is None else "probit",
            mirror_ratio_bounds=(0.1, 4.0),
            delta_u_bounds_eV=(-200.0, 100.0),
            mirror_grid_points=96,
            delta_u_grid_points=121,
        ),
    )
    assert result.success
    assert result.mirror_ratio == pytest.approx(ratio, rel=0.035)
    assert result.delta_u_eff_eV == pytest.approx(-100.0, abs=4.0)
    assert result.effective_field_nT == pytest.approx(7 * result.mirror_ratio)
    assert result.root_mean_square_error < 0.15
    if sigma is not None:
        assert result.sigma_ln_sin2 == pytest.approx(sigma, rel=0.08)


def test_halekas_batched_search_matches_scalar_grid_with_missing_cells() -> None:
    counts = _counts(0.85, None)
    affected = np.array(counts.affected_counts, copy=True)
    affected[::2, ::4] = np.nan
    counts = replace(counts, affected_counts=affected)
    settings = HalekasFitSettings(
        mirror_ratio_bounds=(0.4, 2.0),
        delta_u_bounds_eV=(-200.0, 100.0),
        spacecraft_potential_eV=10.0,
        mirror_grid_points=17,
        delta_u_grid_points=19,
        hard_refinement_steps=0,
    )
    data = _prepare_distribution(counts, settings)
    best = np.inf
    best_parameters = None
    sin2 = np.sin(np.deg2rad(data.pitch_deg)) ** 2
    for ratio in np.geomspace(*settings.mirror_ratio_bounds, settings.mirror_grid_points):
        for delta in np.linspace(*settings.delta_u_bounds_eV, settings.delta_u_grid_points):
            edge = mirror_boundary_sin2(data.energy_eV, ratio, delta, spacecraft_potential_eV=10.0)
            if not _boundary_supported(edge, sin2, data.valid, settings):
                continue
            model = np.where(sin2[None, :] < edge[:, None], np.log(0.1), 0.0)
            rss = float(np.sum((data.observed_log_ratio[data.valid] - model[data.valid]) ** 2))
            if rss < best:
                best, best_parameters = rss, (ratio, delta)
    result = _fit_hard_distribution(data, settings)
    assert result is not None
    assert result.residual_sum_squares == pytest.approx(best, abs=1e-10)
    assert (result.mirror_ratio, result.delta_u_eff_eV) == pytest.approx(best_parameters)
    refined = _fit_hard_distribution(data, replace(settings, hard_refinement_steps=2))
    assert refined is not None
    assert refined.residual_sum_squares <= result.residual_sum_squares


def test_halekas_lower_bound_tolerance_is_not_set_by_large_upper_bound() -> None:
    settings = HalekasFitSettings(mirror_ratio_bounds=(0.001, 1_000_000.0))
    assert _parameters_at_bounds(0.0011, -100.0, None, settings) == ()
    assert _parameters_at_bounds(0.001, -100.0, None, settings) == ("mirror_ratio_lower",)
    assert _parameters_at_bounds(1_000_000.0, -100.0, None, settings) == ("mirror_ratio_upper",)
