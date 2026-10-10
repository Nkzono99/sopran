"""Ideal finite-bin ER response with optional conservative return transport.

Ratios are log10 (dex). The model ratio can be fitted to log ratios (Huber or
squared loss) or to paired counts through a conditional binomial or
beta-binomial likelihood. The optimizer and forward response run in Rust.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal, cast

import numpy as np
from numpy.polynomial.legendre import leggauss
from numpy.typing import ArrayLike, NDArray
from scipy.linalg import eigh_tridiagonal  # type: ignore[import-untyped]
from scipy.special import erf  # type: ignore[import-untyped]

from sopran.experimental.electron_reflection.common import ElectronReflectionCounts, FloatArray

AngularTransport = Literal["none", "out"]
FiniteBinLoss = Literal["huber", "squared", "binomial", "beta_binomial"]
CountSelection = Literal["paired", "total"]
COUNT_LOSSES = frozenset({"binomial", "beta_binomial"})


@dataclass(frozen=True)
class FiniteBinObservation:
    """Folded 0–90 deg PAD, with explicit eV edges and incident flux.

    Flux must use a common relative scale across pitch within each energy row.
    Missing incident bins are NaN and are log-interpolated for transport; they
    remain excluded from the fitted cells. Exposure corrections belong upstream.

    Count losses additionally need ``affected_counts`` and ``reference_counts``
    with ``exposure_ratio`` = affected/reference exposure (default one).
    ``model_offset_dex`` is a known log10 affected/reference efficiency added
    to the model, e.g. an inter-sensor calibration.
    """

    energy_edges_eV: ArrayLike
    pitch_edges_deg: ArrayLike
    incident_flux: ArrayLike
    observed_log_ratio_dex: ArrayLike
    b_sc_nT: float
    fit_valid: ArrayLike | None = None
    affected_counts: ArrayLike | None = None
    reference_counts: ArrayLike | None = None
    exposure_ratio: ArrayLike | None = None
    model_offset_dex: ArrayLike | None = None

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
        if (self.affected_counts is None) != (self.reference_counts is None):
            raise ValueError("affected_counts and reference_counts must be given together")
        arrays: list[tuple[str, FloatArray]] = []
        if self.affected_counts is not None:
            affected = np.asarray(self.affected_counts, dtype=float)
            reference = np.asarray(self.reference_counts, dtype=float)
            if affected.shape != shape or reference.shape != shape:
                raise ValueError("counts must have shape (energy bins, pitch bins)")
            if not (np.isfinite(affected[valid]).all() and np.isfinite(reference[valid]).all()):
                raise ValueError("counts must be finite in fitted cells")
            if np.any(affected[valid] < 0) or np.any(reference[valid] < 0):
                raise ValueError("counts must be non-negative")
            if np.any(affected[valid] + reference[valid] <= 0):
                raise ValueError("fitted cells need a positive total count")
            arrays += [("affected_counts", affected), ("reference_counts", reference)]
        for name, raw, default in (
            ("exposure_ratio", self.exposure_ratio, 1.0),
            ("model_offset_dex", self.model_offset_dex, 0.0),
        ):
            value = np.broadcast_to(
                np.asarray(default if raw is None else raw, dtype=float), shape
            ).copy()
            if not np.isfinite(value[valid]).all() or (
                name == "exposure_ratio" and np.any(value[valid] <= 0)
            ):
                raise ValueError(f"{name} must be finite (exposure positive) in fitted cells")
            arrays.append((name, value))
        for name, value in (
            ("energy_edges_eV", energy),
            ("pitch_edges_deg", pitch),
            ("incident_flux", flux),
            ("observed_log_ratio_dex", observed),
            ("fit_valid", valid),
            *arrays,
        ):
            object.__setattr__(self, name, value.copy())

    @property
    def has_counts(self) -> bool:
        return self.affected_counts is not None

    @classmethod
    def from_counts(
        cls,
        counts: ElectronReflectionCounts,
        *,
        energy_edges_eV: ArrayLike,
        pitch_edges_deg: ArrayLike,
        min_counts: float = 1,
        min_pitch_bins_per_energy: int = 3,
        pseudocount: float = 0.5,
        fit_valid: ArrayLike | None = None,
        selection: CountSelection = "total",
    ) -> FiniteBinObservation:
        """Prepare corrected log10 ratios and counts; retain low-count flux for D.

        ``selection="total"`` (default) requires affected + reference >=
        ``min_counts``; it keeps zero affected counts and suits the conditional
        count likelihoods. ``selection="paired"`` requires both counts >=
        ``min_counts``; with ``min_counts=5`` it is the D-gallery cut for the
        log-ratio losses. It selects on the affected count and therefore
        censors deep loss-cone cells. Both also require a finite exposure ratio
        in [0.01, 100] and row support.
        """
        if (
            not np.isfinite(min_counts)
            or min_counts < 0
            or pseudocount <= 0
            or not np.isfinite(pseudocount)
            or min_pitch_bins_per_energy < 1
            or selection not in {"paired", "total"}
        ):
            raise ValueError("invalid count preparation settings")
        a, r = np.asarray(counts.affected_counts), np.asarray(counts.reference_counts)
        xa, xr = np.asarray(counts.affected_exposure), np.asarray(counts.reference_exposure)
        known = np.isfinite(r) & np.isfinite(xr) & (xr > 0)
        flux = np.divide(r + pseudocount, xr, out=np.full(r.shape, np.nan), where=known)
        with np.errstate(divide="ignore", invalid="ignore"):
            exposure_ratio = xa / xr
            observed = np.log10((a + pseudocount) / (r + pseudocount) / exposure_ratio)
        count_cut = (
            (a >= min_counts) & (r >= min_counts)
            if selection == "paired"
            else (a + r >= min_counts) & (a + r > 0)
        )
        valid = (
            np.isfinite(a)
            & known
            & count_cut
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
        result = cls(
            energy_edges_eV,
            pitch_edges_deg,
            flux,
            observed,
            counts.b_sc_nT,
            valid,
            affected_counts=np.where(valid, a, np.nan),
            reference_counts=np.where(valid, r, np.nan),
            exposure_ratio=np.where(valid, exposure_ratio, 1.0),
        )
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
    Count losses return twice the negative log likelihood relative to the
    saturated binomial (a deviance); ``beta_binomial`` (default) also fits the
    concentration that absorbs systematic over-dispersion. Count losses need
    counts (``FiniteBinObservation.from_counts``); flux-only observations use
    ``loss="huber"`` or ``"squared"``.
    ``scale_prior_sigma_dex`` adds a Gaussian prior on log10(scale) around 0
    (count losses only). ``local_converged`` reports Nelder–Mead termination,
    not global optimality.
    """

    angular_transport: AngularTransport = "none"
    loss: FiniteBinLoss = "beta_binomial"
    huber_delta_dex: float = 0.1
    beam_enabled: bool = True
    beam_amplitude_bounds: tuple[float, float] = (0.25, 8.0)
    mirror_ratio_bounds: tuple[float, float] = (0.001, 1000.0)
    bottom_ratio_bounds: tuple[float, float] = (0.0001, 1.0)
    delta_u_bounds_eV: tuple[float, float] = (-500.0, 1000.0)
    scale_bounds: tuple[float, float] = (0.01, 100.0)
    sigma_bounds_deg: tuple[float, float] = (0.0, 90.0)
    concentration_bounds: tuple[float, float] = (1.0, 1.0e6)
    scale_prior_sigma_dex: float | None = None
    min_boundary_rows: int = 3
    pitch_subdivisions: int = 8
    generations: int = 180
    seeds: int = 2
    random_seed: int = 20261002

    def __post_init__(self) -> None:
        if self.angular_transport not in {"none", "out"} or self.loss not in {
            "huber",
            "squared",
            *COUNT_LOSSES,
        }:
            raise ValueError(
                "angular_transport must be none/out; "
                "loss must be huber/squared/binomial/beta_binomial"
            )
        if not np.isfinite(self.huber_delta_dex) or self.huber_delta_dex <= 0:
            raise ValueError("huber_delta_dex must be finite and positive")
        for name in (
            "mirror_ratio_bounds",
            "bottom_ratio_bounds",
            "delta_u_bounds_eV",
            "scale_bounds",
            "sigma_bounds_deg",
            "concentration_bounds",
            "beam_amplitude_bounds",
        ):
            bounds = getattr(self, name)
            if len(bounds) != 2 or not np.isfinite(bounds).all() or bounds[0] > bounds[1]:
                raise ValueError(f"invalid {name}")
            if name not in {"delta_u_bounds_eV", "sigma_bounds_deg"} and bounds[0] <= 0:
                raise ValueError(f"{name} must be positive")
        if self.scale_prior_sigma_dex is not None and (
            self.loss not in COUNT_LOSSES
            or not np.isfinite(self.scale_prior_sigma_dex)
            or self.scale_prior_sigma_dex <= 0
        ):
            raise ValueError("scale_prior_sigma_dex must be positive and needs a count loss")
        if not isinstance(self.min_boundary_rows, int) or self.min_boundary_rows < 0:
            raise ValueError("min_boundary_rows must be a non-negative integer")
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
    """Physical parameters; ``concentration`` is used only by ``beta_binomial``."""

    mirror_ratio: float
    bottom_ratio: float
    delta_u_eV: float
    scale: float = 1.0
    sigma_deg: float = 0.0
    concentration: float = 100.0

    def vector(self) -> list[float]:
        values = (
            self.mirror_ratio,
            self.bottom_ratio,
            self.delta_u_eV,
            self.scale,
            self.sigma_deg,
            self.concentration,
        )
        if (
            not np.isfinite(values).all()
            or self.mirror_ratio <= 0
            or not 0 < self.bottom_ratio <= 1
            or self.scale <= 0
            or not 0 <= self.sigma_deg <= 90
            or self.concentration <= 0
        ):
            raise ValueError("invalid finite-bin physical parameters")
        return [
            float(np.log10(self.mirror_ratio)),
            float(np.log10(self.bottom_ratio)),
            self.delta_u_eV / 500,
            float(np.log10(self.scale)),
            self.sigma_deg,
            float(np.log10(self.concentration)),
        ]


