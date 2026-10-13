from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from difflib import get_close_matches
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from sopran.core.config import DownloadMode, resolve_download_mode
from sopran.core.data import SopranArray
from sopran.core.errors import DatasetNotFoundError
from sopran.core.pages import GuidePage, InfoPage, public_doc_urls
from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.core.store import Store
from sopran.core.time import TimeRange

from .cdaweb import (
    PROBE_IDS,
    ArtemisFileSource,
    EsaMode,
    artemis_remote_dir,
    read_esa_variable,
    read_fgm_field,
)

if TYPE_CHECKING:
    import xarray as xr

    from sopran.core.plotting import PlotItem
    from sopran.core.view import View

MissingMode = Literal["empty", "warn", "error"]

_GUIDE_LANGUAGES = ("ja", "en")
_PUBLIC_DOC_URLS = public_doc_urls("data/artemis/")

ARTEMIS_MAGNETIC_FIELD = VariableSchema(
    name="magnetic_field",
    aliases=("b", "fgm"),
    dims=("time", "component"),
    units="nT",
    frame="GSE",
    description="FGM spin-resolution (~3 s, FGS) magnetic field vector in GSE.",
)
ARTEMIS_FGM_SCHEMA = InstrumentSchema(
    mission="artemis",
    instrument="fgm",
    variables=(ARTEMIS_MAGNETIC_FIELD,),
)
ARTEMIS_ION_ENERGY_FLUX = VariableSchema(
    name="ion_energy_flux",
    aliases=("ion_eflux", "esa"),
    dims=("time", "energy_bin"),
    units="eV/(cm^2 s sr eV)",
    description=(
        "ESA ion differential energy flux; the energy table is the per-record "
        "(time, energy_bin) coordinate 'energy' in eV."
    ),
    log_scale=True,
    log_dims=("energy",),
)
ARTEMIS_ELECTRON_ENERGY_FLUX = VariableSchema(
    name="electron_energy_flux",
    aliases=("electron_eflux",),
    dims=("time", "energy_bin"),
    units="eV/(cm^2 s sr eV)",
    description=(
        "ESA electron differential energy flux; the energy table is the per-record "
        "(time, energy_bin) coordinate 'energy' in eV."
    ),
    log_scale=True,
    log_dims=("energy",),
)
ARTEMIS_ION_DENSITY = VariableSchema(
    name="ion_density",
    dims=("time",),
    units="cm^-3",
    description="ESA ground-processed ion density moment.",
)
ARTEMIS_ION_VELOCITY = VariableSchema(
    name="ion_velocity",
    aliases=("ion_bulk_velocity",),
    dims=("time", "component"),
    units="km/s",
    frame="GSE",
    description="ESA ground-processed ion bulk velocity moment in GSE.",
)
ARTEMIS_ELECTRON_DENSITY = VariableSchema(
    name="electron_density",
    dims=("time",),
    units="cm^-3",
    description="ESA ground-processed electron density moment.",
)
ARTEMIS_ESA_SCHEMA = InstrumentSchema(
    mission="artemis",
    instrument="esa",
    variables=(
        ARTEMIS_ION_ENERGY_FLUX,
        ARTEMIS_ELECTRON_ENERGY_FLUX,
        ARTEMIS_ION_DENSITY,
        ARTEMIS_ION_VELOCITY,
        ARTEMIS_ELECTRON_DENSITY,
    ),
)

# variable name -> (species, CDF quantity)
_ESA_QUANTITIES: dict[str, tuple[Literal["i", "e"], Any]] = {
    "ion_energy_flux": ("i", "en_eflux"),
    "electron_energy_flux": ("e", "en_eflux"),
    "ion_density": ("i", "density"),
    "ion_velocity": ("i", "velocity_gse"),
    "electron_density": ("e", "density"),
}


