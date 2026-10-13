"""Measured-field residuals against a crustal model and a quiet-time baseline.

``residual_decomposition`` splits ``B_observed - B_base`` into the component
along a reference direction and the perpendicular magnitude. ``quiet_field_
baseline`` builds a per-cell median of a field quantity under quiet upstream
conditions so that ``B_sc / B_quiet`` can be read as the local compression.
Both are table transforms; the physical reading of the residual (external
field, induced field, model error) is left to the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class FieldResidual:
    """Vector residual and its decomposition, one row per record."""

    residual_nT: FloatArray
    residual_abs_nT: FloatArray
    base_abs_nT: FloatArray
    observed_abs_nT: FloatArray
    parallel_nT: FloatArray
    perpendicular_abs_nT: FloatArray
    fractional_abs: FloatArray
    direction_source: str

    def to_pandas(self) -> Any:
        import pandas as pd

        return pd.DataFrame(
            {
                "residual_x_nT": self.residual_nT[:, 0],
                "residual_y_nT": self.residual_nT[:, 1],
                "residual_z_nT": self.residual_nT[:, 2],
                "residual_abs_nT": self.residual_abs_nT,
                "base_abs_nT": self.base_abs_nT,
                "observed_abs_nT": self.observed_abs_nT,
                "parallel_nT": self.parallel_nT,
                "perpendicular_abs_nT": self.perpendicular_abs_nT,
                "fractional_abs": self.fractional_abs,
            }
        )


def residual_decomposition(
    observed_nT: ArrayLike,
    base_nT: ArrayLike,
    direction_nT: ArrayLike | None = None,
) -> FieldResidual:
    """``observed - base`` with the component along ``direction`` (default: observed).

    Rows whose direction is not finite or has zero norm fall back to the
    observed direction; rows where both fail get NaN parallel/perpendicular
    parts. ``fractional_abs`` is ``|residual| / |base|`` (NaN when ``|base|`` is 0).
    """

    observed = _rows3(observed_nT, "observed_nT")
    base = _rows3(base_nT, "base_nT")
    if base.shape != observed.shape:
        raise ValueError("observed_nT and base_nT must have the same shape")
    if direction_nT is None:
        direction = observed
        source = "observed"
    else:
        direction = _rows3(direction_nT, "direction_nT")
        if direction.shape != observed.shape:
            raise ValueError("direction_nT must match observed_nT shape")
        source = "supplied_with_observed_fallback"
    residual = observed - base
    residual_abs = _norm_rows(residual)
    base_abs = _norm_rows(base)
    observed_abs = _norm_rows(observed)
    unit = _unit_rows(direction)
    fallback = ~np.isfinite(unit).all(axis=1)
    unit[fallback] = _unit_rows(observed)[fallback]
    parallel = np.sum(residual * unit, axis=1)
    with np.errstate(invalid="ignore"):
        perpendicular = np.sqrt(np.maximum(residual_abs**2 - parallel**2, 0.0))
        fractional = np.where(
            np.isfinite(base_abs) & (base_abs > 0.0), residual_abs / base_abs, np.nan
        )
    return FieldResidual(
        residual_nT=residual,
        residual_abs_nT=residual_abs,
        base_abs_nT=base_abs,
        observed_abs_nT=observed_abs,
        parallel_nT=parallel,
        perpendicular_abs_nT=perpendicular,
        fractional_abs=fractional,
        direction_source=source,
    )


def svm3d_residual(
    grid: Any,
    position_me_km: ArrayLike,
    observed_nT: ArrayLike,
    *,
    bounds: str = "nan",
) -> FieldResidual:
    """Residual of the measured MOON_ME field against the SVM3D shell grid at each position."""

    base = np.asarray(grid.field_at(position_me_km, bounds=bounds), dtype=float)
    return residual_decomposition(observed_nT, base)


@dataclass(frozen=True)
class QuietBaseline:
    """Per-record quiet baseline with the cell statistics it came from."""

    value: FloatArray
    source: NDArray[np.str_]
    cell_count: NDArray[np.int64]
    grid_deg: float
    global_median: float

    def to_pandas(self) -> Any:
        import pandas as pd

        return pd.DataFrame(
            {
                "b_quiet": self.value,
                "b_quiet_source": self.source,
                "b_quiet_cell_count": self.cell_count,
            }
        )


def quiet_field_baseline(
    lon_deg: ArrayLike,
    lat_deg: ArrayLike,
    value: ArrayLike,
    quiet: ArrayLike,
    *,
    grid_deg: float = 10.0,
    min_events: int = 5,
    fallback: ArrayLike | None = None,
) -> QuietBaseline:
    """Median of ``value`` in ``grid_deg`` lon/lat cells over ``quiet`` rows.

    Cells with fewer than ``min_events`` quiet rows use the global quiet
    median, then ``fallback`` (for example ``svm_nT + 1``) when the global
    median is not finite. ``source`` records which one each row received.
    """

    lon = np.asarray(lon_deg, dtype=float)
    lat = np.asarray(lat_deg, dtype=float)
    values = np.asarray(value, dtype=float)
    mask = np.asarray(quiet, dtype=bool)
    if not (lon.shape == lat.shape == values.shape == mask.shape) or lon.ndim != 1:
        raise ValueError("lon_deg, lat_deg, value and quiet must be one-dimensional and aligned")
    if not np.isfinite(grid_deg) or grid_deg <= 0.0 or 360.0 % grid_deg != 0.0:
        raise ValueError("grid_deg must divide 360 degrees")
    lon_index = np.floor((np.mod(lon + 180.0, 360.0)) / grid_deg).astype(np.int64)
    lat_index = np.clip(
        np.floor((lat + 90.0) / grid_deg).astype(np.int64), 0, int(180.0 / grid_deg) - 1
    )
    cell = lat_index * int(360.0 / grid_deg) + lon_index
    usable = mask & np.isfinite(values) & np.isfinite(lon) & np.isfinite(lat)
    global_median = float(np.median(values[usable])) if np.any(usable) else float("nan")
    out = np.full(values.shape, np.nan)
    source = np.full(values.shape, "fallback", dtype="<U19")
    counts = np.zeros(values.shape, dtype=np.int64)
    for key in np.unique(cell[usable]):
        members = usable & (cell == key)
        count = int(np.count_nonzero(members))
        rows = cell == key
        counts[rows] = count
        if count >= int(min_events):
            out[rows] = float(np.median(values[members]))
            source[rows] = "quiet_grid_median"
    remaining = ~np.isfinite(out)
    if np.isfinite(global_median):
        out[remaining] = global_median
        source[remaining] = "global_quiet_median"
    elif fallback is not None:
        fill = np.asarray(fallback, dtype=float)
        out[remaining] = fill[remaining]
    return QuietBaseline(
        value=out,
        source=source.astype(str),
        cell_count=counts,
        grid_deg=float(grid_deg),
        global_median=global_median,
    )


def _rows3(values: ArrayLike, name: str) -> FloatArray:
    array = np.asarray(values, dtype=float)
    if array.ndim == 1 and array.size == 3:
        array = array.reshape(1, 3)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError(f"{name} must have shape (rows, 3)")
    return array


def _norm_rows(values: FloatArray) -> FloatArray:
    finite = np.isfinite(values).all(axis=1)
    return cast(FloatArray, np.where(finite, np.linalg.norm(values, axis=1), np.nan))


def _unit_rows(values: FloatArray) -> FloatArray:
    norm = _norm_rows(values)
    with np.errstate(invalid="ignore", divide="ignore"):
        unit = values / norm[:, None]
    unit[~(np.isfinite(norm) & (norm > 0.0))] = np.nan
    return cast(FloatArray, unit)


__all__ = [
    "FieldResidual",
    "QuietBaseline",
    "quiet_field_baseline",
    "residual_decomposition",
    "svm3d_residual",
]
