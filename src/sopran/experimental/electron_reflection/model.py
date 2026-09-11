from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from math import exp, log
from typing import Literal, cast

import numpy as np
from numpy.typing import ArrayLike, NDArray

CandidateModel = Literal["no_edge", "mirror_only", "electrostatic"]
ContrastModel = Literal["auto", "free", "constant", "band"]
ResolvedContrastModel = Literal["none", "free", "constant", "band"]
FitQualityGrade = Literal["good", "review", "poor", "reject"]
FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class ElectronReflectionCounts:
    """Paired affected/reference electron counts on a folded 0-90 degree PAD.

    Rows are energy bins and columns are folded pitch-angle bins. Exposure is
    proportional to integration time times detector response; only its ratio
    between paired cells affects the conditional likelihood.
    """

    energy_eV: ArrayLike
    pitch_deg: ArrayLike
    affected_counts: ArrayLike
    reference_counts: ArrayLike
    b_sc_nT: float
    affected_exposure: ArrayLike | float = 1.0
    reference_exposure: ArrayLike | float = 1.0
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        energy = _float_array(self.energy_eV)
        pitch = _float_array(self.pitch_deg)
        affected = _float_array(self.affected_counts)
        reference = _float_array(self.reference_counts)
        if energy.ndim != 1:
            raise ValueError("energy_eV must be one-dimensional")
        if pitch.ndim != 1:
            raise ValueError("pitch_deg must be one-dimensional")
        if affected.ndim != 2 or reference.ndim != 2:
            raise ValueError("affected_counts and reference_counts must be two-dimensional")
        if affected.shape != reference.shape:
            raise ValueError("affected_counts and reference_counts must have the same shape")
        expected_shape = (energy.size, pitch.size)
        if affected.shape != expected_shape:
            raise ValueError("count array shape must equal (len(energy_eV), len(pitch_deg))")
        if np.any(np.isfinite(affected) & (affected < 0.0)) or np.any(
            np.isfinite(reference) & (reference < 0.0)
        ):
            raise ValueError("counts must be non-negative or NaN")
        finite_counts = np.concatenate(
            (affected[np.isfinite(affected)], reference[np.isfinite(reference)])
        )
        if finite_counts.size and not np.allclose(finite_counts, np.rint(finite_counts)):
            raise ValueError("counts must contain integer-valued observations")
        if not np.all(np.isfinite(energy)) or np.any(energy <= 0.0):
            raise ValueError("energy_eV must contain finite positive values")
        if not np.all(np.isfinite(pitch)) or np.any(pitch <= 0.0) or np.any(pitch >= 90.0):
            raise ValueError("pitch_deg must contain finite values strictly between 0 and 90")
        if not np.isfinite(self.b_sc_nT) or self.b_sc_nT <= 0.0:
            raise ValueError("b_sc_nT must be finite and positive")
        affected_exposure = _broadcast_positive(
            self.affected_exposure,
            affected.shape,
            name="affected_exposure",
        )
        reference_exposure = _broadcast_positive(
            self.reference_exposure,
            affected.shape,
            name="reference_exposure",
        )
        object.__setattr__(self, "energy_eV", energy)
        object.__setattr__(self, "pitch_deg", pitch)
        object.__setattr__(self, "affected_counts", affected)
        object.__setattr__(self, "reference_counts", reference)
        object.__setattr__(self, "affected_exposure", affected_exposure)
        object.__setattr__(self, "reference_exposure", reference_exposure)


@dataclass(frozen=True)
class EffectiveFieldQualitySettings:
    """Thresholds calibrated against observed/fitted pitch-map review panels."""

    good_log_ratio_residual_p90: float = 2.0
    review_log_ratio_residual_p90: float = 2.5
    good_pitch_pattern_correlation: float = 0.75
    review_pitch_pattern_correlation: float = 0.5
    good_pitch_pattern_nrmse: float = 0.75
    review_pitch_pattern_nrmse: float = 1.0
    standardized_residual_sigma: float = 3.0
    good_standardized_inlier_fraction: float = 0.9
    review_standardized_inlier_fraction: float = 0.75

    def __post_init__(self) -> None:
        if not 0.0 < self.good_log_ratio_residual_p90 <= self.review_log_ratio_residual_p90:
            raise ValueError("log-ratio residual thresholds must be positive with good <= review")
        if not (
            0.0
            <= self.review_pitch_pattern_correlation
            <= self.good_pitch_pattern_correlation
            <= 1.0
        ):
            raise ValueError(
                "pitch-pattern correlation thresholds must satisfy 0 <= review <= good <= 1"
            )
        if not 0.0 < self.good_pitch_pattern_nrmse <= self.review_pitch_pattern_nrmse:
            raise ValueError("pitch-pattern NRMSE thresholds must be positive with good <= review")
        if self.standardized_residual_sigma <= 0.0:
            raise ValueError("standardized_residual_sigma must be positive")
        if not (
            0.0
            <= self.review_standardized_inlier_fraction
            <= self.good_standardized_inlier_fraction
            <= 1.0
        ):
            raise ValueError("standardized inlier thresholds must satisfy 0 <= review <= good <= 1")


