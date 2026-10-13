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

from .files import (
    PPI_VOLUME_URL,
    VOLUMES,
    LpFileSource,
    lp_provider_path,
    lp_support_path,
    read_energy_bins,
    read_er_3d,
    read_er_flux,
    read_mag,
    read_theta,
)

if TYPE_CHECKING:
    import xarray as xr

    from sopran.core.plotting import PlotItem
    from sopran.core.view import View

MissingMode = Literal["empty", "warn", "error"]

_GUIDE_LANGUAGES = ("ja", "en")
_PUBLIC_DOC_URLS = public_doc_urls("data/lunar-prospector/")
_FLUX_UNITS = "1/(cm^2 s sr eV)"

LP_MAG_SCHEMA = InstrumentSchema(
    mission="lunar_prospector",
    instrument="mag",
    variables=(
        VariableSchema(
            name="magnetic_field",
            aliases=("b",),
            dims=("time", "component"),
            units="nT",
            frame="SSE",
            description="5-s magnetic field in selenocentric solar ecliptic (SSE) coordinates.",
        ),
        VariableSchema(
            name="magnetic_field_sel",
            dims=("time", "component"),
            units="nT",
            frame="SEL",
            description="5-s magnetic field in selenographic (SEL) Cartesian coordinates.",
        ),
        VariableSchema(
            name="magnetic_field_rms",
            dims=("time",),
            units="nT",
            description="RMS deviation of the field within each 5-s average.",
        ),
        VariableSchema(
            name="position",
            dims=("time", "component"),
            units="km",
            frame="SSE",
            description="Spacecraft position from the Moon centre in SSE.",
        ),
        VariableSchema(
            name="position_sel",
            dims=("time", "component"),
            units="km",
            frame="SEL",
            description="Spacecraft position from the Moon centre in SEL.",
        ),
    ),
)
LP_ER_SCHEMA = InstrumentSchema(
    mission="lunar_prospector",
    instrument="er",
    variables=(
        VariableSchema(
            name="electron_flux",
            dims=("time", "energy_bin"),
            units=_FLUX_UNITS,
            description=(
                "~80-s omnidirectional differential electron number flux in 15 energy bins; "
                "'energy' is the (time, energy_bin) table in effect, in eV."
            ),
            log_scale=True,
            log_dims=("energy",),
        ),
        VariableSchema(
            name="electron_flux_3d",
            dims=("time", "energy_bin", "look"),
            units=_FLUX_UNITS,
            description=(
                "3-D electron spectra (15 energies x 88 look directions per ~80-s spectrum) "
                "with theta, phi and the despun-spacecraft field as coordinates."
            ),
            log_scale=True,
            log_dims=("energy",),
        ),
    ),
)


class LunarProspector:
    """Entry point for Lunar Prospector MAG/ER Level 1B data (1998-01-16 to 1999-07-29)."""

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
        self.files = LpFileSource(self.store, timeout_seconds=timeout_seconds)
        self.mag: LpInstrument = LpInstrument(self, "mag", LP_MAG_SCHEMA)
        self.er: LpInstrument = LpInstrument(self, "er", LP_ER_SCHEMA)

    @classmethod
    def from_view(cls, view: View) -> LunarProspector:
        """Build endpoints that default to the view's time, Store and download policy."""

        return cls(
            store=view.project.store,
            download=cast("DownloadMode | None", view.context.download),
            view=view,
        )

    def info(self) -> InfoPage:
        first, last = VOLUMES[0][1], VOLUMES[-1][2]
        return InfoPage(
            title="Lunar Prospector",
            lines=(
                "mag: magnetometer (5-s field and position)",
                "er: electron reflectometer (omnidirectional and 3-D electron flux)",
                f"coverage: {first.isoformat()} to {last.isoformat()}",
                "source: PDS PPI Level 1B volumes LP_1201-LP_1204",
            ),
        )

    def guide(self, *, language: str = "ja") -> GuidePage:
        return _read_guide(language=language)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        return GuidePage(
            title="Lunar Prospector Example",
            markdown="""# Lunar Prospector Example

```python
import sopran as spn

lp = spn.lunar_prospector
time = spn.period("1998-02-01T00:00", "1998-02-01T06:00")

spn.stack(
    lp.er.electron_flux.spectrogram(time),
    lp.mag.magnetic_field.lines(time, components="xyz"),
).plot()
```
""",
            source="sopran.missions.lunar_prospector.examples",
        )

    def _energy_bins(self, download: DownloadMode) -> tuple[Any, Any] | None:
        path = self.files.fetch(lp_support_path("ER_LO_TS", "E_BINS.TAB"), download=download)
        return None if path is None else read_energy_bins(path)

    def _theta(self, download: DownloadMode) -> Any | None:
        path = self.files.fetch(lp_support_path("ER_3DIST", "THETA.TAB"), download=download)
        return None if path is None else read_theta(path)


