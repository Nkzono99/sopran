from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize
from scipy.special import ndtr

from sopran.analysis.electron_reflection.model import (
    ElectronReflectionCounts,
    FloatArray,
    _validate_positive_bounds,
    mirror_boundary_sin2,
)

HalekasEdgeTransition = Literal["hard", "probit"]


@dataclass(frozen=True)
class HalekasFitSettings:
    """Settings for a normalized full-distribution Halekas-style fit.

    The default ``hard`` model reproduces the sharp loss-cone component used
    by Halekas et al. (2008): normalized reflected/incident ratio is one
    outside the loss cone and a fixed backscatter fraction inside it. The
    optional ``probit`` transition only adds a finite edge width to that same
    synthetic distribution.

    Positive surface-to-spacecraft field ratios include values below one.
    This implementation does not yet add the upward secondary-electron beam.
    """

    edge_transition: HalekasEdgeTransition = "hard"
    min_energy_bins: int = 3
    min_pitch_bins_per_energy: int = 3
    min_total_counts: int = 100
    mirror_ratio_bounds: tuple[float, float] = (0.001, 1000.0)
    delta_u_bounds_eV: tuple[float, float] = (-500.0, 1000.0)
    spacecraft_potential_eV: float = 0.0
    backscatter_fraction: float = 0.1
    count_pseudocount: float = 0.5
    mirror_grid_points: int = 512
    delta_u_grid_points: int = 601
    hard_refinement_steps: int = 2
    min_boundary_energy_bins: int = 3
    sigma_ln_sin2_bounds: tuple[float, float] = (0.02, 1.5)
    smooth_max_iterations: int = 1200

    def __post_init__(self) -> None:
        if self.edge_transition not in {"hard", "probit"}:
            raise ValueError("edge_transition must be 'hard' or 'probit'")
        if self.min_energy_bins < 2:
            raise ValueError("min_energy_bins must be at least 2")
        if self.min_pitch_bins_per_energy < 2:
            raise ValueError("min_pitch_bins_per_energy must be at least 2")
        if self.min_total_counts <= 0:
            raise ValueError("min_total_counts must be positive")
        _validate_positive_bounds("mirror_ratio_bounds", self.mirror_ratio_bounds)
        if not self.delta_u_bounds_eV[0] < self.delta_u_bounds_eV[1]:
            raise ValueError("delta_u_bounds_eV must satisfy lower < upper")
        if not 0.0 < self.backscatter_fraction < 1.0:
            raise ValueError("backscatter_fraction must be between zero and one")
        if self.count_pseudocount <= 0.0:
            raise ValueError("count_pseudocount must be positive")
        if self.mirror_grid_points < 3 or self.delta_u_grid_points < 3:
            raise ValueError("hard-fit grid dimensions must be at least 3")
        if self.hard_refinement_steps < 0:
            raise ValueError("hard_refinement_steps must be non-negative")
        if self.min_boundary_energy_bins < 2:
            raise ValueError("min_boundary_energy_bins must be at least 2")
        if not (
            0.0 < self.sigma_ln_sin2_bounds[0] < self.sigma_ln_sin2_bounds[1]
        ):
            raise ValueError("sigma_ln_sin2_bounds must satisfy 0 < lower < upper")
        if self.smooth_max_iterations <= 0:
            raise ValueError("smooth_max_iterations must be positive")
        if not np.isfinite(self.spacecraft_potential_eV):
            raise ValueError("spacecraft_potential_eV must be finite")


@dataclass(frozen=True)
class HalekasDistributionFit:
    """Best normalized synthetic distribution for one paired PAD.

    ``effective_field_nT`` is the boundary-model field, not necessarily the
    maximum field along the path or the crustal field alone.
    """

    success: bool
    reason: str
    edge_transition: HalekasEdgeTransition
    mirror_ratio: float | None
    effective_field_nT: float | None
    delta_u_eff_eV: float | None
    sigma_ln_sin2: float | None
    backscatter_fraction: float
    residual_sum_squares: float
    root_mean_square_error: float
    gaussian_bic: float
    hard_to_smooth_delta_bic: float
    no_loss_cone_root_mean_square_error: float
    fractional_rss_improvement: float
    n_energy_bins: int
    n_pitch_bins: int
    n_cells: int
    total_counts: int
    energy_eV: FloatArray
    pitch_deg: FloatArray
    observed_log_ratio: FloatArray
    fitted_log_ratio: FloatArray
    boundary_pitch_deg: FloatArray
    at_bounds: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedDistribution:
    energy_eV: FloatArray
    pitch_deg: FloatArray
    observed_log_ratio: FloatArray
    valid: NDArray[np.bool_]
    total_counts: int

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
class _HardCandidate:
    mirror_ratio: float
    delta_u_eff_eV: float
    residual_sum_squares: float


