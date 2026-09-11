"""Bounded magnetic-vector interpolation and radial hemisphere geometry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import ArrayLike, NDArray

if TYPE_CHECKING:
    from sopran.core.time import TimeRange
    from sopran.missions.kaguya.lmag import KaguyaLmagData
    from sopran.missions.kaguya.mission import DownloadMode, LmagInstrument

GEOMETRY_POLICY = "bounded_geometry_v2"
# The public LMAG series has 4 s cadence; allow one missing sample, not long gaps.
MAX_GEOMETRY_GAP_SECONDS = 8.0


def load_lmag_with_margin(
    instrument: LmagInstrument, time: TimeRange, *, download: DownloadMode | None = None,
) -> KaguyaLmagData:
    """Require the requested data, but permit missing optional boundary files."""
    from sopran.core.time import TimeRange

    instrument.load(time, download=download, missing="error")
    margin = timedelta(seconds=MAX_GEOMETRY_GAP_SECONDS)
    return instrument.load(
        TimeRange(time.start - margin, time.stop + margin), download=download, missing="empty"
    )


@dataclass(frozen=True)
class VectorInterpolation:
    values: NDArray[np.float64]
    bracket_seconds: NDArray[np.float64]
    nearest_seconds: NDArray[np.float64]
    valid: NDArray[np.bool_]


def interpolate_vectors(
    source_seconds: ArrayLike,
    vectors: ArrayLike,
    target_seconds: ArrayLike,
    *,
    max_gap_seconds: float = MAX_GEOMETRY_GAP_SECONDS,
) -> VectorInterpolation:
    """Interpolate only within finite, ordered source brackets of bounded width.

    An exact finite sample remains usable beside a gap. Nonfinite source values
    are not dropped: doing so would silently bridge missing telemetry.
    """
    source = np.asarray(source_seconds, dtype=float)
    target = np.asarray(target_seconds, dtype=float)
    values = np.asarray(vectors, dtype=float)
    if source.ndim != 1 or target.ndim != 1 or values.shape != (source.size, 3):
        raise ValueError("expected source/target time vectors and source x 3 values")
    if not np.all(np.isfinite(source)) or np.any(np.diff(source) <= 0):
        raise ValueError("source times must be finite and strictly increasing")
    if not np.isfinite(max_gap_seconds) or max_gap_seconds <= 0:
        raise ValueError("max_gap_seconds must be finite and positive")
    result = np.full((target.size, 3), np.nan)
    bracket = np.full(target.size, np.nan)
    nearest = np.full(target.size, np.nan)
    valid = np.zeros(target.size, dtype=bool)
    if not source.size:
        return VectorInterpolation(result, bracket, nearest, valid)
    right = np.searchsorted(source, target)
    hi = np.clip(right, 0, source.size - 1)
    exact = source[hi] == target
    lo = np.where(exact, hi, np.clip(right - 1, 0, source.size - 1))
    bracket = source[hi] - source[lo]
    nearest = np.minimum(np.abs(target - source[lo]), np.abs(target - source[hi]))
    valid = (
        np.isfinite(target) & (target >= source[0]) & (target <= source[-1])
        & (bracket <= max_gap_seconds)
        & np.all(np.isfinite(values[lo]), axis=1)
        & np.all(np.isfinite(values[hi]), axis=1)
    )
    for component in range(3):
        result[valid, component] = np.interp(target[valid], source, values[:, component])
    return VectorInterpolation(result, bracket, nearest, valid)


def geometry_support(
    magnetic: ArrayLike, position: ArrayLike,
) -> tuple[NDArray[np.bool_], NDArray[np.str_], NDArray[np.float64]]:
    """Return valid rows, outgoing hemispheres and B/r cosine (not connectivity)."""
    b, r = np.asarray(magnetic, dtype=float), np.asarray(position, dtype=float)
    norm = np.linalg.norm(b, axis=1) * np.linalg.norm(r, axis=1)
    cosine = np.divide(np.sum(b * r, axis=1), norm, out=np.full(len(b), np.nan), where=norm > 0)
    valid = np.isfinite(cosine) & (cosine != 0)
    sides = np.where(valid, np.where(cosine > 0, "low", "high"), "unknown")
    return valid, sides, np.clip(cosine, -1, 1)
