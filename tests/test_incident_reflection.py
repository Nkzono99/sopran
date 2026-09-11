from dataclasses import replace

import numpy as np
import pytest

from sopran.analysis.electron_reflection import global_joint as gj
from sopran.analysis.electron_reflection.incident import IncidentProblem


def make_problem(model="electrostatic", beam=False, anisotropic=True, backend="rust"):
    settings = gj.GlobalJointFitSettings(
        loss_cone_model="shared", spectrum_knots=4, edge_transition="hard", secondary_beam="off"
    )
    edges = np.linspace(0, 180, 17)
    counts = np.full((12, 16), 1000.0)
    counts[0, :3] = 0
    counts[1, 4] = np.nan
    observations = {
        name: gj.GlobalPitchCountObservation(
            energy_eV=np.geomspace(40, 1200, 12),
            pitch_deg=(edges[:-1] + edges[1:]) / 2,
            pitch_edges_deg=edges,
            counts=counts.copy(),
            exposure=np.ones((12, 16)),
            b_sc_nT=5.0 + i,
            affected_side="low" if i == 0 else "high",
        )
        for i, name in enumerate(("S1", "S2"))
    }
    prepared = tuple(gj._prepare_observation(n, o, settings) for n, o in observations.items())
    base = gj._build_problem(
        prepared,
        model,
        "none" if model == "no_edge" else "constant",
        settings,
        beam_enabled=beam,
        transition_model="none" if model == "no_edge" else "hard",
    )
    p = IncidentProblem(base, anisotropic=anisotropic, backend=backend)
    v = p.initial.copy()
    if model != "no_edge":
        v[0] = np.log(8.3 if model == "mirror_only" else 4.1)
        if model == "electrostatic":
            v[1] = -97.0
    v[base.layout.hemisphere_baseline] = np.log(0.8)
    if anisotropic:
        v[p.n_base :] = [1.1, 1.8, 0.7]
    if beam:
        v[base.layout.beam] = np.log([0.6, 80.0, 0.3, 15.0])
    return p, v


@pytest.mark.parametrize("model", ["no_edge", "mirror_only", "electrostatic"])
@pytest.mark.parametrize("beam", [False, True])
@pytest.mark.parametrize("anisotropic", [False, True])
def test_native_equivalence(model, beam, anisotropic):
    pytest.importorskip("sopran._native")
    p, v = make_problem(model, beam, anisotropic)
    mean, _ = p.predict(v)
    np.testing.assert_allclose(p._native.predict(v), mean, rtol=2e-12)
    expected, gradient = p.objective_python(v)
    actual, native_gradient = p.objective(v)
    assert actual == pytest.approx(expected, rel=2e-11, abs=2e-7)
    np.testing.assert_allclose(native_gradient, gradient, rtol=2e-8, atol=2e-6)


@pytest.mark.parametrize("model", ["no_edge", "mirror_only", "electrostatic"])
def test_native_gradient(model):
    pytest.importorskip("sopran._native")
    p, v = make_problem(model, True)
    _, grad = p.objective(v)
    numeric = []
    for i in range(len(v)):
        h = 1e-5 * max(1.0, abs(v[i]))
        delta = np.zeros_like(v)
        delta[i] = h
        numeric.append((p.objective(v + delta)[0] - p.objective(v - delta)[0]) / (2 * h))
    np.testing.assert_allclose(grad, numeric, rtol=1e-4, atol=1e-3)


@pytest.mark.parametrize("field,delta,shape", [(0.01, -500, 2), (5000, 1000, 1e6), (4.1, 30, 1e6)])
def test_native_extreme_parameters(field, delta, shape):
    pytest.importorskip("sopran._native")
    p, v = make_problem(beam=True)
    v[:2] = [np.log(field), delta]
    v[p.layout.dispersions] = np.log(shape)
    v[p.layout.gains] = 0.8
    expected, gradient = p.objective_python(v)
    actual, native = p.objective(v)
    assert actual == pytest.approx(expected, rel=1e-9, abs=3e-6)
    np.testing.assert_allclose(native, gradient, rtol=1e-7, atol=3e-6)


def test_fit_preserves_better_feasible_seed(monkeypatch):
    from scipy.optimize import OptimizeResult

    from sopran.analysis.electron_reflection import incident

    p, seed = make_problem(backend="python")
    best = p.objective(seed)[0]
    monkeypatch.setattr(
        incident,
        "minimize",
        lambda *a, **k: OptimizeResult(
            x=seed + 0.1,
            fun=best + 10,
            success=True,
            message="converged",
            nit=1,
        ),
    )
    fit = p.fit([seed])
    assert not fit.success
    assert fit.nll <= best + 1e-6
    np.testing.assert_allclose(fit.vector, seed)


def test_native_vector_validation():
    pytest.importorskip("sopran._native")
    p, v = make_problem()
    with pytest.raises(ValueError):
        p.objective(v[:-1])
    v[0] = np.nan
    with pytest.raises(ValueError):
        p.objective(v)


