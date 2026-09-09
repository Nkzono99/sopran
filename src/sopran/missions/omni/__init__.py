"""NASA OMNI2 hourly near-Earth solar-wind and geomagnetic data."""

from .hourly import Omni, OmniData, OmniVariable, read_omni_hourly

__all__ = ["Omni", "OmniData", "OmniVariable", "read_omni_hourly"]
