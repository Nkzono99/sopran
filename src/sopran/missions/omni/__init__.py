"""NASA OMNI2 hourly near-Earth solar-wind and geomagnetic data."""

from sopran.core.sources import register_source

from .hourly import Omni, OmniData, OmniVariable, read_omni_hourly

register_source("omni", "sopran.missions.omni.hourly:Omni.from_view")

__all__ = ["Omni", "OmniData", "OmniVariable", "read_omni_hourly"]
