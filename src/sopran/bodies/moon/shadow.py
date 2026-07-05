from __future__ import annotations

from typing import Any

import numpy as np

from sopran.maps.raster import RasterLayer

from .sza import (
    normalize_vector,
    sun_vector_from_parameters,
    sza_layer_from_parameters,
    sza_values,
)


def legacy_shadowmap_filename(sza: float | int | str) -> str:
    return f"is_shadow_{sza}deg_0.tif"


def compute_shadow_layer(endpoint: Any, plan: Any) -> RasterLayer:
    parameters = dict(plan.parameters)
    method = str(parameters.get("method", "sza_threshold"))
    if method == "terrain_ray":
        return compute_terrain_ray_shadow_layer(endpoint, plan)
    if method != "sza_threshold":
        raise NotImplementedError(
            "Moon.shadow.compute currently supports method='sza_threshold' "
            "and method='terrain_ray'"
        )
    threshold = float(parameters.get("threshold_deg", 90.0))
    sza = sza_layer_from_parameters(
        parameters,
        body=endpoint.body.name,
        metadata=plan.to_metadata()["parameters"],
    )
    values = np.where(np.isnan(sza.values), np.nan, (sza.values > threshold).astype(float))
    return RasterLayer(
        values,
        lon=sza.lon,
        lat=sza.lat,
        product="shadow",
        variable="shadow",
        source="computed.sza_threshold",
        units="fraction",
        body=endpoint.body.name,
        metadata={
            **plan.to_metadata()["parameters"],
            "method": method,
            "threshold_deg": threshold,
            "sza": sza.spec.to_metadata(),
            "legacy_shadowmap_pattern": legacy_shadowmap_filename("{sza}"),
        },
    )


def compute_terrain_ray_shadow_layer(endpoint: Any, plan: Any) -> RasterLayer:
    parameters = dict(plan.parameters)
    dem = parameters.get("dem", parameters.get("like"))
    if not isinstance(dem, RasterLayer):
        raise ValueError("Moon.shadow.compute(method='terrain_ray') requires dem=RasterLayer")
    sun_vector, geometry_source, geometry_metadata = sun_vector_from_parameters(parameters)
    sza_metadata = {
        "geometry_source": geometry_source,
        "geometry": geometry_source,
        **geometry_metadata,
        **plan.to_metadata()["parameters"],
    }
    sza_metadata["geometry_source"] = geometry_source
    sza_metadata["geometry"] = geometry_source
    sza_metadata.update(geometry_metadata)
    sza = RasterLayer(
        sza_values(dem.lon, dem.lat, sun_vector),
        lon=dem.lon,
        lat=dem.lat,
        product="sza",
        variable="sza",
        source="computed.sza",
        units="deg",
        body=endpoint.body.name,
        metadata=sza_metadata,
    )
    moon_radius_m = float(parameters.get("moon_radius_m", 1_737_400.0))
    max_steps = parameters.get("max_steps")
    margin_deg = float(parameters.get("horizon_margin_deg", 0.0))
    values = terrain_ray_shadow_values(
        dem,
        sun_vector=sun_vector,
        moon_radius_m=moon_radius_m,
        max_steps=int(max_steps) if max_steps is not None else None,
        horizon_margin_deg=margin_deg,
    )
    return RasterLayer(
        values,
        lon=dem.lon,
        lat=dem.lat,
        product="shadow",
        variable="shadow",
        source="computed.terrain_ray",
        units="fraction",
        body=endpoint.body.name,
        metadata={
            **plan.to_metadata()["parameters"],
            "method": "terrain_ray",
            "geometry_source": geometry_source,
            **geometry_metadata,
            "moon_radius_m": moon_radius_m,
            "max_steps": int(max_steps) if max_steps is not None else max(dem.shape),
            "horizon_margin_deg": margin_deg,
            "dem": dem.spec.to_metadata(),
            "sza": sza.spec.to_metadata(),
        },
    )


def terrain_ray_shadow_values(
    dem: RasterLayer,
    *,
    sun_vector: np.ndarray,
    moon_radius_m: float,
    max_steps: int | None = None,
    horizon_margin_deg: float = 0.0,
) -> np.ndarray:
    sun = normalize_vector(np.asarray(sun_vector, dtype=np.float64))
    values = np.full(dem.shape, np.nan, dtype=np.float64)
    default_steps = max(dem.shape)
    steps = default_steps if max_steps is None else max(int(max_steps), 0)
    for row in range(dem.shape[0]):
        for col in range(dem.shape[1]):
            height = float(dem.values[row, col])
            if not np.isfinite(height):
                continue
            values[row, col] = _terrain_shadow_at_cell(
                dem,
                row=row,
                col=col,
                sun_vector=sun,
                moon_radius_m=moon_radius_m,
                max_steps=steps,
                horizon_margin_deg=horizon_margin_deg,
            )
    return values


