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
)


def observation():
    pitch = np.linspace(0, 90, 9)
    centers = (pitch[:-1] + pitch[1:]) / 2
    flux = np.tile(100 + 3000 * np.exp(-0.5 * ((centers - 35) / 8) ** 2), (2, 1))
    return FiniteBinObservation([100, 200, 400], pitch, flux, np.zeros_like(flux), 5.0)


@pytest.mark.parametrize("sigma", [0.0, 0.5, 12.0, 90.0])
def test_conservative_kernel_and_native_projection(sigma):
    obs = observation()
    model = FiniteBinModel(obs, FiniteBinFitSettings(angular_transport="out", beam_enabled=False))
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
    a = FiniteBinModel(obs).evaluate(params)
    b = FiniteBinModel(obs, FiniteBinFitSettings(angular_transport="out")).evaluate(params)
    fraction = np.clip((obs.pitch_edges_deg[1:] - 30) / np.diff(obs.pitch_edges_deg), 0, 1)
    expected = np.tile(np.log10(0.8 * (0.1 + 0.9 * fraction)), (2, 1))
    np.testing.assert_allclose(a.fitted_log_ratio_dex, expected, atol=1e-13)
    np.testing.assert_array_equal(a.fitted_log_ratio_dex, b.fitted_log_ratio_dex)
    # The option is authoritative even when nonzero sigma is passed to evaluation.
    c = FiniteBinModel(obs).evaluate(replace(params, sigma_deg=20))
    np.testing.assert_array_equal(a.fitted_log_ratio_dex, c.fitted_log_ratio_dex)


def test_missing_incident_flux_is_interpolated_but_excluded_and_rows_do_not_mix():
    obs = observation()
    flux = obs.incident_flux.copy()
    flux[0, 0] = np.nan
    changed = replace(obs, incident_flux=flux)
    params = FiniteBinParameters(2, 0.1, -80, sigma_deg=20)
    settings = FiniteBinFitSettings(angular_transport="out")
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
    settings = FiniteBinFitSettings(
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
    obs = FiniteBinObservation.from_counts(
        replace(counts, affected_counts=sparse),
        energy_edges_eV=[100, 200, 400],
        pitch_edges_deg=edges,
    )
    assert not obs.fit_valid[0].any()
    assert obs.fit_valid[1].all()
    # Low counts still carry incident flux, but they do not enter the objective.
    assert np.isfinite(obs.incident_flux).all()


def test_obvious_field_degeneracies_and_mission_adapter():
    import sopran as spn
    from sopran.experimental.kaguya.er import KaguyaErInstrument

    obs = observation()
    mask = obs.fit_valid.copy()
    mask[:, :2] = False
    result = FiniteBinModel(replace(obs, fit_valid=mask)).evaluate(FiniteBinParameters(100, 0.1, 0))
    assert "barrier_unobserved" in result.field_flags
    settings = FiniteBinFitSettings(
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
        model = FiniteBinModel(obs, FiniteBinFitSettings(angular_transport="out"))
        for golden in event["evaluations"]:
            result = model.evaluate(FiniteBinParameters(*golden["parameters"]))
            assert result.beam_template == golden["beam_template"]
            assert result.objective_sum == pytest.approx(golden["objective_sum"], abs=1e-9)
            np.testing.assert_allclose(
                result.fitted_log_ratio_dex[result.fit_valid],
                golden["prediction"],
                atol=1e-9,
                rtol=1e-9,
            )


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
