from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
from importlib.resources import files
from typing import Any

from sopran.core.data import SopranArray
from sopran.core.errors import DatasetNotFoundError
from sopran.core.pages import GuidePage, InfoPage
from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.core.store import Store
from sopran.core.time import TimeRange, _filter_polars_time

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
ARTEMIS_ION_ENERGY_FLUX = VariableSchema(
    name="ion_energy_flux",
    aliases=("ion_eflux", "esa"),
    dims=("time", "energy"),
    units="eV/(cm^2 s sr eV)",
    description="ARTEMIS ESA ion differential energy flux.",
)
ARTEMIS_ESA_SCHEMA = InstrumentSchema(
    mission="artemis",
    instrument="esa",
    variables=(ARTEMIS_ION_ENERGY_FLUX,),
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

    def guide(self, *, language: str = "ja") -> GuidePage:
        return _read_guide(title="ARTEMIS", language=language)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        return _example_page(
            "ARTEMIS Example",
            """# ARTEMIS Example

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
art = spn.Artemis(store=store)
time = spn.day("2011-07-01")

stack = spn.stack(
    art.p1.esa.ion_energy_flux.spectrogram(time, y="energy", log_color=True),
    art.p1.fgm.magnetic_field.lines(time, components="xyz"),
)
plot_result = stack.plot()
fig = plot_result.fig
```
""",
        )


class ArtemisProbe:
    def __init__(self, mission: Artemis, probe: str) -> None:
        self.mission = mission
        self.probe = probe
        self.fgm = ArtemisFgmInstrument(self)
        self.esa = ArtemisEsaInstrument(self)

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"ARTEMIS.{self.probe.upper()}",
            lines=(
                "fgm: fluxgate magnetometer",
                "esa: electrostatic analyzer",
            ),
        )

    def guide(self, *, language: str = "ja") -> GuidePage:
        return self.mission.guide(language=language)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        return self.mission.example()


class ArtemisFgmInstrument:
    def __init__(self, probe: ArtemisProbe) -> None:
        self.probe = probe
        self.magnetic_field = ArtemisVariableEndpoint(
            instrument=self,
            schema=ARTEMIS_MAGNETIC_FIELD,
        )
        self.b = self.magnetic_field

    @property
    def instrument_id(self) -> str:
        return "fgm"

    @property
    def dataset_prefix(self) -> str:
        return f"artemis.{self.probe.probe}.{self.instrument_id}"

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"ARTEMIS.{self.probe.probe.upper()}.FGM",
            lines=(f"{ARTEMIS_MAGNETIC_FIELD.name}: {ARTEMIS_MAGNETIC_FIELD.description}",),
        )

    def schema(self) -> InstrumentSchema:
        return ARTEMIS_FGM_SCHEMA

    def guide(self, *, language: str = "ja") -> GuidePage:
        return self.probe.guide(language=language).with_schema(ARTEMIS_FGM_SCHEMA)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        probe = self.probe.probe
        return _example_page(
            f"ARTEMIS {probe.upper()} FGM Example",
            f"""# ARTEMIS {probe.upper()} FGM Example

```python
import sopran as spn

art = spn.Artemis()
time = spn.day("2011-07-01")

magnetic_field = art.{probe}.fgm.magnetic_field.load(time)
item = art.{probe}.fgm.magnetic_field.lines(time, components="xyz")
plot_result = spn.stack(item).plot()
```
""",
        )

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        raise _unknown_variable_error(
            probe=self.probe.probe,
            instrument=self.instrument_id,
            name=name,
            schema=ARTEMIS_FGM_SCHEMA,
        )


