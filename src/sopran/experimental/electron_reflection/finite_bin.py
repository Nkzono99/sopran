"""Ideal finite-bin ER response with optional conservative return transport.

Ratios are log10 (dex). This is a folded flux model, separate from the raw-count
likelihood estimators. The optimizer and forward response run in Rust.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast

import numpy as np
from numpy.polynomial.legendre import leggauss
from numpy.typing import ArrayLike, NDArray
from scipy.linalg import eigh_tridiagonal  # type: ignore[import-untyped]
from scipy.special import erf  # type: ignore[import-untyped]

from sopran.experimental.electron_reflection.common import ElectronReflectionCounts, FloatArray

AngularTransport = Literal["none", "out"]
FiniteBinLoss = Literal["huber", "squared"]


@dataclass(frozen=True)
class FiniteBinObservation:
    """Folded 0–90 deg PAD, with explicit eV edges and incident flux.

    Flux must use a common relative scale across pitch within each energy row.
    Missing incident bins are NaN and are log-interpolated for transport; they
    remain excluded from the fitted cells. Exposure corrections belong upstream.
    """

    energy_edges_eV: ArrayLike
    pitch_edges_deg: ArrayLike
    incident_flux: ArrayLike
    observed_log_ratio_dex: ArrayLike
    b_sc_nT: float
    fit_valid: ArrayLike | None = None

    def __post_init__(self) -> None:
        energy = np.asarray(self.energy_edges_eV, dtype=float)
        pitch = np.asarray(self.pitch_edges_deg, dtype=float)
        for name, edges in (("energy_edges_eV", energy), ("pitch_edges_deg", pitch)):
            if (
                edges.ndim != 1
                or edges.size < 2
                or not np.isfinite(edges).all()
                or np.any(np.diff(edges) <= 0)
            ):
                raise ValueError(f"{name} must be finite, increasing 1-D edges")
        if energy[0] <= 0 or pitch[0] != 0 or pitch[-1] != 90:
            raise ValueError("energy edges must be positive; pitch edges must cover 0–90 deg")
        shape = (energy.size - 1, pitch.size - 1)
        flux = np.asarray(self.incident_flux, dtype=float)
        observed = np.asarray(self.observed_log_ratio_dex, dtype=float)
        if flux.shape != shape or observed.shape != shape:
            raise ValueError("flux and log ratio must have shape (energy bins, pitch bins)")
        if np.isinf(flux).any() or np.any(np.isfinite(flux) & (flux <= 0)):
            raise ValueError("incident flux must be positive or NaN")
        valid = (
            np.isfinite(observed)
            if self.fit_valid is None
            else np.asarray(self.fit_valid, dtype=bool)
        )
        if valid.shape != shape:
            raise ValueError("fit_valid must have the same shape as flux")
        valid = valid & np.isfinite(observed) & np.isfinite(flux)
        if not valid.any():
            raise ValueError("at least one finite observed and incident cell is required")
        if not np.isfinite(self.b_sc_nT) or self.b_sc_nT <= 0:
            raise ValueError("b_sc_nT must be positive and finite")
        for name, value in (
            ("energy_edges_eV", energy),
            ("pitch_edges_deg", pitch),
            ("incident_flux", flux),
            ("observed_log_ratio_dex", observed),
            ("fit_valid", valid),
        ):
            object.__setattr__(self, name, value.copy())

    @classmethod
    def from_counts(
        cls,
        counts: ElectronReflectionCounts,
        *,
        energy_edges_eV: ArrayLike,
        pitch_edges_deg: ArrayLike,
        min_counts: float = 5,
        min_pitch_bins_per_energy: int = 3,
        pseudocount: float = 0.5,
        fit_valid: ArrayLike | None = None,
    ) -> FiniteBinObservation:
        """Prepare corrected log10 ratios; retain low-count incident flux for D.

        Cells require both counts >= ``min_counts``, positive finite exposure,
        an affected/reference exposure ratio in [0.01, 100], and row support.
        These cuts match the D-gallery experiment and are explicit input cuts.
        """
        if (
            not np.isfinite(min_counts)
            or min_counts < 0
            or pseudocount <= 0
            or not np.isfinite(pseudocount)
            or min_pitch_bins_per_energy < 1
        ):
            raise ValueError("invalid count preparation settings")
        a, r = np.asarray(counts.affected_counts), np.asarray(counts.reference_counts)
        xa, xr = np.asarray(counts.affected_exposure), np.asarray(counts.reference_exposure)
        known = np.isfinite(r) & np.isfinite(xr) & (xr > 0)
        flux = np.divide(r + pseudocount, xr, out=np.full(r.shape, np.nan), where=known)
        with np.errstate(divide="ignore", invalid="ignore"):
            exposure_ratio = xa / xr
            observed = np.log10((a + pseudocount) / (r + pseudocount) / exposure_ratio)
        valid = (
            np.isfinite(a)
            & known
            & (a >= min_counts)
            & (r >= min_counts)
            & (xa > 0)
            & np.isfinite(exposure_ratio)
            & (exposure_ratio >= 0.01)
            & (exposure_ratio <= 100)
        )
        if fit_valid is not None:
            supplied = np.asarray(fit_valid, dtype=bool)
            if supplied.shape != valid.shape:
                raise ValueError("fit_valid must match counts")
            valid &= supplied
        valid &= (valid.sum(axis=1) >= min_pitch_bins_per_energy)[:, None]
        result = cls(energy_edges_eV, pitch_edges_deg, flux, observed, counts.b_sc_nT, valid)
        energy_centers, pitch_centers = np.asarray(counts.energy_eV), np.asarray(counts.pitch_deg)
        energy_edges, pitch_edges = (
            np.asarray(result.energy_edges_eV),
            np.asarray(result.pitch_edges_deg),
        )
        if not np.all(
            (energy_centers > energy_edges[:-1]) & (energy_centers < energy_edges[1:])
        ) or not np.all((pitch_centers > pitch_edges[:-1]) & (pitch_centers < pitch_edges[1:])):
            raise ValueError("count coordinates must lie inside their supplied bins")
        return result


@dataclass(frozen=True)
class FiniteBinFitSettings:
    """Bottom and scale vary by default; D_out is explicitly opt-in.

    Equal bounds fix a parameter (including Rm for an Area-mean counterfactual).
    Huber is twice the conventional Huber loss, preserving the pilot objective.
    ``local_converged`` reports Nelder–Mead termination, not global optimality.
    """

    angular_transport: AngularTransport = "none"
    loss: FiniteBinLoss = "huber"
    huber_delta_dex: float = 0.1
    beam_enabled: bool = True
    mirror_ratio_bounds: tuple[float, float] = (0.001, 1000.0)
    bottom_ratio_bounds: tuple[float, float] = (0.0001, 1.0)
    delta_u_bounds_eV: tuple[float, float] = (-500.0, 1000.0)
    scale_bounds: tuple[float, float] = (0.01, 100.0)
    sigma_bounds_deg: tuple[float, float] = (0.0, 90.0)
    pitch_subdivisions: int = 8
    generations: int = 180
    seeds: int = 2
    random_seed: int = 20261002

    def __post_init__(self) -> None:
        if self.angular_transport not in {"none", "out"} or self.loss not in {"huber", "squared"}:
            raise ValueError("angular_transport must be none/out; loss must be huber/squared")
        if not np.isfinite(self.huber_delta_dex) or self.huber_delta_dex <= 0:
            raise ValueError("huber_delta_dex must be finite and positive")
        for name in (
            "mirror_ratio_bounds",
            "bottom_ratio_bounds",
            "delta_u_bounds_eV",
            "scale_bounds",
            "sigma_bounds_deg",
        ):
            bounds = getattr(self, name)
            if len(bounds) != 2 or not np.isfinite(bounds).all() or bounds[0] > bounds[1]:
                raise ValueError(f"invalid {name}")
            if (
                name in {"mirror_ratio_bounds", "bottom_ratio_bounds", "scale_bounds"}
                and bounds[0] <= 0
            ):
                raise ValueError(f"{name} must be positive")
        if (
            self.bottom_ratio_bounds[1] > 1
            or not 0 <= self.sigma_bounds_deg[0] <= self.sigma_bounds_deg[1] <= 90
        ):
            raise ValueError("bottom <= 1 and sigma in [0, 90] are required")
        for name in ("pitch_subdivisions", "generations", "seeds", "random_seed"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < (
                1 if name in {"pitch_subdivisions", "seeds"} else 0
            ):
                raise ValueError(f"invalid {name}")
        if self.random_seed > 2**64 - 1:
            raise ValueError("random_seed must fit u64")


@dataclass(frozen=True)
class FiniteBinParameters:
    mirror_ratio: float
    bottom_ratio: float
    delta_u_eV: float
    scale: float = 1.0
    sigma_deg: float = 0.0

    def vector(self) -> list[float]:
        values = (self.mirror_ratio, self.bottom_ratio, self.delta_u_eV, self.scale, self.sigma_deg)
        if (
            not np.isfinite(values).all()
            or self.mirror_ratio <= 0
            or not 0 < self.bottom_ratio <= 1
            or self.scale <= 0
            or not 0 <= self.sigma_deg <= 90
        ):
            raise ValueError("invalid finite-bin physical parameters")
        return [
            float(np.log10(self.mirror_ratio)),
            float(np.log10(self.bottom_ratio)),
            self.delta_u_eV / 500,
            float(np.log10(self.scale)),
            self.sigma_deg,
        ]


@dataclass(frozen=True)
class FiniteBinFit:
    parameters: FiniteBinParameters
    effective_field_nT: float
    settings: FiniteBinFitSettings
    objective_sum: float
    objective_mean: float
    root_mean_square_error_dex: float
    beam_template: int
    local_converged: bool
    evaluations: int
    field_unconstrained: bool
    field_flags: tuple[str, ...]
    at_bounds: tuple[str, ...]
    interpolated_incident_bins: int
    fitted_log_ratio_dex: FloatArray
    fit_valid: NDArray[np.bool_]
    d_out: FloatArray
    transport_pitch_edges_deg: FloatArray


class FiniteBinModel:
    """Reusable prepared response; D acts on solid-angle integrated intensity.

    D has no energy mixing and no flux across folded pitch 0/90 deg. It is a
    reduced axisymmetric transport model, not a calibrated detector response.
    """

    def __init__(
        self, observation: FiniteBinObservation, settings: FiniteBinFitSettings | None = None
    ) -> None:
        self.observation = observation
        self.settings = settings or FiniteBinFitSettings()
        from sopran._native import FiniteBinProblem  # type: ignore[import-not-found]

        pitch = np.asarray(observation.pitch_edges_deg)
        subdivisions = self.settings.pitch_subdivisions
        fine = np.r_[
            np.concatenate(
                [
                    np.linspace(lo, hi, subdivisions + 1)[:-1]
                    for lo, hi in zip(pitch[:-1], pitch[1:], strict=True)
                ]
            ),
            pitch[-1],
        ]
        self.transport_pitch_edges_deg = fine
        mu = np.cos(np.deg2rad(fine))
        self.weights = -np.diff(mu)
        centers = (mu[:-1] + mu[1:]) / 2
        conductance = (1 - mu[1:-1] ** 2) / abs(np.diff(centers))
        diagonal = -(np.r_[0.0, conductance] + np.r_[conductance, 0.0]) / self.weights
        off_diagonal = conductance / np.sqrt(self.weights[:-1] * self.weights[1:])
        self.eigenvalues, self.eigenvectors = eigh_tridiagonal(diagonal, off_diagonal)
        self.eigenvalues[-1] = 0
        flux = np.asarray(observation.incident_flux).copy()
        valid = np.asarray(observation.fit_valid)
        self.rows = np.flatnonzero(valid.any(axis=1))
        flux = flux[self.rows]
        known = np.isfinite(flux)
        self.interpolated_incident_bins = int((~known).sum())
        pitch_centers = (pitch[:-1] + pitch[1:]) / 2
        for row in range(len(flux)):
            k = known[row]
            flux[row, ~k] = np.exp(
                np.interp(pitch_centers[~k], pitch_centers[k], np.log(flux[row, k]))
            )
        reference = flux / np.median(flux, axis=1)[:, None]
        angular = []
        for width in (10.0, 20.0):
            lo, hi = np.minimum(fine[:-1], 3 * width), np.minimum(fine[1:], 3 * width)
            angular.append(
                width
                * np.sqrt(np.pi / 2)
                * (erf(hi / (np.sqrt(2) * width)) - erf(lo / (np.sqrt(2) * width)))
                / np.diff(fine)
            )
        nodes, weights = leggauss(17)
        energy = np.asarray(observation.energy_edges_eV)
        observed = np.where(valid, observation.observed_log_ratio_dex, 0.0)[self.rows]
        self._native = FiniteBinProblem(
            pitch.tolist(),
            fine.tolist(),
            self.weights.tolist(),
            self.eigenvalues.tolist(),
            self.eigenvectors.ravel().tolist(),
            np.asarray(angular).tolist(),
            nodes.tolist(),
            (weights / weights.sum()).tolist(),
            subdivisions,
            energy[self.rows].tolist(),
            energy[self.rows + 1].tolist(),
            reference.tolist(),
            valid[self.rows].tolist(),
            observed.tolist(),
            self.settings.beam_enabled,
            self.settings.huber_delta_dex if self.settings.loss == "huber" else 0.0,
        )

    def kernel(self, sigma_deg: float) -> FloatArray:
        """Return D[j_out, j_in]; columns sum to one; isotropic flux is stationary."""
        if not np.isfinite(sigma_deg) or not 0 <= sigma_deg <= 90:
            raise ValueError("sigma_deg must be finite and in [0, 90]")
        if sigma_deg == 0:
            return np.eye(len(self.weights))
        decay = np.exp(self.eigenvalues * np.deg2rad(sigma_deg) ** 2 / 4)
        heat = (self.eigenvectors * decay) @ self.eigenvectors.T
        matrix = np.maximum(np.sqrt(self.weights[:, None] / self.weights[None, :]) * heat, 0)
        return cast(FloatArray, matrix / matrix.sum(axis=0, keepdims=True))

    def evaluate(self, parameters: FiniteBinParameters) -> FiniteBinFit:
        """Evaluate fixed parameters and choose the best retained beam template."""
        x = parameters.vector()
        if self.settings.angular_transport == "none":
            x[4] = 0
        cost, template, prediction, barrier = self._native.evaluate(x)
        return self._result(x, cost, template, prediction, False, 1, barrier)

    def fit(self, *, starts: Sequence[FiniteBinParameters] = ()) -> FiniteBinFit:
        """Run seeded best/1/bin DE and bounded Nelder–Mead entirely in Rust."""
        settings = self.settings
        bounds = [
            np.log10(settings.mirror_ratio_bounds).tolist(),
            np.log10(settings.bottom_ratio_bounds).tolist(),
            (np.asarray(settings.delta_u_bounds_eV) / 500).tolist(),
            np.log10(settings.scale_bounds).tolist(),
            list(settings.sigma_bounds_deg) if settings.angular_transport == "out" else [0.0, 0.0],
        ]
        initial = [p.vector() for p in starts] or [FiniteBinParameters(2.0, 0.1, -50.0).vector()]
        x, cost, template, prediction, converged, calls, barrier = self._native.fit(
            bounds,
            initial,
            settings.generations,
            settings.seeds,
            settings.random_seed,
        )
        return self._result(x, cost, template, prediction, converged, calls, barrier)

    def _result(
        self,
        x: Sequence[float],
        cost: float,
        template: int,
        prediction: Sequence[float],
        converged: bool,
        calls: int,
        barrier: bool,
    ) -> FiniteBinFit:
        params = FiniteBinParameters(10 ** x[0], 10 ** x[1], x[2] * 500, 10 ** x[3], x[4])
        observation, settings = self.observation, self.settings
        fitted: FloatArray = np.full(np.asarray(observation.incident_flux).shape, np.nan)
        fitted[self.rows] = np.asarray(prediction).reshape(len(self.rows), fitted.shape[1])
        valid = np.asarray(observation.fit_valid, dtype=bool)
        residual = (fitted - np.asarray(observation.observed_log_ratio_dex, dtype=float))[valid]
        at_bounds = []
        for name, value, bounds in (
            ("mirror_ratio", x[0], np.log10(settings.mirror_ratio_bounds)),
            ("bottom_ratio", x[1], np.log10(settings.bottom_ratio_bounds)),
            ("delta_u_eV", x[2], np.asarray(settings.delta_u_bounds_eV) / 500),
            ("scale", x[3], np.log10(settings.scale_bounds)),
            ("sigma_deg", x[4], settings.sigma_bounds_deg),
        ):
            if (
                bounds[0] < bounds[1]
                and (name != "sigma_deg" or settings.angular_transport == "out")
                and min(abs(value - bounds[0]), abs(value - bounds[1])) < 1e-3
            ):
                at_bounds.append(name)
        flags = tuple(
            name
            for name, active in (
                ("no_contrast", params.bottom_ratio >= 0.99),
                ("barrier_unobserved", barrier),
                ("field_at_search_bound", "mirror_ratio" in at_bounds),
            )
            if active
        )
        return FiniteBinFit(
            parameters=params,
            effective_field_nT=observation.b_sc_nT * params.mirror_ratio,
            settings=settings,
            objective_sum=cost,
            objective_mean=cost / residual.size,
            root_mean_square_error_dex=float(np.sqrt(np.mean(residual**2))),
            beam_template=template,
            local_converged=converged,
            evaluations=calls,
            field_unconstrained=bool(flags),
            field_flags=flags,
            at_bounds=tuple(at_bounds),
            interpolated_incident_bins=self.interpolated_incident_bins,
            fitted_log_ratio_dex=fitted,
            fit_valid=valid.copy(),
            d_out=self.kernel(params.sigma_deg),
            transport_pitch_edges_deg=self.transport_pitch_edges_deg.copy(),
        )


def fit_finite_bin_distribution(
    observation: FiniteBinObservation,
    *,
    settings: FiniteBinFitSettings | None = None,
    starts: Sequence[FiniteBinParameters] = (),
) -> FiniteBinFit:
    """Fit a folded finite-bin distribution with optional D_out and Huber loss."""
    return FiniteBinModel(observation, settings).fit(starts=starts)
