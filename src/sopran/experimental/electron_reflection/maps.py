"""Paired affected/reference count maps built from native pitch-angle records.

Each native record keeps its own energy and pitch bins. Records are oriented so
that the affected (outgoing) hemisphere is at low pitch, redistributed onto a
common log-energy x pitch grid by bin overlap, summed as counts and exposure
(never as ratios), and folded into affected and reference halves.
Redistribution assumes uniform density within each log-energy and pitch bin.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
Side = Literal["low", "high"]


@dataclass(frozen=True)
class PitchCountRecord:
    """Raw counts and exposure of one native record on its own (energy, pitch) bins."""

    counts: FloatArray
    exposure: FloatArray
    energy_edges_eV: FloatArray
    pitch_edges_deg: FloatArray
    affected_side: Side

    def __post_init__(self) -> None:
        counts = np.asarray(self.counts, dtype=float)
        exposure = np.asarray(self.exposure, dtype=float)
        energy_edges = np.asarray(self.energy_edges_eV, dtype=float)
        pitch_edges = np.asarray(self.pitch_edges_deg, dtype=float)
        if counts.ndim != 2 or exposure.shape != counts.shape:
            raise ValueError("counts and exposure must share an (energy, pitch) shape")
        if energy_edges.shape != (counts.shape[0] + 1,) or pitch_edges.shape != (
            counts.shape[1] + 1,
        ):
            raise ValueError("bin edges must have one more value than the matching axis")
        if not np.all(np.isfinite(energy_edges)) or np.any(energy_edges <= 0.0):
            raise ValueError("energy edges must be finite and positive")
        if np.any(np.diff(energy_edges) <= 0.0) or np.any(np.diff(pitch_edges) <= 0.0):
            raise ValueError("bin edges must increase")
        if pitch_edges[0] < 0.0 or pitch_edges[-1] > 180.0:
            raise ValueError("pitch edges must lie within 0-180 degrees")
        finite = counts[np.isfinite(counts)]
        if np.any(finite < 0.0) or np.any(np.abs(finite - np.rint(finite)) > 1.0e-8):
            raise ValueError("counts must be raw non-negative integer event counts")
        if self.affected_side not in ("low", "high"):
            raise ValueError("affected_side must be 'low' or 'high'")
        object.__setattr__(self, "counts", counts)
        object.__setattr__(self, "exposure", exposure)
        object.__setattr__(self, "energy_edges_eV", energy_edges)
        object.__setattr__(self, "pitch_edges_deg", pitch_edges)

    @classmethod
    def from_spectrum(cls, spectrum: Any, *, index: int, affected_side: Side) -> PitchCountRecord:
        """Take record ``index`` of a raw-count (time, energy, pitch_angle) spectrum.

        Energy rows are sorted; rows sharing an energy are summed over their
        measured cells. Energy edges are geometric midpoints between centers and
        pitch edges come from the spectrum's ``pitch_edges`` attribute.
        """

        array = spectrum.to_xarray() if hasattr(spectrum, "to_xarray") else spectrum
        if str(array.attrs.get("value")) != "counts" or str(array.attrs.get("units")) not in {
            "count",
            "counts",
        }:
            raise ValueError("paired maps require a raw-count spectrum")
        if tuple(str(dim) for dim in array.dims) != ("time", "energy", "pitch_angle"):
            raise ValueError("spectrum must have (time, energy, pitch_angle) dimensions")
        if not 0 <= index < array.sizes["time"]:
            raise IndexError("index must select an existing record")
        counts = np.asarray(array.values[index], dtype=float)
        exposure = np.asarray(array.coords["exposure"].values[index], dtype=float)
        energy_coord = np.asarray(array.coords["energy_eV"].values, dtype=float)
        energy = (energy_coord[index] if energy_coord.ndim == 2 else energy_coord).reshape(-1)
        pitch = np.asarray(array.coords["pitch_angle"].values, dtype=float)
        order = np.argsort(energy, kind="stable")
        energy, counts, exposure = energy[order], counts[order], exposure[order]
        unique, group = np.unique(energy, return_inverse=True)
        if unique.size != energy.size:
            measured = np.isfinite(counts) & np.isfinite(exposure) & (exposure > 0.0)
            summed_counts = np.full((unique.size, pitch.size), np.nan)
            summed_exposure = np.full_like(summed_counts, np.nan)
            for row in range(unique.size):
                rows = group == row
                supported = np.any(measured[rows], axis=0)
                summed_counts[row, supported] = np.sum(
                    np.where(measured[rows], counts[rows], 0.0), axis=0
                )[supported]
                summed_exposure[row, supported] = np.sum(
                    np.where(measured[rows], exposure[rows], 0.0), axis=0
                )[supported]
            energy, counts, exposure = unique, summed_counts, summed_exposure
        edges = array.attrs.get("pitch_edges")
        return cls(
            counts=counts,
            exposure=exposure,
            energy_edges_eV=_energy_edges(energy),
            pitch_edges_deg=(
                np.asarray(edges, dtype=float) if edges is not None else _pitch_edges(pitch)
            ),
            affected_side=affected_side,
        )


@dataclass(frozen=True)
class PairedMapSettings:
    """Common grid: log-spaced energy edges and equal pitch bins over 0-180 degrees."""

    energy_min_eV: float = 20.0
    energy_max_eV: float = 1500.0
    energy_bins: int = 24
    pitch_bins: int = 16

    def __post_init__(self) -> None:
        if not (
            np.isfinite(self.energy_min_eV)
            and np.isfinite(self.energy_max_eV)
            and 0.0 < self.energy_min_eV < self.energy_max_eV
        ):
            raise ValueError("energy limits must be finite, positive and increasing")
        if self.energy_bins < 3 or self.pitch_bins < 6 or self.pitch_bins % 2:
            raise ValueError("require >=3 energy bins and an even number of >=6 pitch bins")

    @property
    def energy_edges_eV(self) -> FloatArray:
        return np.geomspace(self.energy_min_eV, self.energy_max_eV, self.energy_bins + 1)

    @property
    def pitch_edges_deg(self) -> FloatArray:
        return np.linspace(0.0, 180.0, self.pitch_bins + 1)


@dataclass(frozen=True)
class PairedMap:
    """Full-pitch sums and their affected/reference folds on the common grid.

    ``affected`` is the low-pitch half after orientation and ``reference`` the
    high-pitch half reversed, so column ``j`` of both is the same folded pitch.
    ``pair_observed`` marks cells with positive exposure on both sides and
    ``fit_valid`` additionally requires counts and enough cells per energy row.
    """

    energy_eV: FloatArray
    energy_edges_eV: FloatArray
    pitch_edges_deg: FloatArray
    global_counts: FloatArray
    global_exposure: FloatArray
    affected_counts: FloatArray
    reference_counts: FloatArray
    affected_exposure: FloatArray
    reference_exposure: FloatArray
    pair_observed: BoolArray
    fit_valid: BoolArray

    def arrays(self) -> dict[str, np.ndarray]:
        """Arrays by name, as stored in an ER batch input shard."""

        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def accumulate_pitch_map(
    records: Iterable[PitchCountRecord], settings: PairedMapSettings | None = None
) -> tuple[FloatArray, FloatArray]:
    """Sum oriented record counts and exposure on the common grid by bin overlap."""

    grid = settings or PairedMapSettings()
    target_energy = np.log(grid.energy_edges_eV)
    target_pitch = grid.pitch_edges_deg
    counts = np.zeros((grid.energy_bins, grid.pitch_bins))
    exposure = np.zeros_like(counts)
    for record in records:
        c, x = record.counts, record.exposure
        valid = np.isfinite(c) & np.isfinite(x) & (x > 0.0)
        pitch_edges = record.pitch_edges_deg
        if record.affected_side == "high":
            pitch_edges = 180.0 - pitch_edges[::-1]
            c, x, valid = c[:, ::-1], x[:, ::-1], valid[:, ::-1]
        energy_overlap = bin_overlap_fraction(np.log(record.energy_edges_eV), target_energy)
        pitch_overlap = bin_overlap_fraction(pitch_edges, target_pitch)
        counts += energy_overlap.T @ np.where(valid, c, 0.0) @ pitch_overlap
        exposure += energy_overlap.T @ np.where(valid, x, 0.0) @ pitch_overlap
    return counts, exposure


def fold_pitch_map(
    global_counts: ArrayLike,
    global_exposure: ArrayLike,
    settings: PairedMapSettings | None = None,
    *,
    min_pitch_bins_per_energy: int = 3,
    spacecraft_potential_eV: float = 0.0,
    require_positive_pairs: bool = False,
) -> PairedMap:
    """Fold full-pitch sums into affected/reference halves and mark usable cells."""

    grid = settings or PairedMapSettings()
    counts = np.asarray(global_counts, dtype=float)
    exposure = np.asarray(global_exposure, dtype=float)
    if counts.shape != (grid.energy_bins, grid.pitch_bins) or exposure.shape != counts.shape:
        raise ValueError("global maps must match the settings grid")
    split = grid.pitch_bins // 2
    affected, reference = counts[:, :split], counts[:, split:][:, ::-1]
    affected_exposure, reference_exposure = exposure[:, :split], exposure[:, split:][:, ::-1]
    observed = (affected_exposure > 0.0) & (reference_exposure > 0.0)
    valid = observed & ((affected + reference) > 0.0)
    if require_positive_pairs:
        valid &= (affected > 0.0) & (reference > 0.0)
    energy_edges = grid.energy_edges_eV
    energy = np.sqrt(energy_edges[:-1] * energy_edges[1:])
    supported = (valid.sum(axis=1) >= min_pitch_bins_per_energy) & (
        energy > spacecraft_potential_eV
    )
    valid &= supported[:, None]
    return PairedMap(
        energy_eV=energy,
        energy_edges_eV=energy_edges,
        pitch_edges_deg=grid.pitch_edges_deg,
        global_counts=counts,
        global_exposure=exposure,
        affected_counts=affected,
        reference_counts=reference,
        affected_exposure=affected_exposure,
        reference_exposure=reference_exposure,
        pair_observed=observed,
        fit_valid=valid,
    )


def build_paired_map(
    records: Iterable[PitchCountRecord],
    settings: PairedMapSettings | None = None,
    **fold_options: Any,
) -> PairedMap:
    """``accumulate_pitch_map`` followed by ``fold_pitch_map``."""

    grid = settings or PairedMapSettings()
    counts, exposure = accumulate_pitch_map(records, grid)
    return fold_pitch_map(counts, exposure, grid, **fold_options)


def bin_overlap_fraction(source_edges: ArrayLike, target_edges: ArrayLike) -> FloatArray:
    """Fraction of each source bin that falls in each target bin (source x target)."""

    source = np.asarray(source_edges, dtype=float)
    target = np.asarray(target_edges, dtype=float)
    lower = np.maximum(source[:-1, None], target[None, :-1])
    upper = np.minimum(source[1:, None], target[None, 1:])
    overlap = np.maximum(0.0, upper - lower)
    width = (source[1:] - source[:-1])[:, None]
    fraction: FloatArray = np.divide(
        overlap, width, out=np.zeros_like(overlap), where=width > 0.0
    )
    return fraction


def _energy_edges(centers: FloatArray) -> FloatArray:
    if centers.size == 1:
        return np.asarray([centers[0] / np.sqrt(2.0), centers[0] * np.sqrt(2.0)])
    middle = np.sqrt(centers[:-1] * centers[1:])
    return np.concatenate(([centers[0] ** 2 / middle[0]], middle, [centers[-1] ** 2 / middle[-1]]))


def _pitch_edges(centers: FloatArray) -> FloatArray:
    if centers.size == 1:
        half = min(float(centers[0]), 180.0 - float(centers[0]), 5.0)
        return np.asarray([centers[0] - half, centers[0] + half])
    middle = 0.5 * (centers[:-1] + centers[1:])
    return np.concatenate(
        (
            [max(0.0, centers[0] - (middle[0] - centers[0]))],
            middle,
            [min(180.0, centers[-1] + (centers[-1] - middle[-1]))],
        )
    )


__all__ = [
    "PairedMap",
    "PairedMapSettings",
    "PitchCountRecord",
    "accumulate_pitch_map",
    "bin_overlap_fraction",
    "build_paired_map",
    "fold_pitch_map",
]
