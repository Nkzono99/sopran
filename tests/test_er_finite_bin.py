"""Transport invariants, flux response and search, independent of mission I/O."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from sopran.experimental.electron_reflection import (
    ElectronReflectionCounts,
    FiniteBinFitSettings,
    FiniteBinModel,
    FiniteBinObservation,
    FiniteBinParameters,
    fit_finite_bin_distribution,
    profile_mirror_ratio,
)


def huber(**kwargs):
    """Flux-only observations need a log-ratio loss; the default is beta-binomial."""
    return FiniteBinFitSettings(loss="huber", **kwargs)


def observation():
    pitch = np.linspace(0, 90, 9)
    centers = (pitch[:-1] + pitch[1:]) / 2
    flux = np.tile(100 + 3000 * np.exp(-0.5 * ((centers - 35) / 8) ** 2), (2, 1))
    return FiniteBinObservation([100, 200, 400], pitch, flux, np.zeros_like(flux), 5.0)


@pytest.mark.parametrize("sigma", [0.0, 0.5, 12.0, 90.0])
def test_conservative_kernel_and_native_projection(sigma):
    obs = observation()
    model = FiniteBinModel(obs, huber(angular_transport="out", beam_enabled=False))
    kernel = model.kernel(sigma)
    assert np.min(kernel) >= 0
    np.testing.assert_allclose(kernel.sum(axis=0), 1, atol=2e-12)
    np.testing.assert_allclose(kernel @ model.weights, model.weights, atol=2e-12)
    if sigma == 0:
        np.testing.assert_array_equal(kernel, np.eye(len(model.weights)))
    # rho=1 removes the barrier: this independently checks native D + bin response.
    fine_flux = np.repeat(obs.incident_flux, 8, axis=1)
    outgoing = (fine_flux * model.weights) @ kernel.T / model.weights
    expected = np.log10(outgoing.reshape(2, 8, 8).mean(axis=2) / obs.incident_flux)
    result = model.evaluate(FiniteBinParameters(4, 1, 0, sigma_deg=sigma))
    np.testing.assert_allclose(result.fitted_log_ratio_dex, expected, atol=2e-12)
    assert result.field_unconstrained


def test_zero_transport_matches_analytic_finite_bin_and_default():
    obs = observation()
    params = FiniteBinParameters(4, 0.1, 0, 0.8)
    a = FiniteBinModel(obs, huber()).evaluate(params)
    b = FiniteBinModel(obs, huber(angular_transport="out")).evaluate(params)
    fraction = np.clip((obs.pitch_edges_deg[1:] - 30) / np.diff(obs.pitch_edges_deg), 0, 1)
    expected = np.tile(np.log10(0.8 * (0.1 + 0.9 * fraction)), (2, 1))
    np.testing.assert_allclose(a.fitted_log_ratio_dex, expected, atol=1e-13)
    np.testing.assert_array_equal(a.fitted_log_ratio_dex, b.fitted_log_ratio_dex)
    # The option is authoritative even when nonzero sigma is passed to evaluation.
    c = FiniteBinModel(obs, huber()).evaluate(replace(params, sigma_deg=20))
    np.testing.assert_array_equal(a.fitted_log_ratio_dex, c.fitted_log_ratio_dex)


def test_missing_incident_flux_is_interpolated_but_excluded_and_rows_do_not_mix():
    obs = observation()
    flux = obs.incident_flux.copy()
    flux[0, 0] = np.nan
    changed = replace(obs, incident_flux=flux)
    params = FiniteBinParameters(2, 0.1, -80, sigma_deg=20)
    settings = huber(angular_transport="out")
    result = FiniteBinModel(changed, settings).evaluate(params)
    assert result.interpolated_incident_bins == 1
    assert not result.fit_valid[0, 0]
    assert np.isfinite(result.fitted_log_ratio_dex).all()
    baseline = FiniteBinModel(obs, settings).evaluate(params)
    np.testing.assert_array_equal(baseline.fitted_log_ratio_dex[1], result.fitted_log_ratio_dex[1])


@pytest.mark.parametrize("loss", ["huber", "squared"])
def test_objective_is_distinct_from_reported_rmse(loss):
    obs = observation()
    values = np.zeros_like(obs.observed_log_ratio_dex)
    values[0, 0] = -3
    result = FiniteBinModel(
        replace(obs, observed_log_ratio_dex=values), FiniteBinFitSettings(loss=loss)
    ).evaluate(FiniteBinParameters(4, 0.1, 0))
    residual = result.fitted_log_ratio_dex - values
    costs = (
        residual**2
        if loss == "squared"
        else np.where(abs(residual) <= 0.1, residual**2, 0.2 * abs(residual) - 0.01)
    )
    assert result.objective_sum == pytest.approx(costs.sum())
    assert result.objective_mean == pytest.approx(costs.mean())
    assert result.root_mean_square_error_dex == pytest.approx(np.sqrt(np.mean(residual**2)))


def test_fixed_field_refits_potential_and_no_transport_parameter():
    obs = observation()
    settings = huber(
        angular_transport="out",
        beam_enabled=False,
        mirror_ratio_bounds=(2, 2),
        bottom_ratio_bounds=(0.1, 0.1),
        scale_bounds=(1, 1),
        sigma_bounds_deg=(10, 10),
        generations=30,
        seeds=1,
        pitch_subdivisions=4,
    )
    truth = FiniteBinParameters(2, 0.1, -80, sigma_deg=10)
    prediction = FiniteBinModel(obs, settings).evaluate(truth).fitted_log_ratio_dex
    fit_obs = replace(obs, observed_log_ratio_dex=prediction)
    result = fit_finite_bin_distribution(
        fit_obs, settings=settings, starts=[replace(truth, delta_u_eV=100)]
    )
    assert result.parameters.delta_u_eV == pytest.approx(-80, abs=0.01)
    assert result.effective_field_nT == 10
    assert result.local_converged
    assert result.objective_sum < 1e-10
    assert result.settings == settings
    assert "mirror_ratio" not in result.at_bounds


def test_count_preparation_respects_exposure_and_input_cuts():
    edges = np.linspace(0, 90, 5)
    counts = ElectronReflectionCounts(
        [150, 300],
        (edges[:-1] + edges[1:]) / 2,
        np.full((2, 4), 20.0),
        np.full((2, 4), 10.0),
        5.0,
        affected_exposure=2.0,
        reference_exposure=1.0,
    )
    obs = FiniteBinObservation.from_counts(
        counts, energy_edges_eV=[100, 200, 400], pitch_edges_deg=edges
    )
    np.testing.assert_allclose(obs.observed_log_ratio_dex, np.log10(20.5 / 10.5 / 2))
    assert obs.fit_valid.all()
    sparse = counts.affected_counts.copy()
    sparse[0, :2] = 1
    paired = FiniteBinObservation.from_counts(
        replace(counts, affected_counts=sparse),
        energy_edges_eV=[100, 200, 400],
        pitch_edges_deg=edges,
        selection="paired",
        min_counts=5,
    )
    assert not paired.fit_valid[0].any()
    assert paired.fit_valid[1].all()
    # Low counts still carry incident flux, but they do not enter the objective.
    assert np.isfinite(paired.incident_flux).all()
    # The default total-count selection keeps low affected counts for the likelihood.
    sparse[0, 0] = 0
    total = FiniteBinObservation.from_counts(
        replace(counts, affected_counts=sparse),
        energy_edges_eV=[100, 200, 400],
        pitch_edges_deg=edges,
    )
    assert total.fit_valid.all()
    np.testing.assert_array_equal(total.affected_counts, sparse)
    np.testing.assert_allclose(total.exposure_ratio, 2.0)


def test_obvious_field_degeneracies_and_mission_adapter():
    import sopran as spn
    from sopran.experimental.kaguya.er import KaguyaErInstrument

    obs = observation()
    mask = obs.fit_valid.copy()
    mask[:, :2] = False
    result = FiniteBinModel(replace(obs, fit_valid=mask), huber()).evaluate(
        FiniteBinParameters(100, 0.1, 0)
    )
    assert "barrier_unobserved" in result.field_flags
    settings = huber(
        mirror_ratio_bounds=(4, 4),
        bottom_ratio_bounds=(0.1, 0.1),
        delta_u_bounds_eV=(0, 0),
        scale_bounds=(1, 1),
    )
    er = KaguyaErInstrument(spn.Kaguya(download="never"))
    result = er.effective_field.fit_finite_bin(obs, settings=settings)
    assert result.local_converged
    assert result.parameters.sigma_deg == 0
    assert not hasattr(spn, "FiniteBinModel")


def test_frozen_synthetic_events_match_pilot_predictions_and_beam_selection():
    fixture = json.loads((Path(__file__).parent / "fixtures/er_finite_bin_golden.json").read_text())
    for event in fixture["events"]:
        obs = FiniteBinObservation(
            event["energy_edges_eV"],
            event["pitch_edges_deg"],
            np.asarray(event["incident_flux"], float),
            event["observed_log_ratio_dex"],
            event["b_sc_nT"],
            event["fit_valid"],
        )
        model = FiniteBinModel(obs, huber(angular_transport="out"))
        for golden in event["evaluations"]:
            parameters = FiniteBinParameters(*golden["parameters"])
            # Pilot templates: 1 + 8*energy width + 4*pitch width + amplitude index.
            old = golden["beam_template"]
            shape = 0 if old == 0 else 1 + 2 * ((old - 1) // 8) + ((old - 1) // 4) % 2
            amplitude = 1.0 if old == 0 else [0.5, 1.0, 2.0, 4.0][(old - 1) % 4]
            pinned = FiniteBinModel(
                obs,
                huber(angular_transport="out", beam_amplitude_bounds=(amplitude, amplitude)),
            ).evaluate(parameters)
            assert pinned.beam_template == shape
            assert pinned.objective_sum == pytest.approx(golden["objective_sum"], abs=1e-9)
            np.testing.assert_allclose(
                pinned.fitted_log_ratio_dex[pinned.fit_valid],
                golden["prediction"],
                atol=1e-9,
                rtol=1e-9,
            )
            # A continuous amplitude can only lower the objective of the pilot grid.
            result = model.evaluate(parameters)
            assert result.objective_sum <= golden["objective_sum"] + 1e-9
            if old:
                assert result.beam_template == shape
                assert 0.25 <= result.beam_amplitude <= 8


@pytest.mark.parametrize(
    "kwargs",
    [
        {"angular_transport": "both"},
        {"loss": "invalid"},
        {"mirror_ratio_bounds": (-1, 1)},
        {"bottom_ratio_bounds": (0.1, 2)},
        {"pitch_subdivisions": 0},
        {"seeds": 0},
        {"delta_u_bounds_eV": (float("nan"), 1000)},
    ],
)
def test_invalid_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        FiniteBinFitSettings(**kwargs)


def synthetic_counts(level, *, seed=3, truth=None, ratio=None, b_sc=5.0):
    """Poisson paired counts on a KAGUYA-like 20-1500 eV, 8-pitch grid."""
    energy_edges = np.geomspace(20, 1500, 13)
    pitch_edges = np.linspace(0, 90, 9)
    energy = np.sqrt(energy_edges[:-1] * energy_edges[1:])
    pitch = (pitch_edges[:-1] + pitch_edges[1:]) / 2
    shape = (energy.size, pitch.size)
    if ratio is None:
        dummy = FiniteBinObservation(
            energy_edges, pitch_edges, np.ones(shape), np.zeros(shape), b_sc
        )
        model = FiniteBinModel(dummy, huber(beam_enabled=False))
        ratio = 10 ** model.evaluate(truth).fitted_log_ratio_dex
    rng = np.random.default_rng(seed)
    expected = np.repeat((level * (energy / 100) ** -1.0)[:, None], pitch.size, axis=1)
    reference = rng.poisson(expected).astype(float)
    affected = rng.poisson(expected * ratio).astype(float)
    counts = ElectronReflectionCounts(energy, pitch, affected, reference, b_sc)
    return counts, energy_edges, pitch_edges


TRUTH = FiniteBinParameters(4.0, 0.15, -40.0, 0.9)
FAST = dict(beam_enabled=False, generations=60, seeds=1)


def test_count_deviances_match_scipy_binomial_and_beta_binomial():
    from scipy.stats import betabinom, binom  # type: ignore[import-untyped]

    counts, energy_edges, pitch_edges = synthetic_counts(20.0, truth=TRUTH)
    counts = replace(counts, affected_exposure=1.5)
    obs = FiniteBinObservation.from_counts(
        counts, energy_edges_eV=energy_edges, pitch_edges_deg=pitch_edges
    )
    a = obs.affected_counts[obs.fit_valid]
    n = a + obs.reference_counts[obs.fit_valid]
    saturated = binom.logpmf(a, n, a / n)
    for loss, concentration in (("binomial", 100.0), ("beta_binomial", 30.0)):
        params = replace(TRUTH, concentration=concentration)
        result = FiniteBinModel(obs, FiniteBinFitSettings(loss=loss, beam_enabled=False)).evaluate(
            params
        )
        odds = 1.5 * 10 ** result.fitted_log_ratio_dex[obs.fit_valid]
        q = odds / (1 + odds)
        if loss == "binomial":
            likelihood = binom.logpmf(a, n, q)
        else:
            likelihood = betabinom.logpmf(a, n, concentration * q, concentration * (1 - q))
        expected = 2 * np.sum(saturated - likelihood)
        assert result.objective_sum == pytest.approx(expected, rel=1e-9, abs=1e-8)


def test_count_likelihood_recovers_field_with_zero_affected_counts():
    counts, energy_edges, pitch_edges = synthetic_counts(8.0, truth=TRUTH)
    obs = FiniteBinObservation.from_counts(
        counts, energy_edges_eV=energy_edges, pitch_edges_deg=pitch_edges
    )
    assert np.any(obs.affected_counts[obs.fit_valid] == 0)
    result = fit_finite_bin_distribution(obs, settings=FiniteBinFitSettings(**FAST))
    assert abs(np.log10(result.parameters.mirror_ratio / TRUTH.mirror_ratio)) < 0.15
    assert result.boundary_rows >= 3
    assert result.loss_cone_delta_bic is not None and result.loss_cone_delta_bic > 0
    assert not result.field_unconstrained
    profile = profile_mirror_ratio(obs, result, points=13)
    assert not profile.improved_minimum
    assert profile.interval_bounded
    low, high = profile.interval_nT
    assert low <= TRUTH.mirror_ratio * counts.b_sc_nT <= high
    np.testing.assert_allclose(profile.effective_field_nT, profile.mirror_ratio * 5.0)
    assert profile.minimum_fit.objective_sum <= result.objective_sum
    # Interpolated ends lie strictly between grid points around the interval.
    assert low > profile.effective_field_nT[0] and high < profile.effective_field_nT[-1]


def test_energy_step_without_pitch_structure_is_flagged():
    energy = np.sqrt(np.geomspace(20, 1500, 13)[:-1] * np.geomspace(20, 1500, 13)[1:])
    step = np.repeat(np.where(energy < 80, 1.0, 0.3)[:, None], 8, axis=1)
    counts, energy_edges, pitch_edges = synthetic_counts(200.0, ratio=step)
    obs = FiniteBinObservation.from_counts(
        counts, energy_edges_eV=energy_edges, pitch_edges_deg=pitch_edges
    )
    result = fit_finite_bin_distribution(obs, settings=FiniteBinFitSettings(**FAST))
    assert result.field_unconstrained
    assert "loss_cone_unsupported" in result.field_flags


def test_model_offset_and_scale_prior_constrain_the_outside_level():
    efficiency = np.log10(0.8)
    counts, energy_edges, pitch_edges = synthetic_counts(500.0, truth=TRUTH)
    counts = replace(counts, affected_counts=np.rint(counts.affected_counts * 0.8))
    obs = FiniteBinObservation.from_counts(
        counts, energy_edges_eV=energy_edges, pitch_edges_deg=pitch_edges
    )
    fixed = dict(
        mirror_ratio_bounds=(4, 4), bottom_ratio_bounds=(0.15, 0.15), delta_u_bounds_eV=(-40, -40)
    )
    settings = FiniteBinFitSettings(**FAST, **fixed)
    raw = fit_finite_bin_distribution(obs, settings=settings)
    calibrated = fit_finite_bin_distribution(
        replace(obs, model_offset_dex=efficiency), settings=settings
    )
    assert raw.parameters.scale == pytest.approx(0.72, rel=0.05)
    assert calibrated.parameters.scale == pytest.approx(0.9, rel=0.05)
    pinned = fit_finite_bin_distribution(
        obs, settings=replace(settings, scale_prior_sigma_dex=1e-4)
    )
    assert pinned.parameters.scale == pytest.approx(1.0, abs=0.01)


def test_count_losses_need_counts_and_count_only_prior():
    with pytest.raises(ValueError, match="flux-only"):
        FiniteBinModel(observation(), FiniteBinFitSettings())
    with pytest.raises(ValueError, match="scale_prior"):
        FiniteBinFitSettings(loss="huber", scale_prior_sigma_dex=0.1)
    with pytest.raises(ValueError):
        FiniteBinFitSettings(concentration_bounds=(0, 10))
