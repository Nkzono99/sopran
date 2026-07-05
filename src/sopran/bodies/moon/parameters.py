from __future__ import annotations

from typing import Any, cast

from .models import metadata_value


def surface_parameters(product: str, parameters: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(parameters)
    if product in {"shadow", "illumination"} and (
        "method" in normalized or "model" in normalized
    ):
        model = surface_model(normalized)
        normalized["method"] = model
        normalized["model"] = model
    if (
        product == "sza"
        or "geometry_source" in normalized
        or "geometry" in normalized
        or "ephemeris" in normalized
    ):
        default_geometry = "spice" if product == "sza" else None
        geometry = geometry_source(normalized, default=default_geometry)
        normalized["geometry"] = geometry
        normalized["geometry_source"] = geometry
    reference = coordinate_reference(normalized)
    normalized["lon_domain"] = canonical_lon_domain(
        str(normalized.get("lon_domain", reference.get("lon_domain", "0_360")))
    )
    normalized["lon_direction"] = canonical_lon_direction(
        str(
            normalized.get(
                "lon_direction",
                reference.get("lon_direction", "east_positive"),
            )
        )
    )
    normalized["lat_type"] = canonical_lat_type(
        str(normalized.get("lat_type", reference.get("lat_type", "planetocentric")))
    )
    normalized["shape"] = canonical_shape(
        str(normalized.get("shape", reference.get("shape", "spherical")))
    )
    datum = normalized.get("datum", reference.get("datum"))
    if datum is not None:
        normalized["datum"] = str(datum)
    normalized["projection"] = canonical_projection(
        str(normalized.get("projection", reference.get("projection", "native")))
    )
    normalized["area_or_point"] = canonical_area_or_point(
        str(normalized.get("area_or_point", reference.get("area_or_point", "area")))
    )
    return normalized


def surface_model(parameters: dict[str, Any]) -> str:
    method = parameters.get("method")
    model = parameters.get("model")
    if method is not None and model is not None and str(method) != str(model):
        raise ValueError("method and model must match when both are provided")
    value = method if method is not None else model
    if value is None:
        raise ValueError("method/model cannot be empty")
    return str(value)


def geometry_source(parameters: dict[str, Any], *, default: str | None) -> str:
    value = parameters.get(
        "geometry_source",
        parameters.get("geometry", parameters.get("ephemeris", default)),
    )
    if value is None:
        raise ValueError("geometry_source cannot be empty")
    return str(value)


def coordinate_reference(parameters: dict[str, Any]) -> dict[str, Any]:
    region = metadata_value(parameters.get("region"))
    if isinstance(region, dict):
        return region
    dem = metadata_value(parameters.get("dem"))
    if isinstance(dem, dict) and isinstance(dem.get("parameters"), dict):
        return cast(dict[str, Any], dem["parameters"])
    return {}


def canonical_lon_domain(lon_domain: str) -> str:
    if lon_domain == "minus180_180":
        return "-180_180"
    if lon_domain in {"0_360", "-180_180"}:
        return lon_domain
    raise ValueError("lon_domain must be '0_360', '-180_180', or 'minus180_180'")


def canonical_lon_direction(lon_direction: str) -> str:
    if lon_direction in {"east_positive", "west_positive"}:
        return lon_direction
    raise ValueError("lon_direction must be 'east_positive' or 'west_positive'")


def canonical_lat_type(lat_type: str) -> str:
    if lat_type in {"planetocentric", "planetographic"}:
        return lat_type
    raise ValueError("lat_type must be 'planetocentric' or 'planetographic'")


def canonical_shape(shape: str) -> str:
    aliases = {
        "sphere": "spherical",
        "spice": "spice_body_radii",
        "body_radii": "spice_body_radii",
    }
    canonical = aliases.get(shape, shape)
    allowed = {"spherical", "ellipsoid", "triaxial", "spice_body_radii"}
    if canonical in allowed:
        return canonical
    raise ValueError(
        "shape must be one of spherical, ellipsoid, triaxial, "
        "spice_body_radii, sphere, spice, or body_radii"
    )


def canonical_projection(projection: str) -> str:
    aliases = {
        "polar_stereo": "polar_stereographic",
    }
    canonical = aliases.get(projection, projection)
    allowed = {
        "equirectangular",
        "polar_stereographic",
        "orthographic",
        "azimuthal_equidistant",
        "lambert",
        "native",
    }
    if canonical in allowed:
        return canonical
    raise ValueError(
        "projection must be one of equirectangular, polar_stereographic, "
        "orthographic, azimuthal_equidistant, lambert, native, or polar_stereo"
    )


def canonical_area_or_point(area_or_point: str) -> str:
    if area_or_point in {"area", "point"}:
        return area_or_point
    raise ValueError("area_or_point must be 'area' or 'point'")