@dataclass(frozen=True)
class FiniteBinFit:
    """Fit result.

    ``beam_template`` is 0 (none) or 1 + shape, where shape = 2 * (log-energy
    width 0.15/0.30 index) + (pitch width 10/20 deg index); ``beam_amplitude``
    is its continuous amplitude. ``boundary_rows`` counts energy rows with
    fitted cells on both sides of the bin-mean boundary.
    ``loss_cone_delta_objective`` compares free per-energy levels without
    (rho = 1) and with the fitted loss cone at the fitted beam; positive values
    favour the pitch boundary. ``loss_cone_delta_bic`` subtracts
    ``k ln(cells)`` for the free Rm/rho/Delta U parameters (count losses only).
    """

    parameters: FiniteBinParameters
    effective_field_nT: float
    settings: FiniteBinFitSettings
    objective_sum: float
    objective_mean: float
    root_mean_square_error_dex: float
    beam_template: int
    beam_amplitude: float
    local_converged: bool
    evaluations: int
    field_unconstrained: bool
    field_flags: tuple[str, ...]
    at_bounds: tuple[str, ...]
    interpolated_incident_bins: int
    boundary_rows: int
    loss_cone_delta_objective: float
    loss_cone_delta_bic: float | None
    fitted_log_ratio_dex: FloatArray
    fit_valid: NDArray[np.bool_]
    d_out: FloatArray
    transport_pitch_edges_deg: FloatArray


