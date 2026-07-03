from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from sopran.core.errors import BackendError, DecodeError


@dataclass(frozen=True)
class RasterSpec:
    body: str
    product: str
    variable: str
    source: str
    units: str | None = None
    frame: str = "Moon body-fixed"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "body": self.body,
            "product": self.product,
            "variable": self.variable,
            "source": self.source,
            "units": self.units,
            "frame": self.frame,
            "metadata": self.metadata,
        }


class RasterLayer:
    """Small 2D lon/lat raster interface for Moon map layers."""

    def __init__(
        self,
        values: Any,
        *,
        lon: Any,
        lat: Any,
        product: str,
        variable: str,
        source: str,
        units: str | None = None,
        body: str = "moon",
        frame: str = "Moon body-fixed",
        path: Path | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        array = np.asarray(values, dtype=np.float64)
        lon_array = np.asarray(lon, dtype=np.float64)
        lat_array = np.asarray(lat, dtype=np.float64)
        if array.ndim != 2:
            raise ValueError("RasterLayer values must be a 2D array")
        if array.shape != (lat_array.size, lon_array.size):
            raise ValueError(
                "RasterLayer shape must match latitude and longitude axes: "
                f"{array.shape} != ({lat_array.size}, {lon_array.size})"
            )
        self.values = array
        self.lon = lon_array
        self.lat = lat_array
        self.product = product
        self.variable = variable
        self.source = source
        self.units = units
        self.body = body
        self.frame = frame
        self.path = Path(path) if path is not None else None
        self.metadata = metadata or {}
        self.spec = RasterSpec(
            body=body,
            product=product,
            variable=variable,
            source=source,
            units=units,
            frame=frame,
            metadata=self.metadata,
        )

    @property
    def shape(self) -> tuple[int, int]:
        return self.values.shape

    def sample(self, *, lat: Any, lon: Any, method: str = "nearest") -> Any:
        if method != "nearest":
            raise ValueError("RasterLayer.sample currently supports method='nearest'")
        lat_values, lon_values = np.broadcast_arrays(
            np.asarray(lat, dtype=np.float64),
            np.asarray(lon, dtype=np.float64),
        )
        flat = [
            self.values[_nearest_index(self.lat, y), _nearest_index(self.lon, x)]
            for y, x in zip(lat_values.ravel(), lon_values.ravel(), strict=True)
        ]
        sampled = np.asarray(flat, dtype=np.float64).reshape(lat_values.shape)
        if sampled.shape == ():
            return float(sampled)
        return sampled

    def interp(self, *, lat: Any, lon: Any, method: str = "nearest") -> Any:
        return self.sample(lat=lat, lon=lon, method=method)

    def to_xarray(self, *, name: str | None = None):
        try:
            import xarray as xr
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise BackendError(
                "xarray is required for RasterLayer.to_xarray(). "
                'Install it with: pip install -e ".[moon]"'
            ) from exc
        return xr.DataArray(
            self.values,
            dims=("lat", "lon"),
            coords={"lat": self.lat, "lon": self.lon},
            name=name or self.variable,
            attrs={
                "units": self.units,
                "source": self.source,
                "product": self.product,
                "frame": self.frame,
                **self.metadata,
            },
        )


def read_geotiff(
    path: Path | str,
    *,
    product: str,
    variable: str,
    source: str,
    units: str | None,
    body: str = "moon",
    source_scale: float | None = None,
    source_offset: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> RasterLayer:
    rasterio = _import_rasterio()
    source_path = Path(path)
    with rasterio.open(source_path) as dataset:
        band = dataset.read(1, masked=True)
        values = np.asarray(band.filled(np.nan), dtype=np.float64)
        scale = _first_numeric(getattr(dataset, "scales", None), default=1.0)
        offset = _first_numeric(getattr(dataset, "offsets", None), default=0.0)
        if scale == 1.0 and offset == 0.0 and source_scale is not None:
            scale = float(source_scale)
            offset = float(source_offset or 0.0)
        if scale != 1.0 or offset != 0.0:
            values = values * scale + offset
        lon = np.asarray([dataset.xy(0, col)[0] for col in range(dataset.width)])
        lat = np.asarray([dataset.xy(row, 0)[1] for row in range(dataset.height)])
        raster_metadata = {
            "driver": dataset.driver,
            "width": dataset.width,
            "height": dataset.height,
            "crs": str(dataset.crs) if dataset.crs is not None else None,
            "transform": tuple(dataset.transform),
            "scale": scale,
            "offset": offset,
        }
    return RasterLayer(
        values,
        lon=lon,
        lat=lat,
        product=product,
        variable=variable,
        source=source,
        units=units,
        body=body,
        path=source_path,
        metadata={**raster_metadata, **(metadata or {})},
    )


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


def _import_rasterio():
    try:
        return importlib.import_module("rasterio")
    except ModuleNotFoundError as exc:
        raise BackendError(
            "rasterio is required to load Moon GeoTIFF rasters. "
            'Install the Moon optional dependencies with: pip install -e ".[moon]"'
        ) from exc


def _nearest_index(axis: np.ndarray, value: float) -> int:
    return int(np.abs(axis - value).argmin())


def _first_numeric(values: Any, *, default: float) -> float:
    if values is None:
        return default
    try:
        value = values[0]
    except (IndexError, TypeError):
        return default
    if value is None:
        return default
    return float(value)


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
