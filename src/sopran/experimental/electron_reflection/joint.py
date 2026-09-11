from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from math import exp, log
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
from numpy.typing import NDArray

from sopran.experimental.electron_reflection.model import (
    CandidateModel,
    EffectiveFieldEstimate,
    EffectiveFieldFitSettings,
    ElectronReflectionCounts,
    FloatArray,
    ResolvedContrastModel,
    _boundary_support,
    _initial_parameters,
    _negative_log_likelihood,
    _negative_log_likelihood_and_gradient,
    _observed_log_ratio,
    _parameter_layout,
    _physical_candidate,
    _prepare_counts,
    _unpack,
    fit_effective_field,
    mirror_boundary_sin2,
    mirror_transmission_probability,
)


@dataclass(frozen=True)
class JointObservationFit:
    """One sensor's contribution to a shared electron-reflectometry fit."""

    name: str
    energy_eV: FloatArray
    pitch_deg: FloatArray
    valid: NDArray[np.bool_]
    observed_log_ratio: FloatArray
    fitted_log_ratio: FloatArray
    expected_affected_fraction: FloatArray
    standardized_residual: FloatArray
    boundary_pitch_deg: FloatArray
    baseline_log_ratio: FloatArray
    amplitude_log_ratio: FloatArray
    concentration: float
    log_likelihood: float
    log_likelihood_gain_over_no_edge: float
    total_counts: int
    n_cells: int


@dataclass(frozen=True)
class JointEffectiveFieldModelFit:
    """A no-edge, mirror, or electrostatic model fitted to all observations."""

    model: CandidateModel
    success: bool
    reason: str
    mirror_ratio: float | None
    delta_u_eff_eV: float | None
    sigma_ln_b: float | None
    log_likelihood: float | None
    bic: float | None
    n_parameters: int
    n_cells: int
    contrast_model: ResolvedContrastModel
    at_bounds: tuple[str, ...]
    boundary_bracket_fraction: float | None
    strict_boundary_bracket_fraction: float | None
    observations: tuple[JointObservationFit, ...]

    def observation(self, name: str) -> JointObservationFit:
        for observation in self.observations:
            if observation.name == name:
                return observation
        raise KeyError(name)


@dataclass(frozen=True)
class JointEffectiveFieldEstimate:
    """Shared physical estimate with sensor-specific reconstructions."""

    success: bool
    reason: str
    selected_model: CandidateModel
    edge_supported: bool
    mirror_ratio: float | None
    effective_field_nT: float | None
    delta_u_eff_eV: float | None
    sigma_ln_b: float | None
    representative_b_sc_nT: float
    no_edge_delta_bic: float
    electrostatic_delta_bic: float
    contrast_band_delta_bic: float
    model_fits: tuple[JointEffectiveFieldModelFit, ...]
    individual_estimates: tuple[tuple[str, EffectiveFieldEstimate], ...]

    def fit(self, model: CandidateModel) -> JointEffectiveFieldModelFit:
        for candidate in self.model_fits:
            if candidate.model == model:
                return candidate
        raise KeyError(model)

    def individual(self, name: str) -> EffectiveFieldEstimate:
        for observation_name, estimate in self.individual_estimates:
            if observation_name == name:
                return estimate
        raise KeyError(name)

    def to_record(self) -> dict[str, object]:
        selected = self.fit(self.selected_model)
        record: dict[str, object] = {
            "success": self.success,
            "reason": self.reason,
            "selected_model": self.selected_model,
            "edge_supported": self.edge_supported,
            "mirror_ratio": self.mirror_ratio,
            "effective_field_nT": self.effective_field_nT,
            "delta_u_eff_eV": self.delta_u_eff_eV,
            "sigma_ln_b": self.sigma_ln_b,
            "representative_b_sc_nT": self.representative_b_sc_nT,
            "no_edge_delta_bic": self.no_edge_delta_bic,
            "electrostatic_delta_bic": self.electrostatic_delta_bic,
            "contrast_band_delta_bic": self.contrast_band_delta_bic,
            "contrast_model": selected.contrast_model,
            "n_cells": selected.n_cells,
            "n_parameters": selected.n_parameters,
            "at_bounds": ",".join(selected.at_bounds),
        }
        for observation in selected.observations:
            prefix = observation.name.lower().replace("-", "_")
            record[f"{prefix}_n_cells"] = observation.n_cells
            record[f"{prefix}_total_counts"] = observation.total_counts
            record[f"{prefix}_log_likelihood_gain"] = observation.log_likelihood_gain_over_no_edge
            individual = self.individual(observation.name)
            record[f"{prefix}_individual_model"] = individual.selected_model
            record[f"{prefix}_individual_edge_supported"] = individual.edge_supported
            record[f"{prefix}_individual_mirror_ratio"] = individual.mirror_ratio
        return record


