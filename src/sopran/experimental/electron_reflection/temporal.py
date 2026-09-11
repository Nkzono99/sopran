"""Audited neighboring-window initial guesses for independent count fits.

No likelihood or prior is carried between windows. Search checks are computational
heuristics, not confidence intervals or additional data-selection filters.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Literal

import numpy as np

from . import global_joint as gj
from . import integrated as model

FitMap = dict[str, gj.GlobalJointModelFit]
KEYS = tuple(m + s for m in ("no_edge", "mirror_only", "electrostatic") for s in ("", "_beam"))


@dataclass(frozen=True)
class WarmStartPolicy:
    audit_every: int = 16
    chain_windows: int = 64
    max_gap_seconds: float = 16.01
    median_rate_factor: float = 3.0
    tail_rate_factor: float = 5.0
    max_missing_fraction: float = 0.25
    field_change_factor: float = 2.0
    bic_margin: float = 1.0

    def __post_init__(self) -> None:
        if self.audit_every < 1 or self.chain_windows < 1 or self.max_gap_seconds <= 0:
            raise ValueError("Search intervals must be positive")
        if min(self.median_rate_factor, self.tail_rate_factor, self.field_change_factor) <= 1:
            raise ValueError("Search change factors must exceed one")
        if not all(np.isfinite(v) for v in asdict(self).values()):
            raise ValueError("Search policy values must be finite")
        if not 0 <= self.max_missing_fraction <= 1 or self.bic_margin < 0:
            raise ValueError("Invalid search margins")


@dataclass(frozen=True)
class WindowContext:
    sensors: tuple[str, ...]
    energy_range: tuple[float, float]
    orientations: tuple[tuple[str, ...], ...]
    log10_rates: tuple[float | None, ...]
    b_sc_nT: float

    @classmethod
    def from_record(cls, value: Mapping) -> WindowContext:
        return cls(
            tuple(value["sensors"]),
            tuple(value["energy_range"]),
            tuple(tuple(x) for x in value["orientations"]),
            tuple(value["log10_rates"]),
            float(value["b_sc_nT"]),
        )


@dataclass(frozen=True)
class SearchState:
    time_ns: int
    settings_hash: str
    context: WindowContext
    fits: FitMap


@dataclass
class SearchResult:
    prepared: tuple[gj._PreparedGlobalObservation, ...]
    fits: FitMap
    state: SearchState
    mode: Literal["full", "warm", "refined"]
    reasons: tuple[str, ...]
    previous_time_ns: int | None
    audit: dict | None = None

    def to_record(self) -> dict:
        return dict(
            search_mode=self.mode,
            search_reasons=self.reasons,
            search_previous_time_ns=self.previous_time_ns,
            search_context=asdict(self.state.context),
            search_settings_hash=self.state.settings_hash,
            search_time_ns=self.state.time_ns,
            search_audit=self.audit,
        )


def settings_hash(settings: gj.GlobalJointFitSettings) -> str:
    return sha256(
        json.dumps(asdict(settings), sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def state_from_record(record: Mapping, fits: FitMap) -> SearchState | None:
    if not record.get("search_context"):
        return None
    return SearchState(
        int(record["search_time_ns"]),
        record["search_settings_hash"],
        WindowContext.from_record(record["search_context"]),
        fits,
    )


def window_context(
    prepared: tuple[gj._PreparedGlobalObservation, ...], settings: gj.GlobalJointFitSettings
) -> WindowContext:
    sensors = tuple(dict.fromkeys(o.sensor_group for o in prepared))
    energies = np.concatenate(
        [
            o.energy_eV[
                (o.energy_eV >= settings.energy_bounds_eV[0])
                & (o.energy_eV <= settings.energy_bounds_eV[1])
            ]
            for o in prepared
        ]
    )
    counts, exposure = np.zeros((len(sensors), 24)), np.zeros((len(sensors), 24))
    for obs in prepared:
        si = sensors.index(obs.sensor_group)
        ei, pi = np.nonzero(obs.valid)
        energy_bin = np.clip(np.searchsorted([80, 200, 600], obs.energy_eV[ei]), 0, 3)
        pitch_bin = np.clip(np.searchsorted([30, 60], obs.folded_pitch_deg[pi]), 0, 2)
        group = energy_bin * 6 + pitch_bin * 2 + obs.affected[pi].astype(int)
        np.add.at(counts[si], group, obs.counts[ei, pi])
        np.add.at(exposure[si], group, obs.exposure[ei, pi])
    # The half-count is only for the change detector, never for the fitted likelihood.
    rates = tuple(
        float(np.log10((c + 0.5) / e)) if e > 0 else None
        for c, e in zip(counts.ravel(), exposure.ravel(), strict=True)
    )
    return WindowContext(
        sensors,
        (float(energies.min()), float(energies.max())),
        tuple(
            tuple(sorted({o.affected_side for o in prepared if o.sensor_group == s}))
            for s in sensors
        ),
        rates,
        float(np.median([o.b_sc_nT for o in prepared])),
    )


def reset_reasons(
    current: WindowContext,
    time_ns: int,
    signature: str,
    previous: SearchState | None,
    policy: WarmStartPolicy,
) -> list[str]:
    if previous is None:
        return ["no_previous_checkpoint"]
    reasons = []
    if not 0 < (time_ns - previous.time_ns) / 1e9 <= policy.max_gap_seconds:
        reasons.append("time_gap_or_order")
    old = previous.context
    if signature != previous.settings_hash:
        reasons.append("settings_changed")
    if current.sensors != old.sensors or current.energy_range != old.energy_range:
        reasons.append("sensor_or_energy_grid_changed")
    if current.orientations != old.orientations:
        reasons.append("hemisphere_changed")
    if set(previous.fits) != set(KEYS) or any(
        not f.success or not np.isfinite(f.bic) for f in previous.fits.values()
    ):
        reasons.append("previous_candidates_unresolved")
    ratio = current.b_sc_nT / old.b_sc_nT
    if max(ratio, 1 / ratio) > policy.field_change_factor:
        reasons.append("field_changed")
    if current.sensors == old.sensors:
        a = np.array(current.log10_rates, dtype=float)
        b = np.array(old.log10_rates, dtype=float)
        shared = np.isfinite(a) & np.isfinite(b)
        if np.mean(np.isfinite(a) != np.isfinite(b)) > policy.max_missing_fraction:
            reasons.append("coverage_changed")
        if np.any(shared):
            change = np.abs(a[shared] - b[shared])
            if np.median(change) > np.log10(policy.median_rate_factor) or np.quantile(
                change, 0.9
            ) > np.log10(policy.tail_rate_factor):
                reasons.append("distribution_changed")
        else:
            reasons.append("no_common_rate_support")
    return reasons


def better_fit(a: gj.GlobalJointModelFit, b: gj.GlobalJointModelFit) -> gj.GlobalJointModelFit:
    if b.bic < a.bic - 1e-4 or (b.success and abs(b.bic - a.bic) <= 1e-4):
        return b
    return a


def warm_candidates(
    prepared: tuple[gj._PreparedGlobalObservation, ...],
    settings: gj.GlobalJointFitSettings,
    previous: SearchState,
    on_candidate: Callable | None = None,
) -> FitMap:
    fits, problems = {}, {}
    representative_b = np.median([o.b_sc_nT for o in prepared])
    for candidate in ("no_edge", "mirror_only", "electrostatic"):
        for beam in (False, True):
            key = candidate + ("_beam" if beam else "")
            p = problems[key] = model.problem_for(prepared, candidate, beam, settings)
            anchor = (
                model.transfer(p, fits[candidate])
                if beam
                else model.transfer(p, fits["no_edge"])
                if candidate != "no_edge"
                else p.initial
            )
            seeds = [model.transfer(p, previous.fits[key]), anchor]
            if candidate != "no_edge":
                for ratio, delta in ((0.8, -50), (1.5, -100), (5.0, 100)):
                    seed = anchor.copy()
                    seed[0] = np.clip(np.log(representative_b * ratio), *p.bounds[0])
                    if candidate == "electrostatic":
                        seed[1] = delta
                    seeds.append(seed)
            if beam:
                for amplitude, center, width in (
                    (settings.beam_amplitude_bounds[0], 70, 30),
                    (0.5, 70, 20),
                    (0.5, 150, 35),
                    (0.5, 800, 15),
                ):
                    seed = anchor.copy()
                    seed[p.layout.beam] = np.log([amplitude, center, 0.3, width])
                    seeds.append(seed)
            if candidate == "electrostatic":
                nested = model.transfer(p, fits["mirror_only" + ("_beam" if beam else "")])
                for delta in (-60, 0, 30):
                    seed = nested.copy()
                    seed[1] = delta
                    seeds.append(seed)
            fits[key] = model.summarize(
                p, p.fit(seeds, maxiter=settings.effective_field.max_iterations)
            )
            if on_candidate:
                on_candidate(key + "_warm", fits[key])
    snapshot = dict(fits)
    for key, fit in snapshot.items():
        p = problems[key]
        suffix = "_beam" if fit.secondary_beam_enabled else ""
        seeds = [model.transfer(p, fit)]
        for other in ("mirror_only", "electrostatic"):
            if other != fit.model:
                seeds.append(model.transfer(p, snapshot[other + suffix]))
        if not fit.secondary_beam_enabled:
            seeds.append(model.transfer(p, snapshot[fit.model + "_beam"]))
        candidate = model.summarize(
            p, p.fit(seeds, maxiter=settings.effective_field.max_iterations)
        )
        fits[key] = better_fit(fit, candidate)
        if on_candidate:
            on_candidate(key + "_warm_refined", fits[key])
    return fits


def refinement_reasons(
    fits: FitMap,
    settings: gj.GlobalJointFitSettings,
    policy: WarmStartPolicy,
) -> list[str]:
    reasons = []
    if any(not f.success for f in fits.values()):
        reasons.append("nonconverged_candidate")
    _, _, _, chosen = model.choose(fits, settings)
    ef = settings.effective_field
    # Both the selectable null and the best raw null participate in choose().
    # A strong but quality-rejected edge must not hide a marginal competitor.
    null_bics = (chosen["no_edge"].bic, min(fits["no_edge"].bic, fits["no_edge_beam"].bic))
    differences = [
        (null_bic - f.bic, ef.min_edge_delta_bic)
        for null_bic in null_bics
        for f in fits.values()
        if f.model != "no_edge"
    ]
    differences.append(
        (chosen["mirror_only"].bic - chosen["electrostatic"].bic, ef.min_electrostatic_delta_bic)
    )
    differences.extend(
        (fits[m].bic - fits[m + "_beam"].bic, settings.min_secondary_beam_delta_bic)
        for m in ("no_edge", "mirror_only", "electrostatic")
    )
    if any(abs(delta - threshold) <= policy.bic_margin for delta, threshold in differences):
        reasons.append("candidate_bic_close")
    return reasons


def audit_summary(
    warm: FitMap, cold: FitMap, merged: FitMap, settings: gj.GlobalJointFitSettings
) -> dict:
    def describe(fits: FitMap) -> dict:
        selected, reason, _, _ = model.choose(fits, settings)
        return dict(
            model=selected.model,
            beam=selected.secondary_beam_enabled,
            reason=reason,
            mirror_ratio=selected.mirror_ratio,
            delta_u_eV=selected.delta_u_eff_eV,
            labels=model.fit_labels(selected, reason, fits),
            candidates={
                k: dict(
                    bic=f.bic,
                    success=f.success,
                    names=f._parameter_names,
                    parameters=f._parameter_values,
                )
                for k, f in fits.items()
            },
        )

    return dict(
        candidate_bic_warm_minus_full={k: warm[k].bic - cold[k].bic for k in KEYS},
        warm=describe(warm),
        full=describe(cold),
        merged=describe(merged),
    )


def fit_candidates(
    observations: Mapping[str, gj.GlobalPitchCountObservation],
    settings: gj.GlobalJointFitSettings,
    *,
    time_ns: int,
    previous: SearchState | None = None,
    policy: WarmStartPolicy | None = None,
    on_candidate: Callable | None = None,
) -> SearchResult:
    policy = policy or WarmStartPolicy()
    prepared = tuple(gj._prepare_observation(n, o, settings) for n, o in observations.items())
    prepared = tuple(o for o in prepared if np.any(o.valid))
    if len({o.sensor_group for o in prepared}) < 2:
        raise model.UnfitWindow("At least two usable sensor groups are required")
    try:
        gj._validate_global_support(prepared, settings)
    except ValueError as exc:
        raise model.UnfitWindow(str(exc)) from exc
    if sum(np.sum(o.counts[o.valid]) for o in prepared) < settings.effective_field.min_total_counts:
        raise model.UnfitWindow("Insufficient total counts")
    context = window_context(prepared, settings)
    signature = settings_hash(settings)
    reasons = reset_reasons(context, time_ns, signature, previous, policy)
    audit = None
    if reasons:
        prepared, fits = model.fit_candidates(observations, settings, on_candidate=on_candidate)
        mode = "full"
    else:
        try:
            warm = warm_candidates(prepared, settings, previous, on_candidate)
        except (RuntimeError, FloatingPointError) as exc:
            reasons = [f"warm_numerical_failure: {type(exc).__name__}: {exc}"]
            prepared, fits = model.fit_candidates(observations, settings, on_candidate=on_candidate)
            mode = "full"
        else:
            reasons = refinement_reasons(warm, settings, policy)
            if (time_ns // 16_000_000_000) % policy.audit_every == 0:
                reasons.append("periodic_full_audit")
            if reasons:
                _, cold = model.fit_candidates(observations, settings, on_candidate=on_candidate)
                fits = {k: better_fit(warm[k], cold[k]) for k in KEYS}
                audit = audit_summary(warm, cold, fits, settings)
                mode = "refined"
            else:
                fits, mode = warm, "warm"
    state = SearchState(time_ns, signature, context, fits)
    return SearchResult(
        prepared,
        fits,
        state,
        mode,
        tuple(reasons),
        previous.time_ns if previous is not None else None,
        audit,
    )
