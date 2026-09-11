"""Shared incident PAD, finite-response hard loss cone and outgoing beam.

Python prediction is the reference implementation; the packed Rust backend
computes the same count likelihood and analytic gradient for optimization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize
from scipy.special import digamma, gammaln

from sopran.analysis.electron_reflection import global_joint as gj

Array = NDArray[np.float64]


def basis(x: Array, knots: Array) -> Array:
    return np.stack([np.interp(x, knots, row) for row in np.eye(len(knots))], axis=-1)


@dataclass
class Result:
    vector: Array
    success: bool
    message: str
    nll: float
    bic: float
    at_bounds: list[str]
    iterations: int


class IncidentProblem:
    def __init__(
        self,
        problem: gj._Problem,
        *,
        anisotropic: bool = True,
        backend: Literal["python", "rust"] = "rust",
    ) -> None:
        if backend not in {"python", "rust"}:
            raise ValueError("backend must be python or rust")
        if problem.settings.loss_cone_model != "shared" or problem.layout.transition_model not in {
            "hard",
            "none",
        }:
            raise ValueError("This experiment supports shared hard/none models only")
        if problem.settings.background_model != "none" or problem.settings.spectrum_smoothness:
            raise ValueError("This experiment requires no background or spectrum penalty")
        self.problem = problem
        self.layout = problem.layout
        self.n_base = problem.layout.size
        self.knots = np.linspace(problem.log_energy_knots[0], problem.log_energy_knots[-1], 3)
        self.n_aniso = 3 if anisotropic else 0
        self.names = (*problem.names, *[f"incident_pad[{i}]" for i in range(self.n_aniso)])
        self.bounds = (*problem.bounds, *((-4.0, 4.0),) * self.n_aniso)
        self.initial = np.r_[problem.initial, np.zeros(self.n_aniso)]
        parts: dict[str, list[Array]] = {
            k: []
            for k in (
                "energy",
                "ew",
                "lower",
                "upper",
                "affected",
                "b",
                "counts",
                "exposure",
                "sensor",
            )
        }
        self.slices = []
        offset = 0
        for obs, sensor in zip(problem.observations, problem.sensor_indices, strict=True):
            if (
                obs.detector_response_matrix is not None
                or obs.dead_time_seconds
                or np.any(obs.known_background_counts)
            ):
                raise ValueError(
                    "Only diagonal calibrated exposure without background/dead time is supported"
                )
            if not np.any(np.isclose(obs.pitch_edges_deg, 90.0)):
                raise ValueError("Pitch bins must split at 90 degrees")
            ei, pi = np.nonzero(obs.valid)
            count = len(ei)
            self.slices.append(slice(offset, offset + count))
            offset += count
            left, right = obs.pitch_edges_deg[pi], obs.pitch_edges_deg[pi + 1]
            lower = np.minimum(left, 180 - right)
            upper = np.maximum(np.minimum(left, 180 - left), np.minimum(right, 180 - right))
            for key, value in dict(
                energy=obs.energy_response_eV[ei],
                ew=np.broadcast_to(
                    obs.energy_response_weights, (count, len(obs.energy_response_weights))
                ),
                lower=lower,
                upper=upper,
                affected=obs.affected[pi],
                b=np.full(count, obs.b_sc_nT),
                counts=obs.counts[ei, pi],
                exposure=obs.exposure[ei, pi],
                sensor=np.full(count, sensor),
            ).items():
                parts[key].append(value)
        for key, value in parts.items():
            setattr(self, key, np.concatenate(value))
        self.affected = self.affected.astype(bool)
        self.sensor = self.sensor.astype(int)
        self.lower = np.deg2rad(self.lower)[:, None]
        self.upper = np.deg2rad(self.upper)[:, None]
        self.width = self.upper - self.lower
        nodes, weights = np.polynomial.legendre.leggauss(12)
        self.nodes = (nodes + 1) / 2
        self.pw = weights / 2
        self.z_full = np.cos(self.lower[..., None] + self.width[..., None] * self.nodes) ** 2
        self.sb = basis(np.log(self.energy), problem.log_energy_knots)
        self.ab = basis(np.log(self.energy), self.knots)
        self.constant_ll = gammaln(self.counts + 1)
        self._native = None
        if backend == "rust":
            from sopran._native import IncidentHardProblem

            layout = self.layout

            def flat(value: Array) -> Array:
                return np.ascontiguousarray(value, dtype=np.float64).reshape(-1)

            self._native = IncidentHardProblem(
                dict(
                    energy=flat(self.energy),
                    weights=flat(self.ew),
                    lower=flat(self.lower),
                    upper=flat(self.upper),
                    b=flat(self.b),
                    counts=flat(self.counts),
                    exposure=flat(self.exposure),
                    sensor=self.sensor.tolist(),
                    affected=self.affected.tolist(),
                    sb=flat(self.sb),
                    ab=flat(self.ab if self.n_aniso else np.empty(0)),
                    nodes=flat(self.nodes),
                    pw=flat(self.pw),
                    ne=self.energy.shape[1],
                    ns=layout.spectrum.stop - layout.spectrum.start,
                    na=self.n_aniso,
                    np=len(self.names),
                    spectrum=layout.spectrum.start,
                    baseline=layout.hemisphere_baseline.start,
                    contrast=layout.contrast.start if layout.model != "no_edge" else None,
                    beam=layout.beam.start if layout.beam is not None else None,
                    gains=layout.gains.start,
                    dispersion=layout.dispersions.start,
                    anisotropy=self.n_base,
                    model={"no_edge": 0, "mirror_only": 1, "electrostatic": 2}[layout.model],
                    phi=problem.settings.effective_field.spacecraft_potential_eV,
                )
            )

    def moments(self, k: Array, lower: Array, upper: Array) -> tuple[Array, Array]:
        span = np.maximum(0.0, upper - lower)
        z = np.cos(lower[..., None] + span[..., None] * self.nodes) ** 2
        g = np.exp(k[..., None] * z)
        scale = span / self.width
        return np.sum(g * self.pw, axis=-1) * scale, np.sum(g * z * self.pw, axis=-1) * scale

    def predict(self, vector: Array) -> tuple[Array, Array]:
        layout = self.layout
        n = len(self.counts)
        k = self.ab @ vector[self.n_base :] if self.n_aniso else np.zeros_like(self.energy)
        full_g = np.exp(k[..., None] * self.z_full)
        full = np.sum(full_g * self.pw, axis=-1)
        full_k = np.sum(full_g * self.z_full * self.pw, axis=-1)
        surface, surface_k = full.copy(), full_k.copy()
        c = np.exp(vector[layout.hemisphere_baseline.start])
        a = self.affected[:, None]
        derivatives: dict[int, Array] = {}
        if layout.model != "no_edge":
            field = np.exp(vector[layout.physical.start])
            delta = vector[layout.physical.start + 1] if layout.model == "electrostatic" else 0.0
            energy = self.energy - self.problem.settings.effective_field.spacecraft_potential_eV
            boundary = (1 + delta / energy) * self.b[:, None] / field
            angle = np.arcsin(np.sqrt(np.clip(boundary, 0, 1)))
            transmitted, transmitted_k = self.moments(k, np.maximum(self.lower, angle), self.upper)
            floor = np.exp(-vector[layout.contrast.start])
            reflected = c * (floor * full + (1 - floor) * transmitted)
            reflected_k = c * (floor * full_k + (1 - floor) * transmitted_k)
            surface = np.where(a, reflected, full)
            surface_k = np.where(a, reflected_k, full_k)
            derivatives[layout.contrast.start] = np.where(a, c * floor * (transmitted - full), 0.0)
            active = (boundary > 0) & (boundary < 1) & (angle > self.lower) & (angle < self.upper)
            db = np.zeros_like(boundary)
            db[active] = -np.exp(k[active] * (1 - boundary[active])) / (
                2 * np.sqrt(boundary[active] * (1 - boundary[active]))
            )
            db = np.where(a, db * c * (1 - floor) / self.width, 0.0)
            derivatives[layout.physical.start] = -boundary * db
            if layout.model == "electrostatic":
                derivatives[layout.physical.start + 1] = db * self.b[:, None] / (field * energy)
        else:
            surface = np.where(a, c * full, full)
            surface_k = np.where(a, c * full_k, full_k)
        derivatives[layout.hemisphere_baseline.start] = np.where(a, surface, 0.0)
        if layout.beam is not None:
            amplitude, center, sigma_e, sigma_p = np.exp(vector[layout.beam])
            pitch = np.rad2deg(self.lower + self.width * self.nodes)
            pg = np.exp(-0.5 * (pitch / sigma_p) ** 2)
            pmean = np.sum(pg * self.pw, axis=-1)[:, None]
            pdmean = np.sum(pg * (pitch / sigma_p) ** 2 * self.pw, axis=-1)[:, None]
            distance = np.log(self.energy / center)
            eg = amplitude * np.exp(-0.5 * (distance / sigma_e) ** 2)
            beam = np.where(a, eg * pmean, 0.0)
            surface += beam
            derivatives[layout.beam.start] = beam
            derivatives[layout.beam.start + 1] = beam * distance / sigma_e**2
            derivatives[layout.beam.start + 2] = beam * (distance / sigma_e) ** 2
            derivatives[layout.beam.start + 3] = np.where(a, eg * pdmean, 0.0)
        incident = np.exp(self.sb @ vector[layout.spectrum])
        weighted = self.ew * incident
        integral = np.sum(weighted * surface, axis=1)
        gain = np.r_[0.0, vector[layout.gains]][self.sensor]
        factor = self.exposure * np.exp(gain)
        mean = factor * integral
        jac = np.zeros((n, len(vector)))
        jac[:, layout.spectrum] = factor[:, None] * np.einsum(
            "ne,nek->nk", weighted * surface, self.sb
        )
        for index, derivative in derivatives.items():
            jac[:, index] = factor * np.sum(weighted * derivative, axis=1)
        if self.n_aniso:
            jac[:, self.n_base :] = factor[:, None] * np.einsum(
                "ne,nek->nk", weighted * surface_k, self.ab
            )
        for sensor in range(1, len(self.problem.sensor_names)):
            jac[:, layout.gains.start + sensor - 1] = np.where(self.sensor == sensor, mean, 0.0)
        return mean, jac

    def objective(self, vector: Array) -> tuple[float, Array]:
        if self._native is not None:
            value, gradient = self._native.value_and_gradient(
                np.ascontiguousarray(vector, dtype=float)
            )
            return float(value), np.asarray(gradient)
        return self.objective_python(vector)

    def objective_python(self, vector: Array) -> tuple[float, Array]:
        mean, jac = self.predict(vector)
        r = np.exp(vector[self.layout.dispersions])[self.sensor]
        y = self.counts
        ll = (
            gammaln(y + r)
            - gammaln(r)
            - self.constant_ll
            + r * (np.log(r) - np.log(r + mean))
            + y * (np.log(mean) - np.log(r + mean))
        )
        dmean = y / mean - (y + r) / (mean + r)
        gradient = -(jac.T @ dmean)
        dr = r * (
            digamma(y + r) - digamma(r) + np.log(r) + 1 - np.log(r + mean) - (r + y) / (r + mean)
        )
        for si in range(len(self.problem.sensor_names)):
            gradient[self.layout.dispersions.start + si] = -np.sum(dr[self.sensor == si])
        return -float(np.sum(ll)), gradient

    def fit(self, seeds: list[Array], *, maxiter: int = 500) -> Result:
        seeds = [
            np.array([np.clip(x, lo, hi) for x, (lo, hi) in zip(s, self.bounds, strict=True)])
            for s in seeds
        ]
        initial = [(self.objective(s)[0], s) for s in seeds]
        results = [
            minimize(
                self.objective,
                seed,
                method="L-BFGS-B",
                jac=True,
                bounds=self.bounds,
                options=dict(maxiter=maxiter, ftol=1.0e-9, maxls=60),
            )
            for seed in seeds
        ]
        finite = [r for r in results if np.isfinite(r.fun)]
        if not finite:
            raise RuntimeError("No finite optimization result")
        best = min(finite, key=lambda r: r.fun)
        converged = [r for r in finite if r.success and r.fun <= best.fun + 1.0e-4]
        best = min(converged, key=lambda r: r.fun) if converged else best
        initial_value, initial_vector = min(initial, key=lambda item: item[0])
        if initial_value < best.fun - 1.0e-4:
            best.x, best.fun, best.success = initial_vector, initial_value, False
            best.message = "Optimizer did not retain a better feasible seed"
        bound = [
            name
            for name, x, (lo, hi) in zip(self.names, best.x, self.bounds, strict=True)
            if abs(x - lo) < 1.0e-4 or abs(x - hi) < 1.0e-4
        ]
        nparam = sum(lo != hi for lo, hi in self.bounds)
        return Result(
            best.x,
            bool(best.success),
            str(best.message),
            float(best.fun),
            float(2 * best.fun + nparam * np.log(len(self.counts))),
            bound,
            int(best.nit),
        )