def fit_halekas_distribution(
    counts: ElectronReflectionCounts,
    *,
    settings: HalekasFitSettings | None = None,
) -> HalekasDistributionFit:
    """Fit a normalized 2-D synthetic loss-cone distribution.

    This fit does not detect per-energy edges first. It directly minimizes the
    squared log-ratio residual over every valid energy-pitch cell. ``hard``
    performs a grid search over magnetic ratio and potential. ``probit`` starts
    from the hard solution and jointly optimizes those parameters and one edge
    width.
    """

    settings = settings or HalekasFitSettings()
    data = _prepare_distribution(counts, settings)
    if data.n_energy < settings.min_energy_bins:
        return _failed_fit(data, settings, "insufficient_energy_support")
    if data.total_counts < settings.min_total_counts:
        return _failed_fit(data, settings, "insufficient_total_counts")

    hard = _fit_hard_distribution(data, settings)
    if hard is None:
        return _failed_fit(data, settings, "no_supported_boundary_grid_cell")
    if settings.edge_transition == "hard":
        return _result_from_parameters(
            counts,
            data,
            settings,
            mirror_ratio=hard.mirror_ratio,
            delta_u_eff_eV=hard.delta_u_eff_eV,
            sigma_ln_sin2=None,
            hard_reference_rss=hard.residual_sum_squares,
            reason="hard_full_distribution_fit",
        )

    smooth = _fit_smooth_distribution(data, settings, hard)
    if smooth is None:
        return _failed_fit(data, settings, "smooth_optimizer_failed")
    mirror_ratio, delta_u, sigma = smooth
    return _result_from_parameters(
        counts,
        data,
        settings,
        mirror_ratio=mirror_ratio,
        delta_u_eff_eV=delta_u,
        sigma_ln_sin2=sigma,
        hard_reference_rss=hard.residual_sum_squares,
        reason="probit_full_distribution_fit",
    )


def _prepare_distribution(
    counts: ElectronReflectionCounts,
    settings: HalekasFitSettings,
) -> _PreparedDistribution:
    affected = np.asarray(counts.affected_counts, dtype=float)
    reference = np.asarray(counts.reference_counts, dtype=float)
    affected_exposure = np.asarray(counts.affected_exposure, dtype=float)
    reference_exposure = np.asarray(counts.reference_exposure, dtype=float)
    valid = (
        np.isfinite(affected)
        & np.isfinite(reference)
        & np.isfinite(affected_exposure)
        & np.isfinite(reference_exposure)
        & (affected_exposure > 0.0)
        & (reference_exposure > 0.0)
    )
    energy = np.asarray(counts.energy_eV, dtype=float)
    corrected_energy = energy - settings.spacecraft_potential_eV
    supported = (np.count_nonzero(valid, axis=1) >= settings.min_pitch_bins_per_energy) & (
        corrected_energy > 0.0
    )
    supported_indices = np.flatnonzero(supported)
    order = supported_indices[np.argsort(energy[supported_indices])]
    pseudocount = settings.count_pseudocount
    with np.errstate(divide="ignore", invalid="ignore"):
        observed = np.log((affected + pseudocount) / (reference + pseudocount)) - np.log(
            affected_exposure / reference_exposure
        )
    observed = np.where(valid, observed, np.nan)
    return _PreparedDistribution(
        energy_eV=energy[order],
        pitch_deg=np.asarray(counts.pitch_deg, dtype=float),
        observed_log_ratio=np.asarray(observed[order], dtype=float),
        valid=np.asarray(valid[order], dtype=bool),
        total_counts=int(np.rint(np.nansum(affected[supported]) + np.nansum(reference[supported]))),
    )