@dataclass(frozen=True)
class _JointProblem:
    names: tuple[str, ...]
    data: tuple[Any, ...]
    local_layouts: tuple[Any, ...]
    local_maps: tuple[NDArray[np.int64], ...]
    initial: FloatArray
    bounds: tuple[tuple[float, float], ...]
    parameter_names: tuple[str, ...]
    model: CandidateModel
    contrast_model: ResolvedContrastModel


def fit_joint_effective_field(
    observations: Mapping[str, ElectronReflectionCounts],
    *,
    settings: EffectiveFieldFitSettings | None = None,
) -> JointEffectiveFieldEstimate:
    """Fit shared mirror parameters without merging sensor count surfaces.

    Energy baselines, contrast parameters, and beta-binomial concentration are
    fitted independently for every named observation. Mirror ratio, effective
    potential, and transition width are shared by all observations.
    """

    settings = settings or EffectiveFieldFitSettings(profile_likelihood=False)
    if len(observations) < 2:
        raise ValueError("joint fitting requires at least two named observations")
    if any(not str(name).strip() for name in observations):
        raise ValueError("joint observation names must be non-empty")

    prepared: dict[str, Any] = {}
    for name, counts in observations.items():
        data = _prepare_counts(counts, settings)
        if data.n_energy < settings.min_energy_bins:
            raise ValueError(f"{name} has insufficient energy support")
        prepared[str(name)] = data
    total_counts = sum(data.total_counts for data in prepared.values())
    if total_counts < settings.min_total_counts:
        raise ValueError("joint observations have insufficient total counts")

    no_edge = _fit_joint_candidate(prepared, "no_edge", "none", settings)
    mirror, contrast_delta = _fit_joint_mirror(prepared, settings)
    electrostatic = _fit_joint_candidate(
        prepared,
        "electrostatic",
        mirror.contrast_model,
        settings,
    )
    mirror = _attach_no_edge_gains(mirror, no_edge)
    electrostatic = _attach_no_edge_gains(electrostatic, no_edge)
    no_edge_delta = _bic_improvement(no_edge, mirror)
    electrostatic_delta = _bic_improvement(mirror, electrostatic)

    selected = no_edge
    tentative = mirror
    reason = "no_edge_evidence"
    if mirror.success and no_edge_delta >= settings.min_edge_delta_bic:
        if electrostatic.success and electrostatic_delta >= settings.min_electrostatic_delta_bic:
            tentative = electrostatic
        quality_reason = _joint_edge_quality_reason(tentative, settings)
        if quality_reason is None:
            selected = tentative
            reason = (
                "joint_electrostatic_curvature_supported"
                if selected.model == "electrostatic"
                else "joint_mirror_edge_supported"
            )
        elif tentative.model == "electrostatic":
            mirror_reason = _joint_edge_quality_reason(mirror, settings)
            if mirror_reason is None:
                selected = mirror
                reason = "joint_mirror_edge_supported"
            else:
                reason = quality_reason
        else:
            reason = quality_reason

    edge_supported = selected.model != "no_edge"
    representative_b = float(np.median([counts.b_sc_nT for counts in observations.values()]))
    mirror_ratio = selected.mirror_ratio if edge_supported else None
    individual = tuple(
        (
            str(name),
            fit_effective_field(
                counts,
                settings=_without_profile_likelihood(settings),
            ),
        )
        for name, counts in observations.items()
    )
    return JointEffectiveFieldEstimate(
        success=selected.success,
        reason=reason if selected.success else selected.reason,
        selected_model=selected.model,
        edge_supported=edge_supported,
        mirror_ratio=mirror_ratio,
        effective_field_nT=(None if mirror_ratio is None else representative_b * mirror_ratio),
        delta_u_eff_eV=(selected.delta_u_eff_eV if selected.model == "electrostatic" else None),
        sigma_ln_b=selected.sigma_ln_b if edge_supported else None,
        representative_b_sc_nT=representative_b,
        no_edge_delta_bic=no_edge_delta,
        electrostatic_delta_bic=electrostatic_delta,
        contrast_band_delta_bic=contrast_delta,
        model_fits=(no_edge, mirror, electrostatic),
        individual_estimates=individual,
    )


