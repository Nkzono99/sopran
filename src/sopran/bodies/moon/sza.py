from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np

from sopran.core.errors import BackendError
from sopran.maps.raster import RasterLayer


def compute_sza_layer(endpoint: Any, plan: Any) -> RasterLayer:
    return sza_layer_from_parameters(
        plan.parameters,
        body=endpoint.body.name,
        metadata=plan.to_metadata()["parameters"],
    )


def sza_layer_from_parameters(
    parameters: dict[str, Any],
    *,
    body: str,
    metadata: dict[str, Any] | None = None,
) -> RasterLayer:
    provided_sza = parameters.get("sza")
    if isinstance(provided_sza, RasterLayer):
        return provided_sza

    lon, lat = grid_from_parameters(parameters)
    if provided_sza is not None:
        values = np.full((lat.size, lon.size), float(provided_sza), dtype=np.float64)
        source = "provided.sza"
        geometry_source = "provided_sza"
        extra_metadata: dict[str, Any] = {"provided_sza_deg": float(provided_sza)}
    else:
        sun_vector, geometry_source, extra_metadata = sun_vector_from_parameters(parameters)
        values = sza_values(lon, lat, sun_vector)
        source = "computed.sza"

    layer_metadata = {
        "geometry_source": geometry_source,
        **extra_metadata,
        **(metadata or {}),
    }
    layer_metadata["geometry_source"] = geometry_source
    layer_metadata["geometry"] = geometry_source
    layer_metadata.update(extra_metadata)
    return RasterLayer(
        values,
        lon=lon,
        lat=lat,
        product="sza",
        variable="sza",
        source=source,
        units="deg",
        body=body,
        metadata=layer_metadata,
    )


def sza_values(lon: np.ndarray, lat: np.ndarray, sun_vector: np.ndarray) -> np.ndarray:
    lon_rad = np.deg2rad(lon.astype(np.float64))
    lat_rad = np.deg2rad(lat.astype(np.float64))
    cos_lat = np.cos(lat_rad)[:, np.newaxis]
    normals = np.stack(
        (
            cos_lat * np.cos(lon_rad)[np.newaxis, :],
            cos_lat * np.sin(lon_rad)[np.newaxis, :],
            np.sin(lat_rad)[:, np.newaxis] * np.ones_like(lon_rad)[np.newaxis, :],
        ),
        axis=-1,
    )
    dot = np.clip(np.sum(normals * sun_vector, axis=-1), -1.0, 1.0)
    return cast(np.ndarray, np.rad2deg(np.arccos(dot)))


def sun_vector_from_parameters(
    parameters: dict[str, Any],
) -> tuple[np.ndarray, str, dict[str, Any]]:
    if "sun_vector" in parameters:
        vector = normalize_vector(np.asarray(parameters["sun_vector"], dtype=np.float64))
        return vector, "sun_vector", {"sun_vector": vector.tolist()}

    subsolar = parameters.get("subsolar_lon_lat")
    if subsolar is None and ("subsolar_lon" in parameters or "subsolar_lat" in parameters):
        subsolar = (
            float(parameters.get("subsolar_lon", 0.0)),
            float(parameters.get("subsolar_lat", 0.0)),
        )
    if subsolar is not None:
        lon, lat = tuple(float(value) for value in subsolar)
        vector = subsolar_vector(lon=lon, lat=lat)
        return vector, "subsolar_lon_lat", {"subsolar_lon_lat": [lon, lat]}

    provided_sza = parameters.get("sza")
    if isinstance(provided_sza, RasterLayer):
        recovered = sun_vector_from_raster_metadata(provided_sza)
        if recovered is not None:
            return recovered

    if "time" in parameters:
        vector, metadata = spice_sun_vector_from_time(parameters)
        return vector, "spice", metadata
    raise ValueError(
        "Moon.sza.compute requires sun_vector=, subsolar_lon_lat=, or time= "
        "with SPICE kernels."
    )


def sun_vector_from_raster_metadata(
    layer: RasterLayer,
) -> tuple[np.ndarray, str, dict[str, Any]] | None:
    metadata = layer.metadata
    geometry_source = str(metadata.get("geometry_source", "sza_metadata"))
    if "sun_vector" in metadata:
        vector = normalize_vector(np.asarray(metadata["sun_vector"], dtype=np.float64))
        return vector, geometry_source, {"sun_vector": vector.tolist()}
    subsolar = metadata.get("subsolar_lon_lat")
    if subsolar is not None:
        lon, lat = tuple(float(value) for value in subsolar)
        return (
            subsolar_vector(lon=lon, lat=lat),
            geometry_source,
            {"subsolar_lon_lat": [lon, lat]},
        )
    return None


