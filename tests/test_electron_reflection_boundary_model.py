from dataclasses import replace

import numpy as np
import pytest

from sopran.experimental.electron_reflection import global_joint as gj
from sopran.experimental.electron_reflection.model import EffectiveFieldFitSettings


def synthetic_case(mode="fixed", ratio=0.8, beam=False, pitch_bins=16, level=1000.0):
    settings = gj.GlobalJointFitSettings(
        loss_cone_model=mode,
        effective_field=EffectiveFieldFitSettings(
            optimizer_starts=4,
            max_iterations=600,
            profile_likelihood=False,
        ),
        spectrum_knots=4,
        energy_response_samples=4,
        pitch_response_samples=16,
        secondary_beam="off",
    )
    edges = np.linspace(0, 180, pitch_bins + 1)
    observations = {
        name: gj.GlobalPitchCountObservation(
            energy_eV=np.geomspace(40, 1200, 20),
            pitch_deg=(edges[:-1] + edges[1:]) / 2,
            pitch_edges_deg=edges,
            counts=np.full((20, pitch_bins), level),
            exposure=np.ones((20, pitch_bins)),
            b_sc_nT=5.0,
            affected_side="low",
        )
        for name in ("S1", "S2")
    }
    prepared = tuple(gj._prepare_observation(n, o, settings) for n, o in observations.items())
    problem = gj._build_problem(
        prepared,
        "electrostatic",
        "constant",
        settings,
        beam_enabled=beam,
        transition_model="hard",
    )
    truth = problem.initial.copy()
    truth[problem.layout.physical] = (np.log(5 * ratio), -100.0)
    truth[problem.layout.contrast] = np.log(10)
    if mode == "shared":
        truth[problem.layout.hemisphere_baseline] = np.log(1.5)
        truth[problem.layout.contrast] = np.log(5)
    if beam:
        truth[problem.layout.beam] = np.log((2.0, 80.0, 0.3, 15.0))
    rng = np.random.default_rng(45)
    for index, (name, obs) in enumerate(tuple(observations.items())):
        log_mean, _, _ = gj._predicted_surfaces(truth, problem, index, prepared[index])
        observations[name] = replace(obs, counts=rng.poisson(np.exp(log_mean)).astype(float))
    return settings, observations, problem, truth


@pytest.mark.parametrize("mode", ["fixed", "shared"])
@pytest.mark.parametrize("beam", [False, True])
def test_boundary_model_native_and_python_agree(mode, beam):
    _, _, problem, truth = synthetic_case(mode, beam=beam)
    native = gj._native_hard_problem(problem)
    if native is None:
        pytest.skip("native backend unavailable")
    value, gradient = native.value_and_gradient(truth)
    assert value == pytest.approx(gj._objective(truth, problem), abs=1e-8)
    assert np.all(np.isfinite(gradient))
    for i, (lower, upper) in enumerate(problem.bounds):
        if lower == upper:
            assert gradient[i] == 0


def test_fixed_levels_response_and_bic():
    settings, _, problem, truth = synthetic_case()
    _, ratio, _ = gj._predicted_surfaces(truth, problem, 0, problem.observations[0])
    q = np.exp(ratio[:, :8])
    assert np.min(q) == pytest.approx(0.1)
    assert np.max(q) == pytest.approx(1)
    assert np.any((q > 0.11) & (q < 0.99))
    fit = gj._fit_candidate(
        problem.observations,
        "electrostatic",
        "constant",
        settings,
        beam_enabled=False,
        transition_model="hard",
        free_parameters=(),
    )
    assert fit.n_parameters == problem.layout.size - 2
    assert fit.bic == pytest.approx(fit.n_parameters * np.log(fit.n_cells) - 2 * fit.log_likelihood)
    assert "contrast_amplitude" not in fit.at_bounds
    assert "hemisphere_baseline[0]" not in fit.at_bounds


@pytest.mark.parametrize(
    "mode,ratio,pitch_bins",
    [
        ("fixed", 0.8, 16),
        ("fixed", 1.0, 16),
        ("fixed", 2.0, 8),
        ("shared", 0.8, 16),
    ],
)
def test_boundary_model_recovers_counts(mode, ratio, pitch_bins):
    settings, observations, _, _ = synthetic_case(mode, ratio, pitch_bins=pitch_bins)
    result = gj.fit_global_joint_effective_field(observations, settings=settings)
    assert result.selected_model == "electrostatic", result.reason
    assert result.mirror_ratio == pytest.approx(ratio, rel=0.08)
    assert result.delta_u_eff_eV == pytest.approx(-100, abs=8)
    if mode == "shared":
        fit = result.fit(result.selected_model)
        assert np.exp(fit.hemisphere_baseline_log_ratio[0]) == pytest.approx(1.5, rel=0.08)