def plot_joint_effective_field_fit(
    estimate: JointEffectiveFieldEstimate,
    *,
    path: str | Path | None = None,
    surface_limit: float | None = None,
    residual_limit: float | None = None,
    model: CandidateModel | Literal["selected", "best_edge"] = "selected",
) -> Any:
    """Plot observed, reconstructed, and residual surfaces for every sensor."""

    import matplotlib.pyplot as plt  # type: ignore[import-untyped]

    selected = _plot_model_fit(estimate, model)
    rows = len(selected.observations)
    figure, axes = plt.subplots(
        rows,
        3,
        figsize=(14.8, max(4.2, 4.1 * rows)),
        squeeze=False,
        constrained_layout=True,
    )
    ratio_values = np.concatenate(
        [
            observation.observed_log_ratio[observation.valid]
            for observation in selected.observations
            if np.any(observation.valid)
        ]
    )
    residual_values = np.concatenate(
        [
            (observation.observed_log_ratio - observation.fitted_log_ratio)[observation.valid]
            for observation in selected.observations
            if np.any(observation.valid)
        ]
    )
    ratio_scale = surface_limit or _robust_symmetric_limit(ratio_values, minimum=1.0)
    residual_scale = residual_limit or _robust_symmetric_limit(
        residual_values,
        minimum=0.5,
    )
    cmap = plt.colormaps["coolwarm"].with_extremes(bad="#d9d9d9")
    ratio_mesh = None
    residual_mesh = None
    for row, observation in enumerate(selected.observations):
        residual = observation.observed_log_ratio - observation.fitted_log_ratio
        panels = (
            (observation.observed_log_ratio, "Observed log rate ratio", ratio_scale),
            (observation.fitted_log_ratio, "Joint-model reconstruction", ratio_scale),
            (residual, "Observed - reconstructed", residual_scale),
        )
        for column, (values, title, limit) in enumerate(panels):
            axis = axes[row, column]
            mesh = axis.pcolormesh(
                observation.pitch_deg,
                observation.energy_eV,
                np.ma.masked_invalid(values),
                shading="nearest",
                cmap=cmap,
                vmin=-limit,
                vmax=limit,
            )
            if column < 2:
                ratio_mesh = mesh
            else:
                residual_mesh = mesh
            if selected.model != "no_edge":
                axis.plot(
                    observation.boundary_pitch_deg,
                    observation.energy_eV,
                    color="black",
                    linewidth=1.5,
                    label="shared boundary",
                )
                individual = estimate.individual(observation.name)
                if individual.edge_supported and individual.mirror_ratio is not None:
                    individual_boundary = _boundary_pitch(
                        observation.energy_eV,
                        individual.mirror_ratio,
                        individual.delta_u_eff_eV or 0.0,
                    )
                    axis.plot(
                        individual_boundary,
                        observation.energy_eV,
                        color="#00bcd4",
                        linewidth=1.2,
                        linestyle="--",
                        label=f"{observation.name}-only",
                    )
            axis.set(yscale="log", xlim=(0.0, 90.0))
            axis.set_xlabel("Folded pitch angle [deg]")
            axis.set_title(f"{observation.name}: {title}", fontsize=10)
        axes[row, 0].set_ylabel("Energy [eV]")
        if selected.model != "no_edge":
            axes[row, 1].legend(loc="lower left", fontsize=7)
    if ratio_mesh is not None:
        figure.colorbar(
            ratio_mesh,
            ax=list(axes[:, :2].flat),
            pad=0.01,
            label="ln(rate affected/reference)",
        )
    if residual_mesh is not None:
        figure.colorbar(
            residual_mesh,
            ax=list(axes[:, 2].flat),
            pad=0.01,
            label="log-rate residual",
        )
    delta_u = (
        "fixed 0 eV"
        if selected.delta_u_eff_eV is None
        else f"{selected.delta_u_eff_eV:.3g} eV"
    )
    fitted_field = (
        None
        if selected.mirror_ratio is None
        else estimate.representative_b_sc_nT * selected.mirror_ratio
    )
    figure.suptitle(
        f"Separate-sensor joint ER fit | shown={selected.model}\n"
        f"selected={estimate.selected_model} ({estimate.reason}) | "
        f"DeltaBIC(edge)={estimate.no_edge_delta_bic:.2f}\n"
        f"R_m={_format_optional(selected.mirror_ratio)} | "
        f"B_eff={_format_optional(fitted_field, ' nT')} | "
        f"DeltaU={delta_u}\n"
        "Black: shared S1/S2 boundary. Cyan dashed: independently fitted sensor boundary.",
        fontsize=10.5,
    )
    if path is not None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, dpi=150)
    return figure


