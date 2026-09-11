from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import numpy as np
import pytest

from sopran.analysis.electron_reflection import halekas as h
from sopran.analysis.electron_reflection.model import ElectronReflectionCounts, FloatArray


def reference_search(
    data: h._PreparedDistribution,
    settings: h.HalekasFitSettings,
    ratios: FloatArray,
    delta_values: FloatArray,
) -> h._HardCandidate | None:
    """Original full-mask grid search, retained as an independent numerical oracle."""
    sin2_pitch = np.sin(np.deg2rad(data.pitch_deg)) ** 2
    inside_log_ratio = float(np.log(settings.backscatter_fraction))
    observed = data.observed_log_ratio
    best: h._HardCandidate | None = None
    corrected_energy = data.energy_eV - settings.spacecraft_potential_eV
    valid_per_energy = np.sum(data.valid, axis=1)
    for mirror_ratio in ratios:
        boundary = (1.0 + delta_values[:, None] / corrected_energy[None, :]) / mirror_ratio
        inside = sin2_pitch[None, None, :] < boundary[:, :, None]
        below = np.sum(inside & data.valid[None, :, :], axis=2)
        above = valid_per_energy[None, :] - below
        supported = (
            np.sum((below >= 1) & (above >= 1), axis=1) >= settings.min_boundary_energy_bins
        )
        if not np.any(supported):
            continue
        residual = observed[data.valid][None, :] - np.where(
            inside[:, data.valid], inside_log_ratio, 0.0
        )
        rss = np.sum(residual**2, axis=1)
        rss[~supported] = np.inf
        index = int(np.argmin(rss))
        if best is None or rss[index] < best.residual_sum_squares:
            best = h._HardCandidate(
                mirror_ratio=float(mirror_ratio),
                delta_u_eff_eV=float(delta_values[index]),
                residual_sum_squares=float(rss[index]),
            )
    return best


def synthetic_counts(
    seed: int = 0, n_energy: int = 20, n_pitch: int = 20, *, masked: bool = False
) -> ElectronReflectionCounts:
    rng = np.random.default_rng(seed)
    energy = np.geomspace(40.0, 1500.0, n_energy)
    pitch = np.linspace(3.0, 87.0, n_pitch)
    boundary = h.mirror_boundary_sin2(energy, 1.35, -60.0)
    ratio = np.where(np.sin(np.deg2rad(pitch))[None, :] ** 2 < boundary[:, None], 0.1, 1.0)
    exposure = rng.uniform(0.5, 2.0, ratio.shape)
    reference = rng.poisson(500.0, ratio.shape).astype(float)
    affected = rng.poisson(reference * ratio * exposure).astype(float)
    if masked:
        affected[rng.random(ratio.shape) < 0.2] = np.nan
        reference[rng.random(ratio.shape) < 0.1] = np.nan
        affected[0] = 0.0
        reference[1] = 0.0
    return ElectronReflectionCounts(
        energy_eV=energy,
        pitch_deg=pitch,
        affected_counts=affected,
        reference_counts=reference,
        affected_exposure=exposure,
        b_sc_nT=6.0,
    )


@pytest.mark.parametrize("seed", range(12))
def test_search_matches_full_mask_oracle(seed: int) -> None:
    settings = h.HalekasFitSettings(spacecraft_potential_eV=15.0)
    data = h._prepare_distribution(synthetic_counts(seed, masked=True), settings)
    rng = np.random.default_rng(seed)
    order = rng.permutation(data.n_pitch)
    data = replace(
        data,
        pitch_deg=data.pitch_deg[order],
        valid=data.valid[:, order],
        observed_log_ratio=data.observed_log_ratio[:, order],
    )
    ratios = rng.permutation(np.geomspace(0.001, 1000.0, 37))
    deltas = rng.permutation(np.linspace(-500.0, 1000.0, 41))
    assert h._search_hard_grid(data, settings, ratios, deltas) == reference_search(
        data, settings, ratios, deltas
    )


@pytest.mark.parametrize("masked", [False, True])
@pytest.mark.parametrize("transition", ["hard", "probit"])
def test_full_fit_matches_oracle_with_refinement(
    masked: bool, transition: h.HalekasEdgeTransition
) -> None:
    counts = synthetic_counts(82, masked=masked)
    settings = h.HalekasFitSettings(
        edge_transition=transition, mirror_grid_points=72, delta_u_grid_points=81
    )
    actual = h.fit_halekas_distribution(counts, settings=settings)
    with patch.object(h, "_search_hard_grid", reference_search):
        expected = h.fit_halekas_distribution(counts, settings=settings)
    assert actual.success == expected.success
    assert actual.reason == expected.reason
    assert actual.mirror_ratio == expected.mirror_ratio
    assert actual.delta_u_eff_eV == expected.delta_u_eff_eV
    assert actual.sigma_ln_sin2 == expected.sigma_ln_sin2
    assert actual.residual_sum_squares == expected.residual_sum_squares
    assert actual.gaussian_bic == expected.gaussian_bic
    np.testing.assert_array_equal(actual.fitted_log_ratio, expected.fitted_log_ratio)
    np.testing.assert_array_equal(actual.boundary_pitch_deg, expected.boundary_pitch_deg)


def test_no_supported_candidate() -> None:
    settings = h.HalekasFitSettings()
    data = h._prepare_distribution(synthetic_counts(), settings)
    ratios = np.array([1.0e-8, 1.0e-7, 1.0e-6])
    deltas = np.array([0.0, 10.0, 20.0])
    assert reference_search(data, settings, ratios, deltas) is None
    assert h._search_hard_grid(data, settings, ratios, deltas) is None


