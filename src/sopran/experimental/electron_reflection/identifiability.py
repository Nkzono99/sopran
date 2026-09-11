"""Nuisance-refitted B/Delta-U scans for the incident-PAD count model.

These are numerical likelihood diagnostics, not calibrated confidence regions
or a validation of the physical field/potential interpretation.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import copy
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .incident import IncidentProblem, Result


@dataclass
class IncidentLikelihoodScan:
    """Arrays have shape (Delta U, field); field is in nT, Delta U in eV."""

    field_nT: NDArray[np.float64]
    delta_u_eV: NDArray[np.float64]
    baseline: Result
    nll: NDArray[np.float64]
    converged: NDArray[np.bool_]
    nuisance_at_bounds: NDArray[np.bool_]
    vectors: NDArray[np.float64]

    @property
    def consistent(self) -> NDArray[np.bool_]:
        """A constrained minimum cannot improve on the free minimum."""
        return self.converged & self.baseline.success & (self.nll >= self.baseline.nll - 1e-4)

    @property
    def twice_delta_nll(self) -> NDArray[np.float64]:
        return np.where(self.consistent, 2 * np.maximum(0.0, self.nll - self.baseline.nll), np.nan)


def _best(results: Sequence[Result]) -> Result:
    lowest = min(results, key=lambda result: result.nll)
    converged = [r for r in results if r.success and r.nll <= lowest.nll + 1e-4]
    return min(converged, key=lambda result: result.nll) if converged else lowest


def scan_incident_likelihood(
    problem: IncidentProblem,
    *,
    field_nT: Sequence[float],
    delta_u_eV: Sequence[float],
    seeds: Sequence[NDArray[np.float64]],
    maxiter: int = 500,
    on_point: Callable[[int, int, int, Result], None] | None = None,
) -> IncidentLikelihoodScan:
    """Scan both physical parameters while reoptimizing every nuisance.

    Two opposing grid sweeps use both a free-fit seed and the neighboring fit.
    Feasible grid solutions also seed a final unconstrained refinement. Failed
    or optimizer-inconsistent points remain recorded, but are not plotted as
    likelihood-ratio evidence. Neither input bounds nor input seeds are edited.
    """
    if problem.layout.model != "electrostatic":
        raise ValueError("A joint B/Delta-U scan requires the electrostatic model")
    field = np.asarray(field_nT, dtype=float).copy()
    delta = np.asarray(delta_u_eV, dtype=float).copy()
    for axis in (field, delta):
        if axis.ndim != 1 or axis.size < 2 or not np.all(np.isfinite(axis)):
            raise ValueError("Each grid axis must contain at least two finite values")
        if not np.all(np.diff(axis) > 0):
            raise ValueError("Grid axes must be strictly increasing")
    if np.any(field <= 0):
        raise ValueError("Fields must be positive")
    b_index = problem.layout.physical.start
    u_index = b_index + 1
    log_field = np.log(field)
    for axis, index in ((log_field, b_index), (delta, u_index)):
        lo, hi = problem.bounds[index]
        tolerance = 16 * np.finfo(float).eps * max(1.0, abs(lo), abs(hi))
        if np.any(axis < lo - tolerance) or np.any(axis > hi + tolerance):
            raise ValueError("Grid must lie within the original physical bounds")
        np.clip(axis, lo, hi, out=axis)
        if not np.all(np.diff(axis) > 0):
            raise ValueError("Grid coordinates collapse at the physical bounds")
    field = np.exp(log_field)
    starts = [np.array(seed, dtype=float, copy=True) for seed in seeds]
    if not starts or any(
        seed.shape != problem.initial.shape or not np.all(np.isfinite(seed)) for seed in starts
    ):
        raise ValueError("At least one finite full-length seed is required")
    if maxiter < 1:
        raise ValueError("maxiter must be positive")

    baseline = problem.fit(starts, maxiter=maxiter)
    # Copy only the optimizer wrapper. The response buffers/native objective are
    # read-only here; rebuilding them at each grid point is unnecessary.
    constrained = copy(problem)
    results: dict[tuple[int, int], Result] = {}
    path = [
        (j, i)
        for j in range(len(delta))
        for i in (range(len(field)) if j % 2 == 0 else reversed(range(len(field))))
    ]
    for sweep, direction in enumerate((path, list(reversed(path)))):
        neighbor = baseline.vector
        for j, i in direction:
            bounds = list(problem.bounds)
            bounds[b_index] = (float(log_field[i]),) * 2
            bounds[u_index] = (float(delta[j]),) * 2
            constrained.bounds = tuple(bounds)
            trial_seeds = [baseline.vector, neighbor]
            previous = results.get((j, i))
            if previous is not None:
                trial_seeds.append(previous.vector)
            trial = constrained.fit(trial_seeds, maxiter=maxiter)
            retained = trial if previous is None else _best([previous, trial])
            results[j, i] = retained
            neighbor = retained.vector
            if on_point is not None:
                on_point(sweep, j, i, retained)
        best_grid = _best(list(results.values()))
        baseline = _best(
            [baseline, problem.fit([baseline.vector, best_grid.vector], maxiter=maxiter)]
        )

    shape = (len(delta), len(field))
    nll = np.empty(shape)
    success = np.empty(shape, dtype=bool)
    bound = np.empty(shape, dtype=bool)
    vectors = np.empty((*shape, len(problem.initial)))
    physical_names = {problem.names[b_index], problem.names[u_index]}
    for (j, i), result in results.items():
        nll[j, i] = result.nll
        success[j, i] = result.success
        bound[j, i] = bool(set(result.at_bounds) - physical_names)
        vectors[j, i] = result.vector
    return IncidentLikelihoodScan(field, delta, baseline, nll, success, bound, vectors)