def _plot_model_fit(
    estimate: JointEffectiveFieldEstimate,
    model: CandidateModel | Literal["selected", "best_edge"],
) -> JointEffectiveFieldModelFit:
    if model == "selected":
        return estimate.fit(estimate.selected_model)
    if model != "best_edge":
        return estimate.fit(model)
    candidates = [
        fit
        for fit in estimate.model_fits
        if fit.model != "no_edge" and fit.success and fit.bic is not None
    ]
    if not candidates:
        return estimate.fit(estimate.selected_model)
    return min(candidates, key=lambda fit: cast(float, fit.bic))


def _fit_joint_mirror(
    data: Mapping[str, Any],
    settings: EffectiveFieldFitSettings,
) -> tuple[JointEffectiveFieldModelFit, float]:
    if settings.contrast_model != "auto":
        contrast = cast(ResolvedContrastModel, settings.contrast_model)
        return _fit_joint_candidate(data, "mirror_only", contrast, settings), float("nan")
    constant = _fit_joint_candidate(data, "mirror_only", "constant", settings)
    band = _fit_joint_candidate(data, "mirror_only", "band", settings)
    delta = _bic_improvement(constant, band)
    unresolved = {
        "contrast_band_excess_log_ratio",
        "contrast_band_center_eV",
        "contrast_band_width_ln",
    }.intersection(band.at_bounds)
    if band.success and not unresolved and delta >= settings.min_contrast_band_delta_bic:
        return band, delta
    return constant, delta


