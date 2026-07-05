from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from sopran.core.errors import DecodeError
from sopran.maps.raster import RasterLayer


def read_tsunakawa_svm_text(
    path: Path | str,
    *,
    source: str,
    body: str = "moon",
    metadata: dict[str, Any] | None = None,
) -> RasterLayer:
    source_path = Path(path)
    rows = _read_svm_rows(source_path)
    if not rows:
        raise DecodeError(f"Tsunakawa SVM file contains no numeric grid rows: {source_path}")
    lons = np.asarray(sorted({row[0] for row in rows}), dtype=np.float64)
    lats = np.asarray(sorted({row[1] for row in rows}), dtype=np.float64)
    lon_index = {value: index for index, value in enumerate(lons)}
    lat_index = {value: index for index, value in enumerate(lats)}
    values = np.full((lats.size, lons.size), np.nan, dtype=np.float64)
    for lon, lat, bt in rows:
        values[lat_index[lat], lon_index[lon]] = bt
    return RasterLayer(
        values,
        lon=lons,
        lat=lats,
        product="svm",
        variable="svm_tsunakawa2015",
        source=source,
        units="nT",
        body=body,
        path=source_path,
        metadata={
            "model": "tsunakawa2015",
            "input_format": "Tsunakawa LunarSVM text",
            **(metadata or {}),
        },
    )


def read_tsunakawa_svm_npy(
    path: Path | str,
    *,
    source: str,
    resolution_ppd: int = 5,
    body: str = "moon",
    metadata: dict[str, Any] | None = None,
) -> RasterLayer:
    source_path = Path(path)
    values = np.asarray(np.load(source_path), dtype=np.float64)
    if values.ndim != 2:
        raise DecodeError(f"Tsunakawa SVM npy must be a 2D array: {source_path}")
    lons = _grid_centers(-180.0, 180.0, values.shape[1])
    lats = _grid_centers(-90.0, 90.0, values.shape[0])
    return RasterLayer(
        values,
        lon=lons,
        lat=lats,
        product="svm",
        variable="svm_tsunakawa2015",
        source=source,
        units="nT",
        body=body,
        path=source_path,
        metadata={
            "model": "tsunakawa2015",
            "input_format": "Tsunakawa LunarSVM npy",
            "resolution_ppd": resolution_ppd,
            **(metadata or {}),
        },
    )


def _read_svm_rows(path: Path) -> list[tuple[float, float, float]]:
    rows: list[tuple[float, float, float]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            parts = line.split()
            if len(parts) < 6:
                continue
            try:
                lon = float(parts[0])
                lat = float(parts[1])
                bt = float(parts[5])
            except ValueError:
                continue
            rows.append((lon, lat, bt))
    return rows


def _grid_centers(start: float, stop: float, count: int) -> np.ndarray:
    step = (stop - start) / count
    return np.linspace(start + step / 2.0, stop - step / 2.0, count)