class LpInstrument:
    def __init__(self, mission: LunarProspector, name: str, schema: InstrumentSchema) -> None:
        self.mission = mission
        self.name = name
        self.schema_definition = schema
        for variable in schema.variables:
            endpoint = LpVariableEndpoint(self, variable)
            setattr(self, variable.name, endpoint)
            for alias in variable.aliases:
                setattr(self, alias, endpoint)

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"LunarProspector.{self.name.upper()}",
            lines=tuple(
                f"{variable.name}: {variable.description}"
                for variable in self.schema_definition.variables
            ),
        )

    def schema(self) -> InstrumentSchema:
        return self.schema_definition

    def guide(self, *, language: str = "ja") -> GuidePage:
        return self.mission.guide(language=language).with_schema(self.schema_definition)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        return self.mission.example()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        names = [variable.name for variable in self.schema_definition.variables]
        matches = get_close_matches(name, names, n=1, cutoff=0.4)
        suggestion = matches[0] if matches else names[0]
        raise AttributeError(
            f"LunarProspector.{self.name.upper()} has no variable {name!r}.\n\n"
            "Available variables:\n" + "\n".join(f"  {item}" for item in names) + "\n\n"
            f"Did you mean:\n  {suggestion}?\n\n"
            f"Try:\n  lp.{self.name}.info()\n  lp.{self.name}.{suggestion}.load(time)"
        )


@dataclass(frozen=True)
class LpLoadPlan:
    dataset_id: str
    time: TimeRange
    remote_files: tuple[str, ...]