def _fit_joint_candidate(
    data: Mapping[str, Any],
    model: CandidateModel,
    contrast_model: ResolvedContrastModel,
    settings: EffectiveFieldFitSettings,
) -> JointEffectiveFieldModelFit:
    from scipy.optimize import minimize  # type: ignore[import-untyped]

    problem = _build_joint_problem(data, model, contrast_model, settings)
    best = None
    best_value = float("inf")
    for start in _joint_starts(problem, settings):
        result = minimize(
            _joint_objective,
            start,
            args=(problem,),
            method="L-BFGS-B",
            jac=True,
            bounds=problem.bounds,
            options={"maxiter": settings.max_iterations, "ftol": 1.0e-10},
        )
        if np.isfinite(result.fun) and float(result.fun) < best_value:
            best = result
            best_value = float(result.fun)
    if best is None:
        return _empty_joint_fit(model, contrast_model, "optimizer_failed")

    vector = np.asarray(best.x, dtype=float)
    at_bounds = _joint_parameters_at_bounds(vector, problem)
    physical = _shared_physical_parameters(vector, problem)
    mirror_ratio, delta_u, sigma = physical
    log_likelihood = -best_value
    observation_fits = _joint_observation_fits(problem, vector, no_edge=None)
    success = bool(
        np.isfinite(log_likelihood)
        and all(_physical_candidate(local, mirror_ratio, delta_u) for local in problem.data)
    )
    bracket, strict = _joint_boundary_support(problem.data, mirror_ratio, delta_u, settings)
    return JointEffectiveFieldModelFit(
        model=model,
        success=success,
        reason="ok" if success else "non_physical_or_nonfinite_fit",
        mirror_ratio=mirror_ratio,
        delta_u_eff_eV=delta_u,
        sigma_ln_b=sigma,
        log_likelihood=log_likelihood,
        bic=float(
            problem.initial.size * np.log(max(sum(x.n_cells for x in problem.data), 1))
            - 2.0 * log_likelihood
        ),
        n_parameters=int(problem.initial.size),
        n_cells=sum(local.n_cells for local in problem.data),
        contrast_model=contrast_model,
        at_bounds=at_bounds,
        boundary_bracket_fraction=bracket,
        strict_boundary_bracket_fraction=strict,
        observations=observation_fits,
    )


def _build_joint_problem(
    data: Mapping[str, Any],
    model: CandidateModel,
    contrast_model: ResolvedContrastModel,
    settings: EffectiveFieldFitSettings,
) -> _JointProblem:
    names = tuple(data)
    prepared = tuple(data[name] for name in names)
    local_layouts = tuple(
        _parameter_layout(model, local.n_energy, contrast_model) for local in prepared
    )
    shared_count = 0 if model == "no_edge" else 2 + int(model == "electrostatic")
    values: list[float] = [0.0] * shared_count
    bounds: list[tuple[float, float]] = [(0.0, 0.0)] * shared_count
    parameter_names: list[str] = []
    if model != "no_edge":
        parameter_names.append("mirror_ratio")
        bounds[0] = tuple(log(value) for value in settings.mirror_ratio_bounds)
        if model == "electrostatic":
            parameter_names.append("delta_u_eff_eV")
            bounds[1] = settings.delta_u_bounds_eV
        parameter_names.append("sigma_ln_b")
        bounds[shared_count - 1] = tuple(log(value) for value in settings.sigma_ln_b_bounds)

    local_maps: list[NDArray[np.int64]] = []
    local_initials: list[FloatArray] = []
    for name, local, layout in zip(names, prepared, local_layouts, strict=True):
        local_initial, local_bounds = _initial_parameters(local, layout, settings)
        local_initials.append(local_initial)
        mapping = np.full(layout.size, -1, dtype=np.int64)
        if layout.log_mirror is not None:
            mapping[layout.log_mirror] = 0
        if layout.delta_u is not None:
            mapping[layout.delta_u] = 1
        if layout.log_sigma is not None:
            mapping[layout.log_sigma] = shared_count - 1
        shared_local = {layout.log_mirror, layout.delta_u, layout.log_sigma}
        for local_index in range(layout.size):
            if local_index in shared_local:
                continue
            mapping[local_index] = len(values)
            values.append(float(local_initial[local_index]))
            bounds.append(local_bounds[local_index])
            parameter_names.append(_local_parameter_name(name, layout, local_index))
        local_maps.append(mapping)

    if model != "no_edge":
        values[0] = float(
            np.median(
                [
                    value[layout.log_mirror]
                    for value, layout in zip(local_initials, local_layouts, strict=True)
                ]
            )
        )
        if model == "electrostatic":
            values[1] = 0.0
        values[shared_count - 1] = float(
            np.median(
                [
                    value[layout.log_sigma]
                    for value, layout in zip(local_initials, local_layouts, strict=True)
                ]
            )
        )
    return _JointProblem(
        names=names,
        data=prepared,
        local_layouts=local_layouts,
        local_maps=tuple(local_maps),
        initial=np.asarray(values, dtype=float),
        bounds=tuple(bounds),
        parameter_names=tuple(parameter_names),
        model=model,
        contrast_model=contrast_model,
    )