@dataclass(frozen=True)
class EffectiveFieldFitSettings:
    """Numerical and evidence settings for the nested ER model comparison.

    Mirror ratios represent a boundary-model field relative to the spacecraft
    field, not a path maximum; positive sub-unity ratios are permitted.
    """

    min_energy_bins: int = 3
    min_pitch_bins_per_energy: int = 6
    min_total_counts: int = 100
    mirror_ratio_bounds: tuple[float, float] = (0.001, 1000.0)
    delta_u_bounds_eV: tuple[float, float] = (-500.0, 1000.0)
    spacecraft_potential_eV: float = 0.0
    sigma_ln_b_bounds: tuple[float, float] = (0.03, 1.5)
    baseline_log_ratio_bounds: tuple[float, float] = (-8.0, 5.0)
    amplitude_log_ratio_bounds: tuple[float, float] = (0.0, 8.0)
    contrast_model: ContrastModel = "auto"
    contrast_band_width_bounds_ln: tuple[float, float] = (0.15, 2.5)
    concentration_bounds: tuple[float, float] = (2.0, 1_000_000.0)
    min_edge_delta_bic: float = 6.0
    min_electrostatic_delta_bic: float = 1.0
    min_contrast_band_delta_bic: float = 6.0
    min_energy_ratio_step_delta_bic: float = 6.0
    min_energy_ratio_step_bins_per_side: int = 3
    min_boundary_bracket_fraction: float = 0.8
    min_strict_boundary_bracket_fraction: float = 0.5
    optimizer_starts: int = 3
    max_iterations: int = 4000
    profile_likelihood: bool = True
    profile_points: int = 25
    profile_log_ratio_half_width: float = 1.5
    quality: EffectiveFieldQualitySettings = field(default_factory=EffectiveFieldQualitySettings)

    def __post_init__(self) -> None:
        if self.min_energy_bins < 2:
            raise ValueError("min_energy_bins must be at least 2")
        if self.min_pitch_bins_per_energy < 3:
            raise ValueError("min_pitch_bins_per_energy must be at least 3")
        if self.min_total_counts <= 0:
            raise ValueError("min_total_counts must be positive")
        for name, bounds in (
            ("mirror_ratio_bounds", self.mirror_ratio_bounds),
            ("sigma_ln_b_bounds", self.sigma_ln_b_bounds),
            ("concentration_bounds", self.concentration_bounds),
        ):
            _validate_positive_bounds(name, bounds)
        _validate_bounds("delta_u_bounds_eV", self.delta_u_bounds_eV)
        _validate_bounds("baseline_log_ratio_bounds", self.baseline_log_ratio_bounds)
        _validate_bounds("amplitude_log_ratio_bounds", self.amplitude_log_ratio_bounds)
        _validate_positive_bounds(
            "contrast_band_width_bounds_ln",
            self.contrast_band_width_bounds_ln,
        )
        if self.contrast_model not in {"auto", "free", "constant", "band"}:
            raise ValueError("contrast_model must be 'auto', 'free', 'constant', or 'band'")
        for name, value in (
            ("min_boundary_bracket_fraction", self.min_boundary_bracket_fraction),
            (
                "min_strict_boundary_bracket_fraction",
                self.min_strict_boundary_bracket_fraction,
            ),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if not np.isfinite(self.spacecraft_potential_eV):
            raise ValueError("spacecraft_potential_eV must be finite")
        if self.optimizer_starts <= 0:
            raise ValueError("optimizer_starts must be positive")
        if self.min_energy_ratio_step_bins_per_side < 2:
            raise ValueError("min_energy_ratio_step_bins_per_side must be at least 2")
        if self.max_iterations <= 0:
            raise ValueError("max_iterations must be positive")
        if self.profile_points < 5:
            raise ValueError("profile_points must be at least 5")


@dataclass(frozen=True)
class EffectiveFieldModelFit:
    """One fitted member of the nested no-edge/mirror model family."""

    model: CandidateModel
    success: bool
    reason: str
    mirror_ratio: float | None
    delta_u_eff_eV: float | None
    sigma_ln_b: float | None
    baseline_log_ratio: tuple[float, ...]
    amplitude_log_ratio: tuple[float, ...]
    concentration: float | None
    log_likelihood: float | None
    bic: float | None
    n_parameters: int
    n_cells: int
    at_bounds: tuple[str, ...] = ()
    contrast_model: ResolvedContrastModel = "none"
    contrast_band_center_eV: float | None = None
    contrast_band_width_ln: float | None = None
    contrast_band_floor_log_ratio: float | None = None
    contrast_band_peak_log_ratio: float | None = None
    boundary_bracket_fraction: float | None = None
    strict_boundary_bracket_fraction: float | None = None

    @property
    def bound_stuck(self) -> bool:
        return bool(self.at_bounds)


@dataclass(frozen=True)
class EffectiveFieldDiagnostics:
    """Evidence and input-support diagnostics for an effective-field estimate."""

    n_input_energy_bins: int
    n_energy_bins: int
    n_pitch_bins: int
    n_cells: int
    total_counts: int
    no_edge_delta_bic: float
    electrostatic_delta_bic: float
    profile_truncated: bool
    model_fits: tuple[EffectiveFieldModelFit, ...]
    contrast_band_delta_bic: float = float("nan")
    boundary_bracket_fraction: float | None = None
    strict_boundary_bracket_fraction: float | None = None
    edge_candidate_model: CandidateModel = "mirror_only"
    energy_ratio_step_supported: bool = False
    energy_ratio_step_center_eV: float | None = None
    energy_ratio_step_log_ratio: float | None = None
    energy_ratio_step_delta_bic: float = float("nan")
    energy_ratio_step_direction: Literal["up", "down"] | None = None
    edge_fit_log_ratio_residual_median_abs: float = float("nan")
    edge_fit_log_ratio_residual_p90_abs: float = float("nan")
    edge_fit_pitch_pattern_correlation: float = float("nan")
    edge_fit_pitch_pattern_nrmse: float = float("nan")
    edge_fit_standardized_residual_median_abs: float = float("nan")
    edge_fit_standardized_residual_p90_abs: float = float("nan")
    edge_fit_standardized_residual_inlier_fraction: float = float("nan")

    def fit(self, model: CandidateModel) -> EffectiveFieldModelFit:
        for candidate in self.model_fits:
            if candidate.model == model:
                return candidate
        raise KeyError(model)


@dataclass(frozen=True)
class EffectiveFieldEstimate:
    """Selected ER estimate with uncertainty and model-selection diagnostics."""

    success: bool
    reason: str
    selected_model: CandidateModel
    edge_supported: bool
    mirror_ratio: float | None
    mirror_ratio_ci95: tuple[float, float] | None
    effective_field_nT: float | None
    effective_field_ci95_nT: tuple[float, float] | None
    delta_u_eff_eV: float | None
    sigma_ln_b: float | None
    diagnostics: EffectiveFieldDiagnostics
    quality_grade: FitQualityGrade = "reject"
    quality_reasons: tuple[str, ...] = ()

    def to_record(self) -> dict[str, object]:
        """Return a flat record suitable for a feature catalog."""

        ci_ratio = self.mirror_ratio_ci95 or (None, None)
        ci_field = self.effective_field_ci95_nT or (None, None)
        chosen = self.diagnostics.fit(self.selected_model)
        edge_candidate = self.diagnostics.fit(self.diagnostics.edge_candidate_model)
        return {
            "success": self.success,
            "reason": self.reason,
            "selected_model": self.selected_model,
            "edge_supported": self.edge_supported,
            "mirror_ratio": self.mirror_ratio,
            "mirror_ratio_ci95_low": ci_ratio[0],
            "mirror_ratio_ci95_high": ci_ratio[1],
            "effective_field": self.effective_field_nT,
            "effective_field_ci95_low": ci_field[0],
            "effective_field_ci95_high": ci_field[1],
            "delta_u_eff": self.delta_u_eff_eV,
            "sigma_ln_b": self.sigma_ln_b,
            "log_likelihood": chosen.log_likelihood,
            "bic": chosen.bic,
            "no_edge_delta_bic": self.diagnostics.no_edge_delta_bic,
            "electrostatic_delta_bic": self.diagnostics.electrostatic_delta_bic,
            "contrast_band_delta_bic": self.diagnostics.contrast_band_delta_bic,
            "contrast_model": chosen.contrast_model,
            "contrast_band_center": chosen.contrast_band_center_eV,
            "contrast_band_width_ln": chosen.contrast_band_width_ln,
            "contrast_band_floor_log_ratio": (chosen.contrast_band_floor_log_ratio),
            "contrast_band_peak_log_ratio": chosen.contrast_band_peak_log_ratio,
            "edge_candidate_model": self.diagnostics.edge_candidate_model,
            "edge_candidate_contrast_model": edge_candidate.contrast_model,
            "boundary_bracket_fraction": (self.diagnostics.boundary_bracket_fraction),
            "strict_boundary_bracket_fraction": (self.diagnostics.strict_boundary_bracket_fraction),
            "energy_ratio_step_supported": (self.diagnostics.energy_ratio_step_supported),
            "energy_ratio_step_center": (self.diagnostics.energy_ratio_step_center_eV),
            "energy_ratio_step_log_ratio": (self.diagnostics.energy_ratio_step_log_ratio),
            "energy_ratio_step_delta_bic": (self.diagnostics.energy_ratio_step_delta_bic),
            "energy_ratio_step_direction": (self.diagnostics.energy_ratio_step_direction),
            "n_energy_bins": self.diagnostics.n_energy_bins,
            "n_cells": self.diagnostics.n_cells,
            "total_counts": self.diagnostics.total_counts,
            "bound_stuck": edge_candidate.bound_stuck,
            "at_bounds": ",".join(edge_candidate.at_bounds),
            "profile_truncated": self.diagnostics.profile_truncated,
            "quality_grade": self.quality_grade,
            "quality_reasons": ",".join(self.quality_reasons),
            "edge_fit_log_ratio_residual_median_abs": (
                self.diagnostics.edge_fit_log_ratio_residual_median_abs
            ),
            "edge_fit_log_ratio_residual_p90_abs": (
                self.diagnostics.edge_fit_log_ratio_residual_p90_abs
            ),
            "edge_fit_pitch_pattern_correlation": (
                self.diagnostics.edge_fit_pitch_pattern_correlation
            ),
            "edge_fit_pitch_pattern_nrmse": (self.diagnostics.edge_fit_pitch_pattern_nrmse),
            "edge_fit_standardized_residual_median_abs": (
                self.diagnostics.edge_fit_standardized_residual_median_abs
            ),
            "edge_fit_standardized_residual_p90_abs": (
                self.diagnostics.edge_fit_standardized_residual_p90_abs
            ),
            "edge_fit_standardized_residual_inlier_fraction": (
                self.diagnostics.edge_fit_standardized_residual_inlier_fraction
            ),
        }


@dataclass(frozen=True)
class _PreparedCounts:
    energy_eV: FloatArray
    pitch_deg: FloatArray
    affected_counts: FloatArray
    reference_counts: FloatArray
    affected_exposure: FloatArray
    reference_exposure: FloatArray
    valid: NDArray[np.bool_]
    input_energy_bins: int
    total_counts: int
    spacecraft_potential_eV: float

    @property
    def n_energy(self) -> int:
        return int(self.energy_eV.size)

    @property
    def n_pitch(self) -> int:
        return int(self.pitch_deg.size)

    @property
    def n_cells(self) -> int:
        return int(np.count_nonzero(self.valid))


@dataclass(frozen=True)
class _ParameterLayout:
    model: CandidateModel
    contrast_model: ResolvedContrastModel
    n_energy: int
    log_mirror: int | None
    delta_u: int | None
    log_sigma: int | None
    baseline: slice
    amplitude: slice | None
    log_concentration: int

    @property
    def size(self) -> int:
        return self.log_concentration + 1


@dataclass(frozen=True)
class _EnergyRatioStepFit:
    supported: bool
    center_eV: float | None
    step_log_ratio: float | None
    delta_bic: float
    direction: Literal["up", "down"] | None


@dataclass(frozen=True)
class _PredictiveDiagnostics:
    log_ratio_residual_median_abs: float = float("nan")
    log_ratio_residual_p90_abs: float = float("nan")
    pitch_pattern_correlation: float = float("nan")
    pitch_pattern_nrmse: float = float("nan")
    standardized_residual_median_abs: float = float("nan")
    standardized_residual_p90_abs: float = float("nan")
    standardized_residual_inlier_fraction: float = float("nan")


def mirror_boundary_sin2(
    energy_eV: ArrayLike,
    mirror_ratio: float,
    delta_u_eff_eV: float = 0.0,
    *,
    spacecraft_potential_eV: float = 0.0,
) -> FloatArray:
    """Return the modeled loss-cone boundary ``sin^2(alpha_c)``.

    The sign convention is ``surface minus spacecraft``: positive
    ``delta_u_eff_eV`` expands the low-energy loss cone. It is an effective
    curvature parameter, not an assertion that a physical surface potential
    has been identified.
    """

    energy = _float_array(energy_eV)
    corrected = energy - float(spacecraft_potential_eV)
    with np.errstate(divide="ignore", invalid="ignore"):
        boundary = (1.0 + float(delta_u_eff_eV) / corrected) / float(mirror_ratio)
    valid = (
        np.isfinite(corrected)
        & (corrected > 0.0)
        & np.isfinite(boundary)
        & (float(mirror_ratio) > 0.0)
    )
    return cast(FloatArray, np.where(valid, boundary, np.nan))


def mirror_transmission_probability(
    pitch_deg: ArrayLike,
    energy_eV: ArrayLike,
    mirror_ratio: float,
    sigma_ln_b: float,
    *,
    delta_u_eff_eV: float = 0.0,
    spacecraft_potential_eV: float = 0.0,
) -> FloatArray:
    """Return the smooth mirror transmission surface on energy x pitch."""

    from scipy.special import ndtr  # type: ignore[import-untyped]

    pitch = _float_array(pitch_deg)
    energy = _float_array(energy_eV)
    if pitch.ndim != 1 or energy.ndim != 1:
        raise ValueError("pitch_deg and energy_eV must be one-dimensional")
    if not np.isfinite(sigma_ln_b) or sigma_ln_b <= 0.0:
        raise ValueError("sigma_ln_b must be finite and positive")
    boundary = mirror_boundary_sin2(
        energy,
        mirror_ratio,
        delta_u_eff_eV,
        spacecraft_potential_eV=spacecraft_potential_eV,
    )
    sin2_pitch = np.clip(np.sin(np.deg2rad(pitch)) ** 2, 1.0e-12, 1.0 - 1.0e-12)
    with np.errstate(divide="ignore", invalid="ignore"):
        log_boundary = np.where(boundary > 0.0, np.log(boundary), -np.inf)
        z = (np.log(sin2_pitch)[None, :] - log_boundary[:, None]) / float(sigma_ln_b)
    probability = ndtr(z)
    valid = np.isfinite(boundary)[:, None]
    return cast(FloatArray, np.where(valid, probability, np.nan))


def fit_effective_field(
    counts: ElectronReflectionCounts,
    *,
    settings: EffectiveFieldFitSettings | None = None,
) -> EffectiveFieldEstimate:
    """Fit nested count-likelihood models and select the supported ER estimate."""

    settings = settings or EffectiveFieldFitSettings()
    prepared = _prepare_counts(counts, settings)
    if prepared.n_energy < settings.min_energy_bins:
        return _failed_estimate(
            prepared,
            reason="insufficient_energy_support",
        )
    if prepared.total_counts < settings.min_total_counts:
        return _failed_estimate(
            prepared,
            reason="insufficient_total_counts",
        )

    no_edge = _fit_candidate(
        prepared,
        "no_edge",
        settings,
        contrast_model="none",
    )
    mirror, contrast_band_delta = _fit_mirror_candidate(prepared, settings)
    electrostatic = _fit_candidate(
        prepared,
        "electrostatic",
        settings,
        contrast_model=mirror.contrast_model,
    )
    no_edge_delta = _bic_improvement(no_edge, mirror)
    electrostatic_delta = _bic_improvement(mirror, electrostatic)

    selected = no_edge
    reason = "no_edge_evidence"
    edge_evidence = bool(mirror.success and no_edge_delta >= settings.min_edge_delta_bic)
    tentative = mirror
    if edge_evidence:
        if electrostatic.success and electrostatic_delta >= settings.min_electrostatic_delta_bic:
            tentative = electrostatic
        quality_reason = _edge_quality_reason(tentative, settings)
        if quality_reason is None:
            selected = tentative
            reason = (
                "electrostatic_curvature_supported"
                if selected.model == "electrostatic"
                else "mirror_edge_supported"
            )
        elif tentative.model == "electrostatic":
            mirror_quality_reason = _edge_quality_reason(mirror, settings)
            if mirror_quality_reason is None:
                selected = mirror
                reason = "mirror_edge_supported"
            else:
                reason = quality_reason
        else:
            reason = quality_reason

    edge_supported = selected.model != "no_edge"
    diagnostic_edge_fit = selected if edge_supported else tentative

    profile_ci: tuple[float, float] | None = None
    profile_truncated = False
    if settings.profile_likelihood and selected.mirror_ratio is not None:
        profile_ci, profile_truncated = _profile_mirror_ratio(
            prepared,
            selected,
            settings,
        )

    mirror_ratio = selected.mirror_ratio if edge_supported else None
    effective_field = None if mirror_ratio is None else float(counts.b_sc_nT * mirror_ratio)
    effective_ci = (
        None
        if profile_ci is None
        else (
            float(counts.b_sc_nT * profile_ci[0]),
            float(counts.b_sc_nT * profile_ci[1]),
        )
    )
    energy_ratio_step = _fit_energy_ratio_step(
        prepared.energy_eV,
        selected.baseline_log_ratio,
        settings,
    )
    predictive = _predictive_diagnostics(
        prepared,
        diagnostic_edge_fit,
        sigma=settings.quality.standardized_residual_sigma,
    )
    quality_grade, quality_reasons = _fit_quality(
        edge_supported=edge_supported,
        selection_reason=reason,
        predictive=predictive,
        settings=settings.quality,
    )
    diagnostics = EffectiveFieldDiagnostics(
        n_input_energy_bins=prepared.input_energy_bins,
        n_energy_bins=prepared.n_energy,
        n_pitch_bins=prepared.n_pitch,
        n_cells=prepared.n_cells,
        total_counts=prepared.total_counts,
        no_edge_delta_bic=no_edge_delta,
        electrostatic_delta_bic=electrostatic_delta,
        profile_truncated=profile_truncated,
        model_fits=(no_edge, mirror, electrostatic),
        contrast_band_delta_bic=contrast_band_delta,
        boundary_bracket_fraction=diagnostic_edge_fit.boundary_bracket_fraction,
        strict_boundary_bracket_fraction=(diagnostic_edge_fit.strict_boundary_bracket_fraction),
        edge_candidate_model=diagnostic_edge_fit.model,
        energy_ratio_step_supported=energy_ratio_step.supported,
        energy_ratio_step_center_eV=energy_ratio_step.center_eV,
        energy_ratio_step_log_ratio=energy_ratio_step.step_log_ratio,
        energy_ratio_step_delta_bic=energy_ratio_step.delta_bic,
        energy_ratio_step_direction=energy_ratio_step.direction,
        edge_fit_log_ratio_residual_median_abs=(predictive.log_ratio_residual_median_abs),
        edge_fit_log_ratio_residual_p90_abs=(predictive.log_ratio_residual_p90_abs),
        edge_fit_pitch_pattern_correlation=predictive.pitch_pattern_correlation,
        edge_fit_pitch_pattern_nrmse=predictive.pitch_pattern_nrmse,
        edge_fit_standardized_residual_median_abs=(predictive.standardized_residual_median_abs),
        edge_fit_standardized_residual_p90_abs=(predictive.standardized_residual_p90_abs),
        edge_fit_standardized_residual_inlier_fraction=(
            predictive.standardized_residual_inlier_fraction
        ),
    )
    return EffectiveFieldEstimate(
        success=selected.success,
        reason=reason if selected.success else selected.reason,
        selected_model=selected.model,
        edge_supported=edge_supported,
        mirror_ratio=mirror_ratio,
        mirror_ratio_ci95=profile_ci if edge_supported else None,
        effective_field_nT=effective_field,
        effective_field_ci95_nT=effective_ci if edge_supported else None,
        delta_u_eff_eV=(selected.delta_u_eff_eV if selected.model == "electrostatic" else None),
        sigma_ln_b=selected.sigma_ln_b if edge_supported else None,
        diagnostics=diagnostics,
        quality_grade=quality_grade,
        quality_reasons=quality_reasons,
    )


def simulate_electron_reflection_counts(
    *,
    energy_eV: ArrayLike,
    pitch_deg: ArrayLike,
    b_sc_nT: float,
    mirror_ratio: float | None,
    delta_u_eff_eV: float = 0.0,
    spacecraft_potential_eV: float = 0.0,
    sigma_ln_b: float = 0.2,
    reference_counts: float = 500.0,
    inside_ratio: float = 0.12,
    outside_ratio: float = 1.0,
    concentration: float = 150.0,
    affected_exposure: ArrayLike | float = 1.0,
    reference_exposure: ArrayLike | float = 1.0,
    random_seed: int | None = None,
) -> ElectronReflectionCounts:
    """Generate beta-binomial paired counts for recovery and injection tests."""

    if reference_counts <= 0.0:
        raise ValueError("reference_counts must be positive")
    if not 0.0 < inside_ratio <= outside_ratio:
        raise ValueError("ratios must satisfy 0 < inside_ratio <= outside_ratio")
    if concentration <= 0.0:
        raise ValueError("concentration must be positive")
    energy = _float_array(energy_eV)
    pitch = _float_array(pitch_deg)
    shape = (energy.size, pitch.size)
    exposure_a = _broadcast_positive(affected_exposure, shape, name="affected_exposure")
    exposure_r = _broadcast_positive(reference_exposure, shape, name="reference_exposure")
    if mirror_ratio is None:
        ratio = np.full(shape, outside_ratio, dtype=float)
    else:
        transition = mirror_transmission_probability(
            pitch,
            energy,
            mirror_ratio,
            sigma_ln_b,
            delta_u_eff_eV=delta_u_eff_eV,
            spacecraft_potential_eV=spacecraft_potential_eV,
        )
        if not np.all(np.isfinite(transition)):
            raise ValueError("simulation parameters produce an out-of-domain loss-cone boundary")
        log_inside = log(inside_ratio)
        log_outside = log(outside_ratio)
        ratio = np.exp(log_inside + (log_outside - log_inside) * transition)
    logit_mean = np.log(ratio) + np.log(exposure_a) - np.log(exposure_r)
    mean = _expit(logit_mean)
    rng = np.random.default_rng(random_seed)
    total_mean = reference_counts * (1.0 + ratio * exposure_a / exposure_r)
    total = rng.poisson(total_mean).astype(np.int64)
    beta_probability = rng.beta(mean * concentration, (1.0 - mean) * concentration)
    affected = rng.binomial(total, beta_probability).astype(float)
    reference = (total - affected).astype(float)
    return ElectronReflectionCounts(
        energy_eV=energy,
        pitch_deg=pitch,
        affected_counts=affected,
        reference_counts=reference,
        b_sc_nT=b_sc_nT,
        affected_exposure=exposure_a,
        reference_exposure=exposure_r,
        metadata={
            "simulation": True,
            "mirror_ratio": mirror_ratio,
            "delta_u_eff_eV": delta_u_eff_eV,
            "spacecraft_potential_eV": spacecraft_potential_eV,
            "sigma_ln_b": sigma_ln_b,
            "concentration": concentration,
        },
    )


def _prepare_counts(
    counts: ElectronReflectionCounts,
    settings: EffectiveFieldFitSettings,
) -> _PreparedCounts:
    affected = cast(FloatArray, counts.affected_counts)
    reference = cast(FloatArray, counts.reference_counts)
    exposure_a = cast(FloatArray, counts.affected_exposure)
    exposure_r = cast(FloatArray, counts.reference_exposure)
    valid = (
        np.isfinite(affected)
        & np.isfinite(reference)
        & np.isfinite(exposure_a)
        & np.isfinite(exposure_r)
    )
    corrected_energy = cast(FloatArray, counts.energy_eV) - settings.spacecraft_potential_eV
    supported_rows = (np.count_nonzero(valid, axis=1) >= settings.min_pitch_bins_per_energy) & (
        corrected_energy > 0.0
    )
    energy = cast(FloatArray, counts.energy_eV)[supported_rows]
    affected = affected[supported_rows]
    reference = reference[supported_rows]
    exposure_a = exposure_a[supported_rows]
    exposure_r = exposure_r[supported_rows]
    valid = valid[supported_rows]
    total_counts = int(np.rint(np.sum((affected + reference)[valid])))
    return _PreparedCounts(
        energy_eV=energy,
        pitch_deg=cast(FloatArray, counts.pitch_deg),
        affected_counts=affected,
        reference_counts=reference,
        affected_exposure=exposure_a,
        reference_exposure=exposure_r,
        valid=valid,
        input_energy_bins=int(np.asarray(counts.energy_eV).size),
        total_counts=total_counts,
        spacecraft_potential_eV=settings.spacecraft_potential_eV,
    )


def _fit_mirror_candidate(
    data: _PreparedCounts,
    settings: EffectiveFieldFitSettings,
) -> tuple[EffectiveFieldModelFit, float]:
    if settings.contrast_model != "auto":
        contrast_model = cast(ResolvedContrastModel, settings.contrast_model)
        return (
            _fit_candidate(
                data,
                "mirror_only",
                settings,
                contrast_model=contrast_model,
            ),
            float("nan"),
        )

    constant = _fit_candidate(
        data,
        "mirror_only",
        settings,
        contrast_model="constant",
    )
    band = _fit_candidate(
        data,
        "mirror_only",
        settings,
        contrast_model="band",
    )
    band_delta = _bic_improvement(constant, band)
    band_resolved = band.success and not _contrast_band_parameters_at_bounds(band)
    if band_resolved and (
        not constant.success or band_delta >= settings.min_contrast_band_delta_bic
    ):
        return band, band_delta
    return constant, band_delta


def _fit_candidate(
    data: _PreparedCounts,
    model: CandidateModel,
    settings: EffectiveFieldFitSettings,
    *,
    contrast_model: ResolvedContrastModel,
    fixed_log_mirror: float | None = None,
) -> EffectiveFieldModelFit:
    from scipy.optimize import minimize  # type: ignore[import-untyped]

    layout = _parameter_layout(model, data.n_energy, contrast_model)
    initial, bounds = _initial_parameters(data, layout, settings)
    if fixed_log_mirror is not None:
        if layout.log_mirror is None:
            raise ValueError("fixed_log_mirror requires an edge model")
        initial[layout.log_mirror] = fixed_log_mirror
        bounds[layout.log_mirror] = (fixed_log_mirror, fixed_log_mirror)

    best_result = None
    best_value = np.inf
    starts = _optimizer_starts(initial, bounds, layout, settings)
    if fixed_log_mirror is not None:
        starts = starts[:1]
    for start in starts:
        warmed_start = start
        if layout.model != "no_edge" and layout.contrast_model != "free":
            warm_bounds = list(bounds)
            for index in (layout.log_mirror, layout.delta_u, layout.log_sigma):
                if index is not None:
                    warm_bounds[index] = (float(start[index]), float(start[index]))
            warm_result = minimize(
                _negative_log_likelihood_and_gradient,
                start,
                args=(data, layout),
                method="L-BFGS-B",
                jac=True,
                bounds=warm_bounds,
                options={
                    "maxiter": min(settings.max_iterations, 1200),
                    "ftol": 1.0e-10,
                },
            )
            if np.isfinite(warm_result.fun):
                warmed_start = np.asarray(warm_result.x, dtype=float)
        result = minimize(
            _negative_log_likelihood_and_gradient,
            warmed_start,
            args=(data, layout),
            method="L-BFGS-B",
            jac=True,
            bounds=bounds,
            options={"maxiter": settings.max_iterations, "ftol": 1.0e-10},
        )
        value = float(result.fun)
        if np.isfinite(value) and value < best_value:
            best_result = result
            best_value = value
    if best_result is None:
        return _empty_model_fit(
            model,
            data.n_cells,
            layout.size,
            "optimizer_failed",
            contrast_model=contrast_model,
        )

    vector = np.asarray(best_result.x, dtype=float)
    log_likelihood = -best_value
    bic = float(layout.size * np.log(max(data.n_cells, 1)) - 2.0 * log_likelihood)
    mirror_ratio, delta_u, sigma, baseline, amplitude, concentration = _unpack(
        vector,
        layout,
        data.energy_eV,
    )
    at_bounds = _parameters_at_bounds(vector, bounds, layout)
    success = bool(np.isfinite(log_likelihood) and _physical_candidate(data, mirror_ratio, delta_u))
    reason = "ok" if success else "non_physical_or_nonfinite_fit"
    band_center, band_width, band_floor, band_peak = _contrast_band_parameters(
        vector,
        layout,
    )
    bracket_fraction, strict_bracket_fraction = _boundary_support(
        data,
        mirror_ratio,
        delta_u,
        min_transition_energy_bins=settings.min_energy_bins,
    )
    return EffectiveFieldModelFit(
        model=model,
        success=success,
        reason=reason,
        mirror_ratio=mirror_ratio,
        delta_u_eff_eV=delta_u,
        sigma_ln_b=sigma,
        baseline_log_ratio=tuple(float(value) for value in baseline),
        amplitude_log_ratio=tuple(float(value) for value in amplitude),
        concentration=concentration,
        log_likelihood=log_likelihood,
        bic=bic,
        n_parameters=layout.size,
        n_cells=data.n_cells,
        at_bounds=at_bounds,
        contrast_model=contrast_model,
        contrast_band_center_eV=band_center,
        contrast_band_width_ln=band_width,
        contrast_band_floor_log_ratio=band_floor,
        contrast_band_peak_log_ratio=band_peak,
        boundary_bracket_fraction=bracket_fraction,
        strict_boundary_bracket_fraction=strict_bracket_fraction,
    )


def _negative_log_likelihood(
    vector: FloatArray,
    data: _PreparedCounts,
    layout: _ParameterLayout,
) -> float:
    from scipy.special import betaln, gammaln

    mirror_ratio, delta_u, sigma, baseline, amplitude, concentration = _unpack(
        vector,
        layout,
        data.energy_eV,
    )
    if concentration is None or not np.isfinite(concentration):
        return 1.0e30
    if layout.model == "no_edge":
        log_ratio = np.broadcast_to(baseline[:, None], data.affected_counts.shape)
    else:
        if mirror_ratio is None or sigma is None:
            return 1.0e30
        transition = mirror_transmission_probability(
            data.pitch_deg,
            data.energy_eV,
            mirror_ratio,
            sigma,
            delta_u_eff_eV=delta_u or 0.0,
            spacecraft_potential_eV=data.spacecraft_potential_eV,
        )
        if not np.all(np.isfinite(transition[data.valid])):
            return 1.0e30
        log_ratio = baseline[:, None] + amplitude[:, None] * transition
    logit_mean = log_ratio + np.log(data.affected_exposure) - np.log(data.reference_exposure)
    mean = np.clip(_expit(logit_mean), 1.0e-10, 1.0 - 1.0e-10)
    affected = data.affected_counts[data.valid]
    reference = data.reference_counts[data.valid]
    total = affected + reference
    alpha = mean[data.valid] * concentration
    beta = (1.0 - mean[data.valid]) * concentration
    log_choose = gammaln(total + 1.0) - gammaln(affected + 1.0) - gammaln(reference + 1.0)
    values = log_choose + betaln(affected + alpha, reference + beta) - betaln(alpha, beta)
    if not np.all(np.isfinite(values)):
        return 1.0e30
    return float(-np.sum(values))


def _negative_log_likelihood_and_gradient(
    vector: FloatArray,
    data: _PreparedCounts,
    layout: _ParameterLayout,
) -> tuple[float, FloatArray]:
    from scipy.special import betaln, digamma, gammaln, ndtr

    mirror_ratio, delta_u, sigma, baseline, amplitude, concentration = _unpack(
        vector,
        layout,
        data.energy_eV,
    )
    zero_gradient = np.zeros(layout.size, dtype=float)
    if concentration is None or not np.isfinite(concentration):
        return 1.0e30, zero_gradient

    transition: FloatArray | None = None
    z: FloatArray | None = None
    if layout.model == "no_edge":
        log_ratio = np.broadcast_to(baseline[:, None], data.affected_counts.shape)
    else:
        if mirror_ratio is None or sigma is None:
            return 1.0e30, zero_gradient
        boundary = mirror_boundary_sin2(
            data.energy_eV,
            mirror_ratio,
            delta_u or 0.0,
            spacecraft_potential_eV=data.spacecraft_potential_eV,
        )
        sin2_pitch = np.clip(
            np.sin(np.deg2rad(data.pitch_deg)) ** 2,
            1.0e-12,
            1.0 - 1.0e-12,
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            log_boundary = np.where(boundary > 0.0, np.log(boundary), -np.inf)
            z = (np.log(sin2_pitch)[None, :] - log_boundary[:, None]) / sigma
        transition = cast(FloatArray, ndtr(z))
        valid_boundary = np.isfinite(boundary)[:, None]
        transition = cast(
            FloatArray,
            np.where(valid_boundary, transition, np.nan),
        )
        if not np.all(np.isfinite(transition[data.valid])):
            return 1.0e30, zero_gradient
        log_ratio = baseline[:, None] + amplitude[:, None] * transition

    logit_mean = log_ratio + np.log(data.affected_exposure) - np.log(data.reference_exposure)
    mean = np.clip(_expit(logit_mean), 1.0e-10, 1.0 - 1.0e-10)
    affected = data.affected_counts[data.valid]
    reference = data.reference_counts[data.valid]
    total = affected + reference
    probability = mean[data.valid]
    alpha = probability * concentration
    beta = (1.0 - probability) * concentration
    log_choose = gammaln(total + 1.0) - gammaln(affected + 1.0) - gammaln(reference + 1.0)
    values = log_choose + betaln(affected + alpha, reference + beta) - betaln(alpha, beta)
    if not np.all(np.isfinite(values)):
        return 1.0e30, zero_gradient

    score_alpha = (
        digamma(affected + alpha)
        - digamma(total + concentration)
        - digamma(alpha)
        + digamma(concentration)
    )
    score_beta = (
        digamma(reference + beta)
        - digamma(total + concentration)
        - digamma(beta)
        + digamma(concentration)
    )
    score_eta_values = (
        concentration * (score_alpha - score_beta) * probability * (1.0 - probability)
    )
    score_eta = np.zeros(data.affected_counts.shape, dtype=float)
    score_eta[data.valid] = score_eta_values
    gradient = np.zeros(layout.size, dtype=float)

    gradient[layout.baseline] = np.sum(score_eta, axis=1)
    if transition is not None and layout.amplitude is not None:
        amplitude_score = np.sum(score_eta * transition, axis=1)
        if layout.contrast_model == "free":
            gradient[layout.amplitude] = amplitude_score
        elif layout.contrast_model == "constant":
            gradient[layout.amplitude.start] = float(np.sum(amplitude_score))
        else:
            raw = np.asarray(vector[layout.amplitude], dtype=float)
            floor, excess, log_center, log_width = (float(value) for value in raw)
            _ = floor
            width = exp(log_width)
            distance = np.log(data.energy_eV) - log_center
            gaussian = np.exp(-0.5 * (distance / width) ** 2)
            gradient[layout.amplitude.start] = float(np.sum(amplitude_score))
            gradient[layout.amplitude.start + 1] = float(np.sum(amplitude_score * gaussian))
            gradient[layout.amplitude.start + 2] = float(
                np.sum(amplitude_score * excess * gaussian * distance / (width**2))
            )
            gradient[layout.amplitude.start + 3] = float(
                np.sum(amplitude_score * excess * gaussian * (distance / width) ** 2)
            )

        assert z is not None
        assert sigma is not None
        normal_density = np.exp(-0.5 * z**2) / np.sqrt(2.0 * np.pi)
        transition_score = score_eta * amplitude[:, None] * normal_density
        if layout.log_mirror is not None:
            gradient[layout.log_mirror] = float(np.sum(transition_score / sigma))
        if layout.delta_u is not None:
            corrected = data.energy_eV - data.spacecraft_potential_eV
            corrected_with_potential = corrected + float(delta_u or 0.0)
            inverse_denominator = np.divide(
                -1.0,
                sigma * corrected_with_potential,
                out=np.zeros_like(corrected_with_potential),
                where=corrected_with_potential > 0.0,
            )
            gradient[layout.delta_u] = float(
                np.sum(transition_score * inverse_denominator[:, None])
            )
        if layout.log_sigma is not None:
            sigma_score = np.where(np.isfinite(z), -z, 0.0)
            gradient[layout.log_sigma] = float(np.sum(transition_score * sigma_score))

    gradient[layout.log_concentration] = float(
        np.sum(concentration * (probability * score_alpha + (1.0 - probability) * score_beta))
    )
    if not np.all(np.isfinite(gradient)):
        return 1.0e30, zero_gradient
    return float(-np.sum(values)), cast(FloatArray, -gradient)


def _predictive_diagnostics(
    data: _PreparedCounts,
    fit: EffectiveFieldModelFit,
    *,
    sigma: float,
) -> _PredictiveDiagnostics:
    log_ratio = _fitted_log_ratio(data, fit)
    if log_ratio is None or fit.concentration is None:
        return _PredictiveDiagnostics()

    observed_log_ratio = np.log(
        (data.affected_counts + 0.5) / (data.reference_counts + 0.5)
    ) - np.log(data.affected_exposure / data.reference_exposure)
    valid = data.valid & np.isfinite(observed_log_ratio) & np.isfinite(log_ratio)
    if not np.any(valid):
        return _PredictiveDiagnostics()
    log_residual = observed_log_ratio - log_ratio
    absolute_log_residual = np.abs(log_residual[valid])

    observed_centered: list[float] = []
    fitted_centered: list[float] = []
    for energy_index in range(data.n_energy):
        row_valid = valid[energy_index]
        if np.count_nonzero(row_valid) < 3:
            continue
        observed_row = observed_log_ratio[energy_index, row_valid]
        fitted_row = log_ratio[energy_index, row_valid]
        observed_centered.extend((observed_row - float(np.mean(observed_row))).tolist())
        fitted_centered.extend((fitted_row - float(np.mean(fitted_row))).tolist())
    observed_pattern = np.asarray(observed_centered, dtype=float)
    fitted_pattern = np.asarray(fitted_centered, dtype=float)
    pattern_correlation = float("nan")
    pattern_nrmse = float("nan")
    if observed_pattern.size >= 3:
        observed_scale = float(np.std(observed_pattern))
        fitted_scale = float(np.std(fitted_pattern))
        if observed_scale > 0.0:
            pattern_nrmse = float(
                np.sqrt(np.mean((observed_pattern - fitted_pattern) ** 2)) / observed_scale
            )
            if fitted_scale > 0.0:
                pattern_correlation = float(np.corrcoef(observed_pattern, fitted_pattern)[0, 1])

    logit_mean = log_ratio + np.log(data.affected_exposure) - np.log(data.reference_exposure)
    mean = np.clip(_expit(logit_mean), 1.0e-10, 1.0 - 1.0e-10)
    total = data.affected_counts + data.reference_counts
    concentration = float(fit.concentration)
    variance = total * mean * (1.0 - mean) * (total + concentration) / (1.0 + concentration)
    standardized_valid = valid & np.isfinite(variance) & (variance > 0.0)
    if np.any(standardized_valid):
        standardized = (
            data.affected_counts[standardized_valid]
            - total[standardized_valid] * mean[standardized_valid]
        ) / np.sqrt(variance[standardized_valid])
        absolute_standardized = np.abs(standardized)
        standardized_median = float(np.median(absolute_standardized))
        standardized_p90 = float(np.percentile(absolute_standardized, 90.0))
        standardized_inlier_fraction = float(np.mean(absolute_standardized <= sigma))
    else:
        standardized_median = float("nan")
        standardized_p90 = float("nan")
        standardized_inlier_fraction = float("nan")

    return _PredictiveDiagnostics(
        log_ratio_residual_median_abs=float(np.median(absolute_log_residual)),
        log_ratio_residual_p90_abs=float(np.percentile(absolute_log_residual, 90.0)),
        pitch_pattern_correlation=pattern_correlation,
        pitch_pattern_nrmse=pattern_nrmse,
        standardized_residual_median_abs=standardized_median,
        standardized_residual_p90_abs=standardized_p90,
        standardized_residual_inlier_fraction=standardized_inlier_fraction,
    )


def _fitted_log_ratio(
    data: _PreparedCounts,
    fit: EffectiveFieldModelFit,
) -> FloatArray | None:
    baseline = np.asarray(fit.baseline_log_ratio, dtype=float)
    if baseline.shape != (data.n_energy,):
        return None
    if fit.model == "no_edge":
        return np.broadcast_to(baseline[:, None], data.affected_counts.shape)
    amplitude = np.asarray(fit.amplitude_log_ratio, dtype=float)
    if amplitude.shape != (data.n_energy,) or fit.mirror_ratio is None or fit.sigma_ln_b is None:
        return None
    transition = mirror_transmission_probability(
        data.pitch_deg,
        data.energy_eV,
        fit.mirror_ratio,
        fit.sigma_ln_b,
        delta_u_eff_eV=fit.delta_u_eff_eV or 0.0,
        spacecraft_potential_eV=data.spacecraft_potential_eV,
    )
    if not np.all(np.isfinite(transition[data.valid])):
        return None
    return cast(FloatArray, baseline[:, None] + amplitude[:, None] * transition)


def _fit_quality(
    *,
    edge_supported: bool,
    selection_reason: str,
    predictive: _PredictiveDiagnostics,
    settings: EffectiveFieldQualitySettings,
) -> tuple[FitQualityGrade, tuple[str, ...]]:
    if not edge_supported:
        return "reject", (selection_reason,)

    values = (
        predictive.log_ratio_residual_p90_abs,
        predictive.pitch_pattern_correlation,
        predictive.pitch_pattern_nrmse,
        predictive.standardized_residual_inlier_fraction,
    )
    if not all(np.isfinite(value) for value in values):
        return "poor", ("predictive_diagnostics_unavailable",)

    good = (
        predictive.log_ratio_residual_p90_abs <= settings.good_log_ratio_residual_p90
        and predictive.pitch_pattern_correlation >= settings.good_pitch_pattern_correlation
        and predictive.pitch_pattern_nrmse <= settings.good_pitch_pattern_nrmse
        and predictive.standardized_residual_inlier_fraction
        >= settings.good_standardized_inlier_fraction
    )
    review = (
        predictive.log_ratio_residual_p90_abs <= settings.review_log_ratio_residual_p90
        and predictive.pitch_pattern_correlation >= settings.review_pitch_pattern_correlation
        and predictive.pitch_pattern_nrmse <= settings.review_pitch_pattern_nrmse
        and predictive.standardized_residual_inlier_fraction
        >= settings.review_standardized_inlier_fraction
    )
    reasons: list[str] = []
    if predictive.log_ratio_residual_p90_abs > settings.good_log_ratio_residual_p90:
        reasons.append("log_ratio_residual_tail")
    if predictive.pitch_pattern_correlation < settings.good_pitch_pattern_correlation:
        reasons.append("weak_pitch_pattern_agreement")
    if predictive.pitch_pattern_nrmse > settings.good_pitch_pattern_nrmse:
        reasons.append("large_pitch_pattern_error")
    if (
        predictive.standardized_residual_inlier_fraction
        < settings.good_standardized_inlier_fraction
    ):
        reasons.append("standardized_residual_outliers")
    return ("good" if good else "review" if review else "poor"), tuple(reasons)


def _parameter_layout(
    model: CandidateModel,
    n_energy: int,
    contrast_model: ResolvedContrastModel,
) -> _ParameterLayout:
    if model == "no_edge" and contrast_model != "none":
        raise ValueError("no_edge requires contrast_model='none'")
    if model != "no_edge" and contrast_model not in {"free", "constant", "band"}:
        raise ValueError("edge models require a free, constant, or band contrast")
    index = 0
    log_mirror = None
    delta_u = None
    log_sigma = None
    if model != "no_edge":
        log_mirror = index
        index += 1
        if model == "electrostatic":
            delta_u = index
            index += 1
        log_sigma = index
        index += 1
    baseline = slice(index, index + n_energy)
    index += n_energy
    amplitude = None
    if model != "no_edge":
        amplitude_size = {
            "free": n_energy,
            "constant": 1,
            "band": 4,
        }[contrast_model]
        amplitude = slice(index, index + amplitude_size)
        index += amplitude_size
    return _ParameterLayout(
        model=model,
        contrast_model=contrast_model,
        n_energy=n_energy,
        log_mirror=log_mirror,
        delta_u=delta_u,
        log_sigma=log_sigma,
        baseline=baseline,
        amplitude=amplitude,
        log_concentration=index,
    )


def _initial_parameters(
    data: _PreparedCounts,
    layout: _ParameterLayout,
    settings: EffectiveFieldFitSettings,
) -> tuple[FloatArray, list[tuple[float, float]]]:
    vector = np.zeros(layout.size, dtype=float)
    bounds: list[tuple[float, float]] = [(0.0, 0.0)] * layout.size
    observed = _observed_log_ratio(data)
    baseline = np.empty(data.n_energy, dtype=float)
    amplitude = np.empty(data.n_energy, dtype=float)
    edge_values: list[float] = []
    for index in range(data.n_energy):
        finite = data.valid[index] & np.isfinite(observed[index])
        values = observed[index, finite]
        if values.size:
            low = float(np.nanpercentile(values, 20.0))
            high = float(np.nanpercentile(values, 80.0))
            baseline[index] = low
            amplitude[index] = max(high - low, 0.15)
            target = 0.5 * (low + high)
            pitch_values = data.pitch_deg[finite]
            edge_pitch = float(pitch_values[np.argmin(np.abs(values - target))])
            edge_values.append(float(np.sin(np.deg2rad(edge_pitch)) ** 2))
        else:
            baseline[index] = 0.0
            amplitude[index] = 0.2
    baseline = np.clip(baseline, *settings.baseline_log_ratio_bounds)
    amplitude = np.clip(amplitude, *settings.amplitude_log_ratio_bounds)
    if layout.model == "no_edge":
        medians = np.array(
            [np.nanmedian(observed[index, data.valid[index]]) for index in range(data.n_energy)],
            dtype=float,
        )
        vector[layout.baseline] = np.clip(
            medians,
            *settings.baseline_log_ratio_bounds,
        )
    else:
        assert layout.log_mirror is not None
        assert layout.log_sigma is not None
        median_sin2 = float(np.nanmedian(edge_values)) if edge_values else 0.125
        initial_ratio = float(np.clip(1.0 / median_sin2, *settings.mirror_ratio_bounds))
        vector[layout.log_mirror] = log(initial_ratio)
        bounds[layout.log_mirror] = (
            log(settings.mirror_ratio_bounds[0]),
            log(settings.mirror_ratio_bounds[1]),
        )
        if layout.delta_u is not None:
            vector[layout.delta_u] = 0.0
            bounds[layout.delta_u] = settings.delta_u_bounds_eV
        vector[layout.log_sigma] = log(0.2)
        bounds[layout.log_sigma] = (
            log(settings.sigma_ln_b_bounds[0]),
            log(settings.sigma_ln_b_bounds[1]),
        )
        vector[layout.baseline] = baseline
        assert layout.amplitude is not None
        if layout.contrast_model == "free":
            vector[layout.amplitude] = amplitude
            for index in range(layout.amplitude.start, layout.amplitude.stop):
                bounds[index] = settings.amplitude_log_ratio_bounds
        elif layout.contrast_model == "constant":
            vector[layout.amplitude] = float(np.nanmedian(amplitude))
            bounds[layout.amplitude.start] = settings.amplitude_log_ratio_bounds
        else:
            floor = float(np.nanpercentile(amplitude, 10.0))
            peak = float(np.nanpercentile(amplitude, 90.0))
            excess_amplitude = max(peak - floor, 0.05)
            excess = np.clip(amplitude - floor, 0.0, None)
            log_energy = np.log(data.energy_eV)
            if float(np.sum(excess)) > 0.0:
                center = float(np.sum(log_energy * excess) / np.sum(excess))
                variance = float(np.sum((log_energy - center) ** 2 * excess) / np.sum(excess))
                width = float(np.sqrt(max(variance, 0.0)))
            else:
                center = float(np.mean(log_energy))
                width = 0.8
            width = float(np.clip(width, *settings.contrast_band_width_bounds_ln))
            vector[layout.amplitude] = (
                np.clip(floor, *settings.amplitude_log_ratio_bounds),
                np.clip(
                    excess_amplitude,
                    0.0,
                    settings.amplitude_log_ratio_bounds[1],
                ),
                np.clip(center, float(np.min(log_energy)), float(np.max(log_energy))),
                log(width),
            )
            bounds[layout.amplitude.start] = settings.amplitude_log_ratio_bounds
            bounds[layout.amplitude.start + 1] = (
                0.0,
                settings.amplitude_log_ratio_bounds[1],
            )
            bounds[layout.amplitude.start + 2] = (
                float(np.min(log_energy)),
                float(np.max(log_energy)),
            )
            bounds[layout.amplitude.start + 3] = (
                log(settings.contrast_band_width_bounds_ln[0]),
                log(settings.contrast_band_width_bounds_ln[1]),
            )
    for index in range(layout.baseline.start, layout.baseline.stop):
        bounds[index] = settings.baseline_log_ratio_bounds
    vector[layout.log_concentration] = log(100.0)
    bounds[layout.log_concentration] = (
        log(settings.concentration_bounds[0]),
        log(settings.concentration_bounds[1]),
    )
    return vector, bounds


def _optimizer_starts(
    initial: FloatArray,
    bounds: list[tuple[float, float]],
    layout: _ParameterLayout,
    settings: EffectiveFieldFitSettings,
) -> list[FloatArray]:
    starts = [initial.copy()]
    if layout.log_mirror is None:
        return starts
    log_ratios = [log(value) for value in (3.0, 8.0, 20.0, 60.0)]
    delta_values = (0.0, -50.0, 100.0, 250.0)
    if layout.delta_u is not None and settings.mirror_ratio_bounds[0] < 1.0:
        log_ratios[0] = log(0.8)
        delta_values = (-100.0, -50.0, 100.0, 250.0)
    band_center_fractions = (0.3, 0.5, 0.7)
    for index in range(settings.optimizer_starts - 1):
        candidate = initial.copy()
        lower, upper = bounds[layout.log_mirror]
        candidate[layout.log_mirror] = np.clip(log_ratios[index % len(log_ratios)], lower, upper)
        if layout.delta_u is not None:
            lower_delta, upper_delta = bounds[layout.delta_u]
            candidate[layout.delta_u] = np.clip(
                delta_values[index % len(delta_values)],
                lower_delta,
                upper_delta,
            )
        if layout.log_sigma is not None:
            candidate[layout.log_sigma] = log(0.12 if index % 2 == 0 else 0.4)
        if layout.contrast_model == "band" and layout.amplitude is not None:
            center_index = layout.amplitude.start + 2
            lower_center, upper_center = bounds[center_index]
            fraction = band_center_fractions[index % len(band_center_fractions)]
            candidate[center_index] = lower_center + fraction * (upper_center - lower_center)
        starts.append(candidate)
    return starts


def _unpack(
    vector: FloatArray,
    layout: _ParameterLayout,
    energy_eV: FloatArray,
) -> tuple[float | None, float | None, float | None, FloatArray, FloatArray, float]:
    mirror_ratio = None if layout.log_mirror is None else float(exp(vector[layout.log_mirror]))
    delta_u = None if layout.delta_u is None else float(vector[layout.delta_u])
    sigma = None if layout.log_sigma is None else float(exp(vector[layout.log_sigma]))
    baseline = np.asarray(vector[layout.baseline], dtype=float)
    amplitude = _amplitude_by_energy(vector, layout, energy_eV)
    concentration = float(exp(vector[layout.log_concentration]))
    return mirror_ratio, delta_u, sigma, baseline, amplitude, concentration


def _amplitude_by_energy(
    vector: FloatArray,
    layout: _ParameterLayout,
    energy_eV: FloatArray,
) -> FloatArray:
    if layout.amplitude is None:
        return np.array([], dtype=float)
    raw = np.asarray(vector[layout.amplitude], dtype=float)
    if layout.contrast_model == "free":
        return raw
    if layout.contrast_model == "constant":
        return np.full(energy_eV.size, float(raw[0]), dtype=float)
    floor, excess, log_center, log_width = (float(value) for value in raw)
    width = exp(log_width)
    gaussian = np.exp(-0.5 * ((np.log(energy_eV) - log_center) / width) ** 2)
    return cast(FloatArray, floor + excess * gaussian)


def _contrast_band_parameters(
    vector: FloatArray,
    layout: _ParameterLayout,
) -> tuple[float | None, float | None, float | None, float | None]:
    if layout.contrast_model != "band" or layout.amplitude is None:
        return None, None, None, None
    raw = np.asarray(vector[layout.amplitude], dtype=float)
    return (
        float(exp(raw[2])),
        float(exp(raw[3])),
        float(raw[0]),
        float(raw[0] + raw[1]),
    )


def _profile_mirror_ratio(
    data: _PreparedCounts,
    fit: EffectiveFieldModelFit,
    settings: EffectiveFieldFitSettings,
) -> tuple[tuple[float, float] | None, bool]:
    if fit.mirror_ratio is None or fit.log_likelihood is None:
        return None, False
    optimum = log(fit.mirror_ratio)
    global_lower, global_upper = (log(value) for value in settings.mirror_ratio_bounds)
    lower = max(global_lower, optimum - settings.profile_log_ratio_half_width)
    upper = min(global_upper, optimum + settings.profile_log_ratio_half_width)
    left_count = settings.profile_points // 2 + 1
    right_count = settings.profile_points - left_count + 1
    grid = np.concatenate(
        (
            np.linspace(lower, optimum, left_count),
            np.linspace(optimum, upper, right_count)[1:],
        )
    )
    likelihoods = np.full(grid.shape, np.nan, dtype=float)
    center = left_count - 1
    likelihoods[center] = fit.log_likelihood
    profile_settings = replace(settings, optimizer_starts=1, profile_likelihood=False)
    for index, value in enumerate(grid):
        if index == center:
            continue
        candidate = _fit_candidate(
            data,
            fit.model,
            profile_settings,
            contrast_model=fit.contrast_model,
            fixed_log_mirror=float(value),
        )
        if candidate.success and candidate.log_likelihood is not None:
            likelihoods[index] = candidate.log_likelihood
    deviance = np.maximum(
        2.0 * (fit.log_likelihood - likelihoods),
        0.0,
    )
    if not np.isfinite(deviance[center]):
        return None, False
    threshold = 3.841458820694124
    lower_endpoint, lower_truncated = _profile_endpoint(
        grid,
        deviance,
        center=center,
        outward=range(center - 1, -1, -1),
        threshold=threshold,
    )
    upper_endpoint, upper_truncated = _profile_endpoint(
        grid,
        deviance,
        center=center,
        outward=range(center + 1, grid.size),
        threshold=threshold,
    )
    return (
        (float(exp(lower_endpoint)), float(exp(upper_endpoint))),
        lower_truncated or upper_truncated,
    )


def _profile_endpoint(
    grid: FloatArray,
    deviance: FloatArray,
    *,
    center: int,
    outward: range,
    threshold: float,
) -> tuple[float, bool]:
    inside_index = center
    for outside_index in outward:
        outside_deviance = float(deviance[outside_index])
        if not np.isfinite(outside_deviance):
            return float(grid[inside_index]), True
        if outside_deviance >= threshold:
            inside_deviance = float(deviance[inside_index])
            span = outside_deviance - inside_deviance
            if span <= 0.0:
                return float(grid[inside_index]), True
            fraction = (threshold - inside_deviance) / span
            endpoint = grid[inside_index] + fraction * (grid[outside_index] - grid[inside_index])
            return float(endpoint), False
        inside_index = outside_index
    return float(grid[inside_index]), True


def _parameters_at_bounds(
    vector: FloatArray,
    bounds: list[tuple[float, float]],
    layout: _ParameterLayout,
) -> tuple[str, ...]:
    names: list[str] = []
    scalar_names = (
        (layout.log_mirror, "mirror_ratio"),
        (layout.delta_u, "delta_u_eff_eV"),
        (layout.log_sigma, "sigma_ln_b"),
        (layout.log_concentration, "concentration"),
    )
    for index, name in scalar_names:
        if index is None:
            continue
        lower, upper = bounds[index]
        tolerance = 1.0e-4 * max(1.0, abs(lower), abs(upper))
        if abs(vector[index] - lower) <= tolerance or abs(vector[index] - upper) <= tolerance:
            names.append(name)
    if layout.contrast_model == "constant" and layout.amplitude is not None:
        index = layout.amplitude.start
        lower, upper = bounds[index]
        tolerance = 1.0e-4 * max(1.0, abs(lower), abs(upper))
        if abs(vector[index] - lower) <= tolerance or abs(vector[index] - upper) <= tolerance:
            names.append("contrast_amplitude_log_ratio")
    if layout.contrast_model == "band" and layout.amplitude is not None:
        for index, name in (
            (layout.amplitude.start, "contrast_band_floor_log_ratio"),
            (layout.amplitude.start + 1, "contrast_band_excess_log_ratio"),
            (layout.amplitude.start + 2, "contrast_band_center_eV"),
            (layout.amplitude.start + 3, "contrast_band_width_ln"),
        ):
            lower, upper = bounds[index]
            tolerance = 1.0e-4 * max(1.0, abs(lower), abs(upper))
            if abs(vector[index] - lower) <= tolerance or abs(vector[index] - upper) <= tolerance:
                names.append(name)
    return tuple(names)


def _physical_candidate(
    data: _PreparedCounts,
    mirror_ratio: float | None,
    delta_u: float | None,
) -> bool:
    if mirror_ratio is None:
        return True
    boundary = mirror_boundary_sin2(
        data.energy_eV,
        mirror_ratio,
        delta_u or 0.0,
        spacecraft_potential_eV=data.spacecraft_potential_eV,
    )
    return bool(np.all(np.isfinite(boundary)))


def _boundary_support(
    data: _PreparedCounts,
    mirror_ratio: float | None,
    delta_u: float | None,
    *,
    min_transition_energy_bins: int,
) -> tuple[float | None, float | None]:
    if mirror_ratio is None:
        return None, None
    boundary = mirror_boundary_sin2(
        data.energy_eV,
        mirror_ratio,
        delta_u or 0.0,
        spacecraft_potential_eV=data.spacecraft_potential_eV,
    )
    if not np.all(np.isfinite(boundary)):
        return None, None
    transition_energy = (boundary > 0.0) & (boundary < 1.0)
    if np.count_nonzero(transition_energy) < min_transition_energy_bins:
        return None, None
    boundary_pitch = np.full(boundary.shape, np.nan, dtype=float)
    boundary_pitch[transition_energy] = np.rad2deg(np.arcsin(np.sqrt(boundary[transition_energy])))
    below = np.sum(
        data.valid & (data.pitch_deg[None, :] < boundary_pitch[:, None]),
        axis=1,
    )
    above = np.sum(
        data.valid & (data.pitch_deg[None, :] > boundary_pitch[:, None]),
        axis=1,
    )
    bracketed = (below >= 1) & (above >= 1)
    strict = (below >= 2) & (above >= 2)
    return (
        float(np.mean(bracketed[transition_energy])),
        float(np.mean(strict[transition_energy])),
    )


def _observed_log_ratio(data: _PreparedCounts) -> FloatArray:
    with np.errstate(divide="ignore", invalid="ignore"):
        value = np.log((data.affected_counts + 0.5) / (data.reference_counts + 0.5)) - np.log(
            data.affected_exposure / data.reference_exposure
        )
    return cast(FloatArray, np.where(data.valid, value, np.nan))


def _fit_energy_ratio_step(
    energy_eV: FloatArray,
    baseline_log_ratio: tuple[float, ...],
    settings: EffectiveFieldFitSettings,
) -> _EnergyRatioStepFit:
    baseline = np.asarray(baseline_log_ratio, dtype=float)
    valid = np.isfinite(energy_eV) & np.isfinite(baseline) & (energy_eV > 0.0)
    energy = np.asarray(energy_eV[valid], dtype=float)
    values = baseline[valid]
    min_side = settings.min_energy_ratio_step_bins_per_side
    if energy.size < 2 * min_side:
        return _EnergyRatioStepFit(False, None, None, float("nan"), None)

    order = np.argsort(energy)
    energy = energy[order]
    values = values[order]
    log_energy = np.log(energy)
    centered_log_energy = log_energy - float(np.mean(log_energy))
    null_design = np.column_stack((np.ones(energy.size, dtype=float), centered_log_energy))
    null_bic = cast(float, _gaussian_regression_bic(null_design, values))
    best_bic = float("inf")
    best_center: float | None = None
    best_step: float | None = None
    for split in range(min_side, energy.size - min_side + 1):
        step = (np.arange(energy.size) >= split).astype(float)
        design = np.column_stack((null_design, step))
        bic, coefficients = cast(
            tuple[float, FloatArray],
            _gaussian_regression_bic(
                design,
                values,
                return_coefficients=True,
            ),
        )
        if bic < best_bic:
            best_bic = bic
            best_center = float(np.sqrt(energy[split - 1] * energy[split]))
            best_step = float(coefficients[-1])
    delta_bic = float(null_bic - best_bic)
    supported = bool(
        best_center is not None
        and best_step is not None
        and np.isfinite(delta_bic)
        and delta_bic >= settings.min_energy_ratio_step_delta_bic
    )
    if not supported:
        return _EnergyRatioStepFit(False, None, None, delta_bic, None)
    assert best_step is not None
    return _EnergyRatioStepFit(
        True,
        best_center,
        best_step,
        delta_bic,
        "up" if best_step >= 0.0 else "down",
    )


def _gaussian_regression_bic(
    design: FloatArray,
    values: FloatArray,
    *,
    return_coefficients: bool = False,
) -> float | tuple[float, FloatArray]:
    coefficients, _, _, _ = np.linalg.lstsq(design, values, rcond=None)
    residual = values - design @ coefficients
    rss = max(float(np.sum(residual**2)), np.finfo(float).tiny)
    n_observations = values.size
    bic = float(
        n_observations * np.log(rss / n_observations) + design.shape[1] * np.log(n_observations)
    )
    if return_coefficients:
        return bic, np.asarray(coefficients, dtype=float)
    return bic


def _bic_improvement(simple: EffectiveFieldModelFit, complex: EffectiveFieldModelFit) -> float:
    if not simple.success or not complex.success or simple.bic is None or complex.bic is None:
        return float("-inf")
    return float(simple.bic - complex.bic)


def _edge_parameters_at_bounds(fit: EffectiveFieldModelFit) -> bool:
    return bool({"mirror_ratio", "delta_u_eff_eV", "sigma_ln_b"}.intersection(fit.at_bounds))


def _contrast_band_parameters_at_bounds(fit: EffectiveFieldModelFit) -> bool:
    return bool(
        {
            "contrast_band_excess_log_ratio",
            "contrast_band_center_eV",
            "contrast_band_width_ln",
        }.intersection(fit.at_bounds)
    )


def _edge_quality_reason(
    fit: EffectiveFieldModelFit,
    settings: EffectiveFieldFitSettings,
) -> str | None:
    if not fit.success:
        return fit.reason
    if _edge_parameters_at_bounds(fit):
        return "edge_parameter_at_bound"
    if _contrast_band_parameters_at_bounds(fit):
        return "contrast_band_parameter_at_bound"
    if (
        fit.boundary_bracket_fraction is None
        or fit.strict_boundary_bracket_fraction is None
        or fit.boundary_bracket_fraction < settings.min_boundary_bracket_fraction
        or fit.strict_boundary_bracket_fraction < settings.min_strict_boundary_bracket_fraction
    ):
        return "insufficient_boundary_bracketing"
    return None


def _failed_estimate(
    data: _PreparedCounts,
    *,
    reason: str,
) -> EffectiveFieldEstimate:
    fits = tuple(
        _empty_model_fit(model, data.n_cells, 0, reason)
        for model in cast(tuple[CandidateModel, ...], ("no_edge", "mirror_only", "electrostatic"))
    )
    diagnostics = EffectiveFieldDiagnostics(
        n_input_energy_bins=data.input_energy_bins,
        n_energy_bins=data.n_energy,
        n_pitch_bins=data.n_pitch,
        n_cells=data.n_cells,
        total_counts=data.total_counts,
        no_edge_delta_bic=float("-inf"),
        electrostatic_delta_bic=float("-inf"),
        profile_truncated=False,
        model_fits=fits,
    )
    return EffectiveFieldEstimate(
        success=False,
        reason=reason,
        selected_model="no_edge",
        edge_supported=False,
        mirror_ratio=None,
        mirror_ratio_ci95=None,
        effective_field_nT=None,
        effective_field_ci95_nT=None,
        delta_u_eff_eV=None,
        sigma_ln_b=None,
        diagnostics=diagnostics,
    )


def _empty_model_fit(
    model: CandidateModel,
    n_cells: int,
    n_parameters: int,
    reason: str,
    *,
    contrast_model: ResolvedContrastModel = "none",
) -> EffectiveFieldModelFit:
    return EffectiveFieldModelFit(
        model=model,
        success=False,
        reason=reason,
        mirror_ratio=None,
        delta_u_eff_eV=None,
        sigma_ln_b=None,
        baseline_log_ratio=(),
        amplitude_log_ratio=(),
        concentration=None,
        log_likelihood=None,
        bic=None,
        n_parameters=n_parameters,
        n_cells=n_cells,
        contrast_model=contrast_model,
    )


def _float_array(value: ArrayLike) -> FloatArray:
    return np.asarray(value, dtype=np.float64)


def _broadcast_positive(
    value: ArrayLike | float,
    shape: tuple[int, ...],
    *,
    name: str,
) -> FloatArray:
    try:
        array = np.broadcast_to(np.asarray(value, dtype=float), shape).astype(float, copy=True)
    except ValueError as exc:
        raise ValueError(f"{name} must be scalar or broadcast to the count array shape") from exc
    if not np.all(np.isfinite(array)) or np.any(array <= 0.0):
        raise ValueError(f"{name} must contain finite positive values")
    return array


def _expit(value: FloatArray) -> FloatArray:
    from scipy.special import expit

    return cast(FloatArray, expit(value))


def _validate_bounds(name: str, bounds: tuple[float, float]) -> None:
    lower, upper = bounds
    if not np.isfinite(lower) or not np.isfinite(upper) or lower >= upper:
        raise ValueError(f"{name} must contain finite increasing bounds")


def _validate_positive_bounds(name: str, bounds: tuple[float, float]) -> None:
    _validate_bounds(name, bounds)
    if bounds[0] <= 0.0:
        raise ValueError(f"{name} must contain positive bounds")
