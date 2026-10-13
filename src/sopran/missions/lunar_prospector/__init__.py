"""Lunar Prospector MAG/ER Level 1B data from the PDS PPI node."""

from sopran.core.sources import register_source
from sopran.missions.lunar_prospector.mission import (
    LP_ER_SCHEMA,
    LP_MAG_SCHEMA,
    LunarProspector,
)

register_source(
    "lunar_prospector", "sopran.missions.lunar_prospector.mission:LunarProspector.from_view"
)

__all__ = ["LP_ER_SCHEMA", "LP_MAG_SCHEMA", "LunarProspector"]
