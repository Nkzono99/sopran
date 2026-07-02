from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import Any

from sopran.core.data import SopranArray
from sopran.core.time import TimeRange
from sopran.missions.kaguya.pace import PaceData, read_pace_pbf
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

    @cached_property
    def pace(self) -> PaceData | None:
        if not self.files:
            return None
        return read_pace_pbf(self.files)

    def to_xarray(self):
        try:
            import numpy as np
            import xarray as xr
        except ImportError as exc:
            raise RuntimeError("xarray is required for to_xarray()") from exc

        if self.pace is not None:
            return self._pace_to_xarray(np, xr, self.pace)

        return self._empty_xarray(np, xr)

    def _empty_xarray(self, np: Any, xr: Any):
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

    def _pace_to_xarray(self, np: Any, xr: Any, pace: PaceData):
        energy_flux_schema = KAGUYA_ESA1_SCHEMA.variable("energy_flux")
        counts_schema = KAGUYA_ESA1_SCHEMA.variable("counts")
        quality_schema = KAGUYA_ESA1_SCHEMA.variable("quality")
        count_rows = []
        headers = []

        for record in pace.record_order:
            counts = record.arrays.get("cnt")
            if counts is None:
                continue
            count_rows.append(_counts_to_energy_look(counts))
            headers.append(pace.headers[record.index])

        if not count_rows:
            return self._empty_xarray(np, xr)

        look_count = count_rows[0].shape[1]
        if any(row.shape[1] != look_count for row in count_rows):
            raise ValueError("PACE records with mixed look dimensions cannot be stacked yet")

        counts = np.stack(count_rows)
        energy_flux = np.full(counts.shape, np.nan, dtype=float)
        quality = np.array(
            [int(header.get("data_quality", 0)) for header in headers],
            dtype=np.uint32,
        )
        time_values = np.array(
            [_header_time_to_datetime64(header.get("time"), np) for header in headers],
            dtype="datetime64[ns]",
        )

        return xr.Dataset(
            data_vars={
                "energy_flux": (
                    energy_flux_schema.dims,
                    energy_flux,
                    {
                        "units": energy_flux_schema.units,
                        "description": energy_flux_schema.description,
                        "calibration": "not_applied",
                    },
                ),
                "counts": (
                    counts_schema.dims,
                    counts,
                    {"units": counts_schema.units, "description": counts_schema.description},
                ),
                "quality": (
                    quality_schema.dims,
                    quality,
                    {"description": quality_schema.description},
                ),
            },
            coords={
                "time": time_values,
                "energy": np.arange(counts.shape[1]),
                "look": np.arange(counts.shape[2]),
            },
            attrs={
                "mission": "kaguya",
                "instrument": self.instrument,
                "sensor": pace.sensor_name,
                "raw_format": "PACE PBF",
                "source_files": [str(path) for path in self.files],
                "start": self.time.start_iso,
                "stop": self.time.stop_iso,
            },
        )


def _counts_to_energy_look(counts: Any):
    if counts.ndim < 2 or counts.shape[0] != 32:
        raise NotImplementedError(
            f"PACE count records with shape {counts.shape} cannot be mapped to ESA1 yet"
        )
    return counts.reshape(32, -1)


def _header_time_to_datetime64(value: object, np: Any):
    if value is None:
        return np.datetime64("NaT", "ns")
    text = datetime.fromtimestamp(float(value), tz=timezone.utc).replace(tzinfo=None).isoformat()
    return np.datetime64(text, "ns")