def _fit_hard_distribution(
    data: _PreparedDistribution,
    settings: HalekasFitSettings,
) -> _HardCandidate | None:
    lower_ratio, upper_ratio = settings.mirror_ratio_bounds
    ratios = np.geomspace(lower_ratio, upper_ratio, settings.mirror_grid_points)
    delta_values = np.linspace(
        settings.delta_u_bounds_eV[0],
        settings.delta_u_bounds_eV[1],
        settings.delta_u_grid_points,
    )
    best = _search_hard_grid(data, settings, ratios, delta_values)
    for _ in range(settings.hard_refinement_steps):
        if best is None:
            break
        ratio_index = int(np.argmin(np.abs(ratios - best.mirror_ratio)))
        delta_index = int(np.argmin(np.abs(delta_values - best.delta_u_eff_eV)))
        ratios = np.unique(np.r_[best.mirror_ratio, np.geomspace(
            ratios[max(0, ratio_index - 1)],
            ratios[min(len(ratios) - 1, ratio_index + 1)], 17,
        )])
        delta_values = np.unique(np.r_[best.delta_u_eff_eV, np.linspace(
            delta_values[max(0, delta_index - 1)],
            delta_values[min(len(delta_values) - 1, delta_index + 1)], 17,
        )])
        refined = _search_hard_grid(data, settings, ratios, delta_values)
        if refined is not None and refined.residual_sum_squares < best.residual_sum_squares:
            best = refined
    return best


def _search_hard_grid(
    data: _PreparedDistribution,
    settings: HalekasFitSettings,
    ratios: FloatArray,
    delta_values: FloatArray,
) -> _HardCandidate | None:
    sin2_pitch = np.sin(np.deg2rad(data.pitch_deg)) ** 2
    inside_log_ratio = float(np.log(settings.backscatter_fraction))
    order = np.argsort(sin2_pitch, kind="stable")
    valid = data.valid[:, order]
    observed = data.observed_log_ratio[:, order]
    # Nonnegative prefix/suffix costs avoid cancellation near a perfect fit.
    inside_cost = np.where(valid, (observed - inside_log_ratio) ** 2, 0.0)
    outside_cost = np.where(valid, observed**2, 0.0)
    costs = np.pad(np.cumsum(inside_cost, axis=1), ((0, 0), (1, 0))) + np.pad(
        np.cumsum(outside_cost[:, ::-1], axis=1)[:, ::-1], ((0, 0), (0, 1))
    )
    below_counts = np.pad(np.cumsum(valid, axis=1), ((0, 0), (1, 0)))
    finite_costs = bool(np.all(np.isfinite(costs)))
    energy_indices = np.arange(data.n_energy)
    roundoff = 8.0 * np.finfo(float).eps * (data.n_cells + data.n_pitch + data.n_energy)
    best: _HardCandidate | None = None
    corrected_energy = data.energy_eV - settings.spacecraft_potential_eV
    valid_per_energy = np.sum(data.valid, axis=1)
    for mirror_ratio in ratios:
        boundary = (1.0 + delta_values[:, None] / corrected_energy[None, :]) / mirror_ratio
        split = np.searchsorted(sin2_pitch[order], boundary, side="left")
        split[np.isnan(boundary)] = 0
        below = below_counts[energy_indices, split]
        above = valid_per_energy[None, :] - below
        supported = (
            np.sum((below >= 1) & (above >= 1), axis=1) >= settings.min_boundary_energy_bins
        )
        if not np.any(supported):
            continue
        minimum = np.inf
        if finite_costs:
            rss = np.sum(costs[energy_indices, split], axis=1)
            minimum = float(np.min(rss[supported]))
            if best is not None:
                minimum = min(minimum, best.residual_sum_squares)
        if np.isfinite(minimum):
            tolerance = roundoff * max(minimum, np.finfo(float).tiny)
            candidates = np.flatnonzero(supported & (rss <= minimum + tolerance))
            if not candidates.size:
                continue
            # Identical valid-cell maps have identical reference SSE; retain their first index.
            _, first = np.unique(below[candidates], axis=0, return_index=True)
            candidates = candidates[np.sort(first)]
        else:
            # Preserve the original argmin/NaN/inf behavior for nonfinite SSE.
            candidates = np.arange(delta_values.size)
        rss = _hard_grid_candidate_rss(
            data, sin2_pitch, inside_log_ratio, boundary[candidates],
            batched=delta_values.size > 1,
        )
        rss[~supported[candidates]] = np.inf
        selected = int(np.argmin(rss))
        index = int(candidates[selected])
        if best is None or rss[selected] < best.residual_sum_squares:
            best = _HardCandidate(
                mirror_ratio=float(mirror_ratio),
                delta_u_eff_eV=float(delta_values[index]),
                residual_sum_squares=float(rss[selected]),
            )
    return best


