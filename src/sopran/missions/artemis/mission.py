from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from sopran.core.data import SopranArray
from sopran.core.errors import DatasetNotFoundError
from sopran.core.pages import GuidePage, InfoPage
from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.core.store import Store
from sopran.core.time import TimeRange

_GUIDE_LANGUAGES = ("ja", "en")
_PUBLIC_DOC_URL = "https://nkzono99.github.io/sopran/missions/artemis/"

ARTEMIS_MAGNETIC_FIELD = VariableSchema(
    name="magnetic_field",
    aliases=("b", "fgm"),
    dims=("time", "component"),
    units="nT",
    description="ARTEMIS fluxgate magnetic field vector.",
)
ARTEMIS_FGM_SCHEMA = InstrumentSchema(
    mission="artemis",
    instrument="fgm",
    variables=(ARTEMIS_MAGNETIC_FIELD,),
)


class Artemis:
    """Object-oriented entry point for ARTEMIS probes."""

    def __init__(self, *, store: Store | None = None) -> None:
        self.store = store or Store()
        self.p1 = ArtemisProbe(self, "p1")
        self.p2 = ArtemisProbe(self, "p2")

    def info(self) -> InfoPage:
        return InfoPage(
            title="ARTEMIS",
            lines=(
                "p1: ARTEMIS P1 probe",
                "p2: ARTEMIS P2 probe",
            ),
        )

    def guide(self, *, language: str = "en") -> GuidePage:
        return _read_guide(title="ARTEMIS", language=language)

    def help(self, *, language: str = "en") -> GuidePage:
        return self.guide(language=language)


class ArtemisProbe:
    def __init__(self, mission: Artemis, probe: str) -> None:
        self.mission = mission
        self.probe = probe
        self.fgm = ArtemisFgmInstrument(self)

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"ARTEMIS.{self.probe.upper()}",
            lines=("fgm: fluxgate magnetometer",),
        )

    def guide(self, *, language: str = "en") -> GuidePage:
        return self.mission.guide(language=language)

    def help(self, *, language: str = "en") -> GuidePage:
        return self.guide(language=language)


class ArtemisFgmInstrument:
    def __init__(self, probe: ArtemisProbe) -> None:
        self.probe = probe
        self.magnetic_field = ArtemisVariableEndpoint(
            instrument=self,
            schema=ARTEMIS_MAGNETIC_FIELD,
        )
        self.b = self.magnetic_field

    @property
    def dataset_prefix(self) -> str:
        return f"artemis.{self.probe.probe}.fgm"

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"ARTEMIS.{self.probe.probe.upper()}.FGM",
            lines=(f"{ARTEMIS_MAGNETIC_FIELD.name}: {ARTEMIS_MAGNETIC_FIELD.description}",),
        )

    def schema(self) -> InstrumentSchema:
        return ARTEMIS_FGM_SCHEMA

    def guide(self, *, language: str = "en") -> GuidePage:
        return self.probe.guide(language=language).with_schema(ARTEMIS_FGM_SCHEMA)

    def help(self, *, language: str = "en") -> GuidePage:
        return self.guide(language=language)


@dataclass(frozen=True)
class ArtemisLoadPlan:
    dataset_id: str
    time: TimeRange


class ArtemisVariableEndpoint:
    def __init__(self, instrument: ArtemisFgmInstrument, schema: VariableSchema) -> None:
        self.instrument = instrument
        self._schema = schema
        self.name = schema.name

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"{self.instrument.dataset_prefix}.{self.name}",
            lines=(
                f"description: {self._schema.description}",
                f"dims: {self._schema.dims}",
                f"units: {self._schema.units}",
            ),
        )

    def schema(self) -> VariableSchema:
        return self._schema

    def guide(self, *, language: str = "en") -> GuidePage:
        return self.instrument.guide(language=language)

    def help(self, *, language: str = "en") -> GuidePage:
        return self.guide(language=language)

    def plan(self, time: TimeRange) -> ArtemisLoadPlan:
        return ArtemisLoadPlan(
            dataset_id=f"{self.instrument.dataset_prefix}.{self.name}",
            time=time,
        )

    def load(self, time: TimeRange):
        dataset_id = f"{self.instrument.dataset_prefix}.{self.name}"
        try:
            frame = self.instrument.probe.mission.store.scan_dataset(
                dataset_id,
                layer="normalized",
            ).collect()
        except DatasetNotFoundError as exc:
            probe = self.instrument.probe.probe.upper()
            raise NotImplementedError(
                f"ARTEMIS {probe} FGM load is not implemented yet"
            ) from exc
        return SopranArray(
            name=self.name,
            time=time,
            schema=self._schema,
            xr=_frame_to_data_array(frame, self._schema, time),
        )

    def line(self, time: TimeRange, *, x: str = "time", name: str | None = None):
        from sopran.core.plotting import line

        return line(
            lambda: self.load(time).to_xarray(),
            x=x,
            name=name or self.name,
        )


def _read_guide(*, title: str, language: str = "en") -> GuidePage:
    if language not in _GUIDE_LANGUAGES:
        raise ValueError(f"ARTEMIS guide language is not available: {language}")
    package = files("sopran.missions.artemis")
    resource_name = "README.ja.md" if language == "ja" else "README.md"
    markdown = package.joinpath(resource_name).read_text(encoding="utf-8")
    translations = {
        available_language: package.joinpath(
            "README.ja.md" if available_language == "ja" else "README.md"
        ).read_text(encoding="utf-8")
        for available_language in _GUIDE_LANGUAGES
        if available_language != language
    }
    sources = {
        available_language: "sopran.missions.artemis/"
        + ("README.ja.md" if available_language == "ja" else "README.md")
        for available_language in _GUIDE_LANGUAGES
        if available_language != language
    }
    return GuidePage(
        title=title,
        markdown=markdown,
        source=f"sopran.missions.artemis/{resource_name}",
        url=_PUBLIC_DOC_URL,
        language=language,
        available_languages=_GUIDE_LANGUAGES,
        translations=translations,
        sources=sources,
    )


def _frame_to_data_array(frame: Any, schema: VariableSchema, time: TimeRange):
    try:
        import numpy as np
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError("xarray is required for ARTEMIS FGM load()") from exc

    if frame.is_empty():
        return xr.DataArray(
            np.empty((0, 0)),
            dims=schema.dims,
            coords={"time": [], "component": []},
            name=schema.name,
            attrs={"units": schema.units, "description": schema.description},
        )

    if "time" in frame.columns:
        import polars as pl

        frame = frame.filter(
            (pl.col("time") >= time.start_iso) & (pl.col("time") < time.stop_iso)
        )

    rows = frame.sort(["time", "component"]).to_dicts()
    times = _unique(row["time"] for row in rows)
    components = _unique(row["component"] for row in rows)
    values = np.full((len(times), len(components)), np.nan)
    time_index = {value: index for index, value in enumerate(times)}
    component_index = {value: index for index, value in enumerate(components)}
    for row in rows:
        values[time_index[row["time"]], component_index[row["component"]]] = row[
            schema.name
        ]

    return xr.DataArray(
        values,
        dims=schema.dims,
        coords={"time": times, "component": components},
        name=schema.name,
        attrs={"units": schema.units, "description": schema.description},
    )


def _unique(values) -> list[Any]:
    seen = set()
    output = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output