class Artemis:
    """Object-oriented entry point for ARTEMIS probes (P1 = THEMIS-B, P2 = THEMIS-C)."""

    def __init__(
        self,
        *,
        store: Store | None = None,
        download: DownloadMode | None = None,
        view: View | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.store = store or Store()
        self.download = resolve_download_mode(download)
        self.view = view
        self.files = ArtemisFileSource(self.store, timeout_seconds=timeout_seconds)
        self.p1: ArtemisProbe = ArtemisProbe(self, "p1")
        self.p2: ArtemisProbe = ArtemisProbe(self, "p2")

    @classmethod
    def from_view(cls, view: View) -> Artemis:
        """Build a mission whose endpoints default to the view's time, Store and policy."""

        return cls(
            store=view.project.store,
            download=cast("DownloadMode | None", view.context.download),
            view=view,
        )

    def info(self) -> InfoPage:
        return InfoPage(
            title="ARTEMIS",
            lines=(
                "p1: ARTEMIS P1 probe (THEMIS-B)",
                "p2: ARTEMIS P2 probe (THEMIS-C)",
                "source: NASA SPDF/CDAWeb THEMIS Level 2 CDF files",
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

art = spn.artemis
time = spn.day("2011-07-01")

stack = spn.stack(
    art.p1.esa.ion_energy_flux.spectrogram(time),
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
        self.probe_id = PROBE_IDS[probe]
        self.fgm: ArtemisFgmInstrument = ArtemisFgmInstrument(self)
        self.esa: ArtemisEsaInstrument = ArtemisEsaInstrument(self)

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"ARTEMIS.{self.probe.upper()}",
            lines=(
                f"spacecraft: THEMIS-{self.probe_id[-1].upper()} ({self.probe_id})",
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


class _ArtemisInstrument:
    instrument_id: str
    schema_definition: InstrumentSchema

    def __init__(self, probe: ArtemisProbe) -> None:
        self.probe = probe

    @property
    def dataset_prefix(self) -> str:
        return f"artemis.{self.probe.probe}.{self.instrument_id}"

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"ARTEMIS.{self.probe.probe.upper()}.{self.instrument_id.upper()}",
            lines=tuple(
                f"{variable.name}: {variable.description}"
                for variable in self.schema_definition.variables
            ),
        )

    def schema(self) -> InstrumentSchema:
        return self.schema_definition

    def guide(self, *, language: str = "ja") -> GuidePage:
        return self.probe.guide(language=language).with_schema(self.schema_definition)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        probe = self.probe.probe
        instrument = self.instrument_id
        first = self.schema_definition.variables[0].name
        return _example_page(
            f"ARTEMIS {probe.upper()} {instrument.upper()} Example",
            f"""# ARTEMIS {probe.upper()} {instrument.upper()} Example

```python
import sopran as spn

art = spn.artemis
time = spn.day("2011-07-01")

{first} = art.{probe}.{instrument}.{first}.load(time)
plot_result = art.{probe}.{instrument}.{first}.plot(time)
```
""",
        )

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        raise _unknown_variable_error(
            probe=self.probe.probe,
            instrument=self.instrument_id,
            name=name,
            schema=self.schema_definition,
        )


class ArtemisFgmInstrument(_ArtemisInstrument):
    instrument_id = "fgm"
    schema_definition = ARTEMIS_FGM_SCHEMA

    def __init__(self, probe: ArtemisProbe) -> None:
        super().__init__(probe)
        probe_id = probe.probe_id
        self.magnetic_field: ArtemisVariableEndpoint = ArtemisVariableEndpoint(
            self,
            ARTEMIS_MAGNETIC_FIELD,
            lambda path, _mode: read_fgm_field(path, probe_id),
        )
        self.b: ArtemisVariableEndpoint = self.magnetic_field


class ArtemisEsaInstrument(_ArtemisInstrument):
    instrument_id = "esa"
    schema_definition = ARTEMIS_ESA_SCHEMA

    def __init__(self, probe: ArtemisProbe) -> None:
        super().__init__(probe)
        endpoints = {
            variable.name: ArtemisVariableEndpoint(
                self, variable, _esa_reader(probe.probe_id, variable.name), esa=True
            )
            for variable in ARTEMIS_ESA_SCHEMA.variables
        }
        self.ion_energy_flux: ArtemisVariableEndpoint = endpoints["ion_energy_flux"]
        self.electron_energy_flux: ArtemisVariableEndpoint = endpoints["electron_energy_flux"]
        self.ion_density: ArtemisVariableEndpoint = endpoints["ion_density"]
        self.ion_velocity: ArtemisVariableEndpoint = endpoints["ion_velocity"]
        self.electron_density: ArtemisVariableEndpoint = endpoints["electron_density"]
        self.ion_eflux: ArtemisVariableEndpoint = self.ion_energy_flux
        self.electron_eflux: ArtemisVariableEndpoint = self.electron_energy_flux


def _esa_reader(probe_id: str, name: str) -> Callable[[Path, EsaMode], xr.DataArray]:
    species, quantity = _ESA_QUANTITIES[name]

    def read(path: Path, mode: EsaMode) -> xr.DataArray:
        return read_esa_variable(path, probe_id, species=species, mode=mode, quantity=quantity)

    return read


@dataclass(frozen=True)
class ArtemisLoadPlan:
    dataset_id: str
    time: TimeRange
    remote_directories: tuple[str, ...] = ()


class ArtemisVariableEndpoint:
    def __init__(
        self,
        instrument: _ArtemisInstrument,
        schema: VariableSchema,
        reader: Callable[[Path, EsaMode], xr.DataArray],
        *,
        esa: bool = False,
    ) -> None:
        self.instrument = instrument
        self._schema = schema
        self._reader = reader
        self._esa = esa
        self.name = schema.name

    @property
    def dataset_id(self) -> str:
        return f"{self.instrument.dataset_prefix}.{self.name}"

    def info(self) -> InfoPage:
        lines = [
            f"description: {self._schema.description}",
            f"dims: {self._schema.dims}",
            f"units: {self._schema.units}",
            f"frame: {self._schema.frame or 'none'}",
            f"aliases: {', '.join(self._schema.aliases) or 'none'}",
        ]
        if self._esa:
            lines.append("mode: 'reduced' (default, ~3 s), 'full', or 'burst'")
        return InfoPage(title=self.dataset_id, lines=tuple(lines))

    def schema(self) -> VariableSchema:
        return self._schema

    def guide(self, *, language: str = "ja") -> GuidePage:
        return self.instrument.guide(language=language)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        probe = self.instrument.probe.probe
        instrument = self.instrument.instrument_id
        if "component" in self._schema.dims:
            plot_line = f'item = art.{probe}.{instrument}.{self.name}.lines(time, components="xyz")'
        elif "energy_bin" in self._schema.dims:
            plot_line = f"item = art.{probe}.{instrument}.{self.name}.spectrogram(time)"
        else:
            plot_line = f"item = art.{probe}.{instrument}.{self.name}.line(time)"
        return _example_page(
            f"ARTEMIS {probe.upper()} {instrument.upper()} {self.name} Example",
            f"""# ARTEMIS {probe.upper()} {instrument.upper()} {self.name} Example

```python
import sopran as spn

art = spn.artemis
time = spn.day("2011-07-01")

{self.name} = art.{probe}.{instrument}.{self.name}.load(time)
{plot_line}
plot_result = spn.stack(item).plot()
```
""",
        )

    def plan(self, time: TimeRange | None = None) -> ArtemisLoadPlan:
        time = _bound_time(self, time)
        probe_id = self.instrument.probe.probe_id
        years = sorted({int(day[:4]) for day in time.days()})
        return ArtemisLoadPlan(
            dataset_id=self.dataset_id,
            time=time,
            remote_directories=tuple(
                artemis_remote_dir(probe_id, self.instrument.instrument_id, year)
                for year in years
            ),
        )

    def load(
        self,
        time: TimeRange | None = None,
        *,
        download: DownloadMode | None = None,
        mode: EsaMode = "reduced",
        missing: MissingMode = "empty",
    ) -> SopranArray:
        """Read the daily Level 2 files for ``time``, retrieving missing ones per ``download``.

        ``mode`` selects the ESA mode (``reduced``, ``full`` or ``burst``) and is
        ignored for FGM. Days without a file give an empty result by default;
        ``missing="warn"`` or ``"error"`` reports them.
        """

        time = _bound_time(self, time)
        if missing not in ("empty", "warn", "error"):
            raise ValueError("missing must be 'empty', 'warn', or 'error'")
        mission = self.instrument.probe.mission
        policy = mission.download if download is None else resolve_download_mode(download)
        probe_id = self.instrument.probe.probe_id
        arrays: list[xr.DataArray] = []
        paths: list[Path] = []
        missing_days: list[str] = []
        for day in time.days():
            path = mission.files.file_for_day(
                probe_id, self.instrument.instrument_id, date.fromisoformat(day), download=policy
            )
            if path is None:
                missing_days.append(day)
                continue
            paths.append(path)
            arrays.append(self._reader(path, mode))
        if missing_days:
            message = self._missing_message(missing_days, policy)
            if missing == "error":
                raise DatasetNotFoundError(message)
            if missing == "warn":
                warnings.warn(message, UserWarning, stacklevel=2)
        array = _combine(arrays, self._schema, time)
        array.name = self.name
        array.attrs.update(
            {
                "units": self._schema.units,
                "description": self._schema.description,
                "spacecraft": probe_id,
                "source": "NASA SPDF/CDAWeb THEMIS Level 2",
            }
        )
        if self._schema.frame:
            array.attrs["frame"] = self._schema.frame
        if self._esa:
            array.attrs["esa_mode"] = mode
        array.attrs.pop("source_file", None)
        return SopranArray(
            name=self.name,
            time=time,
            schema=self._schema,
            files=tuple(paths),
            xr=array,
        )

    def plot(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        load_options = _pop_load_options(kwargs)
        return self.load(time, **load_options).plot(**kwargs)

    def line(
        self,
        time: TimeRange | None = None,
        *,
        x: str = "time",
        name: str | None = None,
        **load_options: Any,
    ) -> PlotItem:
        time = _bound_time(self, time)
        from sopran.core.plotting import line

        return line(
            lambda: self.load(time, **load_options).to_xarray(),
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
        **load_options: Any,
    ) -> PlotItem:
        time = _bound_time(self, time)
        from sopran.core.plotting import lines

        return lines(
            lambda: self.load(time, **load_options).to_xarray(),
            x=x,
            components=components,
            component_dim=component_dim,
            name=name or self.name,
        )

    def spectrogram(
        self,
        time: TimeRange | None = None,
        *,
        y: str = "energy",
        x: str = "time",
        name: str | None = None,
        log_color: bool | None = None,
        yscale: str | None = None,
        **load_options: Any,
    ) -> PlotItem:
        time = _bound_time(self, time)
        from sopran.core.plotting import spectrogram

        schema = self.schema()
        return spectrogram(
            lambda: self.load(time, **load_options).to_xarray(),
            x=x,
            y=y,
            name=name or self.name,
            log_color=schema.log_scale if log_color is None else bool(log_color),
            yscale=yscale or schema.default_yscale(y),
        )

    def _missing_message(self, days: list[str], policy: DownloadMode) -> str:
        probe = self.instrument.probe.probe.upper()
        instrument = self.instrument.instrument_id.upper()
        shown = ", ".join(days[:5]) + (" ..." if len(days) > 5 else "")
        hint = (
            "Downloads are disabled (download='never'); retry with download='missing'."
            if policy == "never"
            else "The SPDF archive has no file for these days."
        )
        return (
            f"ARTEMIS {probe} {instrument} has no Level 2 file for {len(days)} day(s): "
            f"{shown}. {hint}"
        )


def _pop_load_options(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {key: kwargs.pop(key) for key in ("download", "mode", "missing") if key in kwargs}


def _combine(arrays: list[xr.DataArray], schema: VariableSchema, time: TimeRange) -> xr.DataArray:
    import numpy as np
    import xarray as xr

    if not arrays:
        return _empty_array(schema)
    combined = arrays[0] if len(arrays) == 1 else xr.concat(arrays, dim="time")
    combined = combined.sortby("time")
    times = combined["time"].values
    keep = np.concatenate(([True], times[1:] != times[:-1])) if times.size else times.astype(bool)
    start = np.datetime64(time.start.replace(tzinfo=None), "ns")
    stop = np.datetime64(time.stop.replace(tzinfo=None), "ns")
    keep &= (times >= start) & (times < stop)
    return combined.isel(time=np.flatnonzero(keep))


def _empty_array(schema: VariableSchema) -> xr.DataArray:
    import numpy as np
    import xarray as xr

    times = np.array([], dtype="datetime64[ns]")
    if schema.dims == ("time",):
        return xr.DataArray(np.empty(0), dims=("time",), coords={"time": times})
    if "component" in schema.dims:
        return xr.DataArray(
            np.empty((0, 3)),
            dims=("time", "component"),
            coords={"time": times, "component": ["x", "y", "z"]},
        )
    return xr.DataArray(
        np.empty((0, 0)),
        dims=("time", "energy_bin"),
        coords={
            "time": times,
            "energy_bin": np.arange(0),
            "energy": (("time", "energy_bin"), np.empty((0, 0)), {"units": "eV"}),
        },
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
        url=_PUBLIC_DOC_URLS[language],
        urls=_PUBLIC_DOC_URLS,
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


def _bound_time(endpoint: ArtemisVariableEndpoint, time: TimeRange | None) -> TimeRange:
    """Return ``time``, else the time of the view the mission is bound to."""

    if time is not None:
        return time
    view = endpoint.instrument.probe.mission.view
    if view is not None and view.time is not None:
        return cast(TimeRange, view.time)
    raise _missing_time_error(endpoint)


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
