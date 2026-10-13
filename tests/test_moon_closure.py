from __future__ import annotations

import numpy as np
import pytest

from sopran.experimental.moon import closure


def test_thresholds_apply_and_longitude_wraps_in_both_backends() -> None:
    lon = [-1.0, 1.0, -1.0, 1.0]
    lat = [0.0, 0.0, 2.0, 2.0]
    closed = [1, 1, 0, 1]
    path_max = [12.0, 14.0, 30.0, 13.0]
    separation = [6.0, 7.0, 8.0, 2.0]
    native = closure.classify_closed_islands(
        lon,
        lat,
        closed,
        path_max,
        separation,
        min_path_max_nT=10.0,
        min_footpoint_separation_deg=5.0,
    )
    assert native.strong_closed_island.tolist() == [True, True, False, False]
    assert native.island_id.tolist() == [0, 0, -1, -1]
    assert native.island_count == 1
    strong, island_id = closure._classify_python(
        np.asarray(lon, float),
        np.asarray(lat, float),
        np.asarray(closed, np.uint8),
        np.asarray(path_max, float),
        np.asarray(separation, float),
        10.0,
        5.0,
        1,
    )
    assert strong.tolist() == native.strong_closed_island.tolist()
    assert island_id.tolist() == native.island_id.tolist()


def test_small_components_are_dropped_and_incomplete_grids_are_rejected() -> None:
    lon = [-2.0, 0.0, 2.0] * 3
    lat = [-2.0] * 3 + [0.0] * 3 + [2.0] * 3
    closed = [1, 0, 0, 0, 0, 0, 0, 0, 1]
    path_max = [12.0, 0, 0, 0, 0, 0, 0, 0, 13.0]
    separation = [6.0, 0, 0, 0, 0, 0, 0, 0, 7.0]
    result = closure.classify_closed_islands(
        lon,
        lat,
        closed,
        path_max,
        separation,
        min_path_max_nT=10.0,
        min_footpoint_separation_deg=5.0,
        min_cells=2,
    )
    assert not result.strong_closed_island.any() and result.island_count == 0
    with pytest.raises(ValueError):
        closure.classify_closed_islands(
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1, 1, 1],
            [1.0] * 3,
            [1.0] * 3,
            min_path_max_nT=0.0,
            min_footpoint_separation_deg=0.0,
        )