class ArtemisEsaInstrument:
    def __init__(self, probe: ArtemisProbe) -> None:
        self.probe = probe
        self.ion_energy_flux = ArtemisVariableEndpoint(
            instrument=self,
            schema=ARTEMIS_ION_ENERGY_FLUX,
        )
        self.ion_eflux = self.ion_energy_flux

    @property
    def instrument_id(self) -> str:
        return "esa"

    @property
    def dataset_prefix(self) -> str:
        return f"artemis.{self.probe.probe}.{self.instrument_id}"

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"ARTEMIS.{self.probe.probe.upper()}.ESA",
            lines=(
                f"{ARTEMIS_ION_ENERGY_FLUX.name}: "
                f"{ARTEMIS_ION_ENERGY_FLUX.description}",
            ),
        )

    def schema(self) -> InstrumentSchema:
        return ARTEMIS_ESA_SCHEMA

    def guide(self, *, language: str = "ja") -> GuidePage:
        return self.probe.guide(language=language).with_schema(ARTEMIS_ESA_SCHEMA)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        probe = self.probe.probe
        return _example_page(
            f"ARTEMIS {probe.upper()} ESA Example",
            f"""# ARTEMIS {probe.upper()} ESA Example

```python
import sopran as spn

art = spn.Artemis()
time = spn.day("2011-07-01")

ion_energy_flux = art.{probe}.esa.ion_energy_flux.load(time)
item = art.{probe}.esa.ion_energy_flux.spectrogram(time, y="energy", log_color=True)
plot_result = spn.stack(item).plot()
```
""",
        )

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        raise _unknown_variable_error(
            probe=self.probe.probe,
            instrument=self.instrument_id,
            name=name,
            schema=ARTEMIS_ESA_SCHEMA,
        )


@dataclass(frozen=True)
class ArtemisLoadPlan:
    dataset_id: str
    time: TimeRange


class ArtemisVariableEndpoint:
    def __init__(self, instrument: Any, schema: VariableSchema) -> None:
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
                f"aliases: {', '.join(self._schema.aliases) or 'none'}",
            ),
        )

    def schema(self) -> VariableSchema:
        return self._schema

    def guide(self, *, language: str = "ja") -> GuidePage:
        return self.instrument.guide(language=language)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        probe = self.instrument.probe.probe
        instrument = str(self.instrument.instrument_id)
        if instrument == "fgm":
            plot_line = (
                f"item = art.{probe}.fgm.{self.name}.lines(time, components=\"xyz\")"
            )
        else:
            plot_line = (
                f"item = art.{probe}.esa.{self.name}.spectrogram("
                'time, y="energy", log_color=True)'
            )
        return _example_page(
            f"ARTEMIS {probe.upper()} {instrument.upper()} {self.name} Example",
            f"""# ARTEMIS {probe.upper()} {instrument.upper()} {self.name} Example

```python
import sopran as spn

art = spn.Artemis()
time = spn.day("2011-07-01")

{self.name} = art.{probe}.{instrument}.{self.name}.load(time)
{plot_line}
plot_result = spn.stack(item).plot()
```
""",
        )

    def plan(self, time: TimeRange | None = None) -> ArtemisLoadPlan:
        if time is None:
            raise _missing_time_error(self)
        return ArtemisLoadPlan(
            dataset_id=f"{self.instrument.dataset_prefix}.{self.name}",
            time=time,
        )

    def load(self, time: TimeRange | None = None):
        if time is None:
            raise _missing_time_error(self)
        dataset_id = f"{self.instrument.dataset_prefix}.{self.name}"
        try:
            frame = self.instrument.probe.mission.store.scan_dataset(
                dataset_id,
                layer="normalized",
            ).collect()
        except DatasetNotFoundError as exc:
            probe = self.instrument.probe.probe.upper()
            instrument = str(self.instrument.instrument_id).upper()
            raise NotImplementedError(
                f"ARTEMIS {probe} {instrument} load is not implemented yet"
            ) from exc
        return SopranArray(
            name=self.name,
            time=time,
            schema=self._schema,
            xr=_frame_to_data_array(frame, self._schema, time),
        )

    def line(
        self,
        time: TimeRange | None = None,
        *,
        x: str = "time",
        name: str | None = None,
    ):
        if time is None:
            raise _missing_time_error(self)
        from sopran.core.plotting import line

        return line(
            lambda: self.load(time).to_xarray(),
            x=x,
            name=name or self.name,
        )

    def lines(
        self,
        time: TimeRange | None = None,
        *,
        x: str = "time",
        components: str | tuple[str, ...] | list[str] | None = None,
        component_dim: str = "component",
        name: str | None = None,
    ):
        if time is None:
            raise _missing_time_error(self)
        from sopran.core.plotting import lines

        return lines(
            lambda: self.load(time).to_xarray(),
            x=x,
            components=components,
            component_dim=component_dim,
            name=name or self.name,
        )

    def spectrogram(
        self,
        time: TimeRange | None = None,
        *,
        y: str,
        x: str = "time",
        name: str | None = None,
        log_color: bool = False,
    ):
        if time is None:
            raise _missing_time_error(self)
        from sopran.core.plotting import spectrogram

        return spectrogram(
            lambda: self.load(time).to_xarray(),
            x=x,
            y=y,
            name=name or self.name,
            log_color=log_color,
        )


