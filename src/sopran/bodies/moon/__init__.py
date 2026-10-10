from sopran.bodies.moon.api import Moon, SurfaceEndpoint
from sopran.bodies.moon.dem import load_dem_raster
from sopran.bodies.moon.models import SurfacePlan, SurfaceSource
from sopran.bodies.moon.schema import MOON_SURFACE_SCHEMA
from sopran.core.sources import register_source

register_source("moon", "sopran.bodies.moon.api:Moon.from_view")

__all__ = [
    "MOON_SURFACE_SCHEMA",
    "Moon",
    "SurfaceEndpoint",
    "SurfacePlan",
    "SurfaceSource",
    "load_dem_raster",
]