def _hard_grid_candidate_rss(
    data: _PreparedDistribution,
    sin2_pitch: FloatArray,
    inside_log_ratio: float,
    boundary: FloatArray,
    *,
    batched: bool,
) -> FloatArray:
    inside = sin2_pitch[None, None, :] < boundary[:, :, None]
    residual = data.observed_log_ratio[data.valid][None, :] - np.where(
        inside[:, data.valid], inside_log_ratio, 0.0
    )
    squared = residual**2
    # The original multi-potential array sums along its strided axis, in cell order.
    # A one-candidate sum would instead use NumPy's contiguous pairwise reduction.
    if batched:
        return np.cumsum(squared, axis=1)[:, -1]
    return np.asarray(np.sum(squared, axis=1), dtype=float)


def _fit_smooth_distribution(
    data: _PreparedDistribution,
    settings: HalekasFitSettings,
    hard: _HardCandidate,
) -> tuple[float, float, float] | None:
    ratio_lower, ratio_upper = settings.mirror_ratio_bounds
    sigma_lower, sigma_upper = settings.sigma_ln_sin2_bounds
    bounds = (
        (float(np.log(ratio_lower)), float(np.log(ratio_upper))),
        settings.delta_u_bounds_eV,
        (float(np.log(sigma_lower)), float(np.log(sigma_upper))),
    )
    starts: list[FloatArray] = []
    seeds = [
        (hard.mirror_ratio, hard.delta_u_eff_eV, sigma)
        for sigma in (0.04, 0.12, 0.35, 0.8)
    ]
    seeds.extend(
        (mirror_ratio, hard.delta_u_eff_eV, 0.12)
        for mirror_ratio in (0.3, 0.8, 1.0, 1.2, 2.0, 10.0)
    )
    seeds.extend(
        (hard.mirror_ratio, delta_u, 0.12)
        for delta_u in (
            0.0,
            np.clip(hard.delta_u_eff_eV - 50.0, *settings.delta_u_bounds_eV),
            np.clip(hard.delta_u_eff_eV + 50.0, *settings.delta_u_bounds_eV),
        )
    )
    seen_starts: set[tuple[float, float, float]] = set()
    for mirror_ratio, delta_u, sigma in seeds:
        key = (float(mirror_ratio), float(delta_u), float(sigma))
        if key in seen_starts:
            continue
        seen_starts.add(key)
        if not ratio_lower <= mirror_ratio <= ratio_upper:
            continue
        if sigma_lower <= sigma <= sigma_upper:
            starts.append(
                np.asarray(
                    (np.log(mirror_ratio), delta_u, np.log(sigma)),
                    dtype=float,
                )
            )
    best_value = np.inf
    best_parameters: FloatArray | None = None
    for start in starts:
        result = minimize(
            _smooth_objective,
            start,
            args=(data, settings),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": settings.smooth_max_iterations, "ftol": 1.0e-11},
        )
        if np.isfinite(result.fun) and float(result.fun) < best_value:
            best_value = float(result.fun)
            best_parameters = np.asarray(result.x, dtype=float)
    if best_parameters is None:
        return None
    return (
        float(np.exp(best_parameters[0])),
        float(best_parameters[1]),
        float(np.exp(best_parameters[2])),
    )


