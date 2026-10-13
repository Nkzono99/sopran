"""NASA OMNI near-Earth solar-wind data: hourly OMNI2 and 5-minute HRO."""

from sopran.core.sources import register_source

from .hourly import Omni, OmniData, OmniVariable, read_omni_hourly
from .hro import (
    OMNI_ABERRATION_CORRECTION_KM_S,
    OMNI_HRO_SCHEMA,
    OmniHighResolution,
    OmniHroData,
    read_omni_hro,
    read_omni_hro_arrays,
)

register_source("omni", "sopran.missions.omni.hourly:Omni.from_view")

__all__ = [
    "OMNI_ABERRATION_CORRECTION_KM_S",
    "OMNI_HRO_SCHEMA",
    "Omni",
    "OmniData",
    "OmniHighResolution",
    "OmniHroData",
    "OmniVariable",
    "read_omni_hourly",
    "read_omni_hro",
    "read_omni_hro_arrays",
]
