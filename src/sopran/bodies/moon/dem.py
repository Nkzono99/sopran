from __future__ import annotations

from pathlib import Path
from typing import Any

from sopran.maps.raster import RasterLayer, read_geotiff

from .sources import SURFACE_SOURCE_INFO, canonical_source_id


def load_dem_raster(endpoint: Any, plan: Any, data_path: Path) -> RasterLayer:
    source = str(plan.parameters.get("source", endpoint.default_source or ""))
    return read_geotiff(
        data_path,
        product="dem",
        variable=endpoint.variable,
        source=canonical_source_id(source),
        units=endpoint.units or "m",
        body=endpoint.body.name,
        source_scale=optional_source_scale(source),
        source_offset=optional_source_offset(source),
        region=plan.parameters.get("region"),
        metadata=plan.to_metadata()["parameters"],
    )


def optional_source_scale(source: str | None) -> float | None:
    info = SURFACE_SOURCE_INFO.get(canonical_source_id(source))
    return info.scale if info is not None else None


def optional_source_offset(source: str | None) -> float | None:
    info = SURFACE_SOURCE_INFO.get(canonical_source_id(source))
    return info.offset if info is not None else None