class LpVariableEndpoint:
    def __init__(self, instrument: LpInstrument, schema: VariableSchema) -> None:
        self.instrument = instrument
        self._schema = schema
        self.name = schema.name

    @property
    def dataset_id(self) -> str:
        return f"lunar_prospector.{self.instrument.name}.{self.name}"

    @property
    def _dataset(self) -> str:
        if self.instrument.name == "mag":
            return "MAG"
        return "ER_3DIST" if self.name == "electron_flux_3d" else "ER_LO_TS"

    def info(self) -> InfoPage:
        return InfoPage(
            title=self.dataset_id,
            lines=(
                f"description: {self._schema.description}",
                f"dims: {self._schema.dims}",
                f"units: {self._schema.units}",
                f"frame: {self._schema.frame or 'none'}",
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
        return self.instrument.example()

    def plan(self, time: TimeRange | None = None) -> LpLoadPlan:
        time = _bound_time(self, time)
        paths = (lp_provider_path(self._dataset, date.fromisoformat(day)) for day in time.days())
        return LpLoadPlan(
            dataset_id=self.dataset_id,
            time=time,
            remote_files=tuple(PPI_VOLUME_URL + path for path in paths if path is not None),
        )

    def load(
        self,
        time: TimeRange | None = None,
        *,
        download: DownloadMode | None = None,
        missing: MissingMode = "empty",
    ) -> SopranArray:
        """Read the daily tables for ``time``, retrieving missing ones per ``download``.

        Days outside the mission, or without a table, give an empty result by
        default; ``missing="warn"`` or ``"error"`` reports them.
        """

        time = _bound_time(self, time)
        if missing not in ("empty", "warn", "error"):
            raise ValueError("missing must be 'empty', 'warn', or 'error'")
        mission = self.instrument.mission
        policy = mission.download if download is None else resolve_download_mode(download)
        arrays: list[xr.DataArray] = []
        paths: list[Path] = []
        missing_days: list[str] = []
        reader: Callable[[Path], xr.DataArray] | None = None
        for day in time.days():
            provider_path = lp_provider_path(self._dataset, date.fromisoformat(day))
            path = (
                None
                if provider_path is None
                else mission.files.fetch(provider_path, download=policy)
            )
            if path is not None and reader is None:
                # Energy and angle tables are fetched only once there is a day to read.
                reader = self._reader(policy)
            if path is None or reader is None:
                missing_days.append(day)
                continue
            paths.append(path)
            arrays.append(reader(path))
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
                "source": "PDS PPI Lunar Prospector MAG/ER Level 1B",
            }
        )
        if self._schema.frame:
            array.attrs["frame"] = self._schema.frame
        array.attrs.pop("source_file", None)
        return SopranArray(
            name=self.name, time=time, schema=self._schema, files=tuple(paths), xr=array
        )

    def plot(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        options = {key: kwargs.pop(key) for key in ("download", "missing") if key in kwargs}
        return self.load(time, **options).plot(**kwargs)

    def line(self, time: TimeRange | None = None, **options: Any) -> PlotItem:
        return self.load(_bound_time(self, time), **options).line()

    def lines(
        self,
        time: TimeRange | None = None,
        *,
        components: str | tuple[str, ...] | list[str] | None = None,
        name: str | None = None,
        **options: Any,
    ) -> PlotItem:
        time = _bound_time(self, time)
        from sopran.core.plotting import lines

        return lines(
            lambda: self.load(time, **options).to_xarray(),
            x="time",
            components=components,
            name=name or self.name,
        )

    def spectrogram(
        self,
        time: TimeRange | None = None,
        *,
        y: str = "energy",
        reduction: str = "mean",
        log_color: bool | None = None,
        yscale: str | None = None,
        **options: Any,
    ) -> PlotItem:
        """Spectrogram; the 3-D flux is averaged over look directions unless told otherwise."""

        return self.load(_bound_time(self, time), **options).spectrogram(
            y=y, reduction=reduction, log_color=log_color, yscale=yscale
        )

    def _reader(self, download: DownloadMode) -> Callable[[Path], xr.DataArray] | None:
        mission = self.instrument.mission
        if self._dataset == "MAG":
            return lambda path: read_mag(path)[self.name]
        if self._dataset == "ER_LO_TS":
            energy_bins = mission._energy_bins(download)
            if energy_bins is None:
                return None
            return lambda path: read_er_flux(path, energy_bins)
        theta = mission._theta(download)
        if theta is None:
            return None
        return lambda path: read_er_3d(path, theta)

    def _missing_message(self, days: list[str], policy: DownloadMode) -> str:
        shown = ", ".join(days[:5]) + (" ..." if len(days) > 5 else "")
        first, last = VOLUMES[0][1], VOLUMES[-1][2]
        hint = (
            "Downloads are disabled (download='never'); retry with download='missing'."
            if policy == "never"
            else f"The archive covers {first.isoformat()} to {last.isoformat()}."
        )
        return (
            f"Lunar Prospector {self.instrument.name.upper()} has no {self._dataset} table "
            f"for {len(days)} day(s): {shown}. {hint}"
        )


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
    shape = (0, 15) if schema.dims == ("time", "energy_bin") else (0, 15, 88)
    coords: dict[str, Any] = {
        "time": times,
        "energy_bin": np.arange(15),
        "energy": (("time", "energy_bin"), np.empty((0, 15)), {"units": "eV"}),
    }
    if len(shape) == 3:
        coords["look"] = np.arange(88)
    return xr.DataArray(np.empty(shape), dims=schema.dims, coords=coords)


def _bound_time(endpoint: LpVariableEndpoint, time: TimeRange | None) -> TimeRange:
    if time is not None:
        return time
    view = endpoint.instrument.mission.view
    if view is not None and view.time is not None:
        return cast(TimeRange, view.time)
    raise ValueError(
        f"Time range is required for LunarProspector.{endpoint.instrument.name.upper()}."
        f"{endpoint.name}.\n\n"
        'Examples:\n  time = spn.period("1998-02-01", "1998-02-02")\n'
        f"  lp.{endpoint.instrument.name}.{endpoint.name}.load(time)"
    )


def _read_guide(*, language: str = "ja") -> GuidePage:
    if language not in _GUIDE_LANGUAGES:
        raise ValueError(f"Lunar Prospector guide language is not available: {language}")
    package = files("sopran.missions.lunar_prospector")

    def resource(item: str) -> str:
        return "README.ja.md" if item == "ja" else "README.md"

    return GuidePage(
        title="Lunar Prospector",
        markdown=package.joinpath(resource(language)).read_text(encoding="utf-8"),
        source=f"sopran.missions.lunar_prospector/{resource(language)}",
        url=_PUBLIC_DOC_URLS[language],
        urls=_PUBLIC_DOC_URLS,
        language=language,
        available_languages=_GUIDE_LANGUAGES,
        translations={
            item: package.joinpath(resource(item)).read_text(encoding="utf-8")
            for item in _GUIDE_LANGUAGES
            if item != language
        },
        sources={
            item: f"sopran.missions.lunar_prospector/{resource(item)}"
            for item in _GUIDE_LANGUAGES
            if item != language
        },
    )
