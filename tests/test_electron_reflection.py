from __future__ import annotations

import numpy as np
import pytest
from scipy.special import ndtr

from sopran.experimental.electron_reflection import (
    ElectronReflectionCounts,
    HalekasFitSettings,
    fit_halekas_distribution,
    mirror_boundary_sin2,
)


def test_mirror_boundary_uses_mirror_ratio_and_energy_correction() -> None:
    boundary = mirror_boundary_sin2(
        np.array([100.0, 400.0]),
        mirror_ratio=8.0,
        delta_u_eff_eV=100.0,
    )

    assert boundary.tolist() == pytest.approx([0.25, 0.15625])


def test_halekas_hard_fit_recovers_full_synthetic_distribution() -> None:
    counts = _simulate_halekas_distribution(sigma_ln_sin2=None)
    settings = HalekasFitSettings(
        mirror_ratio_bounds=(1.01, 5.0),
        delta_u_bounds_eV=(-200.0, 200.0),
        mirror_grid_points=72,
        delta_u_grid_points=81,
    )

    result = fit_halekas_distribution(counts, settings=settings)
    reversed_counts = ElectronReflectionCounts(
        energy_eV=counts.energy_eV[::-1],
        pitch_deg=counts.pitch_deg,
        affected_counts=counts.affected_counts[::-1],
        reference_counts=counts.reference_counts[::-1],
        b_sc_nT=counts.b_sc_nT,
    )
    reversed_result = fit_halekas_distribution(reversed_counts, settings=settings)

    assert result.success
    assert result.edge_transition == "hard"
    assert result.mirror_ratio == pytest.approx(1.35, rel=0.05)
    assert result.delta_u_eff_eV == pytest.approx(-60.0, abs=6.0)
    assert result.sigma_ln_sin2 is None
    assert result.root_mean_square_error < 0.01
    assert result.hard_to_smooth_delta_bic == pytest.approx(0.0)
    assert not result.at_bounds
    assert np.all(np.diff(reversed_result.energy_eV) > 0.0)
    assert reversed_result.mirror_ratio == result.mirror_ratio
    assert reversed_result.delta_u_eff_eV == result.delta_u_eff_eV


def test_halekas_probit_fit_recovers_gradual_edge_width() -> None:
    counts = _simulate_halekas_distribution(sigma_ln_sin2=0.22)
    hard_settings = HalekasFitSettings(
        mirror_ratio_bounds=(1.01, 5.0),
        delta_u_bounds_eV=(-200.0, 200.0),
        mirror_grid_points=72,
        delta_u_grid_points=81,
    )
    smooth_settings = HalekasFitSettings(
        edge_transition="probit",
        mirror_ratio_bounds=hard_settings.mirror_ratio_bounds,
        delta_u_bounds_eV=hard_settings.delta_u_bounds_eV,
        mirror_grid_points=hard_settings.mirror_grid_points,
        delta_u_grid_points=hard_settings.delta_u_grid_points,
    )

    hard = fit_halekas_distribution(counts, settings=hard_settings)
    smooth = fit_halekas_distribution(counts, settings=smooth_settings)

    assert smooth.success
    assert smooth.edge_transition == "probit"
    assert smooth.mirror_ratio == pytest.approx(1.35, rel=0.05)
    assert smooth.delta_u_eff_eV == pytest.approx(-60.0, abs=6.0)
    assert smooth.sigma_ln_sin2 == pytest.approx(0.22, rel=0.1)
    assert smooth.root_mean_square_error < hard.root_mean_square_error * 0.02
    assert smooth.hard_to_smooth_delta_bic > 6.0
    assert not smooth.at_bounds


def test_electron_reflection_counts_rejects_non_physical_inputs() -> None:
    with pytest.raises(ValueError, match="same shape"):
        ElectronReflectionCounts(
            energy_eV=np.array([100.0, 200.0]),
            pitch_deg=np.array([10.0, 20.0]),
            affected_counts=np.ones((2, 2)),
            reference_counts=np.ones((2, 3)),
            b_sc_nT=8.0,
        )

    with pytest.raises(ValueError, match="non-negative"):
        ElectronReflectionCounts(
            energy_eV=np.array([100.0]),
            pitch_deg=np.array([10.0]),
            affected_counts=np.array([[-1.0]]),
            reference_counts=np.array([[1.0]]),
            b_sc_nT=8.0,
        )


def test_halekas_excludes_empty_cells_instead_of_reading_ratio_one() -> None:
    counts = _simulate_halekas_distribution(sigma_ln_sin2=None)
    affected = counts.affected_counts.copy()
    reference = counts.reference_counts.copy()
    # Empty high-energy, low-pitch cells sit inside the loss cone.
    affected[-4:, :3] = 0.0
    reference[-4:, :3] = 0.0
    sparse = ElectronReflectionCounts(
        energy_eV=counts.energy_eV,
        pitch_deg=counts.pitch_deg,
        affected_counts=affected,
        reference_counts=reference,
        b_sc_nT=counts.b_sc_nT,
    )
    settings = HalekasFitSettings(
        mirror_ratio_bounds=(1.01, 5.0),
        delta_u_bounds_eV=(-200.0, 200.0),
        mirror_grid_points=72,
        delta_u_grid_points=81,
    )
    result = fit_halekas_distribution(sparse, settings=settings)
    assert result.n_cells == counts.affected_counts.size - 12
    assert result.mirror_ratio == pytest.approx(1.35, rel=0.05)
    assert result.root_mean_square_error < 0.01


def _simulate_halekas_distribution(
    *,
    sigma_ln_sin2: float | None,
) -> ElectronReflectionCounts:
    energy = np.geomspace(40.0, 1_500.0, 20)
    pitch = np.linspace(3.0, 87.0, 20)
    boundary = mirror_boundary_sin2(
        energy,
        mirror_ratio=1.35,
        delta_u_eff_eV=-60.0,
    )
    sin2_pitch = np.sin(np.deg2rad(pitch)) ** 2
    if sigma_ln_sin2 is None:
        outside = np.asarray(sin2_pitch[None, :] >= boundary[:, None], dtype=float)
    else:
        log_boundary = np.full(boundary.shape, -np.inf, dtype=float)
        positive = boundary > 0.0
        log_boundary[positive] = np.log(boundary[positive])
        outside = ndtr((np.log(sin2_pitch)[None, :] - log_boundary[:, None]) / sigma_ln_sin2)
    ratio = 0.1 + 0.9 * outside
    reference = np.full(ratio.shape, 10_000.0)
    affected = np.rint(reference * ratio)
    return ElectronReflectionCounts(
        energy_eV=energy,
        pitch_deg=pitch,
        affected_counts=affected,
        reference_counts=reference,
        b_sc_nT=6.0,
    )
