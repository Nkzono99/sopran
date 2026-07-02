from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sopran.core import Store
from sopran.core.pages import InfoPage
from sopran.core.pipeline import Pipeline
from sopran.core.schema import VariableSchema
from sopran.core.time import TimeRange
from sopran.missions.kaguya.data import KaguyaESA1Data
from sopran.missions.kaguya.files import (
    KaguyaFileSource,
    iter_public_paths,
    lmag_public_templates,
    pace_pbf_public_template,
)
from sopran.missions.kaguya.schema import KAGUYA_ESA1_SCHEMA
from sopran.missions.kaguya.sensors import normalize_sensor

DownloadMode = Literal["never", "missing", "always"]


class Kaguya:
    """Object-oriented entry point for KAGUYA/SELENE public data."""

    def __init__(
        self,
        *,
        store: Store | None = None,
        data_root: Path | str | None = None,
        fallback_roots: list[Path | str] | tuple[Path | str, ...] = (),
        source: KaguyaFileSource | None = None,
    ) -> None:
        self.store = store or Store()
        if source is None:
            local_root = (
                Path(data_root)
                if data_root is not None
                else self.store.raw_path("kaguya", "pds3")
            )
            source = KaguyaFileSource(
                local_root=local_root,
                fallback_roots=tuple(Path(root) for root in fallback_roots),
            )
        self.source = source
        self.esa1 = PaceInstrument(self, "ESA1")
        self.esa2 = PaceInstrument(self, "ESA2")
        self.ima = PaceInstrument(self, "IMA")
        self.iea = PaceInstrument(self, "IEA")
        self.lmag = LmagInstrument(self)

    def info(self) -> InfoPage:
        return InfoPage(
            title="KAGUYA",
            lines=(
                "esa1: PACE Electron Spectrum Analyzer 1",
                "esa2: PACE Electron Spectrum Analyzer 2",
                "ima: PACE Ion Mass Analyzer",
                "iea: PACE Ion Energy Analyzer",
                "lmag: Lunar MAGnetometer",
            ),
        )


@dataclass(frozen=True)
class KaguyaQuery:
    instrument: KaguyaInstrument
    start: object
    stop: object | None = None

    def remote_files(self) -> list[str]:
        return self.instrument.remote_files(self.start, self.stop)

    def remote_urls(self) -> list[str]:
        return [self.instrument.mission.source.remote_url(path) for path in self.remote_files()]

    def files(self, *, download: DownloadMode = "never", overwrite: bool = False) -> list[Path]:
        paths: list[Path] = []
        for remote_file in self.remote_files():
            path = self.instrument.mission.source.local_path(remote_file)
            if download == "never":
                if path.exists():
                    paths.append(path)
                continue
            if download == "missing":
                path = self.instrument.mission.source.download(remote_file, overwrite=False)
            elif download == "always":
                path = self.instrument.mission.source.download(remote_file, overwrite=True)
            else:
                raise ValueError("download must be 'never', 'missing', or 'always'")
            if overwrite or path.exists():
                paths.append(path)
        return paths


@dataclass(frozen=True)
class LoadPlan:
    dataset_id: str
    time: TimeRange
    remote_files: list[str]

    def __str__(self) -> str:
        files = "\n".join(f"  - {path}" for path in self.remote_files)
        return (
            f"SOPRAN plan: {self.dataset_id}\n"
            f"time: {self.time.start_iso} .. {self.time.stop_iso}\n"
            f"remote_files:\n{files}"
        )


class VariableEndpoint:
    def __init__(
        self,
        instrument: PaceInstrument,
        schema: VariableSchema,
        *,
        dataset_id: str,
    ) -> None:
        self.instrument = instrument
        self._schema = schema
        self.dataset_id = dataset_id
        self.name = schema.name

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"KAGUYA.{self.instrument.name}.{self.name}",
            lines=(
                f"description: {self._schema.description}",
                f"dims: {self._schema.dims}",
                f"units: {self._schema.units}",
                f"aliases: {', '.join(self._schema.aliases) or 'none'}",
                f"example: kg.esa1.{self.name}.load(time)",
            ),
        )

    def schema(self) -> VariableSchema:
        return self._schema

    def plan(self, time: TimeRange | None = None) -> LoadPlan:
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        return LoadPlan(
            dataset_id=self.dataset_id,
            time=time,
            remote_files=self.instrument.remote_files_for_period(time),
        )

    def load(self, time: TimeRange | None = None, *, download: DownloadMode = "never"):
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        data = self.instrument.load(time, download=download)
        return getattr(data, self.name)


