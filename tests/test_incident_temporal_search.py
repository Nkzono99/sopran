"""Audited production temporal search, separate from the working-only experiment."""

import json
from dataclasses import replace

import numpy as np
import pytest

from sopran.experimental.electron_reflection import global_joint as gj
from sopran.experimental.electron_reflection import integrated as model
from sopran.experimental.electron_reflection import temporal as t
from sopran.experimental.electron_reflection.incident import IncidentProblem, Result


@pytest.fixture
def sample():
    settings = gj.GlobalJointFitSettings(loss_cone_model="shared", edge_transition="hard")
    edges = np.linspace(0, 180, 17)
    observations = {
        name: gj.GlobalPitchCountObservation(
            energy_eV=np.geomspace(40, 1200, 12),
            pitch_deg=(edges[:-1] + edges[1:]) / 2,
            pitch_edges_deg=edges,
            counts=np.full((12, 16), 100.0),
            exposure=np.ones((12, 16)),
            b_sc_nT=5.0,
            affected_side="low",
        )
        for name in ("S1", "S2")
    }
    prepared = tuple(gj._prepare_observation(n, o, settings) for n, o in observations.items())
    fits = {}
    for i, key in enumerate(t.KEYS):
        candidate = key.removesuffix("_beam")
        fits[key] = replace(
            gj._empty_fit(candidate, "constant", "hard", "test", loss_cone_model="shared"),
            success=True,
            bic=100.0 + i * 20,
            secondary_beam_enabled=key.endswith("_beam"),
            mirror_ratio=None if candidate == "no_edge" else 2.0,
            delta_u_eff_eV=None if candidate == "no_edge" else 0.0,
            boundary_bracket_fraction=1.0,
            strict_boundary_bracket_fraction=1.0,
        )
    state = t.SearchState(
        8_000_000_000, t.settings_hash(settings), t.window_context(prepared, settings), fits
    )
    return settings, observations, prepared, state


@pytest.mark.parametrize(
    "kwargs",
    [
        {"audit_every": 0},
        {"chain_windows": 0},
        {"max_gap_seconds": 0},
        {"median_rate_factor": 1},
        {"max_missing_fraction": 1.1},
        {"bic_margin": -1},
        {"max_gap_seconds": np.nan},
        {"bic_margin": np.inf},
    ],
)
def test_invalid_policy(kwargs):
    with pytest.raises(ValueError):
        t.WarmStartPolicy(**kwargs)


def test_context_roundtrip_and_low_count_diagnostic(sample):
    settings, obs, prepared, state = sample
    assert len(state.context.log10_rates) == 48
    zero = dict(obs, S1=replace(obs["S1"], counts=np.zeros_like(obs["S1"].counts)))
    prepared_zero = tuple(gj._prepare_observation(n, o, settings) for n, o in zero.items())
    context = t.window_context(prepared_zero, settings)
    assert all(x is None or np.isfinite(x) for x in context.log10_rates)
    np.testing.assert_array_equal(prepared_zero[0].counts, 0)
    result = t.SearchResult(prepared, state.fits, state, "warm", (), 0)
    restored = t.state_from_record(json.loads(json.dumps(result.to_record())), state.fits)
    assert restored == state
    assert t.state_from_record({}, state.fits) is None


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"sensors": ("S2", "S1")}, "sensor_or_energy_grid_changed"),
        ({"energy_range": (30.0, 1200.0)}, "sensor_or_energy_grid_changed"),
        ({"orientations": (("high",), ("low",))}, "hemisphere_changed"),
        ({"b_sc_nT": 15.0}, "field_changed"),
        ({"log10_rates": (None,) * 48}, "coverage_changed"),
        ({"log10_rates": (10.0,) * 48}, "distribution_changed"),
    ],
)
def test_resets_on_incompatible_or_changed_observations(sample, change, reason):
    _, _, _, old = sample
    context = replace(old.context, **change)
    assert reason in t.reset_reasons(
        context, old.time_ns + 16_000_000_000, old.settings_hash, old, t.WarmStartPolicy()
    )


def test_gap_settings_and_unresolved_guards(sample):
    _, _, _, old = sample
    policy = t.WarmStartPolicy()
    assert not t.reset_reasons(
        old.context, old.time_ns + 16_000_000_000, old.settings_hash, old, policy
    )
    assert "time_gap_or_order" in t.reset_reasons(
        old.context, old.time_ns, old.settings_hash, old, policy
    )
    assert "settings_changed" in t.reset_reasons(
        old.context, old.time_ns + 16_000_000_000, "different", old, policy
    )
    bad = replace(old, fits=dict(old.fits, no_edge=replace(old.fits["no_edge"], success=False)))
    assert "previous_candidates_unresolved" in t.reset_reasons(
        old.context, old.time_ns + 16_000_000_000, old.settings_hash, bad, policy
    )