def _smooth_objective(
    vector: FloatArray,
    data: _PreparedDistribution,
    settings: HalekasFitSettings,
) -> float:
    mirror_ratio = float(np.exp(vector[0]))
    delta_u = float(vector[1])
    sigma = float(np.exp(vector[2]))
    boundary = mirror_boundary_sin2(
        data.energy_eV,
        mirror_ratio,
        delta_u,
        spacecraft_potential_eV=settings.spacecraft_potential_eV,
    )
    sin2_pitch = np.sin(np.deg2rad(data.pitch_deg)) ** 2
    if not _boundary_supported(boundary, sin2_pitch, data.valid, settings):
        return 1.0e12
    fitted = _synthetic_log_ratio(
        data.pitch_deg,
        boundary,
        settings.backscatter_fraction,
        sigma_ln_sin2=sigma,
    )
    residual = data.observed_log_ratio[data.valid] - fitted[data.valid]
    return float(residual @ residual)


def _result_from_parameters(
    counts: ElectronReflectionCounts,
    data: _PreparedDistribution,
    settings: HalekasFitSettings,
    *,
    mirror_ratio: float,
    delta_u_eff_eV: float,
    sigma_ln_sin2: float | None,
    hard_reference_rss: float,
    reason: str,
) -> HalekasDistributionFit:
    boundary = mirror_boundary_sin2(
        data.energy_eV,
        mirror_ratio,
        delta_u_eff_eV,
        spacecraft_potential_eV=settings.spacecraft_potential_eV,
    )
    fitted = _synthetic_log_ratio(
        data.pitch_deg,
        boundary,
        settings.backscatter_fraction,
        sigma_ln_sin2=sigma_ln_sin2,
    )
    fitted[~data.valid] = np.nan
    residual = data.observed_log_ratio[data.valid] - fitted[data.valid]
    rss = max(float(residual @ residual), np.finfo(float).tiny)
    no_loss_residual = data.observed_log_ratio[data.valid]
    no_loss_rss = max(float(no_loss_residual @ no_loss_residual), np.finfo(float).tiny)
    n_parameters = 2 if sigma_ln_sin2 is None else 3
    bic = _gaussian_bic(rss, data.n_cells, n_parameters)
    hard_bic = _gaussian_bic(hard_reference_rss, data.n_cells, 2)
    boundary_pitch = _boundary_pitch(boundary)
    at_bounds = _parameters_at_bounds(
        mirror_ratio,
        delta_u_eff_eV,
        sigma_ln_sin2,
        settings,
    )
    return HalekasDistributionFit(
        success=True,
        reason=reason,
        edge_transition=settings.edge_transition,
        mirror_ratio=mirror_ratio,
        effective_field_nT=float(counts.b_sc_nT * mirror_ratio),
        delta_u_eff_eV=delta_u_eff_eV,
        sigma_ln_sin2=sigma_ln_sin2,
        backscatter_fraction=settings.backscatter_fraction,
        residual_sum_squares=rss,
        root_mean_square_error=float(np.sqrt(rss / data.n_cells)),
        gaussian_bic=bic,
        hard_to_smooth_delta_bic=float(hard_bic - bic),
        no_loss_cone_root_mean_square_error=float(np.sqrt(no_loss_rss / data.n_cells)),
        fractional_rss_improvement=float(1.0 - rss / no_loss_rss),
        n_energy_bins=data.n_energy,
        n_pitch_bins=data.n_pitch,
        n_cells=data.n_cells,
        total_counts=data.total_counts,
        energy_eV=data.energy_eV,
        pitch_deg=data.pitch_deg,
        observed_log_ratio=data.observed_log_ratio,
        fitted_log_ratio=fitted,
        boundary_pitch_deg=boundary_pitch,
        at_bounds=at_bounds,
    )


def _synthetic_log_ratio(
    pitch_deg: FloatArray,
    boundary_sin2: FloatArray,
    backscatter_fraction: float,
    *,
    sigma_ln_sin2: float | None,
) -> FloatArray:
    sin2_pitch = np.sin(np.deg2rad(pitch_deg)) ** 2
    if sigma_ln_sin2 is None:
        outside_fraction = np.asarray(
            sin2_pitch[None, :] >= boundary_sin2[:, None],
            dtype=float,
        )
    else:
        log_boundary = np.full(boundary_sin2.shape, -np.inf, dtype=float)
        positive = boundary_sin2 > 0.0
        log_boundary[positive] = np.log(boundary_sin2[positive])
        log_pitch = np.log(np.clip(sin2_pitch, 1.0e-15, None))
        outside_fraction = ndtr(
            (log_pitch[None, :] - log_boundary[:, None]) / sigma_ln_sin2
        )
    ratio = backscatter_fraction + (1.0 - backscatter_fraction) * outside_fraction
    return np.log(np.clip(ratio, np.finfo(float).tiny, None))