class KaguyaInstrument:
    def __init__(self, mission: Kaguya, name: str) -> None:
        self.mission = mission
        self.name = name

    def select(self, start: object, stop: object | None = None) -> KaguyaQuery:
        return KaguyaQuery(self, start, stop)

    def remote_files(self, start: object, stop: object | None = None) -> list[str]:
        raise NotImplementedError


class PaceInstrument(KaguyaInstrument):
    def __init__(self, mission: Kaguya, sensor: object, *, version: str = "003") -> None:
        self.sensor = normalize_sensor(sensor)
        self.version = version
        super().__init__(mission, self.sensor)
        if self.sensor == "ESA1":
            self.energy_flux = self._variable("energy_flux")
            self.eflux = self.energy_flux
            self.counts = self._variable("counts")
            self.energy = self._variable("energy")
            self.quality = self._variable("quality")

    def _variable(self, name: str) -> VariableEndpoint:
        return VariableEndpoint(
            self,
            KAGUYA_ESA1_SCHEMA.variable(name),
            dataset_id=f"kaguya.esa1.{name}",
        )

    def __getattr__(self, name: str):
        if name.startswith("__") or self.sensor != "ESA1":
            raise AttributeError(name)
        variables = tuple(variable.name for variable in KAGUYA_ESA1_SCHEMA.variables)
        suggestion = "energy_flux" if name == "flux" else variables[0]
        available = "\n".join(f"  {variable}" for variable in variables)
        raise AttributeError(
            f"Kaguya.{self.name} has no variable {name!r}.\n\n"
            f"Available variables:\n{available}\n\n"
            f"Did you mean:\n  {suggestion}?\n\n"
            f"Try:\n  kg.esa1.info()\n  kg.esa1.{suggestion}.load(time)"
        )

    def remote_files(self, start: object, stop: object | None = None) -> list[str]:
        template = pace_pbf_public_template(self.sensor, version=self.version)
        return iter_public_paths(template, start, stop)

    def remote_files_for_period(self, time: TimeRange) -> list[str]:
        paths: list[str] = []
        for day in time.days():
            paths.extend(self.remote_files(day))
        return paths

    def pipeline(self, time: TimeRange) -> Pipeline:
        return Pipeline(source=f"kaguya.{self.sensor.lower()}", time=time)

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"KAGUYA.{self.name}",
            lines=tuple(
                f"{variable.name}: {variable.description}"
                for variable in KAGUYA_ESA1_SCHEMA.variables
            )
            if self.sensor == "ESA1"
            else (),
        )

    def schema(self):
        if self.sensor != "ESA1":
            raise NotImplementedError(f"Schema is not implemented for {self.sensor}")
        return KAGUYA_ESA1_SCHEMA

    def plan(self, time: TimeRange | None = None) -> LoadPlan:
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.name}")
        return LoadPlan(
            dataset_id=f"kaguya.{self.sensor.lower()}",
            time=time,
            remote_files=self.remote_files_for_period(time),
        )

    def load(
        self,
        time: TimeRange | None = None,
        *,
        download: DownloadMode = "never",
    ) -> KaguyaESA1Data:
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.name}")
        if self.sensor != "ESA1":
            raise NotImplementedError(f"load() is not implemented for {self.sensor}")
        files: list[Path] = []
        for day in time.days():
            files.extend(self.select(day).files(download=download))
        return KaguyaESA1Data(time=time, files=tuple(files))


class LmagInstrument(KaguyaInstrument):
    def __init__(self, mission: Kaguya, *, version: str = "1.0") -> None:
        self.version = version
        super().__init__(mission, "LMAG")

    def remote_files(self, start: object, stop: object | None = None) -> list[str]:
        paths: list[str] = []
        for template in lmag_public_templates(version=self.version):
            paths.extend(iter_public_paths(template, start, stop))
        return paths


def _missing_time_error(endpoint: str) -> ValueError:
    return ValueError(
        f"Time range is required for {endpoint}.\n\n"
        'Examples:\n  time = spn.period("2008-02-01", "2008-02-02")\n'
        f"  kg.esa1.energy_flux.load(time)\n\n"
        "Or use a Project case:\n  case.kaguya.esa1.energy_flux.load()"
    )