def test_all_candidates_have_current_anchor_and_independent_beam_seeds(sample, monkeypatch):
    settings, _, prepared, old = sample
    original = model.problem_for
    calls = {}
    monkeypatch.setattr(model, "problem_for", lambda *a: original(*a, backend="python"))

    def fake_fit(self, seeds, **kwargs):
        key = self.layout.model + ("_beam" if self.layout.beam is not None else "")
        calls.setdefault(key, []).append(np.array(seeds))
        return Result(self.initial.copy(), True, "test", 100.0, 200.0, [], 1)

    monkeypatch.setattr(IncidentProblem, "fit", fake_fit)
    fits = t.warm_candidates(prepared, settings, old)
    assert set(fits) == set(t.KEYS)
    for key, batches in calls.items():
        assert len(batches) == 2
        assert len(batches[0]) >= 2
        if key.endswith("_beam"):
            p = original(prepared, key.removesuffix("_beam"), True, settings, backend="python")
            centers = np.exp(batches[0][:, p.layout.beam][:, 1])
            for center in (70, 150, 800):
                assert np.any(np.isclose(centers, center))


def test_full_first_warm_next_and_audit_merges_better_candidates(sample, monkeypatch):
    settings, obs, prepared, old = sample
    calls = []
    cold = {k: replace(v, bic=v.bic + 2) for k, v in old.fits.items()}
    cold["electrostatic"] = replace(cold["electrostatic"], bic=old.fits["electrostatic"].bic - 3)

    def full(*a, **kw):
        calls.append("full")
        return prepared, cold

    monkeypatch.setattr(model, "fit_candidates", full)
    monkeypatch.setattr(t, "warm_candidates", lambda *a: old.fits)
    monkeypatch.setattr(t, "refinement_reasons", lambda *a: [])
    first = t.fit_candidates(obs, settings, time_ns=old.time_ns)
    assert first.mode == "full" and first.reasons == ("no_previous_checkpoint",)
    second = t.fit_candidates(obs, settings, time_ns=24_000_000_000, previous=old)
    assert second.mode == "warm" and calls == ["full"]
    audit_old = replace(old, time_ns=248_000_000_000)
    audited = t.fit_candidates(obs, settings, time_ns=264_000_000_000, previous=audit_old)
    assert audited.mode == "refined" and "periodic_full_audit" in audited.reasons
    assert audited.fits["no_edge"] is old.fits["no_edge"]
    assert audited.fits["electrostatic"] is cold["electrostatic"]
    assert audited.audit["warm"]["candidates"]["electrostatic"]["bic"] == 180
    assert audited.audit["full"]["candidates"]["electrostatic"]["bic"] == 177


def test_cold_does_not_hide_better_unconverged_candidate(sample):
    _, _, _, old = sample
    good = old.fits["electrostatic"]
    better = replace(good, success=False, bic=good.bic - 5)
    assert t.better_fit(better, good) is better
    tied = replace(good, success=False)
    assert t.better_fit(tied, good) is good


def test_refinement_near_bic_not_temporal_selection_change(sample):
    settings, _, _, old = sample
    fits = dict(old.fits, electrostatic=replace(old.fits["electrostatic"], bic=1.0))
    assert not t.refinement_reasons(fits, settings, t.WarmStartPolicy())
    fits = dict(
        old.fits,
        no_edge_beam=replace(
            old.fits["no_edge_beam"], bic=100 - settings.min_secondary_beam_delta_bic + 0.1
        ),
    )
    assert "candidate_bic_close" in t.refinement_reasons(fits, settings, t.WarmStartPolicy())


def test_single_sensor_still_rejected(sample):
    settings, obs, _, _ = sample
    with pytest.raises(model.UnfitWindow, match="two usable sensor"):
        t.fit_candidates({"S1": obs["S1"]}, settings, time_ns=8_000_000_000)


@pytest.mark.parametrize("raw_null", [False, True])
def test_every_edge_and_best_null_threshold_is_audited(sample, raw_null):
    settings, _, _, old = sample
    fits = dict(old.fits)
    if raw_null:
        fits["no_edge_beam"] = replace(fits["no_edge_beam"], bic=85, at_bounds=("beam_amplitude",))
        fits["mirror_only"] = replace(
            fits["mirror_only"], bic=85 - settings.effective_field.min_edge_delta_bic
        )
    else:
        fits["mirror_only"] = replace(
            fits["mirror_only"], bic=100 - settings.effective_field.min_edge_delta_bic
        )
        fits["electrostatic"] = replace(
            fits["electrostatic"], bic=20, at_bounds=("delta_u_eff_eV",)
        )
    assert "candidate_bic_close" in t.refinement_reasons(fits, settings, t.WarmStartPolicy())


def test_numerical_warm_failure_retries_full_and_records_reason(sample, monkeypatch):
    settings, obs, prepared, old = sample

    def failed(*a):
        raise RuntimeError("No finite optimization result")

    monkeypatch.setattr(t, "warm_candidates", failed)
    monkeypatch.setattr(model, "fit_candidates", lambda *a, **kw: (prepared, old.fits))
    result = t.fit_candidates(obs, settings, time_ns=24_000_000_000, previous=old)
    assert result.mode == "full"
    assert result.reasons[0].startswith("warm_numerical_failure:")
    assert result.fits is old.fits