def _joint_objective(
    vector: FloatArray,
    problem: _JointProblem,
) -> tuple[float, FloatArray]:
    total = 0.0
    gradient = np.zeros_like(vector)
    for local, layout, mapping in zip(
        problem.data,
        problem.local_layouts,
        problem.local_maps,
        strict=True,
    ):
        local_vector = np.asarray(vector[mapping], dtype=float)
        value, local_gradient = _negative_log_likelihood_and_gradient(
            local_vector,
            local,
            layout,
        )
        if not np.isfinite(value):
            return 1.0e30, np.zeros_like(vector)
        total += float(value)
        np.add.at(gradient, mapping, local_gradient)
    return total, gradient


def _joint_starts(
    problem: _JointProblem,
    settings: EffectiveFieldFitSettings,
) -> list[FloatArray]:
    starts = [problem.initial.copy()]
    if problem.model == "no_edge" or settings.optimizer_starts == 1:
        return starts
    ratio_index = 0
    delta_index = 1 if problem.model == "electrostatic" else None
    sigma_index = 2 if problem.model == "electrostatic" else 1
    ratios = np.geomspace(settings.mirror_ratio_bounds[0], settings.mirror_ratio_bounds[1], 7)
    ratio_candidates = (ratios[1], ratios[3], ratios[5])
    sigma_candidates = (0.12, 0.3, 0.7)
    delta_candidates = (-120.0, 0.0, 160.0)
    for index in range(1, settings.optimizer_starts):
        candidate = problem.initial.copy()
        candidate[ratio_index] = log(float(ratio_candidates[index % 3]))
        candidate[sigma_index] = log(
            float(np.clip(sigma_candidates[index % 3], *settings.sigma_ln_b_bounds))
        )
        if delta_index is not None:
            candidate[delta_index] = float(
                np.clip(delta_candidates[index % 3], *settings.delta_u_bounds_eV)
            )
            if index == 1 and settings.mirror_ratio_bounds[0] < 1.0:
                candidate[ratio_index] = log(float(np.clip(0.8, *settings.mirror_ratio_bounds)))
                candidate[delta_index] = float(np.clip(-100.0, *settings.delta_u_bounds_eV))
        starts.append(candidate)
    return starts


def _joint_observation_fits(
    problem: _JointProblem,
    vector: FloatArray,
    *,
    no_edge: JointEffectiveFieldModelFit | None,
) -> tuple[JointObservationFit, ...]:
    fits: list[JointObservationFit] = []
    for name, data, layout, mapping in zip(
        problem.names,
        problem.data,
        problem.local_layouts,
        problem.local_maps,
        strict=True,
    ):
        local_vector = np.asarray(vector[mapping], dtype=float)
        mirror_ratio, delta_u, sigma, baseline, amplitude, concentration = _unpack(
            local_vector,
            layout,
            data.energy_eV,
        )
        if layout.model == "no_edge":
            fitted = np.broadcast_to(baseline[:, None], data.affected_counts.shape).copy()
        else:
            assert mirror_ratio is not None and sigma is not None
            transition = mirror_transmission_probability(
                data.pitch_deg,
                data.energy_eV,
                mirror_ratio,
                sigma,
                delta_u_eff_eV=delta_u or 0.0,
                spacecraft_potential_eV=data.spacecraft_potential_eV,
            )
            fitted = baseline[:, None] + amplitude[:, None] * transition
        observed = _observed_log_ratio(data)
        logit = fitted + np.log(data.affected_exposure / data.reference_exposure)
        probability = 1.0 / (1.0 + np.exp(-np.clip(logit, -40.0, 40.0)))
        total = data.affected_counts + data.reference_counts
        variance = (
            total
            * probability
            * (1.0 - probability)
            * (total + concentration)
            / (1.0 + concentration)
        )
        standardized = np.divide(
            data.affected_counts - total * probability,
            np.sqrt(variance),
            out=np.full_like(total, np.nan),
            where=variance > 0.0,
        )
        for values in (fitted, probability, standardized):
            values[~data.valid] = np.nan
        local_log_likelihood = float(-_negative_log_likelihood(local_vector, data, layout))
        no_edge_likelihood = local_log_likelihood
        if no_edge is not None:
            no_edge_likelihood = no_edge.observation(name).log_likelihood
        fits.append(
            JointObservationFit(
                name=name,
                energy_eV=np.asarray(data.energy_eV, dtype=float),
                pitch_deg=np.asarray(data.pitch_deg, dtype=float),
                valid=np.asarray(data.valid, dtype=bool),
                observed_log_ratio=observed,
                fitted_log_ratio=np.asarray(fitted, dtype=float),
                expected_affected_fraction=np.asarray(probability, dtype=float),
                standardized_residual=np.asarray(standardized, dtype=float),
                boundary_pitch_deg=(
                    np.full(data.energy_eV.shape, np.nan)
                    if mirror_ratio is None
                    else _boundary_pitch(data.energy_eV, mirror_ratio, delta_u or 0.0)
                ),
                baseline_log_ratio=np.asarray(baseline, dtype=float),
                amplitude_log_ratio=np.asarray(amplitude, dtype=float),
                concentration=float(concentration),
                log_likelihood=local_log_likelihood,
                log_likelihood_gain_over_no_edge=(local_log_likelihood - no_edge_likelihood),
                total_counts=data.total_counts,
                n_cells=data.n_cells,
            )
        )
    return tuple(fits)