def _read_guide(*, title: str, language: str = "ja") -> GuidePage:
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


def _example_page(title: str, markdown: str) -> GuidePage:
    return GuidePage(
        title=title,
        markdown=markdown,
        source="sopran.missions.artemis.examples",
    )


def _unknown_variable_error(
    *,
    probe: str,
    instrument: str,
    name: str,
    schema: InstrumentSchema,
) -> AttributeError:
    variable_names = tuple(variable.name for variable in schema.variables)
    aliases = {
        alias: variable.name
        for variable in schema.variables
        for alias in variable.aliases
    }
    candidates = (*variable_names, *aliases)
    matches = get_close_matches(name, candidates, n=1, cutoff=0.4)
    suggestion = aliases.get(matches[0], matches[0]) if matches else variable_names[0]
    available = "\n".join(f"  {variable.name}" for variable in schema.variables)
    probe_path = probe.lower()
    instrument_path = instrument.lower()
    return AttributeError(
        f"ARTEMIS.{probe.upper()}.{instrument.upper()} has no variable {name!r}.\n\n"
        f"Available variables:\n{available}\n\n"
        f"Did you mean:\n  {suggestion}?\n\n"
        f"Try:\n"
        f"  art.{probe_path}.{instrument_path}.info()\n"
        f"  art.{probe_path}.{instrument_path}.{suggestion}.load(time)"
    )


def _missing_time_error(endpoint: ArtemisVariableEndpoint) -> ValueError:
    probe = endpoint.instrument.probe.probe.upper()
    instrument = str(endpoint.instrument.instrument_id).upper()
    probe_path = endpoint.instrument.probe.probe.lower()
    instrument_path = str(endpoint.instrument.instrument_id).lower()
    variable = endpoint.name
    return ValueError(
        f"Time range is required for ARTEMIS.{probe}.{instrument}.{variable}.\n\n"
        'Examples:\n  time = spn.period("2011-07-01", "2011-07-02")\n'
        f"  art.{probe_path}.{instrument_path}.{variable}.load(time)\n\n"
        "Or use a Project case:\n"
        f"  case.artemis.{probe_path}.{instrument_path}.{variable}.load()"
    )


def _frame_to_data_array(frame: Any, schema: VariableSchema, time: TimeRange):
    try:
        import numpy as np
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError("xarray is required for ARTEMIS FGM load()") from exc

    if frame.is_empty():
        secondary_dim = schema.dims[1] if len(schema.dims) > 1 else "value"
        return xr.DataArray(
            np.empty((0, 0)),
            dims=schema.dims,
            coords={"time": [], secondary_dim: []},
            name=schema.name,
            attrs={"units": schema.units, "description": schema.description},
        )

    if "time" in frame.columns:
        frame = _filter_polars_time(frame, time)

    secondary_dim = schema.dims[1]
    rows = frame.sort(["time", secondary_dim]).to_dicts()
    times = _unique(row["time"] for row in rows)
    secondary_values = _unique(row[secondary_dim] for row in rows)
    values = np.full((len(times), len(secondary_values)), np.nan)
    time_index = {value: index for index, value in enumerate(times)}
    secondary_index = {value: index for index, value in enumerate(secondary_values)}
    for row in rows:
        values[time_index[row["time"]], secondary_index[row[secondary_dim]]] = row[
            schema.name
        ]

    return xr.DataArray(
        values,
        dims=schema.dims,
        coords={"time": _datetime64_values(times), secondary_dim: secondary_values},
        name=schema.name,
        attrs={"units": schema.units, "description": schema.description},
    )


def _datetime64_values(values: tuple[Any, ...]):
    import pandas as pd

    return (
        pd.to_datetime(list(values), utc=True)
        .tz_convert(None)
        .to_numpy(dtype="datetime64[ns]")
    )


def _unique(values) -> list[Any]:
    seen = set()
    output = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output
