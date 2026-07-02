from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from sopran.core.data import SopranArray
from sopran.core.time import TimeRange
from sopran.missions.kaguya.schema import KAGUYA_ESA1_SCHEMA


@dataclass(frozen=True)
class KaguyaESA1Data:
    time: TimeRange
    files: tuple[Path, ...] = ()
    instrument: str = "ESA1"

    @cached_property
    def energy_flux(self) -> SopranArray:
        return SopranArray(
            name="energy_flux",
            time=self.time,
            schema=KAGUYA_ESA1_SCHEMA.variable("energy_flux"),
            files=self.files,
        )

    @property
    def eflux(self) -> SopranArray:
        return self.energy_flux

    @cached_property
    def counts(self) -> SopranArray:
        return SopranArray(
            name="counts",
            time=self.time,
            schema=KAGUYA_ESA1_SCHEMA.variable("counts"),
            files=self.files,
        )

    @cached_property
    def energy(self) -> SopranArray:
        return SopranArray(
            name="energy",
            time=self.time,
            schema=KAGUYA_ESA1_SCHEMA.variable("energy"),
            files=self.files,
        )

    @cached_property
    def quality(self) -> SopranArray:
        return SopranArray(
            name="quality",
            time=self.time,
            schema=KAGUYA_ESA1_SCHEMA.variable("quality"),
            files=self.files,
        )

    def to_xarray(self):
        try:
            import numpy as np
            import xarray as xr
        except ImportError as exc:
            raise RuntimeError("xarray is required for to_xarray()") from exc
        energy_flux_schema = KAGUYA_ESA1_SCHEMA.variable("energy_flux")
        counts_schema = KAGUYA_ESA1_SCHEMA.variable("counts")
        quality_schema = KAGUYA_ESA1_SCHEMA.variable("quality")
        return xr.Dataset(
            data_vars={
                "energy_flux": (
                    energy_flux_schema.dims,
                    np.empty((0, 0, 0)),
                    {
                        "units": energy_flux_schema.units,
                        "description": energy_flux_schema.description,
                    },
                ),
                "counts": (
                    counts_schema.dims,
                    np.empty((0, 0, 0)),
                    {"units": counts_schema.units, "description": counts_schema.description},
                ),
                "quality": (
                    quality_schema.dims,
                    np.empty((0,)),
                    {"description": quality_schema.description},
                ),
            },
            coords={"time": [], "energy": [], "look": []},
            attrs={
                "mission": "kaguya",
                "instrument": self.instrument,
                "start": self.time.start_iso,
                "stop": self.time.stop_iso,
            },
        )
