from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

import numpy as np
from numpy.typing import NDArray

from sopran.analysis.electron_reflection.model import (
    CandidateModel,
    ElectronReflectionCounts,
    FloatArray,
    _validate_positive_bounds,
    mirror_boundary_sin2,
)


@dataclass(frozen=True)
class BinaryLossConeFitSettings:
    """Grid and evidence settings for a Halekas-style binary surface fit."""

    min_energy_bins: int = 3
    min_pitch_bins_per_energy: int = 6
    min_total_counts: int = 100
    mirror_ratio_bounds: tuple[float, float] = (0.001, 1000.0)
    delta_u_bounds_eV: tuple[float, float] = (-500.0, 1000.0)
    spacecraft_potential_eV: float = 0.0
    contrast_band_width_bounds_ln: tuple[float, float] = (0.15, 2.5)
    mirror_grid_points: int = 256
    delta_u_grid_points: int = 121
    contrast_center_grid_points: int = 14
    contrast_width_grid_points: int = 9
    min_edge_delta_bic: float = 6.0
    min_electrostatic_delta_bic: float = 1.0
    min_boundary_bracket_fraction: float = 0.8
    min_strict_boundary_bracket_fraction: float = 0.5

    def __post_init__(self) -> None:
        if self.min_energy_bins < 2:
            raise ValueError("min_energy_bins must be at least 2")
        if self.min_pitch_bins_per_energy < 3:
            raise ValueError("min_pitch_bins_per_energy must be at least 3")
        if self.min_total_counts <= 0:
            raise ValueError("min_total_counts must be positive")
        _validate_positive_bounds("mirror_ratio_bounds", self.mirror_ratio_bounds)
        if not self.delta_u_bounds_eV[0] < self.delta_u_bounds_eV[1]:
            raise ValueError("delta_u_bounds_eV must satisfy lower < upper")
        if not (
            0.0 < self.contrast_band_width_bounds_ln[0] < self.contrast_band_width_bounds_ln[1]
        ):
            raise ValueError("contrast_band_width_bounds_ln must satisfy 0 < lower < upper")
        for name, value in (
            ("mirror_grid_points", self.mirror_grid_points),
            ("delta_u_grid_points", self.delta_u_grid_points),
            ("contrast_center_grid_points", self.contrast_center_grid_points),
            ("contrast_width_grid_points", self.contrast_width_grid_points),
        ):
            if value < 3:
                raise ValueError(f"{name} must be at least 3")
        for name, value in (
            ("min_boundary_bracket_fraction", self.min_boundary_bracket_fraction),
            (
                "min_strict_boundary_bracket_fraction",
                self.min_strict_boundary_bracket_fraction,
            ),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class BinaryLossConeModelFit:
    """One profiled hard-boundary member of the binary surface family."""

    model: CandidateModel
    success: bool
    reason: str
    mirror_ratio: float | None
    delta_u_eff_eV: float | None
    contrast_amplitude_log_ratio: float | None
    contrast_band_center_eV: float | None
    contrast_band_width_ln: float | None
    residual_sum_squares: float
    bic: float
    n_parameters: int
    n_cells: int
    boundary_pitch_deg: FloatArray
    fitted_log_ratio: FloatArray


@dataclass(frozen=True)
class BinaryLossConeEstimate:
    """Selected binary 2-D loss-cone surface and nested-model evidence."""

    success: bool
    reason: str
    selected_model: CandidateModel
    edge_supported: bool
    mirror_ratio: float | None
    effective_field_nT: float | None
    delta_u_eff_eV: float | None
    no_edge_delta_bic: float
    electrostatic_delta_bic: float
    model_fits: tuple[BinaryLossConeModelFit, ...]
    energy_eV: FloatArray
    pitch_deg: FloatArray

    def fit(self, model: CandidateModel) -> BinaryLossConeModelFit:
        for candidate in self.model_fits:
            if candidate.model == model:
                return candidate
        raise KeyError(model)


@dataclass(frozen=True)
class _PreparedBinarySurface:
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
class _ProfiledSurface:
    mirror_ratio: float
    delta_u_eff_eV: float
    contrast_amplitude: float
    contrast_center_eV: float
    contrast_width_ln: float
    residual_sum_squares: float
    fitted_log_ratio: FloatArray
    boundary_pitch_deg: FloatArray


def fit_binary_loss_cone(
    counts: ElectronReflectionCounts,
    *,
    settings: BinaryLossConeFitSettings | None = None,
) -> BinaryLossConeEstimate:
    """Fit a sharp physical boundary to the full energy-pitch log-ratio surface.

    Energy offsets and a shared pitch profile are profiled as nuisance terms.
    The edge contrast is a Gaussian band in log energy. This keeps a persistent
    angular background from displacing an energy-localized sharp loss cone.
    """

    settings = settings or BinaryLossConeFitSettings()
    data = _prepare_binary_surface(counts, settings)
    if data.n_energy < settings.min_energy_bins:
        return _failed_estimate(data, "insufficient_energy_support")
    if data.total_counts < settings.min_total_counts:
        return _failed_estimate(data, "insufficient_total_counts")

    rows, columns = np.nonzero(data.valid)
    observed = data.observed_log_ratio[data.valid]
    nuisance = _nuisance_design(rows, columns, data.n_energy)
    q, _ = np.linalg.qr(nuisance, mode="reduced")
    nuisance_rank = int(np.linalg.matrix_rank(nuisance))
    q = q[:, :nuisance_rank]
    observed_residual = observed - q @ (q.T @ observed)
    null_rss = max(float(observed_residual @ observed_residual), np.finfo(float).tiny)
    null_coefficients, _, _, _ = np.linalg.lstsq(nuisance, observed, rcond=None)
    null_fitted = _surface_from_cells(
        nuisance @ null_coefficients,
        data.valid,
    )
    null_parameters = nuisance_rank + 1
    null_bic = _gaussian_bic(null_rss, data.n_cells, null_parameters)
    null_fit = BinaryLossConeModelFit(
        model="no_edge",
        success=True,
        reason="ok",
        mirror_ratio=None,
        delta_u_eff_eV=None,
        contrast_amplitude_log_ratio=None,
        contrast_band_center_eV=None,
        contrast_band_width_ln=None,
        residual_sum_squares=null_rss,
        bic=null_bic,
        n_parameters=null_parameters,
        n_cells=data.n_cells,
        boundary_pitch_deg=np.full(data.n_energy, np.nan, dtype=float),
        fitted_log_ratio=null_fitted,
    )

    band_parameters, band_by_energy = _contrast_band_grid(data.energy_eV, settings)
    mirror_masks = _unique_boundary_masks(data, settings, model="mirror_only")
    electrostatic_masks = _unique_boundary_masks(data, settings, model="electrostatic")
    mirror_profile = _best_profiled_surface(
        data,
        rows,
        nuisance,
        q,
        observed,
        observed_residual,
        mirror_masks,
        band_parameters,
        band_by_energy,
    )
    electrostatic_profile = _best_profiled_surface(
        data,
        rows,
        nuisance,
        q,
        observed,
        observed_residual,
        electrostatic_masks,
        band_parameters,
        band_by_energy,
    )
    mirror_fit = _model_fit(
        "mirror_only",
        mirror_profile,
        data,
        nuisance_rank + 5,
    )
    electrostatic_fit = _model_fit(
        "electrostatic",
        electrostatic_profile,
        data,
        nuisance_rank + 6,
    )
    no_edge_delta = null_fit.bic - mirror_fit.bic
    electrostatic_delta = mirror_fit.bic - electrostatic_fit.bic

    selected = null_fit
    reason = "no_edge_evidence"
    if mirror_fit.success and no_edge_delta >= settings.min_edge_delta_bic:
        selected = mirror_fit
        reason = "binary_mirror_edge_supported"
        if (
            electrostatic_fit.success
            and electrostatic_delta >= settings.min_electrostatic_delta_bic
        ):
            selected = electrostatic_fit
            reason = "binary_electrostatic_curvature_supported"
    edge_supported = selected.model != "no_edge"
    return BinaryLossConeEstimate(
        success=selected.success,
        reason=reason,
        selected_model=selected.model,
        edge_supported=edge_supported,
        mirror_ratio=selected.mirror_ratio if edge_supported else None,
        effective_field_nT=(
            None
            if not edge_supported or selected.mirror_ratio is None
            else float(counts.b_sc_nT * selected.mirror_ratio)
        ),
        delta_u_eff_eV=(selected.delta_u_eff_eV if selected.model == "electrostatic" else None),
        no_edge_delta_bic=no_edge_delta,
        electrostatic_delta_bic=electrostatic_delta,
        model_fits=(null_fit, mirror_fit, electrostatic_fit),
        energy_eV=data.energy_eV,
        pitch_deg=data.pitch_deg,
    )


def _prepare_binary_surface(
    counts: ElectronReflectionCounts,
    settings: BinaryLossConeFitSettings,
) -> _PreparedBinarySurface:
    affected = np.asarray(counts.affected_counts, dtype=float)
    reference = np.asarray(counts.reference_counts, dtype=float)
    exposure_a = np.asarray(counts.affected_exposure, dtype=float)
    exposure_r = np.asarray(counts.reference_exposure, dtype=float)
    valid = (
        np.isfinite(affected)
        & np.isfinite(reference)
        & np.isfinite(exposure_a)
        & np.isfinite(exposure_r)
        & (exposure_a > 0.0)
        & (exposure_r > 0.0)
    )
    corrected_energy = np.asarray(counts.energy_eV, dtype=float) - float(
        settings.spacecraft_potential_eV
    )
    supported = (np.count_nonzero(valid, axis=1) >= settings.min_pitch_bins_per_energy) & (
        corrected_energy > 0.0
    )
    supported_indices = np.flatnonzero(supported)
    energy = np.asarray(counts.energy_eV, dtype=float)
    order = supported_indices[np.argsort(energy[supported_indices])]
    with np.errstate(divide="ignore", invalid="ignore"):
        observed = np.log((affected + 0.5) / (reference + 0.5)) - np.log(exposure_a / exposure_r)
    observed = np.where(valid, observed, np.nan)
    return _PreparedBinarySurface(
        energy_eV=energy[order],
        pitch_deg=np.asarray(counts.pitch_deg, dtype=float),
        observed_log_ratio=np.asarray(observed[order], dtype=float),
        valid=np.asarray(valid[order], dtype=bool),
        total_counts=int(np.rint(np.nansum(affected[supported]) + np.nansum(reference[supported]))),
    )


def _nuisance_design(
    rows: NDArray[np.intp],
    columns: NDArray[np.intp],
    n_energy: int,
) -> FloatArray:
    observed_pitch = np.unique(columns)
    pitch_columns = {int(value): index for index, value in enumerate(observed_pitch[1:])}
    design = np.zeros((rows.size, n_energy + observed_pitch.size - 1), dtype=float)
    design[np.arange(rows.size), rows] = 1.0
    for cell_index, pitch_index in enumerate(columns):
        nuisance_index = pitch_columns.get(int(pitch_index))
        if nuisance_index is not None:
            design[cell_index, n_energy + nuisance_index] = 1.0
    return design


def _contrast_band_grid(
    energy_eV: FloatArray,
    settings: BinaryLossConeFitSettings,
) -> tuple[tuple[tuple[float, float], ...], FloatArray]:
    centers = np.geomspace(
        float(np.min(energy_eV)),
        float(np.max(energy_eV)),
        settings.contrast_center_grid_points,
    )
    widths = np.geomspace(
        settings.contrast_band_width_bounds_ln[0],
        settings.contrast_band_width_bounds_ln[1],
        settings.contrast_width_grid_points,
    )
    parameters: list[tuple[float, float]] = []
    values: list[FloatArray] = []
    log_energy = np.log(energy_eV)
    for center in centers:
        for width in widths:
            parameters.append((float(center), float(width)))
            values.append(np.exp(-0.5 * ((log_energy - np.log(center)) / width) ** 2))
    return tuple(parameters), np.column_stack(values)


def _unique_boundary_masks(
    data: _PreparedBinarySurface,
    settings: BinaryLossConeFitSettings,
    *,
    model: Literal["mirror_only", "electrostatic"],
) -> tuple[tuple[FloatArray, float, float], ...]:
    lower_ratio, upper_ratio = settings.mirror_ratio_bounds
    ratios = np.geomspace(lower_ratio, upper_ratio, settings.mirror_grid_points)
    delta_values = (
        np.asarray([0.0], dtype=float)
        if model == "mirror_only"
        else np.linspace(
            settings.delta_u_bounds_eV[0],
            settings.delta_u_bounds_eV[1],
            settings.delta_u_grid_points,
        )
    )
    sin2_pitch = np.sin(np.deg2rad(data.pitch_deg)) ** 2
    masks: dict[bytes, tuple[FloatArray, float, float]] = {}
    for mirror_ratio in ratios:
        for delta_u in delta_values:
            boundary = mirror_boundary_sin2(
                data.energy_eV,
                float(mirror_ratio),
                float(delta_u),
                spacecraft_potential_eV=settings.spacecraft_potential_eV,
            )
            if not _boundary_is_supported(boundary, sin2_pitch, data.valid, settings):
                continue
            mask = np.asarray(sin2_pitch[None, :] >= boundary[:, None], dtype=float)
            key = np.packbits(mask.astype(np.uint8)).tobytes()
            masks.setdefault(key, (mask, float(mirror_ratio), float(delta_u)))
    return tuple(masks.values())


def _boundary_is_supported(
    boundary: FloatArray,
    sin2_pitch: FloatArray,
    valid: NDArray[np.bool_],
    settings: BinaryLossConeFitSettings,
) -> bool:
    below = np.sum(valid & (sin2_pitch[None, :] < boundary[:, None]), axis=1)
    above = np.sum(valid & (sin2_pitch[None, :] > boundary[:, None]), axis=1)
    transition = (below >= 1) & (above >= 1)
    if np.count_nonzero(transition) < settings.min_energy_bins:
        return False
    return bool(
        np.mean((below[transition] >= 1) & (above[transition] >= 1))
        >= settings.min_boundary_bracket_fraction
        and np.mean((below[transition] >= 2) & (above[transition] >= 2))
        >= settings.min_strict_boundary_bracket_fraction
    )


def _best_profiled_surface(
    data: _PreparedBinarySurface,
    rows: NDArray[np.intp],
    nuisance: FloatArray,
    q: FloatArray,
    observed: FloatArray,
    observed_residual: FloatArray,
    masks: tuple[tuple[FloatArray, float, float], ...],
    band_parameters: tuple[tuple[float, float], ...],
    band_by_energy: FloatArray,
) -> _ProfiledSurface | None:
    null_rss = float(observed_residual @ observed_residual)
    best_rss = np.inf
    best: tuple[FloatArray, float, float, int, float] | None = None
    for mask, mirror_ratio, delta_u in masks:
        regressors = mask[data.valid, None] * band_by_energy[rows, :]
        residualized = regressors - q @ (q.T @ regressors)
        denominator = np.sum(residualized**2, axis=0)
        numerator = observed_residual @ residualized
        usable = denominator > 1.0e-12
        amplitude = np.divide(
            np.maximum(numerator, 0.0),
            denominator,
            out=np.zeros_like(numerator),
            where=usable,
        )
        rss = null_rss - amplitude**2 * denominator
        index = int(np.argmin(rss))
        if usable[index] and float(rss[index]) < best_rss:
            best_rss = float(rss[index])
            best = (mask, mirror_ratio, delta_u, index, float(amplitude[index]))
    if best is None:
        return None
    mask, mirror_ratio, delta_u, band_index, amplitude = best
    center, width = band_parameters[band_index]
    edge_regressor = mask[data.valid] * band_by_energy[rows, band_index]
    nuisance_coefficients, _, _, _ = np.linalg.lstsq(
        nuisance,
        observed - amplitude * edge_regressor,
        rcond=None,
    )
    fitted_cells = nuisance @ nuisance_coefficients + amplitude * edge_regressor
    boundary = mirror_boundary_sin2(data.energy_eV, mirror_ratio, delta_u)
    physical = (boundary > 0.0) & (boundary < 1.0)
    boundary_pitch = np.full(data.n_energy, np.nan, dtype=float)
    boundary_pitch[physical] = np.rad2deg(np.arcsin(np.sqrt(boundary[physical])))
    return _ProfiledSurface(
        mirror_ratio=mirror_ratio,
        delta_u_eff_eV=delta_u,
        contrast_amplitude=amplitude,
        contrast_center_eV=center,
        contrast_width_ln=width,
        residual_sum_squares=max(best_rss, np.finfo(float).tiny),
        fitted_log_ratio=_surface_from_cells(fitted_cells, data.valid),
        boundary_pitch_deg=boundary_pitch,
    )


def _model_fit(
    model: Literal["mirror_only", "electrostatic"],
    profile: _ProfiledSurface | None,
    data: _PreparedBinarySurface,
    n_parameters: int,
) -> BinaryLossConeModelFit:
    if profile is None:
        return BinaryLossConeModelFit(
            model=model,
            success=False,
            reason="no_supported_boundary_grid_cell",
            mirror_ratio=None,
            delta_u_eff_eV=None,
            contrast_amplitude_log_ratio=None,
            contrast_band_center_eV=None,
            contrast_band_width_ln=None,
            residual_sum_squares=float("inf"),
            bic=float("inf"),
            n_parameters=n_parameters,
            n_cells=data.n_cells,
            boundary_pitch_deg=np.full(data.n_energy, np.nan, dtype=float),
            fitted_log_ratio=np.full(data.valid.shape, np.nan, dtype=float),
        )
    return BinaryLossConeModelFit(
        model=model,
        success=True,
        reason="ok",
        mirror_ratio=profile.mirror_ratio,
        delta_u_eff_eV=(profile.delta_u_eff_eV if model == "electrostatic" else None),
        contrast_amplitude_log_ratio=profile.contrast_amplitude,
        contrast_band_center_eV=profile.contrast_center_eV,
        contrast_band_width_ln=profile.contrast_width_ln,
        residual_sum_squares=profile.residual_sum_squares,
        bic=_gaussian_bic(profile.residual_sum_squares, data.n_cells, n_parameters),
        n_parameters=n_parameters,
        n_cells=data.n_cells,
        boundary_pitch_deg=profile.boundary_pitch_deg,
        fitted_log_ratio=profile.fitted_log_ratio,
    )


def _gaussian_bic(rss: float, n_cells: int, n_parameters: int) -> float:
    return float(n_cells * np.log(rss / n_cells) + n_parameters * np.log(n_cells))


def _surface_from_cells(values: FloatArray, valid: NDArray[np.bool_]) -> FloatArray:
    surface = np.full(valid.shape, np.nan, dtype=float)
    surface[valid] = values
    return surface


def _failed_estimate(
    data: _PreparedBinarySurface,
    reason: str,
) -> BinaryLossConeEstimate:
    fits = tuple(
        BinaryLossConeModelFit(
            model=model,
            success=False,
            reason=reason,
            mirror_ratio=None,
            delta_u_eff_eV=None,
            contrast_amplitude_log_ratio=None,
            contrast_band_center_eV=None,
            contrast_band_width_ln=None,
            residual_sum_squares=float("inf"),
            bic=float("inf"),
            n_parameters=0,
            n_cells=data.n_cells,
            boundary_pitch_deg=np.full(data.n_energy, np.nan, dtype=float),
            fitted_log_ratio=np.full(data.valid.shape, np.nan, dtype=float),
        )
        for model in cast(tuple[CandidateModel, ...], ("no_edge", "mirror_only", "electrostatic"))
    )
    return BinaryLossConeEstimate(
        success=False,
        reason=reason,
        selected_model="no_edge",
        edge_supported=False,
        mirror_ratio=None,
        effective_field_nT=None,
        delta_u_eff_eV=None,
        no_edge_delta_bic=float("-inf"),
        electrostatic_delta_bic=float("-inf"),
        model_fits=fits,
        energy_eV=data.energy_eV,
        pitch_deg=data.pitch_deg,
    )