def spice_sun_vector_from_time(parameters: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    try:
        import spiceypy
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise BackendError(
            "spiceypy is required for Moon.sza.compute(time=...). "
            'Install the Moon optional dependencies with: pip install -e ".[moon]"'
        ) from exc

    time_value = parameters["time"]
    frame = str(parameters.get("spice_frame", parameters.get("frame", "MOON_ME")))
    target = str(parameters.get("spice_target", "SUN"))
    observer = str(parameters.get("spice_observer", "MOON"))
    abcorr = str(parameters.get("spice_abcorr", "LT+S"))
    kernels = tuple(Path(path) for path in parameters.get("spice_kernels", ()))
    try:
        for kernel in kernels:
            spiceypy.furnsh(str(kernel))
        et = float(spiceypy.utc2et(_time_to_utc_string(time_value)))
        position, light_time = spiceypy.spkpos(target, et, frame, abcorr, observer)
    except Exception as exc:
        raise BackendError(
            "SPICE-backed Moon.sza.compute(time=...) failed. Provide compatible "
            "leapsecond, planetary ephemeris, and Moon body-fixed frame kernels."
        ) from exc

    vector = normalize_vector(np.asarray(position, dtype=np.float64))
    return vector, {
        "time": str(time_value),
        "sun_vector": vector.tolist(),
        "spice_target": target,
        "spice_observer": observer,
        "spice_frame": frame,
        "spice_abcorr": abcorr,
        "spice_kernels": [path.as_posix() for path in kernels],
        "spice_light_time_s": float(light_time),
    }


def subsolar_vector(*, lon: float, lat: float) -> np.ndarray:
    lon_rad = np.deg2rad(float(lon))
    lat_rad = np.deg2rad(float(lat))
    return normalize_vector(
        np.array(
            [
                np.cos(lat_rad) * np.cos(lon_rad),
                np.cos(lat_rad) * np.sin(lon_rad),
                np.sin(lat_rad),
            ],
            dtype=np.float64,
        )
    )


def normalize_vector(vector: np.ndarray) -> np.ndarray:
    if vector.shape != (3,):
        raise ValueError("sun_vector must contain exactly three components")
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm == 0.0:
        raise ValueError("sun_vector must be finite and non-zero")
    return vector / norm


def _time_to_utc_string(value: Any) -> str:
    if isinstance(value, np.datetime64):
        return np.datetime_as_string(value.astype("datetime64[ns]"), unit="ns") + " UTC"
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).replace(tzinfo=None).isoformat() + " UTC"
    if isinstance(value, (int, float, np.integer, np.floating)):
        timestamp = datetime.fromtimestamp(float(value), tz=UTC)
        return timestamp.replace(tzinfo=None).isoformat() + " UTC"
    text = str(value)
    return text if text.upper().endswith("UTC") else f"{text} UTC"


def grid_from_parameters(parameters: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    grid_source = parameters.get("like", parameters.get("dem"))
    if isinstance(grid_source, RasterLayer):
        return grid_source.lon, grid_source.lat

    if "lon" in parameters and "lat" in parameters:
        lon = np.asarray(parameters["lon"], dtype=np.float64)
        lat = np.asarray(parameters["lat"], dtype=np.float64)
        if lon.ndim != 1 or lat.ndim != 1:
            raise ValueError("lon and lat must be one-dimensional grid axes")
        return lon, lat

    region = parameters.get("region")
    if region is not None:
        return region_grid(region, resolution_deg=float(parameters.get("resolution_deg", 1.0)))

    raise ValueError("A raster grid is required: pass like=, dem=, lon/lat=, or region=")


def region_grid(region: Any, *, resolution_deg: float) -> tuple[np.ndarray, np.ndarray]:
    if resolution_deg <= 0.0:
        raise ValueError("resolution_deg must be positive")
    lon_pair = region["lon"] if isinstance(region, dict) else region.lon
    lat_pair = region["lat"] if isinstance(region, dict) else region.lat
    lon = axis_centers(float(lon_pair[0]), float(lon_pair[1]), resolution_deg, wrap=True)
    lat = axis_centers(float(lat_pair[0]), float(lat_pair[1]), resolution_deg, wrap=False)
    return lon, lat


def axis_centers(start: float, stop: float, step: float, *, wrap: bool) -> np.ndarray:
    if wrap and stop < start:
        first = np.arange(start + step / 2.0, 360.0, step, dtype=np.float64) % 360.0
        second = np.arange(step / 2.0, stop, step, dtype=np.float64)
        return np.concatenate([first, second])
    return np.arange(start + step / 2.0, stop, step, dtype=np.float64)
