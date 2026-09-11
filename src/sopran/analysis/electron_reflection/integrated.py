"""Independent-window incident-PAD/ER candidate comparison.

This preserves the audited six-candidate hard-response experiment. Estimates
are provisional: convergence and edge detection are not field identification.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Literal

import numpy as np

from . import global_joint as gj
from .incident import IncidentProblem, Result


class UnfitWindow(ValueError):
    """Deterministic input-support limitation, not a numerical failure."""


def problem_for(
    observations: tuple[gj._PreparedGlobalObservation, ...],
    model: gj.CandidateModel,
    beam: bool,
    settings: gj.GlobalJointFitSettings,
    *,
    backend: Literal["rust", "python"] = "rust",
) -> IncidentProblem:
    return IncidentProblem(
        gj._build_problem(
            observations,
            model,
            "none" if model == "no_edge" else "constant",
            settings,
            beam_enabled=beam,
            transition_model="none" if model == "no_edge" else "hard",
        ),
        backend=backend,
    )


def transfer(problem: IncidentProblem, fit: gj.GlobalJointModelFit) -> np.ndarray:
    parameters = dict(zip(fit._parameter_names, fit._parameter_values, strict=True))
    return np.array(
        [
            np.clip(parameters.get(name, initial), lo, hi)
            for name, initial, (lo, hi) in zip(
                problem.names, problem.initial, problem.bounds, strict=True
            )
        ]
    )


def summarize(p: IncidentProblem, result: Result) -> gj.GlobalJointModelFit:
    model, beam = p.layout.model, p.layout.beam is not None
    field = np.exp(result.vector[0]) if model != "no_edge" else None
    delta = result.vector[1] if model == "electrostatic" else 0.0 if field is not None else None
    b = np.median([o.b_sc_nT for o in p.problem.observations])
    bracket, strict = gj._global_boundary_support(
        p.problem.observations,
        field,
        delta,
        spacecraft_potential_eV=p.problem.settings.effective_field.spacecraft_potential_eV,
        min_transition_energy_bins=p.problem.settings.effective_field.min_energy_bins,
        normalized_energy_bins=p.problem.settings.normalized_energy_bins,
    )
    amplitude, center, sigma_e, sigma_p = (
        np.exp(result.vector[p.layout.beam]) if beam else (None,) * 4
    )
    empty = gj._empty_fit(
        model,
        p.layout.contrast_model,
        p.layout.transition_model,
        result.message,
        loss_cone_model="shared",
    )
    return replace(
        empty,
        success=result.success,
        mirror_ratio=field / b if field is not None else None,
        delta_u_eff_eV=delta,
        sigma_ln_b=0.0 if field is not None else None,
        secondary_beam_enabled=beam,
        beam_amplitude=amplitude,
        beam_center_eV=center,
        beam_sigma_ln_energy=sigma_e,
        beam_sigma_pitch_deg=sigma_p,
        log_likelihood=-result.nll,
        bic=result.bic,
        n_parameters=sum(lo != hi for lo, hi in p.bounds),
        n_cells=len(p.counts),
        at_bounds=tuple(result.at_bounds),
        boundary_bracket_fraction=bracket,
        strict_boundary_bracket_fraction=strict,
        _parameter_names=p.names,
        _parameter_values=tuple(result.vector),
    )


def fit_candidates(
    observations: Mapping[str, gj.GlobalPitchCountObservation],
    settings: gj.GlobalJointFitSettings,
    *,
    backend: Literal["rust", "python"] = "rust",
    on_candidate: Callable[[str, gj.GlobalJointModelFit], None] | None = None,
) -> tuple[tuple[gj._PreparedGlobalObservation, ...], dict[str, gj.GlobalJointModelFit]]:
    prepared = tuple(gj._prepare_observation(n, o, settings) for n, o in observations.items())
    prepared = tuple(o for o in prepared if np.any(o.valid))
    if len({o.sensor_group for o in prepared}) < 2:
        raise UnfitWindow("At least two usable sensor groups are required")
    try:
        gj._validate_global_support(prepared, settings)
    except ValueError as exc:
        raise UnfitWindow(str(exc)) from exc
    if sum(np.sum(o.counts[o.valid]) for o in prepared) < settings.effective_field.min_total_counts:
        raise UnfitWindow("Insufficient total counts")
    fits: dict[str, gj.GlobalJointModelFit] = {}
    representative_b = np.median([o.b_sc_nT for o in prepared])
    problems = {}
    for model in ("no_edge", "mirror_only", "electrostatic"):
        for beam in (False, True):
            key = model + ("_beam" if beam else "")
            p = problems[key] = problem_for(prepared, model, beam, settings, backend=backend)
            seed = p.initial.copy()
            if beam:
                seed = transfer(p, fits[model])
            elif model != "no_edge":
                seed = transfer(p, fits["no_edge"])
            seeds = [seed]
            if model == "no_edge" and not beam:
                for coefficient in (-1.0, 1.0):
                    other = seed.copy()
                    other[p.n_base :] = coefficient
                    seeds.append(other)
            if model != "no_edge":
                for ratio, delta in ((0.8, -50), (1.5, -100), (5.0, 100)):
                    other = seed.copy()
                    other[0] = np.clip(np.log(representative_b * ratio), *p.bounds[0])
                    if model == "electrostatic":
                        other[1] = delta
                    seeds.append(other)
            if beam:
                for amplitude, center, width in (
                    (settings.beam_amplitude_bounds[0], 70, 30),
                    (0.5, 70, 20),
                    (0.5, 150, 35),
                    (0.5, 800, 15),
                ):
                    other = seed.copy()
                    other[p.layout.beam] = np.log([amplitude, center, 0.3, width])
                    seeds.append(other)
            if model == "electrostatic":
                nested = transfer(p, fits["mirror_only" + ("_beam" if beam else "")])
                for delta in (-100, -60, 0, 30):
                    other = nested.copy()
                    other[1] = delta
                    seeds.append(other)
            fits[key] = summarize(p, p.fit(seeds, maxiter=settings.effective_field.max_iterations))
            if on_candidate:
                on_candidate(key, fits[key])
    # Transfer nuisance parameters symmetrically across nested competitors.
    for _ in range(2):
        snapshot = dict(fits)
        for key, fit in snapshot.items():
            p = problems[key]
            seeds = [transfer(p, fit)]
            suffix = "_beam" if fit.secondary_beam_enabled else ""
            for other_model in ("mirror_only", "electrostatic"):
                other = snapshot[other_model + suffix]
                if other.model != fit.model:
                    seeds.append(transfer(p, other))
            if not fit.secondary_beam_enabled:
                seeds.append(transfer(p, snapshot[fit.model + "_beam"]))
            candidate = summarize(p, p.fit(seeds, maxiter=settings.effective_field.max_iterations))
            if candidate.bic < fit.bic - 1e-4 or (
                candidate.success and abs(candidate.bic - fit.bic) <= 1e-4
            ):
                fits[key] = candidate
            if on_candidate:
                on_candidate(key + "_refined", fits[key])
    return prepared, fits


def choose(
    fits: Mapping[str, gj.GlobalJointModelFit],
    settings: gj.GlobalJointFitSettings,
) -> tuple[gj.GlobalJointModelFit, str, gj.GlobalJointModelFit, dict[str, gj.GlobalJointModelFit]]:
    chosen = {}
    for model in ("no_edge", "mirror_only", "electrostatic"):
        off, on = fits[model], fits[model + "_beam"]
        improvement = gj._bic_improvement(off, on) if off.success and on.success else float("nan")
        use_beam = (
            off.success
            and on.success
            and not any(n.startswith("beam_") for n in on.at_bounds)
            and gj._quality_reason(on, settings) is None
            and improvement >= settings.min_secondary_beam_delta_bic
        )
        chosen[model] = replace(on if use_beam else off, secondary_beam_delta_bic=improvement)
    successful = [f for f in fits.values() if f.success]
    best = min(successful or list(fits.values()), key=lambda f: f.bic)
    if not all(f.success for f in fits.values()):
        reason = "model_comparison_unresolved" if successful else "all_candidates_nonconverged"
        return replace(chosen["no_edge"], success=False, reason=reason), reason, best, chosen
    selected, reason = gj._select_global_model(
        chosen["no_edge"], chosen["mirror_only"], chosen["electrostatic"], settings
    )
    null = min((f for f in successful if f.model == "no_edge"), key=lambda f: f.bic)
    if (
        selected.success
        and selected.model != "no_edge"
        and (null.bic - selected.bic < settings.effective_field.min_edge_delta_bic)
    ):
        reason = "edge_evidence_model_sensitive"
        return replace(null, success=False, reason=reason), reason, best, chosen
    if (
        selected.model == "no_edge"
        and reason == "no_edge_evidence"
        and any(
            f.model != "no_edge"
            and selected.bic - f.bic >= settings.effective_field.min_edge_delta_bic
            for f in successful
        )
    ):
        reason = "edge_candidate_rejected"
    return selected, reason, best, chosen


def fit_labels(
    selected: gj.GlobalJointModelFit, reason: str, fits: Mapping[str, gj.GlobalJointModelFit]
) -> dict[str, object]:
    """Screening labels, not confidence intervals or proof of crustal origin."""
    edge = selected.success and selected.model != "no_edge"
    flags = []
    if selected.at_bounds:
        flags.append("parameter_bound")
    if any(not f.success for f in fits.values()):
        flags.append("nonconverged_competitor")
    successful = [f for f in fits.values() if f.success]
    alternatives = [f for f in successful if f.bic < selected.bic - 1]
    if alternatives:
        flags.append("better_rejected_candidate")
    # A heuristic sensitivity screen; preserve the actual differences as well.
    off, on = fits[selected.model], fits[selected.model + "_beam"]
    field_ratio = None
    delta_difference = None
    if off.success and on.success and off.mirror_ratio and on.mirror_ratio:
        field_ratio = max(off.mirror_ratio / on.mirror_ratio, on.mirror_ratio / off.mirror_ratio)
        delta_difference = abs(off.delta_u_eff_eV - on.delta_u_eff_eV)
        if field_ratio > 1.5 or delta_difference > 30:
            flags.append("beam_sensitive")
    return dict(
        fit_label="edge_fit"
        if edge
        else "no_edge"
        if selected.success and reason == "no_edge_evidence"
        else "edge_quality_rejected"
        if selected.success
        else reason,
        edge_supported=edge,
        field_label="not_identified" if not edge else "review_required" if flags else "provisional",
        field_flags=flags,
        field_identified=False,
        beam_field_ratio=field_ratio,
        beam_delta_u_difference_eV=delta_difference,
        population_screen_pass=bool(edge and not flags),
    )
