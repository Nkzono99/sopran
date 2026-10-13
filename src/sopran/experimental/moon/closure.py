"""Connected islands of closed-like cells on a lon/lat grid.

Cells flagged ``closed_like`` (for example both trace branches reached the
surface) that also pass the path-maximum and footpoint-separation thresholds
are grouped with four-neighbour connectivity and longitude wraparound.
Islands smaller than ``min_cells`` are dropped. The thresholds are the
caller's; this is a grid walk, not a physical closure test.
"""

from __future__ import annotations

import importlib
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray


@dataclass(frozen=True)
class ClosedIslands:
    strong_closed_island: NDArray[np.bool_]
    island_id: NDArray[np.int64]
    min_path_max_nT: float
    min_footpoint_separation_deg: float
    min_cells: int

    @property
    def island_count(self) -> int:
        return (
            int(self.island_id.max() + 1)
            if self.island_id.size and self.island_id.max() >= 0
            else 0
        )

    def to_pandas(self) -> Any:
        import pandas as pd

        return pd.DataFrame(
            {"strong_closed_island": self.strong_closed_island, "island_id": self.island_id}
        )


def classify_closed_islands(
    lon_deg: ArrayLike,
    lat_deg: ArrayLike,
    closed_like: ArrayLike,
    path_max_nT: ArrayLike,
    footpoint_separation_deg: ArrayLike,
    *,
    min_path_max_nT: float,
    min_footpoint_separation_deg: float,
    min_cells: int = 1,
) -> ClosedIslands:
    """Label connected closed islands; inputs are one row per cell of a complete grid."""

    lon = np.ascontiguousarray(np.asarray(lon_deg, dtype=float).reshape(-1))
    lat = np.ascontiguousarray(np.asarray(lat_deg, dtype=float).reshape(-1))
    closed = np.ascontiguousarray(np.asarray(closed_like).reshape(-1).astype(np.uint8))
    path_max = np.ascontiguousarray(np.asarray(path_max_nT, dtype=float).reshape(-1))
    separation = np.ascontiguousarray(np.asarray(footpoint_separation_deg, dtype=float).reshape(-1))
    if not (lon.size == lat.size == closed.size == path_max.size == separation.size):
        raise ValueError("all inputs must have one value per grid cell")
    if min_cells <= 0:
        raise ValueError("min_cells must be positive")
    try:
        native: Any | None = importlib.import_module("sopran._native")
    except ImportError:
        native = None
    if native is not None and hasattr(native, "classify_closed_islands_batch"):
        raw = native.classify_closed_islands_batch(
            lon,
            lat,
            closed,
            path_max,
            separation,
            float(min_path_max_nT),
            float(min_footpoint_separation_deg),
            int(min_cells),
        )
        strong = np.asarray(raw["strong_closed_island"]).astype(bool)
        island_id = np.asarray(raw["island_id"], dtype=np.int64)
    else:
        strong, island_id = _classify_python(
            lon,
            lat,
            closed,
            path_max,
            separation,
            float(min_path_max_nT),
            float(min_footpoint_separation_deg),
            int(min_cells),
        )
    return ClosedIslands(
        strong_closed_island=strong,
        island_id=island_id,
        min_path_max_nT=float(min_path_max_nT),
        min_footpoint_separation_deg=float(min_footpoint_separation_deg),
        min_cells=int(min_cells),
    )


def _classify_python(
    lon: NDArray[np.float64],
    lat: NDArray[np.float64],
    closed: NDArray[np.uint8],
    path_max: NDArray[np.float64],
    separation: NDArray[np.float64],
    min_path_max: float,
    min_separation: float,
    min_cells: int,
) -> tuple[NDArray[np.bool_], NDArray[np.int64]]:
    rows = lon.size
    strong = np.zeros(rows, dtype=bool)
    island_id = np.full(rows, -1, dtype=np.int64)
    if rows == 0:
        return strong, island_id
    if not (np.all(np.isfinite(lon)) and np.all(np.isfinite(lat))):
        raise ValueError("lon/lat arrays must be finite")
    lon_values, lon_index = np.unique(np.round(lon, 9), return_inverse=True)
    lat_values, lat_index = np.unique(np.round(lat, 9), return_inverse=True)
    lon_count, lat_count = lon_values.size, lat_values.size
    if lon_count * lat_count != rows:
        raise ValueError("lon/lat inputs must form a complete rectangular grid")
    grid_index = lat_index * lon_count + lon_index
    if np.unique(grid_index).size != rows:
        raise ValueError("lon/lat grid has duplicate or missing cells")
    row_lookup = np.empty(rows, dtype=np.int64)
    row_lookup[grid_index] = np.arange(rows)
    mask = np.zeros(rows, dtype=bool)
    mask[grid_index] = (
        (closed != 0)
        & np.isfinite(path_max)
        & np.isfinite(separation)
        & (path_max >= min_path_max)
        & (separation >= min_separation)
    )
    visited = np.zeros(rows, dtype=bool)
    next_id = 0
    for start in range(rows):
        if not mask[start] or visited[start]:
            continue
        queue = deque([start])
        visited[start] = True
        component = []
        while queue:
            idx = queue.popleft()
            component.append(idx)
            j, i = divmod(idx, lon_count)
            neighbours = [
                (j - 1, i) if j > 0 else None,
                (j + 1, i) if j + 1 < lat_count else None,
                (j, (i - 1) % lon_count),
                (j, (i + 1) % lon_count),
            ]
            for neighbour in neighbours:
                if neighbour is None:
                    continue
                nidx = neighbour[0] * lon_count + neighbour[1]
                if mask[nidx] and not visited[nidx]:
                    visited[nidx] = True
                    queue.append(nidx)
        if len(component) < min_cells:
            continue
        for idx in component:
            strong[row_lookup[idx]] = True
            island_id[row_lookup[idx]] = next_id
        next_id += 1
    return strong, island_id


__all__ = ["ClosedIslands", "classify_closed_islands"]