def _attach_no_edge_gains(
    fit: JointEffectiveFieldModelFit,
    no_edge: JointEffectiveFieldModelFit,
) -> JointEffectiveFieldModelFit:
    observations = tuple(
        replace(
            observation,
            log_likelihood_gain_over_no_edge=(
                observation.log_likelihood - no_edge.observation(observation.name).log_likelihood
            ),
        )
        for observation in fit.observations
    )
    return replace(fit, observations=observations)


def _shared_physical_parameters(
    vector: FloatArray,
    problem: _JointProblem,
) -> tuple[float | None, float | None, float | None]:
    if problem.model == "no_edge":
        return None, None, None
    mirror_ratio = exp(float(vector[0]))
    if problem.model == "electrostatic":
        return mirror_ratio, float(vector[1]), exp(float(vector[2]))
    return mirror_ratio, None, exp(float(vector[1]))


def _joint_parameters_at_bounds(
    vector: FloatArray,
    problem: _JointProblem,
) -> tuple[str, ...]:
    names: list[str] = []
    for value, bounds, name in zip(
        vector,
        problem.bounds,
        problem.parameter_names,
        strict=True,
    ):
        lower, upper = bounds
        if lower == upper:
            continue
        tolerance = 1.0e-4 * max(1.0, abs(lower), abs(upper))
        if abs(float(value) - lower) <= tolerance or abs(float(value) - upper) <= tolerance:
            names.append(name)
    return tuple(names)


def _joint_boundary_support(
    data: tuple[Any, ...],
    mirror_ratio: float | None,
    delta_u: float | None,
    settings: EffectiveFieldFitSettings,
) -> tuple[float | None, float | None]:
    fractions: list[tuple[float, float, int]] = []
    for local in data:
        bracket, strict = _boundary_support(
            local,
            mirror_ratio,
            delta_u,
            min_transition_energy_bins=settings.min_energy_bins,
        )
        if bracket is not None and strict is not None:
            fractions.append((bracket, strict, local.n_energy))
    if not fractions:
        return None, None
    weight = sum(item[2] for item in fractions)
    return (
        sum(item[0] * item[2] for item in fractions) / weight,
        sum(item[1] * item[2] for item in fractions) / weight,
    )