@pytest.mark.parametrize("changed", ["spectrum", "pad", "weights", "field", "counts"])
def test_response_reuse_keeps_weights_and_distinct_bases(monkeypatch, changed):
    native = pytest.importorskip("sopran._native")
    original = native.IncidentHardProblem
    packed = {}

    def capture(payload):
        packed.update(payload)
        return original(payload)

    monkeypatch.setattr(native, "IncidentHardProblem", capture)
    p, v = make_problem(beam=True)
    # Equal energies/pitch must not imply equal user-supplied basis matrices;
    # weights and per-record Bsc/exposure must still apply to each cell.
    if changed == "spectrum":
        p.sb[0, :, 0] += 0.15
    elif changed == "pad":
        p.ab[0, :, 1] += 0.3
    elif changed == "weights":
        p.ew[1] *= 0.6
    elif changed == "field":
        boundary = (1 + v[1] / p.energy) * p.b[:, None] / np.exp(v[0])
        angle = np.arcsin(np.sqrt(np.clip(boundary, 0, 1)))
        crossing = p.affected[:, None] & (angle > p.lower + 0.02) & (angle < p.upper - 0.02)
        cell = np.nonzero(crossing)[0][0]
        before = p.predict(v)[0]
        p.b[cell] *= 1.03
        assert not np.array_equal(p.predict(v)[0], before)
    else:
        from scipy.special import gammaln

        p.counts[:3] = [0.0, 0.25, 0.75]
        p.constant_ll = gammaln(p.counts + 1)
    v[p.layout.dispersions] = np.log([3.0, 19.0])
    packed.update(sb=p.sb.ravel(), ab=p.ab.ravel(), weights=p.ew.ravel(), b=p.b, counts=p.counts)
    candidate = original(packed)
    expected, gradient = p.objective_python(v)
    value, actual = candidate.value_and_gradient(v)
    assert value == pytest.approx(expected, rel=2e-11, abs=2e-7)
    np.testing.assert_allclose(actual, gradient, rtol=2e-8, atol=2e-6)


def test_labels_separate_edge_from_field_identification():
    from sopran.analysis.electron_reflection.integrated import fit_labels

    fit = replace(
        gj._empty_fit("electrostatic", "constant", "hard", "test", loss_cone_model="shared"),
        success=True,
        bic=100,
        mirror_ratio=0.5,
        delta_u_eff_eV=-80,
    )
    beam = replace(fit, secondary_beam_enabled=True, bic=105)
    fits = {"electrostatic": fit, "electrostatic_beam": beam}
    labels = fit_labels(fit, "electrostatic", fits)
    assert labels["fit_label"] == "edge_fit"
    assert labels["field_label"] == "provisional"
    assert not labels["field_identified"]
    assert labels["population_screen_pass"]
    fits["electrostatic_beam"] = replace(beam, mirror_ratio=2, delta_u_eff_eV=10)
    labels = fit_labels(fit, "electrostatic", fits)
    assert "beam_sensitive" in labels["field_flags"]
    assert not labels["population_screen_pass"]


def test_failed_candidate_never_qualifies_as_field():
    from sopran.analysis.electron_reflection.integrated import fit_labels

    fit = gj._empty_fit("no_edge", "none", "none", "failed", loss_cone_model="shared")
    labels = fit_labels(fit, "all_candidates_nonconverged", {"no_edge": fit, "no_edge_beam": fit})
    assert not labels["population_screen_pass"]
    assert not labels["edge_supported"]
    assert labels["field_label"] == "not_identified"


def test_better_rejected_null_makes_edge_evidence_unresolved():
    from sopran.analysis.electron_reflection.integrated import choose

    settings = gj.GlobalJointFitSettings(loss_cone_model="shared")
    fits = {}
    for model, bic in (("no_edge", 200), ("mirror_only", 100), ("electrostatic", 110)):
        base = replace(
            gj._empty_fit(model, "constant", "hard", "ok", loss_cone_model="shared"),
            success=True,
            bic=bic,
            mirror_ratio=2 if model != "no_edge" else None,
            delta_u_eff_eV=0,
            boundary_bracket_fraction=1,
            strict_boundary_bracket_fraction=1,
        )
        fits[model] = base
        fits[model + "_beam"] = replace(
            base,
            secondary_beam_enabled=True,
            bic=50 if model == "no_edge" else bic + 10,
            at_bounds=("beam_sigma_pitch_deg",),
        )
    selected, reason, _, _ = choose(fits, settings)
    assert not selected.success
    assert reason == "edge_evidence_model_sensitive"
    fits["no_edge_beam"] = replace(fits["no_edge_beam"], success=False)
    selected, reason, _, _ = choose(fits, settings)
    assert not selected.success
    assert reason == "model_comparison_unresolved"


def test_quality_rejection_is_not_no_edge_evidence():
    from sopran.analysis.electron_reflection.integrated import fit_labels

    fit = replace(
        gj._empty_fit("no_edge", "none", "none", "ok", loss_cone_model="shared"),
        success=True,
        bic=200,
    )
    fits = {"no_edge": fit, "no_edge_beam": replace(fit, secondary_beam_enabled=True)}
    labels = fit_labels(fit, "insufficient_boundary_bracketing", fits)
    assert labels["fit_label"] == "edge_quality_rejected"
    assert not labels["edge_supported"]


def test_rejected_beam_edge_is_not_no_edge_evidence():
    from sopran.analysis.electron_reflection.integrated import choose, fit_labels

    settings = gj.GlobalJointFitSettings(loss_cone_model="shared")
    fits = {}
    for model, bic in (("no_edge", 200), ("mirror_only", 210), ("electrostatic", 220)):
        base = replace(
            gj._empty_fit(model, "constant", "hard", "ok", loss_cone_model="shared"),
            success=True,
            bic=bic,
            mirror_ratio=2 if model != "no_edge" else None,
            delta_u_eff_eV=0,
            boundary_bracket_fraction=1,
            strict_boundary_bracket_fraction=1,
        )
        fits[model] = base
        fits[model + "_beam"] = replace(
            base,
            secondary_beam_enabled=True,
            bic=100 if model == "mirror_only" else bic + 10,
            at_bounds=("beam_sigma_pitch_deg",),
        )
    selected, reason, _, _ = choose(fits, settings)
    assert reason == "edge_candidate_rejected"
    assert fit_labels(selected, reason, fits)["fit_label"] == "edge_quality_rejected"