def test_zero_counts_are_retained_and_no_edge_not_forced():
    settings, observations, _, _ = synthetic_case(level=3.0)
    rng = np.random.default_rng(1)
    observations = {
        n: replace(o, counts=rng.poisson(3, np.shape(o.counts)).astype(float))
        for n, o in observations.items()
    }
    prepared = gj._prepare_observation("S1", observations["S1"], settings)
    assert np.all(prepared.valid[prepared.counts == 0])
    result = gj.fit_global_joint_effective_field(observations, settings=settings)
    assert result.selected_model == "no_edge"


def test_shared_beam_auto_recovers_superposed_boundary():
    settings, observations, _, _ = synthetic_case("shared", beam=True)
    settings = replace(settings, secondary_beam="auto", beam_screening=False)
    result = gj.fit_global_joint_effective_field(observations, settings=settings)
    fit = result.fit(result.selected_model)
    assert result.selected_model == "electrostatic"
    assert fit.secondary_beam_enabled
    assert result.mirror_ratio == pytest.approx(0.8, abs=0.05)
    assert result.delta_u_eff_eV == pytest.approx(-100, abs=5)
    assert fit.beam_center_eV == pytest.approx(80, abs=5)
    assert fit.beam_amplitude == pytest.approx(2, rel=0.1)


def test_shared_beam_auto_does_not_force_beam():
    settings, observations, _, _ = synthetic_case("shared")
    settings = replace(settings, secondary_beam="auto", beam_screening=False)
    result = gj.fit_global_joint_effective_field(observations, settings=settings)
    assert not result.fit(result.selected_model).secondary_beam_enabled


def test_smooth_boundary_uses_arithmetic_levels_not_log_interpolation():
    settings, _, hard, _ = synthetic_case("fixed")
    settings = replace(settings, energy_response_samples=1, pitch_response_samples=1)
    observations = tuple(
        gj._prepare_observation(
            o.name,
            gj.GlobalPitchCountObservation(
                energy_eV=o.energy_eV,
                pitch_deg=o.pitch_deg,
                counts=o.counts,
                exposure=o.exposure,
                b_sc_nT=o.b_sc_nT,
                affected_side="low",
            ),
            settings,
        )
        for o in hard.observations
    )
    problem = gj._build_problem(
        observations,
        "electrostatic",
        "constant",
        settings,
        beam_enabled=False,
        transition_model="smooth",
    )
    observation = observations[0]
    vector = problem.initial.copy()
    vector[problem.layout.physical] = (np.log(10), 0, np.log(0.2))
    _, normalized, _ = gj._predicted_surfaces(vector, problem, 0, observation)
    pitch = observation.folded_pitch_response_deg.ravel()
    energy = observation.energy_response_eV[:, 0]
    transition = gj._transition_probability(
        pitch,
        energy,
        2.0,
        sigma_ln_b=0.2,
        transition_model="smooth",
        delta_u_eff_eV=0,
        spacecraft_potential_eV=0,
    )
    np.testing.assert_allclose(
        np.exp(normalized[:, observation.affected]),
        (0.1 + 0.9 * transition)[:, observation.affected],
    )


@pytest.mark.parametrize("mode", ["fixed", "shared"])
def test_failure_preserves_requested_family(mode):
    settings, observations, _, _ = synthetic_case(mode)
    settings = replace(
        settings,
        hemisphere_baseline_knots=1,
        effective_field=replace(settings.effective_field, max_iterations=1),
    )
    result = gj.fit_global_joint_effective_field(observations, settings=settings)
    assert not result.success
    assert all(f.loss_cone_model == mode for f in result.model_fits)
    assert result.to_record()["loss_cone_model"] == mode


def test_boundary_grid_improves_flat_start_without_changing_nuisance():
    settings, observations, problem, truth = synthetic_case("fixed")
    problem = replace(
        problem,
        observations=tuple(
            gj._prepare_observation(n, o, settings) for n, o in observations.items()
        ),
    )
    vector = truth.copy()
    vector[problem.layout.physical] = (np.log(500), 0)
    native = gj._native_hard_problem(problem)
    refined = gj._boundary_grid_start(vector, problem, native)
    assert gj._objective(refined, problem) < gj._objective(vector, problem) - 1
    np.testing.assert_array_equal(
        refined[problem.layout.physical.stop :], vector[problem.layout.physical.stop :]
    )
