"""Model identities and synthetic recovery of the robust mirror-transmission estimator."""

from __future__ import annotations

import math

import numpy as np
import pytest

from sopran.experimental.electron_reflection import ElectronReflectionCounts
from sopran.experimental.electron_reflection import mirror_transmission as mt

pytest.importorskip("scipy")


def test_probability_is_one_half_at_the_boundary_and_monotonic() -> None:
    energy = np.array([120.0, 480.0])
    p0, p1, sigma = 0.30, 24.0, 0.2
    boundary_alpha = np.rad2deg(np.arcsin(np.sqrt(p0 + p1 / energy)))
    probability = mt.transmission_probability(boundary_alpha, energy, p0, p1, sigma)
    assert probability.shape == (2, 2)
    np.testing.assert_allclose(np.diag(probability), 0.5, atol=1e-12)
    order = np.argsort(boundary_alpha)
    assert np.all(np.diff(probability[0, order]) > 0.0)


def test_boundary_matches_the_electrostatic_limit() -> None:
    energy = np.array([120.0, 240.0, 600.0])
    p0, delta_u = 0.24, 45.0
    np.testing.assert_allclose(
        mt.boundary_sin2(energy, p0, delta_u), p0 + p0 * delta_u / energy, atol=1e-12
    )
    np.testing.assert_allclose(mt.width_ln(energy, 0.2), 0.2)
    assert np.isnan(mt.boundary_sin2([10.0], p0, delta_u, spacecraft_potential_eV=20.0)).all()


def _synthetic(
    p0: float, delta_u: float, sigma: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    energy = np.array([100.0, 134.0, 180.0, 244.0, 363.0, 456.0, 603.0, 861.0])
    pitch = np.linspace(5.0, 85.0, 33)
    baseline = -1.35 + 0.08 * np.sin(np.linspace(0.0, np.pi, energy.size))
    amplitude = 1.25 + 0.12 * np.cos(np.linspace(0.0, np.pi, energy.size))
    log_ratio = mt.log_ratio_model(pitch, energy, p0, p0 * delta_u, sigma, baseline, amplitude)
    return energy, pitch, np.exp(log_ratio)


def test_fit_recovers_a_synthetic_boundary_with_outliers() -> None:
    p0, delta_u, sigma = 0.36, 55.0, 0.16
    energy, pitch, ratio = _synthetic(p0, delta_u, sigma)
    ratio[2, 6] *= 2.8
    ratio[5, 28] *= 0.35
    settings = mt.MirrorTransmissionSettings(
        min_profile_contrast=0.01, delta_u_bounds_eV=(-120.0, 160.0), sigma_ln_b_bounds=(0.04, 0.40)
    )
    fit = mt.fit_mirror_transmission(energy, pitch, ratio, 8.0, settings=settings)
    assert fit.success and fit.model_id == mt.MODEL_ID
    assert fit.n_energy_bins == energy.size and fit.n_points == energy.size * pitch.size
    assert fit.p0 is not None and math.isclose(fit.p0, p0, rel_tol=0.12)
    assert fit.b_eff_nT is not None and math.isclose(fit.b_eff_nT, 8.0 / p0, rel_tol=0.12)
    assert fit.delta_u_eff_eV is not None and math.isclose(
        fit.delta_u_eff_eV, delta_u, abs_tol=25.0
    )
    assert fit.sigma_ln_b is not None and math.isclose(fit.sigma_ln_b, sigma, abs_tol=0.07)
    assert fit.no_edge_rmse_log is not None and fit.rmse_log is not None
    assert fit.no_edge_rmse_log > 1.5 * fit.rmse_log
    assert fit.mirror_ratio == pytest.approx(1.0 / fit.p0)
    row = fit.to_row(prefix="rmt_")
    assert "rmt_energy_eV" not in row
    assert "rmt_energy_eV" in fit.to_row(prefix="rmt_", include_diagnostics=True)


def test_variant_suite_and_count_input() -> None:
    energy, pitch, ratio = _synthetic(0.31, 20.0, 0.14)
    variants = mt.fit_mirror_transmission_variants(
        energy,
        pitch,
        ratio,
        8.0,
        base_settings=mt.MirrorTransmissionSettings(
            min_profile_contrast=0.01, delta_u_bounds_eV=(-120.0, 160.0)
        ),
    )
    assert [variant.label for variant in variants] == [
        "mirror_only",
        "electrostatic",
        "smooth_low_energy",
        "smooth_width",
    ]
    assert variants[0].fit.delta_u_eff_eV == 0.0
    assert all(variant.fit.aic_log is not None for variant in variants if variant.fit.success)
    reference = np.full(ratio.shape, 1000.0)
    counts = ElectronReflectionCounts(
        energy_eV=energy,
        pitch_deg=pitch,
        affected_counts=np.rint(reference * ratio),
        reference_counts=reference,
        b_sc_nT=8.0,
    )
    e, p, r, b = mt.ratio_from_counts(counts)
    assert e.shape == energy.shape and p.shape == pitch.shape and b == 8.0
    np.testing.assert_allclose(r, np.rint(reference * ratio) / reference)


def test_failures_are_reported_without_raising() -> None:
    energy = np.array([100.0, 200.0])
    pitch = np.linspace(5.0, 85.0, 9)
    flat = mt.fit_mirror_transmission(energy, pitch, np.ones((2, 9)), 8.0)
    assert not flat.success and flat.fail_reason == "too_few_supported_energy_bins"
    bad = mt.fit_mirror_transmission(energy, pitch, np.ones((3, 9)), 8.0)
    assert bad.fail_reason.startswith("input_error")
    wrong_model = mt.fit_mirror_transmission(
        *_synthetic(0.3, 10.0, 0.15),
        8.0,
        settings=mt.MirrorTransmissionSettings(boundary_model="other", min_profile_contrast=0.01),
    )
    assert wrong_model.fail_reason == "invalid_boundary_model:other"