def _boundary_supported(
    boundary_sin2: FloatArray,
    sin2_pitch: FloatArray,
    valid: NDArray[np.bool_],
    settings: HalekasFitSettings,
) -> bool:
    below = np.sum(valid & (sin2_pitch[None, :] < boundary_sin2[:, None]), axis=1)
    above = np.sum(valid & (sin2_pitch[None, :] >= boundary_sin2[:, None]), axis=1)
    return bool(
        np.count_nonzero((below >= 1) & (above >= 1))
        >= settings.min_boundary_energy_bins
    )


def _boundary_pitch(boundary_sin2: FloatArray) -> FloatArray:
    physical = (boundary_sin2 >= 0.0) & (boundary_sin2 <= 1.0)
    pitch = np.full(boundary_sin2.shape, np.nan, dtype=float)
    pitch[physical] = np.degrees(np.arcsin(np.sqrt(boundary_sin2[physical])))
    return pitch


def _failed_fit(
    data: _PreparedDistribution,
    settings: HalekasFitSettings,
    reason: str,
) -> HalekasDistributionFit:
    return HalekasDistributionFit(
        success=False,
        reason=reason,
        edge_transition=settings.edge_transition,
        mirror_ratio=None,
        effective_field_nT=None,
        delta_u_eff_eV=None,
        sigma_ln_sin2=None,
        backscatter_fraction=settings.backscatter_fraction,
        residual_sum_squares=float("inf"),
        root_mean_square_error=float("inf"),
        gaussian_bic=float("inf"),
        hard_to_smooth_delta_bic=float("-inf"),
        no_loss_cone_root_mean_square_error=float("inf"),
        fractional_rss_improvement=float("-inf"),
        n_energy_bins=data.n_energy,
        n_pitch_bins=data.n_pitch,
        n_cells=data.n_cells,
        total_counts=data.total_counts,
        energy_eV=data.energy_eV,
        pitch_deg=data.pitch_deg,
        observed_log_ratio=data.observed_log_ratio,
        fitted_log_ratio=np.full(data.valid.shape, np.nan, dtype=float),
        boundary_pitch_deg=np.full(data.n_energy, np.nan, dtype=float),
        at_bounds=(),
    )


def _gaussian_bic(rss: float, n_cells: int, n_parameters: int) -> float:
    safe_rss = max(float(rss), np.finfo(float).tiny)
    return float(n_cells * np.log(safe_rss / n_cells) + n_parameters * np.log(n_cells))


def _parameters_at_bounds(
    mirror_ratio: float,
    delta_u_eff_eV: float,
    sigma_ln_sin2: float | None,
    settings: HalekasFitSettings,
) -> tuple[str, ...]:
    at_bounds: list[str] = []
    for name, value, bounds in (
        ("mirror_ratio", mirror_ratio, settings.mirror_ratio_bounds),
        ("delta_u_eff_eV", delta_u_eff_eV, settings.delta_u_bounds_eV),
    ):
        tolerance = 1.0e-12 if name == "mirror_ratio" else 1.0e-6
        if np.isclose(value, bounds[0], atol=tolerance, rtol=1.0e-6):
            at_bounds.append(f"{name}_lower")
        elif np.isclose(value, bounds[1], atol=tolerance, rtol=1.0e-6):
            at_bounds.append(f"{name}_upper")
    if sigma_ln_sin2 is not None:
        lower, upper = settings.sigma_ln_sin2_bounds
        tolerance = 1.0e-6 * upper
        if np.isclose(sigma_ln_sin2, lower, atol=tolerance, rtol=0.0):
            at_bounds.append("sigma_ln_sin2_lower")
        elif np.isclose(sigma_ln_sin2, upper, atol=tolerance, rtol=0.0):
            at_bounds.append("sigma_ln_sin2_upper")
    return tuple(at_bounds)


__all__ = [
    "HalekasDistributionFit",
    "HalekasEdgeTransition",
    "HalekasFitSettings",
    "fit_halekas_distribution",
]
