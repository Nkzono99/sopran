"""Shared paired-count input and magnetic/electrostatic boundary convention."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class ElectronReflectionCounts:
    """Paired affected/reference electron counts on a folded 0-90 degree PAD.

    Rows are energy bins and columns are folded pitch-angle bins. Exposure is
    proportional to integration time times detector response; only its ratio
    between paired cells corrects the affected/reference flux ratio.
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
    has been identified. Energies are those measured at the spacecraft. A
    non-zero ``spacecraft_potential_eV`` converts them to the ambient plasma,
    and ``delta_u_eff_eV`` then becomes surface minus ambient plasma.
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