def _terrain_shadow_at_cell(
    dem: RasterLayer,
    *,
    row: int,
    col: int,
    sun_vector: np.ndarray,
    moon_radius_m: float,
    max_steps: int,
    horizon_margin_deg: float,
) -> float:
    lon = float(dem.lon[col])
    lat = float(dem.lat[row])
    normal, east, north = _local_basis(lon=lon, lat=lat)
    up_component = float(np.dot(sun_vector, normal))
    if up_component <= 0.0:
        return 1.0
    horizontal_east = float(np.dot(sun_vector, east))
    horizontal_north = float(np.dot(sun_vector, north))
    horizontal_norm = float(np.hypot(horizontal_east, horizontal_north))
    if horizontal_norm == 0.0 or max_steps == 0:
        return 0.0

    sun_altitude = float(np.arcsin(np.clip(up_component, -1.0, 1.0)))
    ray_step = _ray_index_step(
        dem,
        row=row,
        horizontal_east=horizontal_east,
        horizontal_north=horizontal_north,
        moon_radius_m=moon_radius_m,
    )
    if ray_step is None:
        return 0.0
    row_step, col_step = ray_step
    origin_height = float(dem.values[row, col])
    visited: set[tuple[int, int]] = set()
    cursor_row = float(row)
    cursor_col = float(col)
    margin = np.deg2rad(horizon_margin_deg)
    for _ in range(max_steps):
        cursor_row += row_step
        cursor_col += col_step
        sample_row = int(round(cursor_row))
        sample_col = int(round(cursor_col))
        if not (0 <= sample_row < dem.shape[0] and 0 <= sample_col < dem.shape[1]):
            break
        sample = (sample_row, sample_col)
        if sample == (row, col) or sample in visited:
            continue
        visited.add(sample)
        sample_height = float(dem.values[sample_row, sample_col])
        if not np.isfinite(sample_height):
            continue
        distance = _surface_distance_m(
            dem,
            row0=row,
            col0=col,
            row1=sample_row,
            col1=sample_col,
            moon_radius_m=moon_radius_m,
        )
        if distance <= 0.0:
            continue
        horizon_angle = float(np.arctan2(sample_height - origin_height, distance))
        if horizon_angle > sun_altitude + margin:
            return 1.0
    return 0.0


def _local_basis(*, lon: float, lat: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lon_rad = np.deg2rad(lon)
    lat_rad = np.deg2rad(lat)
    cos_lat = np.cos(lat_rad)
    normal = np.array(
        [cos_lat * np.cos(lon_rad), cos_lat * np.sin(lon_rad), np.sin(lat_rad)],
        dtype=np.float64,
    )
    east = np.array([-np.sin(lon_rad), np.cos(lon_rad), 0.0], dtype=np.float64)
    north = np.array(
        [-np.sin(lat_rad) * np.cos(lon_rad), -np.sin(lat_rad) * np.sin(lon_rad), cos_lat],
        dtype=np.float64,
    )
    return normal, east, north


def _ray_index_step(
    dem: RasterLayer,
    *,
    row: int,
    horizontal_east: float,
    horizontal_north: float,
    moon_radius_m: float,
) -> tuple[float, float] | None:
    lon_step = _axis_step(dem.lon)
    lat_step = _axis_step(dem.lat)
    lat_rad = np.deg2rad(float(dem.lat[row]))
    col_speed = 0.0
    row_speed = 0.0
    if lon_step != 0.0:
        lon_m = moon_radius_m * np.cos(lat_rad) * np.deg2rad(abs(lon_step))
        if lon_m > 0.0:
            col_speed = horizontal_east * np.sign(lon_step) / lon_m
    if lat_step != 0.0:
        lat_m = moon_radius_m * np.deg2rad(abs(lat_step))
        if lat_m > 0.0:
            row_speed = horizontal_north * np.sign(lat_step) / lat_m
    scale = max(abs(row_speed), abs(col_speed))
    if scale == 0.0:
        return None
    return row_speed / scale, col_speed / scale


def _axis_step(axis: np.ndarray) -> float:
    if axis.size < 2:
        return 0.0
    diffs = np.diff(axis.astype(np.float64))
    finite = diffs[np.isfinite(diffs) & (diffs != 0.0)]
    if finite.size == 0:
        return 0.0
    return float(np.median(finite))


def _surface_distance_m(
    dem: RasterLayer,
    *,
    row0: int,
    col0: int,
    row1: int,
    col1: int,
    moon_radius_m: float,
) -> float:
    lat0 = float(dem.lat[row0])
    lon0 = float(dem.lon[col0])
    lat1 = float(dem.lat[row1])
    lon1 = float(dem.lon[col1])
    delta_lon = _smallest_lon_delta(lon1 - lon0)
    mean_lat = np.deg2rad((lat0 + lat1) / 2.0)
    east = moon_radius_m * np.cos(mean_lat) * np.deg2rad(delta_lon)
    north = moon_radius_m * np.deg2rad(lat1 - lat0)
    return float(np.hypot(east, north))


def _smallest_lon_delta(delta: float) -> float:
    return float((delta + 180.0) % 360.0 - 180.0)
