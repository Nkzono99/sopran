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


RAVAT2020_COMPONENTS = {
    "total": (5, "Total field magnitude"),
    "br": (2, "Radial field Br (positive outward)"),
    "btheta": (3, "Colatitudinal field Btheta (positive southward)"),
    "bphi": (4, "Azimuthal field Bphi (positive eastward)"),
}


def read_ravat2020_grid(
    path: Path | str,
    *,
    component: str = "total",
    source: str,
    body: str = "moon",
    metadata: dict[str, Any] | None = None,
) -> RasterLayer:
    """Read the Ravat et al. (2020) surface field grid for one field component.

    The file lists longitude, latitude, Br, Btheta, Bphi and total field per line.
    Grid axes are rebuilt from the coordinate values, so row order is not assumed.
    """

    import pandas as pd

    key = component.lower()
    if key not in RAVAT2020_COMPONENTS:
        raise ValueError(
            "component must be one of " + ", ".join(sorted(RAVAT2020_COMPONENTS))
        )
    source_path = Path(path)
    column, description = RAVAT2020_COMPONENTS[key]
    try:
        table = pd.read_csv(
            source_path,
            sep=r"\s+",
            header=None,
            usecols=[0, 1, column],
            skiprows=_leading_text_lines(source_path),
            dtype=np.float64,
        )
    except (ValueError, pd.errors.ParserError) as exc:
        raise DecodeError(f"Ravat 2020 grid is not a numeric table: {source_path}") from exc
    if table.empty:
        raise DecodeError(f"Ravat 2020 file contains no numeric grid rows: {source_path}")
    lons, lon_index = np.unique(table[0].to_numpy(), return_inverse=True)
    lats, lat_index = np.unique(table[1].to_numpy(), return_inverse=True)
    values = np.full((lats.size, lons.size), np.nan, dtype=np.float64)
    values[lat_index, lon_index] = table[column].to_numpy()
    return RasterLayer(
        values,
        lon=lons,
        lat=lats,
        product="svm",
        variable="svm_ravat2020",
        source=source,
        units="nT",
        body=body,
        path=source_path,
        metadata={
            "model": "ravat2020",
            "component": key,
            "component_description": description,
            "surface": "ellipsoid, equatorial radius 1738.1 km, polar radius 1736.0 km",
            "input_format": "Ravat et al. 2020 lon/lat/Br/Btheta/Bphi/total text grid",
            **(metadata or {}),
        },
    )


def _leading_text_lines(path: Path, *, limit: int = 1000) -> int:
    """Count header lines before the first line whose first six fields are numbers."""

    with path.open("r", encoding="utf-8", errors="replace") as file:
        for index, line in enumerate(file):
            if index >= limit:
                break
            parts = line.split()
            if len(parts) >= 6:
                try:
                    [float(part) for part in parts[:6]]
                except ValueError:
                    continue
                return index
    return 0


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