@pytest.mark.parametrize("n_delta", [1, 3])
def test_ties_and_exact_pitch_boundary(n_delta: int) -> None:
    settings = h.HalekasFitSettings()
    pitch = np.array([70.0, 30.0, 50.0, 30.0, 10.0])
    data = h._PreparedDistribution(
        energy_eV=np.array([100.0, 200.0, 300.0]),
        pitch_deg=pitch,
        observed_log_ratio=np.full((3, 5), np.log(0.1) / 2.0),
        valid=np.ones((3, 5), dtype=bool),
        total_counts=1000,
    )
    exact_ratio = 1.0 / np.sin(np.deg2rad(30.0)) ** 2
    ratios = np.array([exact_ratio, 2.0, 3.0, exact_ratio])
    deltas = np.zeros(n_delta)
    actual = h._search_hard_grid(data, settings, ratios, deltas)
    expected = reference_search(data, settings, ratios, deltas)
    assert actual == expected
    assert actual is not None
    assert actual.mirror_ratio == ratios[0]


def test_invalid_cells_do_not_affect_support_or_sse() -> None:
    settings = h.HalekasFitSettings()
    data = h._prepare_distribution(synthetic_counts(), settings)
    valid = np.zeros_like(data.valid)
    valid[:2] = True
    data = replace(data, valid=valid, observed_log_ratio=np.where(valid, 0.0, np.nan))
    ratios = np.array([1.1, 2.0, 5.0])
    deltas = np.array([-20.0, 0.0, 20.0])
    assert reference_search(data, settings, ratios, deltas) is None
    assert h._search_hard_grid(data, settings, ratios, deltas) is None


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf, 9.0e153])
def test_nonfinite_sse_matches_oracle(value: float) -> None:
    settings = h.HalekasFitSettings()
    data = h._PreparedDistribution(
        energy_eV=np.array([100.0, 200.0, 300.0]),
        pitch_deg=np.array([10.0, 70.0]),
        observed_log_ratio=np.full((3, 2), value),
        valid=np.ones((3, 2), dtype=bool),
        total_counts=1000,
    )
    ratios = np.array([2.0, 1.0, 3.0])
    deltas = np.array([-10000.0, 0.0, 10.0])
    with np.errstate(over="ignore", invalid="ignore"):
        actual = h._search_hard_grid(data, settings, ratios, deltas)
        expected = reference_search(data, settings, ratios, deltas)
    assert actual is not None and expected is not None
    assert actual.mirror_ratio == expected.mirror_ratio
    assert actual.delta_u_eff_eV == expected.delta_u_eff_eV
    np.testing.assert_equal(actual.residual_sum_squares, expected.residual_sum_squares)


def test_nonfinite_potential_candidates_match_oracle() -> None:
    settings = h.HalekasFitSettings()
    data = h._prepare_distribution(synthetic_counts(), settings)
    ratios = np.array([0.5, 1.0, 2.0])
    deltas = np.array([np.nan, np.inf, -np.inf, -50.0, 0.0])
    assert h._search_hard_grid(data, settings, ratios, deltas) == reference_search(
        data, settings, ratios, deltas
    )


@pytest.mark.parametrize("seed", range(6))
def test_roundoff_close_candidates_retain_original_winner(seed: int) -> None:
    settings = h.HalekasFitSettings(backscatter_fraction=0.2)
    data = h._prepare_distribution(synthetic_counts(seed, masked=True), settings)
    rng = np.random.default_rng(seed)
    observed = np.log(settings.backscatter_fraction) / 2.0 + rng.normal(
        scale=1.0e-14, size=data.valid.shape
    )
    data = replace(data, observed_log_ratio=np.where(data.valid, observed, np.nan))
    ratios = np.geomspace(0.1, 10.0, 17)[::-1]
    deltas = np.linspace(-400.0, 300.0, 19)[::-1]
    assert h._search_hard_grid(data, settings, ratios, deltas) == reference_search(
        data, settings, ratios, deltas
    )


def test_perfect_fit_preserves_tiny_residual() -> None:
    settings = h.HalekasFitSettings()
    data = h._prepare_distribution(synthetic_counts(), settings)
    ratios = np.array([1.35, 1.2, 1.5])
    deltas = np.array([-60.0, -40.0, 0.0])
    boundary = (1.0 + deltas[0] / data.energy_eV) / ratios[0]
    observed = h._synthetic_log_ratio(
        data.pitch_deg, boundary, settings.backscatter_fraction, sigma_ln_sin2=None
    )
    observed += 1.0e-14
    data = replace(data, observed_log_ratio=observed)
    actual = h._search_hard_grid(data, settings, ratios, deltas)
    assert actual == reference_search(data, settings, ratios, deltas)
    assert actual is not None
    assert 0.0 < actual.residual_sum_squares < 1.0e-24


@pytest.mark.parametrize("valid", [False, True])
def test_public_failure_reason_is_unchanged(valid: bool) -> None:
    counts = synthetic_counts()
    if not valid:
        counts = replace(counts, affected_counts=np.full((20, 20), np.nan))
    settings = h.HalekasFitSettings(mirror_ratio_bounds=(1.0e-8, 1.0e-6))
    actual = h.fit_halekas_distribution(counts, settings=settings)
    with patch.object(h, "_search_hard_grid", reference_search):
        expected = h.fit_halekas_distribution(counts, settings=settings)
    assert not actual.success
    assert actual.reason == expected.reason
    assert actual.residual_sum_squares == expected.residual_sum_squares
