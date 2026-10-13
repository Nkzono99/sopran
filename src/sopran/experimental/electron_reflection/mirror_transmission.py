"""Robust mirror-transmission model for a reference-ratio pitch distribution.

A comparison estimator ported from lunarsat (``robust_mirror_transmission_
log_ratio_v1``). The affected/reference ratio is modelled in log space as
``a_j + A_j P(E_j, alpha_k)`` with per-energy baseline ``a_j`` and contrast
``A_j`` nuisance terms, and one shared boundary across energy:

``sin^2(alpha_c) = p0 (1 + (DeltaU + smooth(E)) / E)``,
``P = Phi((ln sin^2 alpha - ln sin^2 alpha_c) / sigma(E))``,

where ``p0 = B_sc / B_eff`` is the high-energy asymptote, ``sigma`` is a
log-width (constant or energy-broadened) and ``smooth`` is an optional
low-energy correction with the same high-energy limit. The fit minimises a
soft-L1 loss with ``scipy.optimize.least_squares``. Compared with the
lunarsat implementation the initial boundary guess is simpler (threshold
crossings per energy row); the model, bounds and loss are the same.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from sopran.experimental.electron_reflection.common import ElectronReflectionCounts

FloatArray = NDArray[np.float64]
MODEL_ID = "robust_mirror_transmission_log_ratio_v1"
DEFAULT_DELTA_U_BOUNDS_EV = (-1000.0, 1000.0)


@dataclass(frozen=True)
class MirrorTransmissionSettings:
    """Bounds, nuisance ranges and robust loss of the mirror-transmission fit."""

    min_energy_bins: int = 3
    min_pitch_bins_per_energy: int = 6
    min_profile_contrast: float = 0.03
    boundary_model: str = "electrostatic"
    width_model: str = "constant"
    p0_bounds: tuple[float, float] = (0.01, 0.99)
    delta_u_bounds_eV: tuple[float, float] = DEFAULT_DELTA_U_BOUNDS_EV
    fixed_delta_u_eff_eV: float | None = None
    spacecraft_potential_eV: float = 0.0
    smooth_energy_eV: float = 300.0
    smooth_beta_bounds_eV: tuple[float, float] = (-300.0, 300.0)
    initial_smooth_beta1_eV: float = 0.0
    initial_smooth_beta2_eV: float = 0.0
    smooth_beta_regularization_eV: float | None = 150.0
    sigma_ln_b_bounds: tuple[float, float] = (0.03, 1.5)
    initial_sigma_ln_b: float = 0.20
    width_u_bounds_eV: tuple[float, float] = (0.0, 600.0)
    initial_width_u_eV: float = 0.0
    width_energy_e0_eV: float = 100.0
    width_u_regularization_eV: float | None = 250.0
    baseline_bounds_log: tuple[float, float] = (-8.0, 4.0)
    amplitude_bounds_log: tuple[float, float] = (0.0, 8.0)
    ratio_epsilon: float = 1.0e-12
    robust_loss: str = "soft_l1"
    robust_f_scale: float = 0.20
    max_nfev: int = 8000

    def metadata(self) -> dict[str, Any]:
        return {"model_id": MODEL_ID, **asdict(self)}


@dataclass(frozen=True)
class MirrorTransmissionFit:
    """Fit result; ``success`` requires a converged optimiser and an interior boundary."""

    success: bool
    b_eff_nT: float | None
    delta_u_eff_eV: float | None
    sigma_ln_b: float | None
    p0: float | None
    p1: float | None
    n_energy_bins: int
    n_points: int
    rmse_log: float | None
    r2_log: float | None
    fail_reason: str
    cost: float | None = None
    nfev: int | None = None
    model_id: str = MODEL_ID
    n_input_energy_bins: int | None = None
    n_input_points: int | None = None
    b_sc_reference_nT: float | None = None
    boundary_model: str | None = None
    width_model: str | None = None
    spacecraft_potential_eV: float | None = None
    smooth_beta1_eV: float | None = None
    smooth_beta2_eV: float | None = None
    width_u_eV: float | None = None
    p0_at_bound: bool | None = None
    delta_u_eff_at_bound: bool | None = None
    sigma_ln_b_at_bound: bool | None = None
    no_edge_rmse_log: float | None = None
    no_edge_r2_log: float | None = None
    rss_log: float | None = None
    n_model_parameters: int | None = None
    aic_log: float | None = None
    bic_log: float | None = None
    energy_eV: tuple[float, ...] | None = None
    alpha_lc_deg: tuple[float, ...] | None = None
    boundary_sin2: tuple[float, ...] | None = None
    baseline_by_energy: tuple[float, ...] | None = None
    amplitude_by_energy: tuple[float, ...] | None = None

    @property
    def mirror_ratio(self) -> float | None:
        return None if self.p0 is None or self.p0 <= 0.0 else 1.0 / self.p0

    def to_row(self, prefix: str = "", *, include_diagnostics: bool = False) -> dict[str, Any]:
        row = asdict(self)
        if not include_diagnostics:
            for key in (
                "energy_eV",
                "alpha_lc_deg",
                "boundary_sin2",
                "baseline_by_energy",
                "amplitude_by_energy",
            ):
                row.pop(key, None)
        return row if not prefix else {f"{prefix}{key}": value for key, value in row.items()}


@dataclass(frozen=True)
class MirrorTransmissionVariantFit:
    label: str
    settings: MirrorTransmissionSettings
    fit: MirrorTransmissionFit


def boundary_sin2(
    energy_eV: ArrayLike,
    p0: float,
    delta_u_eff_eV: float,
    *,
    smooth_beta1_eV: float = 0.0,
    smooth_beta2_eV: float = 0.0,
    smooth_energy_eV: float = 300.0,
    spacecraft_potential_eV: float = 0.0,
) -> FloatArray:
    """``p0 (1 + (DeltaU + beta1 s^2 + beta2 s^3) / E')`` with ``s = E* / (E' + E*)``."""

    energy = np.asarray(energy_eV, dtype=float)
    corrected = energy - float(spacecraft_potential_eV)
    e_star = float(smooth_energy_eV)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        smooth = e_star / (corrected + e_star)
        delta = float(smooth_beta1_eV) * smooth**2 + float(smooth_beta2_eV) * smooth**3
        out = float(p0) * (1.0 + (float(delta_u_eff_eV) + delta) / corrected)
    valid = (
        np.isfinite(corrected)
        & (corrected > 0.0)
        & np.isfinite(e_star)
        & (e_star > 0.0)
        & np.isfinite(out)
    )
    return np.asarray(np.where(valid, out, np.nan), dtype=float)


def width_ln(
    energy_eV: ArrayLike,
    sigma_ln_b: float,
    *,
    width_u_eV: float = 0.0,
    width_energy_e0_eV: float = 100.0,
    spacecraft_potential_eV: float = 0.0,
) -> FloatArray:
    """Log-width ``sqrt(sigma^2 + (U_w / (E' + E0))^2)`` per energy."""

    energy = np.asarray(energy_eV, dtype=float)
    corrected = energy - float(spacecraft_potential_eV)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        out = np.sqrt(
            float(sigma_ln_b) ** 2
            + (float(width_u_eV) / (corrected + float(width_energy_e0_eV))) ** 2
        )
    valid = (
        np.isfinite(corrected)
        & (corrected > 0.0)
        & (float(sigma_ln_b) > 0.0)
        & (float(width_u_eV) >= 0.0)
        & (corrected + float(width_energy_e0_eV) > 0.0)
        & np.isfinite(out)
        & (out > 0.0)
    )
    return np.asarray(np.where(valid, out, np.nan), dtype=float)


def transmission_probability(
    pitch_deg: ArrayLike,
    energy_eV: ArrayLike,
    p0: float,
    p1: float,
    sigma_ln_b: float,
    *,
    spacecraft_potential_eV: float = 0.0,
    smooth_beta1_eV: float = 0.0,
    smooth_beta2_eV: float = 0.0,
    smooth_energy_eV: float = 300.0,
    width_u_eV: float = 0.0,
    width_energy_e0_eV: float = 100.0,
) -> FloatArray:
    """Reflection probability ``Phi((ln x - ln x_c) / sigma)`` with ``x = sin^2(alpha)``."""

    from scipy.special import ndtr  # type: ignore[import-untyped]

    pitch = np.asarray(pitch_deg, dtype=float)
    energy = np.asarray(energy_eV, dtype=float)
    if pitch.ndim != 1 or energy.ndim != 1:
        raise ValueError("pitch_deg and energy_eV must be one-dimensional")
    delta_u = float(p1) / float(p0) if float(p0) != 0.0 else np.nan
    corrected = energy - float(spacecraft_potential_eV)
    sigma = width_ln(
        energy,
        sigma_ln_b,
        width_u_eV=width_u_eV,
        width_energy_e0_eV=width_energy_e0_eV,
        spacecraft_potential_eV=spacecraft_potential_eV,
    )
    x_c = boundary_sin2(
        energy,
        p0,
        delta_u,
        smooth_beta1_eV=smooth_beta1_eV,
        smooth_beta2_eV=smooth_beta2_eV,
        smooth_energy_eV=smooth_energy_eV,
        spacecraft_potential_eV=spacecraft_potential_eV,
    )
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        x = np.clip(np.sin(np.deg2rad(pitch)) ** 2, 1.0e-12, 1.0 - 1.0e-12)
        z = (np.log(x)[None, :] - np.log(x_c)[:, None]) / sigma[:, None]
        out = ndtr(z)
    valid = (
        np.isfinite(out)
        & np.isfinite(corrected[:, None])
        & (corrected[:, None] > 0.0)
        & np.isfinite(x_c[:, None])
        & (x_c[:, None] > 0.0)
        & (x_c[:, None] < 1.0)
        & np.isfinite(sigma[:, None])
    )
    return np.asarray(np.where(valid, out, np.nan), dtype=float)


def log_ratio_model(
    pitch_deg: ArrayLike,
    energy_eV: ArrayLike,
    p0: float,
    p1: float,
    sigma_ln_b: float,
    baseline_by_energy: ArrayLike,
    amplitude_by_energy: ArrayLike,
    **model: Any,
) -> FloatArray:
    """``a_j + A_j P(E_j, alpha_k)`` in natural-log ratio units."""

    probability = transmission_probability(pitch_deg, energy_eV, p0, p1, sigma_ln_b, **model)
    baseline = np.asarray(baseline_by_energy, dtype=float)
    amplitude = np.asarray(amplitude_by_energy, dtype=float)
    if baseline.shape != (probability.shape[0],) or amplitude.shape != (probability.shape[0],):
        raise ValueError(
            "baseline_by_energy and amplitude_by_energy must have one value per energy"
        )
    with np.errstate(invalid="ignore"):
        out = baseline[:, None] + amplitude[:, None] * probability
    return np.asarray(np.where(np.isfinite(out), out, np.nan), dtype=float)


def variant_settings(
    base: MirrorTransmissionSettings | None = None,
) -> tuple[tuple[str, MirrorTransmissionSettings], ...]:
    """The nested variants: mirror only, electrostatic, smooth low energy, smooth width."""

    settings = base or MirrorTransmissionSettings()
    return (
        (
            "mirror_only",
            replace(
                settings,
                boundary_model="mirror_only",
                width_model="constant",
                fixed_delta_u_eff_eV=0.0,
            ),
        ),
        (
            "electrostatic",
            replace(settings, boundary_model="electrostatic", width_model="constant"),
        ),
        (
            "smooth_low_energy",
            replace(settings, boundary_model="smooth_low_energy", width_model="constant"),
        ),
        (
            "smooth_width",
            replace(settings, boundary_model="smooth_low_energy", width_model="energy_broadened"),
        ),
    )


def ratio_from_counts(
    counts: ElectronReflectionCounts,
) -> tuple[FloatArray, FloatArray, FloatArray, float]:
    """``(energy_eV, pitch_deg, affected/reference rate ratio, b_sc_nT)`` from paired counts."""

    affected = np.asarray(counts.affected_counts, dtype=float) / np.asarray(
        counts.affected_exposure, dtype=float
    )
    reference = np.asarray(counts.reference_counts, dtype=float) / np.asarray(
        counts.reference_exposure, dtype=float
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(reference > 0.0, affected / reference, np.nan)
    return (
        np.asarray(counts.energy_eV, dtype=float),
        np.asarray(counts.pitch_deg, dtype=float),
        np.asarray(ratio, dtype=float),
        float(counts.b_sc_nT),
    )


def fit_mirror_transmission(
    energy_eV: ArrayLike,
    pitch_deg: ArrayLike,
    ratio: ArrayLike,
    b_sc_nT: float | ArrayLike,
    *,
    settings: MirrorTransmissionSettings | None = None,
) -> MirrorTransmissionFit:
    """Fit the shared boundary and log-width to a ``(energy, pitch)`` ratio PAD."""

    selected = settings or MirrorTransmissionSettings()
    try:
        energy, pitch, pad, b_sc = _inputs(energy_eV, pitch_deg, ratio, b_sc_nT)
    except ValueError as exc:
        return _failed(f"input_error:{exc}", 0, 0)
    n_input_energy = int(energy.size)
    n_input_points = int(np.count_nonzero(np.isfinite(pad)))
    potential = float(selected.spacecraft_potential_eV)
    eps = float(selected.ratio_epsilon)
    with np.errstate(divide="ignore", invalid="ignore"):
        y_all = np.log(np.where(pad > eps, pad, np.nan))
    accepted, edges = _screen_rows(
        energy,
        pitch,
        y_all,
        potential,
        min_pitch_bins=int(selected.min_pitch_bins_per_energy),
        min_contrast=float(selected.min_profile_contrast),
    )
    rows = np.flatnonzero(accepted)
    failed_common = dict(n_input_energy_bins=n_input_energy, n_input_points=n_input_points)
    if rows.size < int(selected.min_energy_bins):
        return _failed("too_few_supported_energy_bins", int(rows.size), 0, **failed_common)
    energy_fit = energy[rows]
    corrected = energy_fit - potential
    b_sc_fit = b_sc[rows]
    y = y_all[rows]
    finite = np.isfinite(y) & (pitch[None, :] >= 0.0) & (pitch[None, :] <= 90.0)
    n_points = int(np.count_nonzero(finite))
    if n_points == 0:
        return _failed("no_positive_finite_pad_points", int(rows.size), 0, **failed_common)
    reason = _validate(selected, corrected)
    if reason:
        return _failed(reason, int(rows.size), n_points, **failed_common)
    b_sc_reference = float(np.nanmedian(b_sc_fit))
    if not np.isfinite(b_sc_reference) or b_sc_reference <= 0.0:
        return _failed("invalid_b_sc_reference", int(rows.size), n_points, **failed_common)
    smooth_active = selected.boundary_model == "smooth_low_energy"
    width_active = selected.width_model == "energy_broadened"
    p0_lo, p0_hi = selected.p0_bounds
    delta_lo, delta_hi = selected.delta_u_bounds_eV
    delta_lo = max(float(delta_lo), -0.95 * float(np.nanmin(corrected)))
    sigma_lo, sigma_hi = selected.sigma_ln_b_bounds
    beta_lo, beta_hi = selected.smooth_beta_bounds_eV
    width_lo, width_hi = selected.width_u_bounds_eV
    base_lo, base_hi = selected.baseline_bounds_log
    amp_lo, amp_hi = selected.amplitude_bounds_log
    fixed_delta = 0.0 if selected.boundary_model == "mirror_only" else selected.fixed_delta_u_eff_eV
    fixed = fixed_delta is not None
    initial_p0, initial_delta = _initial_boundary(
        corrected, edges[rows], fixed_delta, (p0_lo, p0_hi), (delta_lo, delta_hi)
    )
    baseline0, amplitude0 = _initial_row_terms(y, finite, (base_lo, base_hi), (amp_lo, amp_hi))
    core = [initial_p0]
    lower = [p0_lo]
    upper = [p0_hi]
    if not fixed:
        core.append(initial_delta)
        lower.append(delta_lo)
        upper.append(delta_hi)
    core.append(float(np.clip(selected.initial_sigma_ln_b, sigma_lo + 1e-9, sigma_hi - 1e-9)))
    lower.append(sigma_lo)
    upper.append(sigma_hi)
    if smooth_active:
        core.extend(
            [
                float(np.clip(selected.initial_smooth_beta1_eV, beta_lo + 1e-9, beta_hi - 1e-9)),
                float(np.clip(selected.initial_smooth_beta2_eV, beta_lo + 1e-9, beta_hi - 1e-9)),
            ]
        )
        lower.extend([beta_lo, beta_lo])
        upper.extend([beta_hi, beta_hi])
    if width_active:
        core.append(float(np.clip(selected.initial_width_u_eV, width_lo + 1e-9, width_hi - 1e-9)))
        lower.append(width_lo)
        upper.append(width_hi)
    n_rows = rows.size
    x0 = np.asarray([*core, *baseline0, *amplitude0], dtype=float)
    lower_array = np.asarray([*lower, *([base_lo] * n_rows), *([amp_lo] * n_rows)], dtype=float)
    upper_array = np.asarray([*upper, *([base_hi] * n_rows), *([amp_hi] * n_rows)], dtype=float)
    n_core = len(core)

    def unpack(
        params: FloatArray,
    ) -> tuple[float, float, float, float, float, float, FloatArray, FloatArray]:
        index = 0
        p0 = float(params[index])
        index += 1
        if fixed:
            delta = float(fixed_delta)  # type: ignore[arg-type]
        else:
            delta = float(params[index])
            index += 1
        sigma = float(params[index])
        index += 1
        beta1 = beta2 = 0.0
        if smooth_active:
            beta1, beta2 = float(params[index]), float(params[index + 1])
            index += 2
        width_u = float(params[index]) if width_active else 0.0
        baseline = params[n_core : n_core + n_rows]
        amplitude = params[n_core + n_rows : n_core + 2 * n_rows]
        return p0, delta, sigma, beta1, beta2, width_u, baseline, amplitude

    def model(params: FloatArray) -> FloatArray:
        p0, delta, sigma, beta1, beta2, width_u, baseline, amplitude = unpack(params)
        return log_ratio_model(
            pitch,
            energy_fit,
            p0,
            p0 * delta,
            sigma,
            baseline,
            amplitude,
            spacecraft_potential_eV=potential,
            smooth_beta1_eV=beta1,
            smooth_beta2_eV=beta2,
            smooth_energy_eV=float(selected.smooth_energy_eV),
            width_u_eV=width_u,
            width_energy_e0_eV=float(selected.width_energy_e0_eV),
        )

    def residual(params: FloatArray) -> FloatArray:
        out = np.asarray(model(params)[finite] - y[finite], dtype=float)
        out[~np.isfinite(out)] = 1.0e6
        penalties = []
        _, _, _, beta1, beta2, width_u, _, _ = unpack(params)
        reg = selected.smooth_beta_regularization_eV
        if smooth_active and reg is not None and float(reg) > 0.0:
            penalties.extend([beta1 / float(reg), beta2 / float(reg)])
        width_reg = selected.width_u_regularization_eV
        if width_active and width_reg is not None and float(width_reg) > 0.0:
            penalties.append(width_u / float(width_reg))
        return np.concatenate([out, np.asarray(penalties, dtype=float)]) if penalties else out

    from scipy.optimize import least_squares  # type: ignore[import-untyped]

    try:
        opt = least_squares(
            residual,
            x0=x0,
            bounds=(lower_array, upper_array),
            loss=selected.robust_loss,
            f_scale=selected.robust_f_scale,
            max_nfev=selected.max_nfev,
        )
    except Exception as exc:
        return _failed(
            f"least_squares_exception:{type(exc).__name__}", int(n_rows), n_points, **failed_common
        )
    p0_fit, delta_fit, sigma_fit, beta1_fit, beta2_fit, width_fit, baseline_fit, amplitude_fit = (
        unpack(opt.x)
    )
    prediction = model(opt.x)
    resid = prediction[finite] - y[finite]
    keep = np.isfinite(resid)
    resid = resid[keep]
    observed = y[finite][keep]
    rmse_value = float(np.sqrt(np.mean(resid**2))) if resid.size else float("nan")
    ss_res = float(np.sum(resid**2)) if resid.size else float("nan")
    ss_tot = float(np.sum((observed - observed.mean()) ** 2)) if observed.size else float("nan")
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else float("nan")
    row_means = np.array(
        [np.nanmean(y[i][finite[i]]) if np.any(finite[i]) else np.nan for i in range(n_rows)]
    )
    no_edge = np.broadcast_to(row_means[:, None], y.shape)[finite][keep] - observed
    no_edge_rmse = float(np.sqrt(np.mean(no_edge**2))) if no_edge.size else float("nan")
    no_edge_r2 = 1.0 - float(np.sum(no_edge**2)) / ss_tot if ss_tot > 0.0 else float("nan")
    n_parameters = int(opt.x.size)
    if resid.size and np.isfinite(ss_res):
        variance = max(ss_res / resid.size, 1.0e-300)
        aic = float(resid.size * math.log(variance) + 2.0 * n_parameters)
        bic = float(resid.size * math.log(variance) + n_parameters * math.log(resid.size))
    else:
        aic = bic = float("nan")
    sin2 = boundary_sin2(
        energy_fit,
        p0_fit,
        delta_fit,
        smooth_beta1_eV=beta1_fit,
        smooth_beta2_eV=beta2_fit,
        smooth_energy_eV=float(selected.smooth_energy_eV),
        spacecraft_potential_eV=potential,
    )
    domain_ok = bool(np.all(np.isfinite(sin2) & (sin2 > 0.0) & (sin2 < 1.0)))
    with np.errstate(invalid="ignore"):
        alpha = np.rad2deg(np.arcsin(np.sqrt(np.clip(sin2, 0.0, 1.0))))
    success = bool(opt.success and domain_ok and np.isfinite(rmse_value))
    reason = (
        "ok"
        if success
        else ("losscone_domain" if opt.success else f"optimizer_not_successful:{opt.message}")
    )
    return MirrorTransmissionFit(
        success=success,
        b_eff_nT=_finite(b_sc_reference / p0_fit) if p0_fit > 0.0 else None,
        delta_u_eff_eV=_finite(delta_fit),
        sigma_ln_b=_finite(sigma_fit),
        p0=_finite(p0_fit),
        p1=_finite(p0_fit * delta_fit),
        n_energy_bins=int(n_rows),
        n_points=n_points,
        rmse_log=_finite(rmse_value),
        r2_log=_finite(r2),
        fail_reason=reason,
        cost=_finite(float(opt.cost)),
        nfev=int(opt.nfev),
        n_input_energy_bins=n_input_energy,
        n_input_points=n_input_points,
        b_sc_reference_nT=_finite(b_sc_reference),
        boundary_model=selected.boundary_model,
        width_model=selected.width_model,
        spacecraft_potential_eV=potential,
        smooth_beta1_eV=_finite(beta1_fit) if smooth_active else None,
        smooth_beta2_eV=_finite(beta2_fit) if smooth_active else None,
        width_u_eV=_finite(width_fit) if width_active else None,
        p0_at_bound=_at_bound(p0_fit, (p0_lo, p0_hi)),
        delta_u_eff_at_bound=False if fixed else _at_bound(delta_fit, (delta_lo, delta_hi)),
        sigma_ln_b_at_bound=_at_bound(sigma_fit, (sigma_lo, sigma_hi)),
        no_edge_rmse_log=_finite(no_edge_rmse),
        no_edge_r2_log=_finite(no_edge_r2),
        rss_log=_finite(ss_res),
        n_model_parameters=n_parameters,
        aic_log=_finite(aic),
        bic_log=_finite(bic),
        energy_eV=tuple(float(v) for v in energy_fit),
        alpha_lc_deg=tuple(float(v) for v in alpha),
        boundary_sin2=tuple(float(v) for v in sin2),
        baseline_by_energy=tuple(float(v) for v in baseline_fit),
        amplitude_by_energy=tuple(float(v) for v in amplitude_fit),
    )


def fit_mirror_transmission_variants(
    energy_eV: ArrayLike,
    pitch_deg: ArrayLike,
    ratio: ArrayLike,
    b_sc_nT: float | ArrayLike,
    *,
    base_settings: MirrorTransmissionSettings | None = None,
    variants: Sequence[tuple[str, MirrorTransmissionSettings]] | None = None,
) -> tuple[MirrorTransmissionVariantFit, ...]:
    """Fit the nested variant suite for model comparison (AIC/BIC in each fit)."""

    selected = tuple(variants) if variants is not None else variant_settings(base_settings)
    return tuple(
        MirrorTransmissionVariantFit(
            label=label,
            settings=settings,
            fit=fit_mirror_transmission(energy_eV, pitch_deg, ratio, b_sc_nT, settings=settings),
        )
        for label, settings in selected
    )


def _inputs(
    energy_eV: ArrayLike, pitch_deg: ArrayLike, ratio: ArrayLike, b_sc_nT: float | ArrayLike
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    energy = np.asarray(energy_eV, dtype=float).reshape(-1)
    pitch = np.asarray(pitch_deg, dtype=float).reshape(-1)
    pad = np.asarray(ratio, dtype=float)
    if pad.shape != (energy.size, pitch.size):
        raise ValueError("ratio must have shape (energy, pitch)")
    if not np.all(np.isfinite(energy)) or np.any(energy <= 0.0):
        raise ValueError("energy_eV must be finite and positive")
    if not np.all(np.isfinite(pitch)):
        raise ValueError("pitch_deg must be finite")
    b_sc = np.broadcast_to(np.asarray(b_sc_nT, dtype=float), (energy.size,)).astype(float)
    if np.any(~np.isfinite(b_sc)) or np.any(b_sc <= 0.0):
        raise ValueError("b_sc_nT must be finite and positive")
    return energy, pitch, pad, b_sc


def _screen_rows(
    energy: FloatArray,
    pitch: FloatArray,
    y: FloatArray,
    potential: float,
    *,
    min_pitch_bins: int,
    min_contrast: float,
) -> tuple[NDArray[np.bool_], FloatArray]:
    """Rows with enough finite cells and a depletion at small pitch; edge guess per row."""

    rows = energy.size
    accepted = np.zeros(rows, dtype=bool)
    edges = np.full(rows, np.nan)
    order = np.argsort(pitch)
    for i in range(rows):
        finite = np.isfinite(y[i]) & (pitch >= 0.0) & (pitch <= 90.0)
        if energy[i] - potential <= 0.0 or np.count_nonzero(finite) < min_pitch_bins:
            continue
        values = y[i][order]
        mask = finite[order]
        valid = values[mask]
        low = float(np.nanmedian(valid[: max(2, valid.size // 4)]))
        high = float(np.nanmedian(valid[-max(2, valid.size // 4) :]))
        if (
            not np.isfinite(low)
            or not np.isfinite(high)
            or (high - low) < math.log(1.0 + min_contrast)
        ):
            continue
        threshold = 0.5 * (low + high)
        crossing = np.flatnonzero(
            (values[:-1] < threshold) & (values[1:] >= threshold) & mask[:-1] & mask[1:]
        )
        if crossing.size == 0:
            continue
        k = int(crossing[0])
        p_sorted = pitch[order]
        fraction = (
            (threshold - values[k]) / (values[k + 1] - values[k])
            if values[k + 1] != values[k]
            else 0.5
        )
        edges[i] = float(
            p_sorted[k] + np.clip(fraction, 0.0, 1.0) * (p_sorted[k + 1] - p_sorted[k])
        )
        accepted[i] = True
    return accepted, edges


def _initial_boundary(
    corrected: FloatArray,
    edges_deg: FloatArray,
    fixed_delta: float | None,
    p0_bounds: tuple[float, float],
    delta_bounds: tuple[float, float],
) -> tuple[float, float]:
    sin2 = np.sin(np.deg2rad(edges_deg)) ** 2
    finite = np.isfinite(sin2) & np.isfinite(corrected) & (corrected > 0.0)
    initial_p0 = 0.25
    initial_delta = 0.0 if fixed_delta is None else float(fixed_delta)
    if np.count_nonzero(finite) >= 2:
        design = np.column_stack([np.ones(np.count_nonzero(finite)), 1.0 / corrected[finite]])
        try:
            solution, *_ = np.linalg.lstsq(design, sin2[finite], rcond=None)
            if solution[0] > 0.0:
                initial_p0 = float(solution[0])
                if fixed_delta is None:
                    initial_delta = float(solution[1] / solution[0])
        except np.linalg.LinAlgError:
            pass
    elif np.any(finite):
        initial_p0 = float(np.nanmedian(sin2[finite]))
    initial_delta = float(np.clip(initial_delta, delta_bounds[0] + 1e-9, delta_bounds[1] - 1e-9))
    factor = float(np.nanmax(1.0 + initial_delta / corrected))
    if np.isfinite(factor) and factor > 0.0:
        initial_p0 = min(initial_p0, 0.98 / factor)
    return float(np.clip(initial_p0, p0_bounds[0] + 1e-9, p0_bounds[1] - 1e-9)), initial_delta


def _initial_row_terms(
    y: FloatArray,
    finite: NDArray[np.bool_],
    baseline_bounds: tuple[float, float],
    amplitude_bounds: tuple[float, float],
) -> tuple[list[float], list[float]]:
    baselines = []
    amplitudes = []
    for row, mask in zip(y, finite, strict=True):
        values = row[mask]
        if values.size:
            low = float(np.nanpercentile(values, 20.0))
            high = float(np.nanpercentile(values, 80.0))
        else:
            low, high = 0.0, 1.0
        baselines.append(float(np.clip(low, baseline_bounds[0] + 1e-6, baseline_bounds[1] - 1e-6)))
        amplitudes.append(
            float(np.clip(high - low, amplitude_bounds[0] + 1e-6, amplitude_bounds[1] - 1e-6))
        )
    return baselines, amplitudes


def _validate(settings: MirrorTransmissionSettings, corrected: FloatArray) -> str:
    p0_lo, p0_hi = settings.p0_bounds
    delta_lo, delta_hi = settings.delta_u_bounds_eV
    delta_lo = max(float(delta_lo), -0.95 * float(np.nanmin(corrected)))
    sigma_lo, sigma_hi = settings.sigma_ln_b_bounds
    beta_lo, beta_hi = settings.smooth_beta_bounds_eV
    width_lo, width_hi = settings.width_u_bounds_eV
    base_lo, base_hi = settings.baseline_bounds_log
    amp_lo, amp_hi = settings.amplitude_bounds_log
    smooth = settings.boundary_model == "smooth_low_energy"
    width = settings.width_model == "energy_broadened"
    fixed = 0.0 if settings.boundary_model == "mirror_only" else settings.fixed_delta_u_eff_eV
    if settings.boundary_model not in {"mirror_only", "electrostatic", "smooth_low_energy"}:
        return f"invalid_boundary_model:{settings.boundary_model}"
    if settings.width_model not in {"constant", "energy_broadened"}:
        return f"invalid_width_model:{settings.width_model}"
    if settings.boundary_model == "mirror_only" and settings.fixed_delta_u_eff_eV not in (
        None,
        0.0,
    ):
        return "mirror_only_requires_zero_delta_u"
    if not (0.0 < p0_lo < p0_hi < 1.0):
        return "invalid_p0_bounds"
    if not (np.isfinite(delta_lo) and np.isfinite(delta_hi) and delta_lo < delta_hi):
        return "invalid_delta_u_bounds"
    if fixed is not None and not (np.isfinite(fixed) and delta_lo <= float(fixed) <= delta_hi):
        return "fixed_delta_u_outside_bounds"
    if not (0.0 < sigma_lo < sigma_hi):
        return "invalid_sigma_ln_b_bounds"
    if smooth and not (np.isfinite(settings.smooth_energy_eV) and settings.smooth_energy_eV > 0.0):
        return "invalid_smooth_energy_eV"
    if smooth and not (beta_lo < beta_hi):
        return "invalid_smooth_beta_bounds_eV"
    if width and not (0.0 <= width_lo < width_hi):
        return "invalid_width_u_bounds_eV"
    if width and not (
        np.isfinite(settings.width_energy_e0_eV) and settings.width_energy_e0_eV >= 0.0
    ):
        return "invalid_width_energy_e0_eV"
    if not (base_lo < base_hi) or not (amp_lo < amp_hi):
        return "invalid_nuisance_bounds"
    return ""


def _failed(reason: str, n_energy_bins: int, n_points: int, **extra: Any) -> MirrorTransmissionFit:
    return MirrorTransmissionFit(
        success=False,
        b_eff_nT=None,
        delta_u_eff_eV=None,
        sigma_ln_b=None,
        p0=None,
        p1=None,
        n_energy_bins=n_energy_bins,
        n_points=n_points,
        rmse_log=None,
        r2_log=None,
        fail_reason=reason,
        **extra,
    )


def _finite(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def _at_bound(value: float, bounds: tuple[float, float], tolerance: float = 1.0e-6) -> bool:
    span = max(abs(bounds[1] - bounds[0]), 1.0e-12)
    return bool(
        abs(value - bounds[0]) <= tolerance * span or abs(bounds[1] - value) <= tolerance * span
    )


__all__ = [
    "DEFAULT_DELTA_U_BOUNDS_EV",
    "MODEL_ID",
    "MirrorTransmissionFit",
    "MirrorTransmissionSettings",
    "MirrorTransmissionVariantFit",
    "boundary_sin2",
    "fit_mirror_transmission",
    "fit_mirror_transmission_variants",
    "log_ratio_model",
    "ratio_from_counts",
    "transmission_probability",
    "variant_settings",
    "width_ln",
]