DEFAULT_STARTS = tuple(
    FiniteBinParameters(mirror_ratio, 0.1, delta_u)
    for mirror_ratio in (2.0, 1.2, 5.0, 20.0)
    for delta_u in (-50.0, 0.0, 50.0)
)


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
        settings = self.settings
        if settings.loss in COUNT_LOSSES and not observation.has_counts:
            raise ValueError(
                "count losses need affected/reference counts; "
                "use loss='huber' or 'squared' for flux-only observations"
            )
        # __post_init__ stores these optional inputs as float arrays.
        if observation.has_counts:
            affected = np.where(valid, cast(FloatArray, observation.affected_counts), 0.0)
            unaffected = np.where(valid, cast(FloatArray, observation.reference_counts), 0.0)
            total = affected + unaffected
        else:
            affected = total = np.zeros(valid.shape)
        log_exposure = np.log(np.where(valid, cast(FloatArray, observation.exposure_ratio), 1.0))
        offset = np.where(valid, cast(FloatArray, observation.model_offset_dex), 0.0)
        prior = settings.scale_prior_sigma_dex
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
            affected[self.rows].tolist(),
            total[self.rows].tolist(),
            log_exposure[self.rows].tolist(),
            offset[self.rows].tolist(),
            settings.beam_enabled,
            list(settings.beam_amplitude_bounds),
            settings.loss,
            settings.huber_delta_dex,
            0.0 if prior is None else prior**-2,
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
        """Evaluate fixed parameters and choose the best beam shape and amplitude."""
        x = parameters.vector()
        if self.settings.angular_transport == "none":
            x[4] = 0
        cost, template, amplitude, prediction, barrier, rows = self._native.evaluate(x)
        return self._result(x, cost, template, amplitude, prediction, False, 1, barrier, rows)

    def _bounds(self) -> list[list[float]]:
        settings = self.settings
        concentration = (
            np.log10(settings.concentration_bounds).tolist()
            if settings.loss == "beta_binomial"
            else [2.0, 2.0]
        )
        return [
            np.log10(settings.mirror_ratio_bounds).tolist(),
            np.log10(settings.bottom_ratio_bounds).tolist(),
            (np.asarray(settings.delta_u_bounds_eV) / 500).tolist(),
            np.log10(settings.scale_bounds).tolist(),
            list(settings.sigma_bounds_deg) if settings.angular_transport == "out" else [0.0, 0.0],
            concentration,
        ]

    def fit(self, *, starts: Sequence[FiniteBinParameters] = ()) -> FiniteBinFit:
        """Run seeded best/1/bin DE and bounded Nelder–Mead entirely in Rust.

        Without ``starts``, Nelder–Mead also refines ``DEFAULT_STARTS``: DE
        alone missed the best basin in 2 of 7 audited KAGUYA windows.
        """
        settings = self.settings
        initial = [p.vector() for p in (starts or DEFAULT_STARTS)]
        x, cost, template, amplitude, prediction, converged, calls, barrier, rows = (
            self._native.fit(
                self._bounds(),
                initial,
                settings.generations,
                settings.seeds,
                settings.random_seed,
            )
        )
        return self._result(
            x, cost, template, amplitude, prediction, converged, calls, barrier, rows
        )

    def _result(
        self,
        x: Sequence[float],
        cost: float,
        template: int,
        amplitude: float,
        prediction: Sequence[float],
        converged: bool,
        calls: int,
        barrier: bool,
        boundary_rows: int,
    ) -> FiniteBinFit:
        params = FiniteBinParameters(
            10 ** x[0], 10 ** x[1], x[2] * 500, 10 ** x[3], x[4], 10 ** x[5]
        )
        observation, settings = self.observation, self.settings
        fitted: FloatArray = np.full(np.asarray(observation.incident_flux).shape, np.nan)
        fitted[self.rows] = np.asarray(prediction).reshape(len(self.rows), fitted.shape[1])
        valid = np.asarray(observation.fit_valid, dtype=bool)
        residual = (fitted - np.asarray(observation.observed_log_ratio_dex, dtype=float))[valid]
        bounds_by_name = dict(
            zip(
                (
                    "mirror_ratio",
                    "bottom_ratio",
                    "delta_u_eV",
                    "scale",
                    "sigma_deg",
                    "concentration",
                ),
                self._bounds(),
                strict=True,
            )
        )
        at_bounds = [
            name
            for (name, bounds), value in zip(bounds_by_name.items(), x, strict=True)
            if bounds[0] < bounds[1] and min(abs(value - bounds[0]), abs(value - bounds[1])) < 1e-3
        ]
        null, alternative = self._native.loss_cone_test(
            list(x), template, amplitude, bounds_by_name["concentration"]
        )
        delta = null - alternative
        free = sum(
            bounds_by_name[name][0] < bounds_by_name[name][1]
            for name in ("mirror_ratio", "bottom_ratio", "delta_u_eV")
        )
        delta_bic = delta - free * np.log(residual.size) if settings.loss in COUNT_LOSSES else None
        flags = tuple(
            name
            for name, active in (
                ("no_contrast", params.bottom_ratio >= 0.99),
                ("barrier_unobserved", barrier),
                ("field_at_search_bound", "mirror_ratio" in at_bounds),
                ("boundary_rows_insufficient", boundary_rows < settings.min_boundary_rows),
                ("loss_cone_unsupported", delta_bic is not None and delta_bic <= 0),
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
            beam_amplitude=amplitude,
            local_converged=converged,
            evaluations=calls,
            field_unconstrained=bool(flags),
            field_flags=flags,
            at_bounds=tuple(at_bounds),
            interpolated_incident_bins=self.interpolated_incident_bins,
            boundary_rows=boundary_rows,
            loss_cone_delta_objective=float(delta),
            loss_cone_delta_bic=None if delta_bic is None else float(delta_bic),
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
    """Fit a folded finite-bin distribution with optional D_out and the chosen loss."""
    return FiniteBinModel(observation, settings).fit(starts=starts)


@dataclass(frozen=True)
class FiniteBinProfile:
    """Objective with Rm fixed on a grid, other parameters re-optimized.

    For count losses ``objective_sum`` is a deviance, so ``delta_objective <=
    threshold`` (3.84, 95% for one parameter) is a profile-likelihood interval;
    the beta-binomial concentration absorbs over-dispersion. Interval ends are
    interpolated in log Rm between grid points; ``interval_bounded`` is false
    when the interval reaches the end of the grid. Log-ratio losses return the
    profile without an interval. ``minimum_fit`` is the lowest objective among
    the input fit and the profile points.
    """

    mirror_ratio: FloatArray
    effective_field_nT: FloatArray
    objective_sum: FloatArray
    delta_objective: FloatArray
    fits: tuple[FiniteBinFit, ...]
    threshold: float | None
    interval_nT: tuple[float, float] | None
    interval_bounded: bool
    improved_minimum: bool
    minimum_fit: FiniteBinFit


def profile_mirror_ratio(
    observation: FiniteBinObservation,
    fit: FiniteBinFit,
    *,
    mirror_ratios: ArrayLike | None = None,
    half_width_dex: float = 1.0,
    points: int = 21,
    threshold: float = 3.841458820694124,
) -> FiniteBinProfile:
    """Profile Rm around ``fit`` with warm-started Nelder–Mead at each grid point.

    The default grid spans ``fit`` Rm ± ``half_width_dex`` in ``points`` log
    steps, clipped to the search bounds. Each point refines the best fit and
    its neighbour with Rm fixed; no DE runs, so a profile point below the fit
    (``improved_minimum``) indicates that the fit missed a better basin.
    """
    settings = fit.settings
    lower, upper = settings.mirror_ratio_bounds
    center = fit.parameters.mirror_ratio
    if mirror_ratios is None:
        grid = center * np.logspace(-half_width_dex, half_width_dex, points)
        grid = np.unique(np.r_[np.clip(grid, lower, upper), center])
    else:
        grid = np.unique(np.asarray(mirror_ratios, dtype=float))
        if grid.ndim != 1 or grid.size < 2 or np.any(grid <= 0) or not np.isfinite(grid).all():
            raise ValueError("mirror_ratios must contain at least two positive values")
    order = np.argsort(np.abs(np.log(grid / center)))
    fits: dict[float, FiniteBinFit] = {}
    for index in order:
        ratio = float(grid[index])
        neighbours = [
            fits[float(grid[j])].parameters
            for j in (index - 1, index + 1)
            if 0 <= j < grid.size and float(grid[j]) in fits
        ]
        starts = [replace(p, mirror_ratio=ratio) for p in (fit.parameters, *neighbours)]
        model = FiniteBinModel(
            observation,
            replace(settings, mirror_ratio_bounds=(ratio, ratio), generations=0),
        )
        fits[ratio] = model.fit(starts=starts)
    ordered = tuple(fits[float(r)] for r in grid)
    objective = np.array([f.objective_sum for f in ordered])
    minimum = min(float(objective.min()), fit.objective_sum)
    delta = objective - minimum
    interval: tuple[float, float] | None = None
    bounded = False
    count_loss = settings.loss in COUNT_LOSSES
    if count_loss:
        inside = np.flatnonzero(delta <= threshold)
        if inside.size:
            first, last = int(inside[0]), int(inside[-1])
            log_grid = np.log(grid)

            def crossing(i: int, j: int) -> float:
                # Linear in log Rm between an outside point i and inside point j.
                weight = (delta[i] - threshold) / (delta[i] - delta[j])
                return float(np.exp(log_grid[i] + weight * (log_grid[j] - log_grid[i])))

            low = crossing(first - 1, first) if first > 0 else float(grid[first])
            high = crossing(last + 1, last) if last < grid.size - 1 else float(grid[last])
            interval = (low * observation.b_sc_nT, high * observation.b_sc_nT)
            bounded = first > 0 and last < grid.size - 1
    return FiniteBinProfile(
        mirror_ratio=grid,
        effective_field_nT=grid * observation.b_sc_nT,
        objective_sum=objective,
        delta_objective=delta,
        fits=ordered,
        threshold=threshold if count_loss else None,
        interval_nT=interval,
        interval_bounded=bounded,
        improved_minimum=bool(objective.min() < fit.objective_sum - 1e-6),
        minimum_fit=min((fit, *ordered), key=lambda f: f.objective_sum),
    )