def _joint_edge_quality_reason(
    fit: JointEffectiveFieldModelFit,
    settings: EffectiveFieldFitSettings,
) -> str | None:
    if not fit.success:
        return fit.reason
    shared_bounds = {
        "mirror_ratio",
        "delta_u_eff_eV",
        "sigma_ln_b",
    }.intersection(fit.at_bounds)
    if shared_bounds:
        return "edge_parameter_at_bound"
    band_bounds = [name for name in fit.at_bounds if "contrast_band_" in name]
    if fit.contrast_model == "band" and band_bounds:
        return "contrast_band_parameter_at_bound"
    if (
        fit.boundary_bracket_fraction is None
        or fit.strict_boundary_bracket_fraction is None
        or fit.boundary_bracket_fraction < settings.min_boundary_bracket_fraction
        or fit.strict_boundary_bracket_fraction < settings.min_strict_boundary_bracket_fraction
    ):
        return "insufficient_boundary_bracketing"
    return None


def _local_parameter_name(name: str, layout: Any, index: int) -> str:
    prefix = name.lower().replace("-", "_")
    if layout.baseline.start <= index < layout.baseline.stop:
        return f"{prefix}.baseline[{index - layout.baseline.start}]"
    if layout.amplitude is not None and layout.amplitude.start <= index < layout.amplitude.stop:
        labels = {
            "constant": ("contrast_amplitude_log_ratio",),
            "band": (
                "contrast_band_floor_log_ratio",
                "contrast_band_excess_log_ratio",
                "contrast_band_center_eV",
                "contrast_band_width_ln",
            ),
        }
        offset = index - layout.amplitude.start
        label = labels.get(layout.contrast_model, (f"contrast[{offset}]",) * layout.amplitude.stop)[
            offset
        ]
        return f"{prefix}.{label}"
    if index == layout.log_concentration:
        return f"{prefix}.concentration"
    return f"{prefix}.parameter[{index}]"


def _bic_improvement(
    simple: JointEffectiveFieldModelFit,
    complex: JointEffectiveFieldModelFit,
) -> float:
    if simple.bic is None or complex.bic is None:
        return float("nan")
    return float(simple.bic - complex.bic)


def _boundary_pitch(
    energy_eV: FloatArray,
    mirror_ratio: float,
    delta_u_eff_eV: float,
) -> FloatArray:
    boundary = mirror_boundary_sin2(energy_eV, mirror_ratio, delta_u_eff_eV)
    physical = np.isfinite(boundary) & (boundary >= 0.0) & (boundary <= 1.0)
    pitch = np.full(boundary.shape, np.nan, dtype=float)
    pitch[physical] = np.degrees(np.arcsin(np.sqrt(boundary[physical])))
    return pitch


def _without_profile_likelihood(settings: EffectiveFieldFitSettings) -> EffectiveFieldFitSettings:
    if not settings.profile_likelihood:
        return settings
    return replace(settings, profile_likelihood=False)


def _empty_joint_fit(
    model: CandidateModel,
    contrast_model: ResolvedContrastModel,
    reason: str,
) -> JointEffectiveFieldModelFit:
    return JointEffectiveFieldModelFit(
        model=model,
        success=False,
        reason=reason,
        mirror_ratio=None,
        delta_u_eff_eV=None,
        sigma_ln_b=None,
        log_likelihood=None,
        bic=None,
        n_parameters=0,
        n_cells=0,
        contrast_model=contrast_model,
        at_bounds=(),
        boundary_bracket_fraction=None,
        strict_boundary_bracket_fraction=None,
        observations=(),
    )


def _robust_symmetric_limit(values: FloatArray, *, minimum: float) -> float:
    finite = np.abs(np.asarray(values, dtype=float))
    finite = finite[np.isfinite(finite)]
    return minimum if not finite.size else max(minimum, float(np.percentile(finite, 97.5)))


def _format_optional(value: float | None, suffix: str = "") -> str:
    return "n/a" if value is None or not np.isfinite(value) else f"{value:.3g}{suffix}"


__all__ = [
    "JointEffectiveFieldEstimate",
    "JointEffectiveFieldModelFit",
    "JointObservationFit",
    "fit_joint_effective_field",
    "plot_joint_effective_field_fit",
]
