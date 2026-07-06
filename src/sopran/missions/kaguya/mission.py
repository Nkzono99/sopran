from __future__ import annotations

import json
import os
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import get_close_matches
from importlib.resources import files
from inspect import signature
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast
from urllib.error import HTTPError

from sopran.core import Store
from sopran.core.coverage import (
    coverage_bins,
    coverage_dataset_id,
    coverage_frame_from_xarray,
    coverage_schema,
    coverage_variant_id,
    read_cached_coverage_frame,
    validate_coverage_freq,
)
from sopran.core.errors import DatasetNotFoundError
from sopran.core.pages import GuidePage, InfoPage
from sopran.core.pipeline import Pipeline, PipelineResult
from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.core.time import TimeRange, _filter_polars_time, day, period
from sopran.missions.kaguya.data import (
    KaguyaPaceData,
    _pitch_angle_spectrum_dataset_id,
    _pitch_angle_spectrum_variant_id,
    _read_pitch_angle_spectrum_store,
)
from sopran.missions.kaguya.files import (
    KaguyaFileSource,
    iter_hourly_public_paths,
    iter_public_paths,
    lmag_public_templates,
    lrs_public_template,
    pace_pbf_public_template,
)
from sopran.missions.kaguya.geometry import (
    MOON_MEAN_RADIUS_KM,
    array_from_polars,
    connection_schema,
    connection_variant_id,
    lmag_altitude,
    lmag_magnetic_connection,
    lmag_position,
    lmag_position_gse,
    lmag_radial_distance,
    lmag_subpoint,
    lmag_sza,
    orbit_variant_id,
    variant_metadata,
)
from sopran.missions.kaguya.lmag import KaguyaLmagData, read_lmag_public
from sopran.missions.kaguya.lrs import (
    KaguyaLrsData,
    empty_lrs_data,
    lrs_array_from_polars,
    lrs_kind_for_variable,
    read_lrs_public,
)
from sopran.missions.kaguya.pace import (
    PACE_CALIBRATION_BASE_URL,
    PaceCalibration,
    pace_calibration_remote_files,
    read_pace_fov,
    read_pace_info,
)
from sopran.missions.kaguya.schema import (
    KAGUYA_ESA1_SCHEMA,
    KAGUYA_LMAG_SCHEMA,
    KAGUYA_LRS_SCHEMA,
    KAGUYA_ORBIT_SCHEMA,
    kaguya_pace_schema,
)
from sopran.missions.kaguya.sensors import normalize_sensor

if TYPE_CHECKING:
    from sopran.core.data import SopranArray
    from sopran.core.plotting import PlotItem, PlotResult

DownloadMode = Literal["never", "missing", "always"]
MissingMode = Literal["empty", "warn", "error"]
CacheMode = Literal["use", "refresh", "never"]
_GUIDE_LANGUAGES = ("ja", "en")
_PUBLIC_DOC_URLS = {
    "README.md": "https://nkzono99.github.io/sopran/missions/kaguya/",
    "ESA1.md": "https://nkzono99.github.io/sopran/missions/kaguya/esa1/",
}


class Kaguya:
    """Object-oriented entry point for KAGUYA/SELENE public data."""

    def __init__(
        self,
        *,
        store: Store | None = None,
        data_root: Path | str | None = None,
        fallback_roots: list[Path | str] | tuple[Path | str, ...] = (),
        source: KaguyaFileSource | None = None,
        download: DownloadMode | None = None,
    ) -> None:
        self.download = _default_download_mode(download)
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
        self.esa1: PaceInstrument = PaceInstrument(self, "ESA1")
        self.esa2: PaceInstrument = PaceInstrument(self, "ESA2")
        self.ima: PaceInstrument = PaceInstrument(self, "IMA")
        self.iea: PaceInstrument = PaceInstrument(self, "IEA")
        self.lmag: LmagInstrument = LmagInstrument(self)
        self.lrs: LrsInstrument = LrsInstrument(self)
        self.orbit: OrbitInstrument = OrbitInstrument(self)

    def info(self) -> InfoPage:
        return InfoPage(
            title="KAGUYA",
            lines=(
                "esa1: PACE Electron Spectrum Analyzer 1",
                "esa2: PACE Electron Spectrum Analyzer 2",
                "ima: PACE Ion Mass Analyzer",
                "iea: PACE Ion Energy Analyzer",
                "lmag: Lunar MAGnetometer",
                "lrs: Lunar Radar Sounder plasma wave spectra",
            ),
        )

    def guide(self, topic: str | None = None, *, language: str = "ja") -> GuidePage:
        if topic is None:
            return _read_guide("README.md", title="KAGUYA/SELENE", language=language)
        normalized = topic.lower().replace("-", "").replace("_", "")
        pace_topics = {
            "esa1": self.esa1,
            "esas1": self.esa1,
            "paceesa1": self.esa1,
            "esa2": self.esa2,
            "esas2": self.esa2,
            "paceesa2": self.esa2,
            "ima": self.ima,
            "paceima": self.ima,
            "iea": self.iea,
            "paceiea": self.iea,
        }
        if normalized in pace_topics:
            return pace_topics[normalized].guide(language=language)
        if normalized in {"lmag", "mag"}:
            return self.lmag.guide(language=language)
        if normalized in {"lrs", "npw", "wfc"}:
            return self.lrs.guide(language=language)
        raise KeyError(f"Unknown KAGUYA guide topic: {topic}")

    def help(self, topic: str | None = None, *, language: str = "ja") -> GuidePage:
        return self.guide(topic, language=language)

    def example(self) -> GuidePage:
        return _example_page(
            "KAGUYA Example",
            """# KAGUYA Example

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")

counts = kg.esa1.counts.load(time)
fig = counts.plot()
```
""",
        )


class EndpointInstrument(Protocol):
    mission: Kaguya
    name: str

    def guide(self, *, language: str = "ja") -> GuidePage: ...

    def remote_files_for_period(
        self,
        time: TimeRange,
        *args: Any,
        **kwargs: Any,
    ) -> list[str]: ...

    def load(self, time: TimeRange, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class KaguyaQuery:
    instrument: KaguyaInstrument
    start: object
    stop: object | None = None

    def remote_files(self) -> list[str]:
        return self.instrument.remote_files(self.start, self.stop)

    def remote_urls(self) -> list[str]:
        return [self.instrument.mission.source.remote_url(path) for path in self.remote_files()]

    def files(
        self,
        *,
        download: DownloadMode | None = None,
        overwrite: bool = False,
    ) -> list[Path]:
        download = self.instrument.mission.download if download is None else download
        _validate_download_mode(download)
        paths: list[Path] = []
        for remote_file in self.remote_files():
            path = self.instrument.mission.source.local_path(remote_file)
            if download == "never":
                if path.exists():
                    paths.append(path)
                continue
            if download == "missing":
                try:
                    path = self.instrument.mission.source.download(remote_file, overwrite=False)
                except HTTPError as exc:
                    if self.instrument.is_optional_missing_file(remote_file, exc):
                        continue
                    raise
            elif download == "always":
                try:
                    path = self.instrument.mission.source.download(remote_file, overwrite=True)
                except HTTPError as exc:
                    if self.instrument.is_optional_missing_file(remote_file, exc):
                        continue
                    raise
            _register_downloaded_raw_file(
                self.instrument.mission.store,
                self.instrument.mission.source,
                path,
                remote_file=remote_file,
            )
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
        instrument: EndpointInstrument,
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
                f"example: {_endpoint_path(self)}.load(time)",
            ),
        )

    def schema(self) -> VariableSchema:
        return self._schema

    def guide(self, *, language: str = "ja") -> GuidePage:
        return self.instrument.guide(language=language)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        endpoint_path = _endpoint_path(self)
        plot_line = _endpoint_plot_example(self)
        return _example_page(
            f"KAGUYA {self.instrument.name} {self.name} Example",
            f"""# KAGUYA {self.instrument.name} {self.name} Example

```python
import sopran as spn

kg = spn.Kaguya()
time = spn.day("2008-01-01")

{self.name} = {endpoint_path}.load(time)

{plot_line}
stack = spn.stack(item)
plot_result = stack.plot()
fig = plot_result.fig
```
""",
        )

    def plan(self, time: TimeRange | None = None) -> LoadPlan:
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        return LoadPlan(
            dataset_id=self.dataset_id,
            time=time,
            remote_files=self.instrument.remote_files_for_period(time),
        )

    def pipeline(self, time: TimeRange | None = None) -> Pipeline:
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        return Pipeline(
            source=self.dataset_id,
            time=time,
            context=self.instrument,
            default_variable=self.name,
        )

    def coverage(
        self,
        time: TimeRange | None = None,
        *,
        freq: Literal["day", "month"] = "day",
        cache: CacheMode = "use",
        download: DownloadMode | None = None,
        missing: MissingMode | None = None,
        calibration: PaceCalibration | Literal["auto"] | None = "auto",
        dataset_id: str | None = None,
        layer: str = "features",
    ) -> Any:
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        validate_coverage_freq(freq)
        _validate_cache_mode(cache)
        resolved_dataset_id = dataset_id or coverage_dataset_id(self.dataset_id)
        variant_id = coverage_variant_id(freq)
        if cache == "use":
            cached = read_cached_coverage_frame(
                self.instrument.mission.store,
                dataset_id=resolved_dataset_id,
                layer=layer,
                variant_id=variant_id,
                time=time,
            )
            if cached is not None:
                return cached

        loaded = _load_endpoint_for_coverage(
            self,
            time,
            download=download,
            missing=missing,
            calibration=calibration,
        )
        bins = coverage_bins(time, freq=freq)
        expected = _expected_remote_file_counts(self.instrument, bins)
        available = _available_source_file_counts(self.instrument, loaded.files, bins)
        frame = coverage_frame_from_xarray(
            loaded.to_xarray(),
            time=time,
            freq=freq,
            source_dataset_id=self.dataset_id,
            mission="kaguya",
            instrument=self.instrument.name.lower(),
            product=self.name,
            expected_remote_files=expected,
            available_source_files=available,
        )
        if cache != "never":
            self.instrument.mission.store.write_parquet_dataset(
                dataset_id=resolved_dataset_id,
                layer=layer,
                variant_id=variant_id,
                variant={
                    "freq": freq,
                    "source_dataset": self.dataset_id,
                },
                mission="kaguya",
                instrument=self.instrument.name.lower(),
                product="coverage",
                schema=coverage_schema(
                    mission="kaguya",
                    instrument=self.instrument.name.lower(),
                ),
                time_coverage=time,
                frame=frame,
                source_files=tuple(str(path) for path in loaded.files),
                source_datasets=(self.dataset_id,),
                overwrite=True,
                producer="sopran.kaguya.coverage",
                parameters={
                    "coverage": {
                        "freq": freq,
                        "source_dataset": self.dataset_id,
                        "metric": "finite_sample_count",
                    },
                },
            )
        return frame

    def load(
        self,
        time: TimeRange | None = None,
        *,
        download: DownloadMode | None = None,
        missing: MissingMode | None = None,
        calibration: PaceCalibration | Literal["auto"] | None = "auto",
    ) -> SopranArray:
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        kwargs: dict[str, Any] = {"download": download}
        if missing is not None:
            kwargs["missing"] = missing
        if self.name == "energy_flux":
            kwargs["calibration"] = calibration
        data = self.instrument.load(time, **kwargs)
        if self.name == "energy_flux":
            return cast("SopranArray", data.to_energy_flux())
        return cast("SopranArray", getattr(data, self.name))

    def plot(
        self,
        time: TimeRange | None = None,
        *,
        download: DownloadMode | None = None,
        missing: MissingMode | None = None,
        cache: CacheMode | None = None,
        calibration: PaceCalibration | Literal["auto"] | None = "auto",
        **kwargs: Any,
    ) -> PlotResult | object | None:
        loaded = _load_endpoint(
            self,
            time,
            download=download,
            missing=missing,
            cache=cache,
            calibration=calibration,
        )
        if self.name == "energy_flux":
            kwargs.setdefault("log_color", True)
            kwargs.setdefault("yscale", "log")
        kwargs.setdefault("dataset_id", self.dataset_id)
        kwargs.setdefault("time_range", loaded.time)
        kwargs.setdefault("frame", self._schema.frame)
        kwargs["metadata"] = _merge_metadata(
            _endpoint_plot_metadata(
                self,
                loaded,
                download=download,
                missing=missing,
                cache=cache,
            ),
            kwargs.pop("metadata", None),
        )
        return cast("PlotResult | object | None", loaded.plot(**kwargs))

    def line(
        self,
        time: TimeRange | None = None,
        *,
        x: str = "time",
        name: str | None = None,
        download: DownloadMode | None = None,
        missing: MissingMode | None = None,
        cache: CacheMode | None = None,
        calibration: PaceCalibration | Literal["auto"] | None = "auto",
    ) -> PlotItem:
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        from sopran.core.plotting import line

        return line(
            lambda: _load_endpoint(
                self,
                time,
                download=download,
                missing=missing,
                cache=cache,
                calibration=calibration,
            ).to_xarray(),
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
        download: DownloadMode | None = None,
        missing: MissingMode | None = None,
        cache: CacheMode | None = None,
        calibration: PaceCalibration | Literal["auto"] | None = "auto",
    ) -> PlotItem:
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        from sopran.core.plotting import lines

        return lines(
            lambda: _load_endpoint(
                self,
                time,
                download=download,
                missing=missing,
                cache=cache,
                calibration=calibration,
            ).to_xarray(),
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
        download: DownloadMode | None = None,
        reduce_dims: tuple[str, ...] | None = None,
        reduction: str = "sum",
        log_color: bool | None = None,
        yscale: str | None = None,
        ylim: tuple[float, float] | None = None,
        vmin: float | None = None,
        vmax: float | None = None,
        missing: MissingMode | None = None,
        cache: CacheMode | None = None,
        calibration: PaceCalibration | Literal["auto"] | None = "auto",
    ) -> PlotItem:
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        from sopran.core.plotting import spectrogram

        return spectrogram(
            lambda: _load_endpoint_plot_array(
                self,
                time,
                download=download,
                missing=missing,
                cache=cache,
                calibration=calibration,
                x=x,
                y=y,
                reduce_dims=reduce_dims,
                reduction=reduction,
            ),
            x=x,
            y=y,
            name=name or self.name,
            log_color=bool(log_color if log_color is not None else self.name == "energy_flux"),
            yscale=yscale or ("log" if self.name == "energy_flux" else None),
            ylim=ylim,
            vmin=vmin,
            vmax=vmax,
        )

    def pitch_angle_spectrum(
        self,
        time: TimeRange | None = None,
        magnetic_field: Any | None = None,
        *,
        calibration: PaceCalibration | Literal["auto"] | None = "auto",
        download: DownloadMode | None = None,
        missing: MissingMode | None = None,
        pitch_bins: Any = "native",
        look_frame: str = "SELENE_M_SPACECRAFT",
        magnetic_frame: str | None = None,
        min_look_bins: int = 1,
        frame_context: Any | None = None,
        cache: CacheMode = "use",
        variant_id: str | None = None,
        dataset_id: str | None = None,
        layer: str = "features",
    ) -> Any:
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        if magnetic_field is None:
            raise TypeError("pitch_angle_spectrum() requires magnetic_field=...")
        if self.name not in {"counts", "energy_flux"}:
            raise ValueError(
                f"{_endpoint_path(self)} cannot be converted to pitch_angle_spectrum"
            )
        _validate_cache_mode(cache)
        resolved_dataset_id = dataset_id
        resolved_variant_id = variant_id
        if cache != "never":
            resolved_dataset_id = _pitch_angle_spectrum_dataset_id(
                self.instrument.name,
                value=self.name,
                dataset_id=dataset_id,
            )
            resolved_variant_id = _pitch_angle_spectrum_variant_id(
                value=self.name,
                magnetic_field=magnetic_field,
                pitch_bins=pitch_bins,
                look_frame=look_frame,
                magnetic_frame=magnetic_frame,
                min_look_bins=min_look_bins,
                variant_id=variant_id,
            )
            if cache == "use":
                cached = _read_pitch_angle_spectrum_store(
                    self.instrument.mission.store,
                    dataset_id=resolved_dataset_id,
                    layer=layer,
                    variant_id=resolved_variant_id,
                    time=time,
                )
                if cached is not None:
                    return cached
        data = self.instrument.load(
            time,
            calibration=calibration,
            download=download,
            missing=missing or "empty",
        )
        return data.pitch_angle_spectrum(
            magnetic_field,
            value=self.name,
            pitch_bins=pitch_bins,
            look_frame=look_frame,
            magnetic_frame=magnetic_frame,
            min_look_bins=min_look_bins,
            frame_context=frame_context,
            cache=cache,
            store=self.instrument.mission.store,
            variant_id=resolved_variant_id,
            dataset_id=resolved_dataset_id,
            layer=layer,
        )

    def pitch_spectrogram(
        self,
        time: TimeRange | None = None,
        magnetic_field: Any | None = None,
        *,
        calibration: PaceCalibration | Literal["auto"] | None = "auto",
        download: DownloadMode | None = None,
        missing: MissingMode | None = None,
        pitch_bins: Any = "native",
        look_frame: str = "SELENE_M_SPACECRAFT",
        magnetic_frame: str | None = None,
        min_look_bins: int = 1,
        frame_context: Any | None = None,
        cache: CacheMode = "use",
        variant_id: str | None = None,
        dataset_id: str | None = None,
        layer: str = "features",
        energy: Any | None = None,
        reduction: str = "sum",
        log_color: bool = False,
        name: str | None = None,
    ) -> PlotItem:
        spectrum = self.pitch_angle_spectrum(
            time,
            magnetic_field,
            calibration=calibration,
            download=download,
            missing=missing,
            pitch_bins=pitch_bins,
            look_frame=look_frame,
            magnetic_frame=magnetic_frame,
            min_look_bins=min_look_bins,
            frame_context=frame_context,
            cache=cache,
            variant_id=variant_id,
            dataset_id=dataset_id,
            layer=layer,
        )
        return cast(
            "PlotItem",
            spectrum.pitch_spectrogram(
                energy=energy,
                reduction=reduction,
                log_color=log_color,
                name=name,
            ),
        )


class OrbitInstrument:
    def __init__(self, mission: Kaguya) -> None:
        self.mission = mission
        self.name = "orbit"
        self.position = GeometryArrayEndpoint(
            self,
            KAGUYA_ORBIT_SCHEMA.variable("position"),
            dataset_id="kaguya.orbit.position",
            compute=lambda data, **_: lmag_position(data),
            product="position",
        )
        self.position_gse = GeometryArrayEndpoint(
            self,
            KAGUYA_ORBIT_SCHEMA.variable("position_gse"),
            dataset_id="kaguya.orbit.position_gse",
            compute=lambda data, **_: lmag_position_gse(data),
            product="position_gse",
        )
        self.radial_distance = GeometryArrayEndpoint(
            self,
            KAGUYA_ORBIT_SCHEMA.variable("radial_distance"),
            dataset_id="kaguya.orbit.radial_distance",
            compute=lambda data, **_: lmag_radial_distance(data),
            product="radial_distance",
        )
        self.radius = self.radial_distance
        self.altitude = GeometryArrayEndpoint(
            self,
            KAGUYA_ORBIT_SCHEMA.variable("altitude"),
            dataset_id="kaguya.orbit.altitude",
            compute=lambda data, *, radius_km, **_: lmag_altitude(
                data,
                radius_km=radius_km,
            ),
            product="altitude",
        )
        self.subpoint = GeometryArrayEndpoint(
            self,
            KAGUYA_ORBIT_SCHEMA.variable("subpoint"),
            dataset_id="kaguya.orbit.subpoint",
            compute=lambda data, **_: lmag_subpoint(data),
            product="subpoint",
        )
        self.sza = GeometryArrayEndpoint(
            self,
            KAGUYA_ORBIT_SCHEMA.variable("sza"),
            dataset_id="kaguya.orbit.sza",
            compute=lambda data, *, sun_vector, sun_frame, context, backend, **_: lmag_sza(
                data,
                sun_vector=sun_vector,
                sun_frame=sun_frame,
                context=context,
                backend=backend,
            ),
            product="sza",
        )


class GeometryArrayEndpoint:
    def __init__(
        self,
        orbit: OrbitInstrument,
        schema: VariableSchema,
        *,
        dataset_id: str,
        compute: Any,
        product: str,
    ) -> None:
        self.instrument = orbit
        self._schema = schema
        self.dataset_id = dataset_id
        self.name = schema.name
        self._compute = compute
        self._product = product

    def schema(self) -> VariableSchema:
        return self._schema

    def load(
        self,
        time: TimeRange | None = None,
        *,
        radius_km: float = MOON_MEAN_RADIUS_KM,
        cache: CacheMode = "use",
        download: DownloadMode | None = None,
        frame: str | None = None,
        sun_vector: Any | None = None,
        sun_frame: str = "MOON_ME",
        context: Any | None = None,
        backend: str | None = None,
        missing: MissingMode = "empty",
    ) -> Any:
        if time is None:
            raise _missing_time_error(f"Kaguya.orbit.{self.name}")
        _validate_cache_mode(cache)
        if self.name == "sza" and sun_vector is None:
            raise ValueError("sun_vector is required for KAGUYA orbit sza")
        variant_id = orbit_variant_id(
            self.name,
            radius_km=radius_km,
            sun_vector=sun_vector,
            sun_frame=sun_frame,
            context=context,
            backend=backend,
        )
        if cache == "use":
            cached = _read_cached_array(
                self.instrument.mission.store,
                self.dataset_id,
                variant_id=variant_id,
                schema=self._schema,
                time=time,
            )
            if cached is not None:
                return _maybe_transform_geometry_array(
                    cached,
                    frame=frame,
                    context=context,
                    backend=backend,
                )
        data = self.instrument.mission.lmag.load(time, download=download, missing=missing)
        product = self._compute(
            data,
            radius_km=radius_km,
            sun_vector=sun_vector,
            sun_frame=sun_frame,
            context=context,
            backend=backend,
        )
        if cache != "never" and data.missing_reason is None:
            self.instrument.mission.store.write_parquet_dataset(
                dataset_id=self.dataset_id,
                variant_id=variant_id,
                variant=variant_metadata(
                    radius_km=radius_km,
                    sun_vector=sun_vector,
                    sun_frame=sun_frame,
                    context=context,
                    backend=backend,
                ),
                layer="features",
                mission="kaguya",
                instrument="orbit",
                product=self._product,
                schema=KAGUYA_ORBIT_SCHEMA,
                time_coverage=time,
                frame=product.to_polars(),
                source_files=tuple(str(path) for path in data.files),
                source_datasets=("kaguya.lmag",),
                overwrite=True,
                producer=f"sopran.kaguya.orbit.{self.name}",
            )
        return _maybe_transform_geometry_array(
            product,
            frame=frame,
            context=context,
            backend=backend,
        )


def _maybe_transform_geometry_array(
    product: Any,
    *,
    frame: str | None,
    context: Any | None,
    backend: str | None,
) -> Any:
    if frame is None:
        return product
    if frame == product.schema.frame:
        return product
    if product.name not in {"position", "position_gse"}:
        raise ValueError(
            "frame transform is only supported for KAGUYA orbit position vectors"
        )
    return product.transform(frame, context=context, backend=backend)


class KaguyaInstrument:
    def __init__(self, mission: Kaguya, name: str) -> None:
        self.mission = mission
        self.name = name

    def select(self, start: object, stop: object | None = None) -> KaguyaQuery:
        return KaguyaQuery(self, start, stop)

    def remote_files(self, start: object, stop: object | None = None) -> list[str]:
        raise NotImplementedError

    def is_optional_missing_file(self, remote_file: str, exc: HTTPError) -> bool:
        return False


class PaceInstrument(KaguyaInstrument):
    def __init__(self, mission: Kaguya, sensor: object, *, version: str = "003") -> None:
        self.sensor = normalize_sensor(sensor)
        self.version = version
        super().__init__(mission, self.sensor)
        self.energy_flux: VariableEndpoint = self._variable("energy_flux")
        self.eflux: VariableEndpoint = self.energy_flux
        self.counts: VariableEndpoint = self._variable("counts")
        self.energy: VariableEndpoint = self._variable("energy")
        self.quality: VariableEndpoint = self._variable("quality")

    def _variable(self, name: str) -> VariableEndpoint:
        return VariableEndpoint(
            self,
            self.schema().variable(name),
            dataset_id=f"kaguya.{self.sensor.lower()}.{name}",
        )

    def calibration_remote_files(self) -> list[str]:
        return pace_calibration_remote_files([self.sensor])

    def calibration_files(self, *, download: DownloadMode | None = None) -> list[Path]:
        download = self.mission.download if download is None else download
        _validate_download_mode(download)
        source = KaguyaFileSource(
            local_root=self.mission.store.raw_path("kaguya", "calibration", "pace"),
            remote_base_url=PACE_CALIBRATION_BASE_URL,
        )
        paths: list[Path] = []
        for remote_file in self.calibration_remote_files():
            path = source.local_path(remote_file)
            if download == "never":
                if path.exists():
                    paths.append(path)
                continue
            if download == "missing":
                path = source.download(remote_file, overwrite=False)
            elif download == "always":
                path = source.download(remote_file, overwrite=True)
            _register_downloaded_calibration_file(
                self.mission.store,
                source,
                path,
                remote_file=remote_file,
            )
            if path.exists():
                paths.append(path)
        return paths

    def load_calibration(self, *, download: DownloadMode | None = None) -> PaceCalibration:
        paths = self.calibration_files(download=download)
        fov_files = [
            path
            for path in paths
            if "FOV_ANGLE" in path.as_posix().upper()
        ]
        info_files = [
            path
            for path in paths
            if "KAGUYA_MAP_PACE_INFORMATION" in path.as_posix().upper()
        ]
        return PaceCalibration(
            fov=read_pace_fov(fov_files) if fov_files else {},
            info=read_pace_info(info_files) if info_files else {},
        )

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        suggestion = _schema_variable_suggestion(name, schema=self.schema())
        available = "\n".join(
            f"  {variable.name}" for variable in self.schema().variables
        )
        raise AttributeError(
            f"Kaguya.{self.name} has no variable {name!r}.\n\n"
            f"Available variables:\n{available}\n\n"
            f"Did you mean:\n  {suggestion}?\n\n"
            f"Try:\n  kg.{self.sensor.lower()}.info()\n"
            f"  kg.{self.sensor.lower()}.{suggestion}.load(time)"
        )

    def remote_files(self, start: object, stop: object | None = None) -> list[str]:
        template = pace_pbf_public_template(self.sensor, version=self.version)
        return iter_public_paths(template, start, stop)

    def remote_files_for_period(self, time: TimeRange) -> list[str]:
        paths: list[str] = []
        for time_day in time.days():
            paths.extend(self.remote_files(time_day))
        return paths

    def pipeline(self, time: TimeRange) -> Pipeline:
        return Pipeline(source=f"kaguya.{self.sensor.lower()}", time=time, context=self)

    def _scan_pipeline(self, pipeline: Pipeline) -> Any:
        variable = _pipeline_variable(pipeline)
        dataset_id = pipeline.output_dataset or f"kaguya.{self.sensor.lower()}.{variable}"
        layer = pipeline.output_layer or _pipeline_source_layer(pipeline)
        lazy = self.mission.store.scan_dataset(dataset_id, layer=layer)
        return _filter_lazy_by_time(lazy, pipeline.time)

    def _stream_pipeline(self, pipeline: Pipeline, *, partition: str) -> Any:
        if partition == "all":
            yield self._scan_pipeline(pipeline).collect()
            return
        if partition == "day":
            from sopran.core.pipeline import _stream_frame_by_day

            yield from _stream_frame_by_day(self._scan_pipeline(pipeline).collect())
            return
        if partition == "shard":
            yield from _stream_pipeline_shards(self, pipeline)
            return
        raise NotImplementedError(
            "KAGUYA PACE pipeline stream currently supports partition='all', "
            "partition='day', and partition='shard'"
        )

    def _run_pipeline(
        self,
        pipeline: Pipeline,
        *,
        mode: str = "create",
        run_id: str,
        resume: bool = False,
        only_failed: bool = False,
        on_error: str = "fail",
        download: DownloadMode | None = None,
    ) -> PipelineResult:
        if pipeline.output_dataset is None or pipeline.output_layer is None:
            raise ValueError("Pipeline.write(dataset, layer=...) is required before run()")
        download = self.mission.download if download is None else _coerce_download_mode(download)

        started = perf_counter()
        started_at = _utc_now_iso()
        if resume:
            existing = _complete_pipeline_output(self.mission.store, pipeline)
            if existing is not None:
                log_path = _write_pipeline_log(
                    existing,
                    pipeline=pipeline,
                    run_id=run_id,
                    mode=mode,
                    status="skipped",
                    started_at=started_at,
                    elapsed_seconds=perf_counter() - started,
                    resume=True,
                    only_failed=False,
                    on_error=on_error,
                    download=download,
                )
                _adopt_pipeline_output(pipeline, existing)
                return PipelineResult(
                    plan=pipeline.plan(),
                    status="skipped",
                    message=f"Skipped {pipeline.output_dataset}; complete catalog already exists.",
                    outputs=(existing,),
                    run_id=run_id,
                    log_path=log_path,
                )

        if only_failed:
            existing = _failed_pipeline_output(self.mission.store, pipeline)
            if existing is None:
                raise DatasetNotFoundError(
                    f"Dataset not found for only_failed replay: {pipeline.output_dataset}"
                )
            failed_count = _failed_shard_count(existing)
            if failed_count == 0:
                log_path = _write_pipeline_log(
                    existing,
                    pipeline=pipeline,
                    run_id=run_id,
                    mode=mode,
                    status="skipped",
                    started_at=started_at,
                    elapsed_seconds=perf_counter() - started,
                    resume=False,
                    only_failed=True,
                    on_error=on_error,
                    download=download,
                )
                _adopt_pipeline_output(pipeline, existing)
                return PipelineResult(
                    plan=pipeline.plan(),
                    status="skipped",
                    message=f"Skipped {pipeline.output_dataset}; no failed shards found.",
                    outputs=(existing,),
                    run_id=run_id,
                    log_path=log_path,
                )
            variable = _pipeline_variable(pipeline)
            calibration = _pipeline_calibration(pipeline, variable=variable)
            replayed_count = _replay_failed_pipeline_shards(
                self,
                existing,
                variable=variable,
                download=download,
                calibration=calibration,
            )
            _update_pipeline_dataset_provenance(
                existing,
                pipeline,
                variable=variable,
                mode=mode,
                run_id=run_id,
                download=download,
            )
            replay_quicklooks: tuple[Any, ...] = ()
            if _pipeline_has_quicklook(pipeline):
                replay_data = _load_pace_pipeline_data(
                    self,
                    pipeline.time,
                    download=download,
                    calibration=calibration,
                )
                replay_quicklooks = _write_pipeline_quicklooks(
                    replay_data,
                    existing,
                    pipeline=pipeline,
                    variable=variable,
                    run_id=run_id,
                    download=download,
                )
            log_path = _write_pipeline_log(
                existing,
                pipeline=pipeline,
                run_id=run_id,
                mode=mode,
                status="complete",
                started_at=started_at,
                elapsed_seconds=perf_counter() - started,
                resume=False,
                only_failed=True,
                replayed_shard_count=replayed_count,
                on_error=on_error,
                download=download,
            )
            _adopt_pipeline_output(pipeline, existing)
            return PipelineResult(
                plan=pipeline.plan(),
                status="complete",
                message=f"Replayed {replayed_count} failed shard(s) for {pipeline.output_dataset}",
                outputs=(existing, *replay_quicklooks),
                run_id=run_id,
                log_path=log_path,
            )

        variable = _pipeline_variable(pipeline)
        calibration = _pipeline_calibration(pipeline, variable=variable)
        partition = _pipeline_partition(pipeline)
        data: KaguyaPaceData | None = None
        try:
            if partition == "day":
                output = _write_daily_partitioned_pipeline_output(
                    self,
                    pipeline,
                    variable=variable,
                    mode=mode,
                    run_id=run_id,
                    download=download,
                    calibration=calibration,
                )
            else:
                loaded = _load_pace_pipeline_data(
                    self,
                    pipeline.time,
                    download=download,
                    calibration=calibration,
                )
                _ensure_pipeline_input_files(loaded, self, pipeline.time)
                data = loaded
                output = data.write_parquet(
                    self.mission.store,
                    variable=variable,
                    dataset_id=pipeline.output_dataset,
                    layer=pipeline.output_layer,
                    overwrite=mode == "replace",
                    append=mode == "append",
                    provenance=_pipeline_dataset_provenance(
                        pipeline,
                        variable=variable,
                        mode=mode,
                        run_id=run_id,
                        download=download,
                    ),
                )
        except FileExistsError:
            raise
        except Exception as exc:
            if on_error != "continue":
                raise
            stage = "load" if data is None else "write"
            output = _write_failed_pipeline_output(
                self,
                self.mission.store,
                pipeline,
                variable=variable,
                mode=mode,
                run_id=run_id,
                download=download,
            )
            log_path = _write_pipeline_log(
                output,
                pipeline=pipeline,
                run_id=run_id,
                mode=mode,
                status="partial",
                started_at=started_at,
                elapsed_seconds=perf_counter() - started,
                resume=resume,
                only_failed=only_failed,
                on_error=on_error,
                download=download,
                errors=(_pipeline_error(stage, exc),),
            )
            return PipelineResult(
                plan=pipeline.plan(),
                status="partial",
                message=f"Recorded failed shard for {pipeline.output_dataset}",
                outputs=(output,),
                run_id=run_id,
                log_path=log_path,
            )
        quicklooks: tuple[Any, ...] = ()
        if _pipeline_has_quicklook(pipeline):
            if data is None:
                data = _load_pace_pipeline_data(
                    self,
                    pipeline.time,
                    download=download,
                    calibration=calibration,
                )
                _ensure_pipeline_input_files(data, self, pipeline.time)
            quicklooks = _write_pipeline_quicklooks(
                data,
                output,
                pipeline=pipeline,
                variable=variable,
                run_id=run_id,
                download=download,
            )
        log_path = _write_pipeline_log(
            output,
            pipeline=pipeline,
            run_id=run_id,
            mode=mode,
            status="complete",
            started_at=started_at,
            elapsed_seconds=perf_counter() - started,
            resume=resume,
            only_failed=only_failed,
            on_error=on_error,
            download=download,
        )
        _adopt_pipeline_output(pipeline, output)
        return PipelineResult(
            plan=pipeline.plan(),
            status="complete",
            message=f"Wrote {pipeline.output_dataset}",
            outputs=(output, *quicklooks),
            run_id=run_id,
            log_path=log_path,
        )

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"KAGUYA.{self.name}",
            lines=tuple(
                f"{variable.name}: {variable.description}"
                for variable in self.schema().variables
            ),
        )

    def guide(self, *, language: str = "ja") -> GuidePage:
        if self.sensor == "ESA1":
            return _read_guide(
                "ESA1.md",
                title="PACE ESA1",
                language=language,
            ).with_schema(self.schema())
        return _read_guide(
            "README.md",
            title=f"KAGUYA {self.sensor}",
            language=language,
        ).with_schema(self.schema())

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        return _example_page(
            f"KAGUYA {self.sensor} Example",
            f"""# KAGUYA {self.sensor} Example

```python
import sopran as spn

kg = spn.Kaguya()
time = spn.day("2008-01-01")

data = kg.{self.sensor.lower()}.load(time)
counts = kg.{self.sensor.lower()}.counts.load(time)

stack = spn.stack(
    counts.spectrogram(y="energy"),
    kg.{self.sensor.lower()}.quality.load(time).line(),
)
plot_result = stack.plot()
fig = plot_result.fig
```
""",
        )

    def schema(self) -> Any:
        return kaguya_pace_schema(self.sensor)

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
        calibration: PaceCalibration | Literal["auto"] | None = "auto",
        download: DownloadMode | None = None,
        missing: MissingMode = "empty",
    ) -> KaguyaPaceData:
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.name}")
        _validate_missing_mode(missing)
        if calibration == "auto":
            calibration = self.load_calibration(download=download)
        files: list[Path] = []
        for time_day in time.days():
            files.extend(self.select(time_day).files(download=download))
        missing_reason = None
        if not files:
            missing_reason = _missing_raw_files_message(self, time)
            if missing == "error":
                raise FileNotFoundError(missing_reason)
            if missing == "warn":
                warnings.warn(missing_reason, UserWarning, stacklevel=2)
        return KaguyaPaceData(
            time=time,
            files=tuple(files),
            instrument=self.sensor,
            calibration=calibration,
            store=self.mission.store,
            missing_reason=missing_reason,
        )


def _filter_lazy_by_time(lazy: Any, time: TimeRange) -> Any:
    return _filter_polars_time(lazy, time)


def _filter_frame_by_time(frame: Any, time: TimeRange) -> Any:
    return _filter_polars_time(frame, time)


def _validate_download_mode(download: str | None) -> None:
    if download not in ("never", "missing", "always"):
        raise ValueError("download must be 'never', 'missing', or 'always'")


def _coerce_download_mode(download: str | None) -> DownloadMode:
    _validate_download_mode(download)
    return cast(DownloadMode, download)


def _validate_missing_mode(missing: str) -> None:
    if missing not in ("empty", "warn", "error"):
        raise ValueError("missing must be 'empty', 'warn', or 'error'")


def _default_download_mode(download: DownloadMode | None) -> DownloadMode:
    if download is None:
        if _truthy_env("SOPRAN_OFFLINE"):
            download = "never"
        else:
            download = _coerce_download_mode(
                os.environ.get("SOPRAN_DOWNLOAD_MODE", "missing")
            )
    return _coerce_download_mode(download)


def _missing_raw_files_message(instrument: Any, time: TimeRange) -> str:
    expected = ", ".join(instrument.remote_files_for_period(time))
    return (
        f"No local KAGUYA {instrument.name} raw files found for "
        f"{time.start_iso} .. {time.stop_iso}. Expected: {expected}"
    )


def _missing_partial_raw_files_message(
    instrument: Any,
    time: TimeRange,
    missing_files: list[str],
) -> str:
    missing = ", ".join(missing_files)
    return (
        f"Missing local KAGUYA {instrument.name} raw files for "
        f"{time.start_iso} .. {time.stop_iso}. Missing: {missing}"
    )


def _missing_lrs_raw_files_message(
    instrument: LrsInstrument,
    time: TimeRange,
    *,
    kind: str,
    missing_files: list[str] | None = None,
) -> str:
    missing_files = missing_files or instrument.remote_files_for_period(time, kind=kind)
    missing = ", ".join(missing_files)
    if len(missing_files) == len(instrument.remote_files_for_period(time, kind=kind)):
        return (
            f"No local KAGUYA LRS {kind.upper()} raw files found for "
            f"{time.start_iso} .. {time.stop_iso}. Expected: {missing}"
        )
    return (
        f"Missing KAGUYA LRS {kind.upper()} raw files for "
        f"{time.start_iso} .. {time.stop_iso}. Missing: {missing}"
    )


def _resolve_kaguya_files(
    instrument: KaguyaInstrument,
    remote_files: list[str],
    *,
    download: DownloadMode | None,
    overwrite: bool = False,
) -> list[Path]:
    download = instrument.mission.download if download is None else download
    _validate_download_mode(download)
    paths: list[Path] = []
    for remote_file in remote_files:
        path = instrument.mission.source.local_path(remote_file)
        if download == "never":
            if path.exists():
                paths.append(path)
            continue
        if download == "missing":
            try:
                path = instrument.mission.source.download(remote_file, overwrite=False)
            except HTTPError as exc:
                if instrument.is_optional_missing_file(remote_file, exc):
                    continue
                raise
        elif download == "always":
            try:
                path = instrument.mission.source.download(remote_file, overwrite=True)
            except HTTPError as exc:
                if instrument.is_optional_missing_file(remote_file, exc):
                    continue
                raise
        _register_downloaded_raw_file(
            instrument.mission.store,
            instrument.mission.source,
            path,
            remote_file=remote_file,
        )
        if overwrite or path.exists():
            paths.append(path)
    return paths


def _lrs_kinds(kind: str) -> tuple[str, ...]:
    normalized = kind.upper()
    if normalized == "ALL":
        return ("NPW", "WFC")
    if normalized in {"NPW", "WFC"}:
        return (normalized,)
    raise ValueError("kind must be 'NPW', 'WFC', or 'all'")


def _register_downloaded_raw_file(
    store: Store,
    source: Any,
    path: Path,
    *,
    remote_file: str,
) -> None:
    remote_url = getattr(source, "remote_url", None)
    try:
        store.register_raw_file(
            path,
            mission="kaguya",
            provider="darts-pds3",
            provider_path=remote_file,
            data_version=_kaguya_data_version(remote_file),
            download_url=remote_url(remote_file) if callable(remote_url) else None,
        )
    except ValueError:
        return


def _register_downloaded_calibration_file(
    store: Store,
    source: Any,
    path: Path,
    *,
    remote_file: str,
) -> None:
    remote_url = getattr(source, "remote_url", None)
    try:
        store.register_raw_file(
            path,
            mission="kaguya",
            provider="kyoto-u-kaguya-pace-calibration",
            provider_path=remote_file,
            download_url=remote_url(remote_file) if callable(remote_url) else None,
        )
    except ValueError:
        return


def _kaguya_data_version(remote_file: str) -> str | None:
    for part in Path(remote_file).parts:
        if "-v" in part:
            version = part.rsplit("-v", 1)[-1]
            if version:
                return f"v{version}"
    return None


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _load_endpoint_plot_array(
    endpoint: VariableEndpoint,
    time: TimeRange,
    *,
    download: DownloadMode | None,
    missing: MissingMode | None,
    cache: CacheMode | None,
    calibration: PaceCalibration | Literal["auto"] | None,
    x: str,
    y: str,
    reduce_dims: tuple[str, ...] | None,
    reduction: str,
) -> Any:
    array = _load_endpoint(
        endpoint,
        time,
        download=download,
        missing=missing,
        cache=cache,
        calibration=calibration,
    ).to_xarray()
    dims = getattr(array, "dims", ())
    dims_to_reduce = reduce_dims
    if dims_to_reduce is None:
        dims_to_reduce = tuple(dim for dim in dims if dim not in {x, y})
    if dims_to_reduce:
        array = getattr(array, reduction)(dims_to_reduce)
    return array


def _write_pipeline_quicklooks(
    data: KaguyaPaceData,
    output: Any,
    *,
    pipeline: Pipeline,
    variable: str,
    run_id: str,
    download: str,
) -> tuple[object, ...]:
    stages = [stage for stage in pipeline.stages if stage.name == "quicklook"]
    if not stages:
        return ()

    from sopran.core.plotting import stack

    results = []
    for stage in stages:
        name = str(stage.parameters["quicklook_name"])
        root = stage.parameters.get("root")
        if root is None:
            root = output.root / "preview"
        formats = tuple(stage.parameters.get("formats", ("png",)))
        backend = str(stage.parameters.get("backend", "matplotlib"))
        if backend != "matplotlib":
            raise ValueError("KAGUYA pipeline quicklook currently supports only matplotlib")
        aggregation = stage.parameters.get("aggregation", {"mode": "native"})
        item = _pipeline_plot_item(data, variable, y=str(stage.parameters.get("y", "energy")))
        results.append(
            stack(item).quicklook(
                name,
                root=root,
                formats=formats,
                dataset_id=pipeline.output_dataset,
                time_range=pipeline.time,
                frame=stage.parameters.get("frame"),
                aggregation=(
                    aggregation
                    if isinstance(aggregation, dict)
                    else {"mode": str(aggregation)}
                ),
                metadata=_pipeline_quicklook_metadata(
                    pipeline,
                    variable,
                    run_id=run_id,
                    download=download,
                ),
            )
        )
    return tuple(results)


def _pipeline_plot_item(data: KaguyaPaceData, variable: str, *, y: str) -> Any:
    array = getattr(data, variable)
    dims = array.schema.dims
    if "time" in dims and y in dims:
        return array.spectrogram(y=y)
    x = "time" if "time" in dims else dims[0]
    return array.line(x=x)


def _pipeline_quicklook_metadata(
    pipeline: Pipeline,
    variable: str,
    *,
    run_id: str,
    download: str,
) -> dict[str, object]:
    return {
        "pipeline": {
            "download": download,
            "output_dataset": pipeline.output_dataset,
            "output_layer": pipeline.output_layer,
            "run_id": run_id,
            "source": pipeline.source,
            "start": pipeline.time.start_iso,
            "stop": pipeline.time.stop_iso,
            "stages": [stage.name for stage in pipeline.stages],
        },
        "variable": variable,
    }


def _pipeline_dataset_provenance(
    pipeline: Pipeline,
    *,
    variable: str,
    mode: str,
    run_id: str,
    download: str,
) -> dict[str, object]:
    return {
        "pipeline": {
            "download": download,
            "mode": mode,
            "output_dataset": pipeline.output_dataset,
            "output_layer": pipeline.output_layer,
            "run_id": run_id,
            "source": pipeline.source,
            "stages": [stage.name for stage in pipeline.stages],
            "start": pipeline.time.start_iso,
            "stop": pipeline.time.stop_iso,
        },
        "variable": variable,
    }


def _write_failed_pipeline_output(
    instrument: PaceInstrument,
    store: Store,
    pipeline: Pipeline,
    *,
    variable: str,
    mode: str,
    run_id: str,
    download: str,
) -> Any:
    return store.register_dataset(
        dataset_id=str(pipeline.output_dataset),
        layer=str(pipeline.output_layer),
        mission="kaguya",
        instrument=instrument.sensor.lower(),
        product=variable,
        schema=instrument.schema(),
        time_coverage=pipeline.time,
        shards=(
            {
                "path": "shards/part-000.parquet",
                "start": pipeline.time.start_iso,
                "stop": pipeline.time.stop_iso,
                "row_count": 0,
                "checksum": "",
                "status": "failed",
            },
        ),
        provenance=_pipeline_dataset_provenance(
            pipeline,
            variable=variable,
            mode=mode,
            run_id=run_id,
            download=download,
        ),
    )


def _write_daily_partitioned_pipeline_output(
    instrument: PaceInstrument,
    pipeline: Pipeline,
    *,
    variable: str,
    mode: str,
    run_id: str,
    download: DownloadMode,
    calibration: PaceCalibration | Literal["auto"] | None,
) -> Any:
    if mode == "replace":
        raise NotImplementedError(
            "KAGUYA PACE partition='day' does not support mode='replace' yet"
        )

    output = None
    for index, chunk_time in enumerate(_daily_time_ranges(pipeline.time)):
        data = _load_pace_pipeline_data(
            instrument,
            chunk_time,
            download=download,
            calibration=calibration,
        )
        _ensure_pipeline_input_files(data, instrument, chunk_time)
        output = data.write_parquet(
            instrument.mission.store,
            variable=variable,
            dataset_id=pipeline.output_dataset,
            layer=str(pipeline.output_layer),
            shard_path=_daily_partition_shard_path(chunk_time),
            append=mode == "append" or index > 0,
            partitioning=("year", "month", "day"),
            provenance=_pipeline_dataset_provenance(
                pipeline,
                variable=variable,
                mode=mode,
                run_id=run_id,
                download=download,
            ),
        )
    if output is None:
        raise ValueError("Pipeline time range did not produce any daily shard")
    return output


def _load_pace_pipeline_data(
    instrument: PaceInstrument,
    time: TimeRange,
    *,
    download: DownloadMode,
    calibration: PaceCalibration | Literal["auto"] | None,
) -> KaguyaPaceData:
    if calibration is None:
        return instrument.load(time, download=download)
    return instrument.load(time, download=download, calibration=calibration)


def _update_pipeline_dataset_provenance(
    output: Any,
    pipeline: Pipeline,
    *,
    variable: str,
    mode: str,
    run_id: str,
    download: str,
) -> None:
    manifest = output.manifest()
    manifest["provenance"] = _pipeline_dataset_provenance(
        pipeline,
        variable=variable,
        mode=mode,
        run_id=run_id,
        download=download,
    )
    output.manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _pipeline_has_quicklook(pipeline: Pipeline) -> bool:
    return any(stage.name == "quicklook" for stage in pipeline.stages)


def _pipeline_partition(pipeline: Pipeline) -> str | None:
    for stage in reversed(pipeline.stages):
        if stage.name == "write":
            partition = stage.parameters.get("partition")
            return str(partition) if partition is not None else None
    return None


def _stream_pipeline_shards(instrument: PaceInstrument, pipeline: Pipeline) -> Any:
    import polars as pl

    variable = _pipeline_variable(pipeline)
    dataset_id = pipeline.output_dataset or f"kaguya.{instrument.sensor.lower()}.{variable}"
    layer = pipeline.output_layer or _pipeline_source_layer(pipeline)
    output = instrument.mission.store.dataset(dataset_id, layer=layer)
    for shard in output.shards(status="complete"):
        shard_time = _shard_time_range(shard)
        if shard_time.stop <= pipeline.time.start or shard_time.start >= pipeline.time.stop:
            continue
        yield _filter_frame_by_time(
            pl.read_parquet(output.root / str(shard["path"])),
            pipeline.time,
        )


def _complete_pipeline_output(store: Store, pipeline: Pipeline) -> Any:
    try:
        output = store.dataset(str(pipeline.output_dataset), layer=str(pipeline.output_layer))
    except DatasetNotFoundError:
        return None
    if not _catalog_is_complete(output):
        return None
    if not _record_covers_time(output, pipeline):
        return None
    return output


def _adopt_pipeline_output(pipeline: Pipeline, output: Any) -> None:
    adopter = getattr(pipeline.output_target, "adopt_dataset", None)
    if callable(adopter):
        adopter(output)


def _failed_pipeline_output(store: Store, pipeline: Pipeline) -> Any:
    try:
        output = store.dataset(str(pipeline.output_dataset), layer=str(pipeline.output_layer))
    except DatasetNotFoundError:
        return None
    if not _record_covers_time(output, pipeline):
        return None
    return output


def _catalog_is_complete(output: Any) -> bool:
    shards = output.shards()
    if not shards:
        return False
    return all(str(shard.get("status") or "") == "complete" for shard in shards)


def _failed_shard_count(output: Any) -> int:
    return len(output.failed_shards())


def _replay_failed_pipeline_shards(
    instrument: PaceInstrument,
    output: Any,
    *,
    variable: str,
    download: DownloadMode,
    calibration: PaceCalibration | Literal["auto"] | None,
) -> int:
    replayed = 0
    for shard in output.failed_shards():
        shard_time = _shard_time_range(shard)
        data = _load_pace_pipeline_data(
            instrument,
            shard_time,
            download=download,
            calibration=calibration,
        )
        _ensure_pipeline_input_files(data, instrument, shard_time)
        output.replace_shard(
            str(shard["path"]),
            frame=data.to_polars(variable, layout="long"),
            time_coverage=shard_time,
        )
        replayed += 1
    return replayed


def _ensure_pipeline_input_files(
    data: KaguyaPaceData,
    instrument: PaceInstrument,
    time: TimeRange,
) -> None:
    if data.files:
        return
    expected = ", ".join(instrument.remote_files_for_period(time))
    raise FileNotFoundError(
        f"No local KAGUYA {instrument.name} raw files found for "
        f"{time.start_iso} .. {time.stop_iso}. "
        f"Expected: {expected}"
    )


def _daily_time_ranges(time: TimeRange) -> tuple[TimeRange, ...]:
    ranges = []
    for label in time.days():
        full_day = day(label)
        start = max(time.start, full_day.start)
        stop = min(time.stop, full_day.stop)
        if stop > start:
            ranges.append(TimeRange(start, stop))
    return tuple(ranges)


def _daily_partition_shard_path(time: TimeRange) -> str:
    return (
        f"shards/year={time.start.year:04d}/"
        f"month={time.start.month:02d}/"
        f"day={time.start.day:02d}/"
        "part-000.parquet"
    )


def _shard_time_range(shard: dict[str, object]) -> TimeRange:
    start = str(shard.get("start") or "")
    stop = str(shard.get("stop") or "")
    if not start or not stop:
        raise ValueError(f"Failed shard has no time coverage: {shard.get('path')}")
    return period(start, stop)


def _record_covers_time(output: Any, pipeline: Pipeline) -> bool:
    coverage = output.manifest().get("time_coverage") or {}
    return _coverage_contains_time_range(coverage, pipeline.time)


def _write_pipeline_log(
    output: Any,
    *,
    pipeline: Pipeline,
    run_id: str,
    mode: str,
    status: str,
    started_at: str,
    elapsed_seconds: float,
    resume: bool = False,
    only_failed: bool = False,
    replayed_shard_count: int = 0,
    on_error: str = "fail",
    download: str,
    errors: tuple[dict[str, str], ...] = (),
) -> Path:
    shards = [
        cast(dict[str, Any], _jsonable(row))
        for row in output.catalog().iter_rows(named=True)
    ]
    row_count = sum(int(row.get("row_count") or 0) for row in shards)
    failed_shard_count = sum(
        1 for row in shards if str(row.get("status") or "") == "failed"
    )
    finished_at = _utc_now_iso()
    payload = {
        "run_id": run_id,
        "mode": mode,
        "status": status,
        "resume": resume,
        "only_failed": only_failed,
        "on_error": on_error,
        "download": download,
        "failed_shard_count": failed_shard_count,
        "replayed_shard_count": replayed_shard_count,
        "errors": [_jsonable(error) for error in errors],
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": elapsed_seconds,
        "plan": {
            "source": pipeline.source,
            "start": pipeline.time.start_iso,
            "stop": pipeline.time.stop_iso,
            "output_dataset": pipeline.output_dataset,
            "output_layer": pipeline.output_layer,
        },
        "stages": [
            {
                "name": stage.name,
                "parameters": _jsonable(stage.parameters),
            }
            for stage in pipeline.stages
        ],
        "stage_logs": _pipeline_stage_logs(
            pipeline,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            elapsed_seconds=elapsed_seconds,
            row_count=row_count,
            shard_count=len(shards),
        ),
        "row_count": row_count,
        "shards": shards,
    }
    path = cast(Path, output.root / "logs" / f"{run_id}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def _pipeline_error(stage: str, exc: Exception) -> dict[str, str]:
    return {
        "stage": stage,
        "type": exc.__class__.__name__,
        "message": str(exc),
    }


def _pipeline_stage_logs(
    pipeline: Pipeline,
    *,
    status: str,
    started_at: str,
    finished_at: str,
    elapsed_seconds: float,
    row_count: int,
    shard_count: int,
) -> list[dict[str, object]]:
    return [
        {
            "name": stage.name,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_seconds": elapsed_seconds,
            "row_count": row_count,
            "shard_count": shard_count,
            "parameters": _jsonable(stage.parameters),
        }
        for stage in pipeline.stages
    ]


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


class LrsInstrument(KaguyaInstrument):
    npw_rx1: LrsVariableEndpoint
    npw_rx2: LrsVariableEndpoint
    npw_mode: LrsVariableEndpoint
    wfc_ex_db: LrsVariableEndpoint
    wfc_ey_db: LrsVariableEndpoint
    wfc_gain: LrsVariableEndpoint
    wfc_ex_field: LrsVariableEndpoint
    wfc_ey_field: LrsVariableEndpoint
    wfc_ex_power_spectral_density: LrsVariableEndpoint
    wfc_ey_power_spectral_density: LrsVariableEndpoint
    wfc_ex_power: LrsVariableEndpoint
    wfc_ey_power: LrsVariableEndpoint
    wfc_xymode: LrsVariableEndpoint
    wfc_fband: LrsVariableEndpoint
    wfc_omode: LrsVariableEndpoint
    wfc_pdc_ti: LrsVariableEndpoint
    wfc_postgap: LrsVariableEndpoint
    npw: LrsEndpointGroup
    wfc: LrsEndpointGroup

    def __init__(self, mission: Kaguya, *, version: str = "010") -> None:
        self.version = version
        super().__init__(mission, "LRS")
        for variable in KAGUYA_LRS_SCHEMA.variables:
            endpoint = self._variable(variable.name)
            setattr(self, variable.name, endpoint)
        self.wfc_ex_power = self.wfc_ex_power_spectral_density
        self.wfc_ey_power = self.wfc_ey_power_spectral_density
        self.npw = LrsEndpointGroup(
            rx1=self.npw_rx1,
            rx2=self.npw_rx2,
            mode=self.npw_mode,
        )
        self.wfc = LrsEndpointGroup(
            ex_db=self.wfc_ex_db,
            ey_db=self.wfc_ey_db,
            gain=self.wfc_gain,
            ex_field=self.wfc_ex_field,
            ey_field=self.wfc_ey_field,
            ex_power_spectral_density=self.wfc_ex_power_spectral_density,
            ey_power_spectral_density=self.wfc_ey_power_spectral_density,
            ex_power=self.wfc_ex_power_spectral_density,
            ey_power=self.wfc_ey_power_spectral_density,
            xymode=self.wfc_xymode,
            fband=self.wfc_fband,
            omode=self.wfc_omode,
            pdc_ti=self.wfc_pdc_ti,
            postgap=self.wfc_postgap,
        )

    def _variable(self, name: str) -> LrsVariableEndpoint:
        return LrsVariableEndpoint(
            self,
            KAGUYA_LRS_SCHEMA.variable(name),
            dataset_id=f"kaguya.lrs.{name}",
            kind=lrs_kind_for_variable(name),
        )

    def info(self) -> InfoPage:
        return InfoPage(
            title="KAGUYA.LRS",
            lines=tuple(
                f"{variable.name}: {variable.description}"
                for variable in KAGUYA_LRS_SCHEMA.variables
            ),
        )

    def schema(self) -> InstrumentSchema:
        return KAGUYA_LRS_SCHEMA

    def guide(self, *, language: str = "ja") -> GuidePage:
        return _read_guide(
            "README.md",
            title="KAGUYA LRS",
            language=language,
        ).with_schema(KAGUYA_LRS_SCHEMA)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        return _example_page(
            "KAGUYA LRS Example",
            """# KAGUYA LRS Example

```python
import sopran as spn

kg = spn.Kaguya()
time = spn.day("2008-04-01")

ey = kg.lrs.wfc_ey_power_spectral_density.load(time)
item = ey.spectrogram(y="frequency", log_color=True)
plot_result = spn.stack(item).plot()
```
""",
        )

    def plan(
        self,
        time: TimeRange | None = None,
        *,
        kind: str = "all",
    ) -> LoadPlan:
        if time is None:
            raise _missing_time_error("Kaguya.LRS")
        return LoadPlan(
            dataset_id=f"kaguya.lrs.{kind.lower()}",
            time=time,
            remote_files=self.remote_files_for_period(time, kind=kind),
        )

    def remote_files(
        self,
        start: object,
        stop: object | None = None,
        *,
        kind: str = "all",
    ) -> list[str]:
        paths: list[str] = []
        for lrs_kind in _lrs_kinds(kind):
            template, resolution, skip_odd_hours = lrs_public_template(
                lrs_kind,
                version=self.version,
            )
            if resolution == "daily":
                paths.extend(iter_public_paths(template, start, stop))
            elif resolution == "hourly":
                paths.extend(
                    iter_hourly_public_paths(
                        template,
                        start,
                        stop,
                        skip_odd_hours=skip_odd_hours,
                    )
                )
            else:
                raise ValueError(f"Unsupported KAGUYA LRS resolution: {resolution}")
        return paths

    def remote_files_for_period(
        self,
        time: TimeRange,
        *,
        kind: str = "all",
    ) -> list[str]:
        paths: list[str] = []
        kinds = _lrs_kinds(kind)
        if "NPW" in kinds:
            for label in time.days():
                paths.extend(self.remote_files(label, kind="NPW"))
        if "WFC" in kinds:
            paths.extend(self.remote_files(time.start, time.stop, kind="WFC"))
        return paths

    def load(
        self,
        time: TimeRange | None = None,
        *,
        kind: str = "all",
        download: DownloadMode | None = None,
        missing: MissingMode = "empty",
    ) -> KaguyaLrsData:
        if time is None:
            raise _missing_time_error("Kaguya.LRS")
        _validate_missing_mode(missing)
        remote_files = self.remote_files_for_period(time, kind=kind)
        files = _resolve_kaguya_files(self, remote_files, download=download)
        missing_remote_files = [
            remote_file
            for remote_file in remote_files
            if not self.mission.source.local_path(remote_file).exists()
        ]
        missing_reason = (
            _missing_lrs_raw_files_message(
                self,
                time,
                kind=kind,
                missing_files=missing_remote_files,
            )
            if missing_remote_files
            else None
        )
        if missing_reason is not None:
            if missing == "error":
                raise FileNotFoundError(missing_reason)
            if missing == "warn":
                warnings.warn(missing_reason, UserWarning, stacklevel=2)
        if not files:
            return empty_lrs_data(time, kind=kind, missing_reason=missing_reason)
        return read_lrs_public(files, time=time, missing_reason=missing_reason)

    def is_optional_missing_file(self, remote_file: str, exc: HTTPError) -> bool:
        return exc.code == 404


@dataclass(frozen=True)
class LrsEndpointGroup:
    def __init__(self, **endpoints: Any) -> None:
        for name, endpoint in endpoints.items():
            object.__setattr__(self, name, endpoint)


class LrsVariableEndpoint(VariableEndpoint):
    def __init__(
        self,
        instrument: LrsInstrument,
        schema: VariableSchema,
        *,
        dataset_id: str,
        kind: str,
    ) -> None:
        super().__init__(instrument, schema, dataset_id=dataset_id)
        self.kind = kind

    def plan(self, time: TimeRange | None = None) -> LoadPlan:
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        return LoadPlan(
            dataset_id=self.dataset_id,
            time=time,
            remote_files=self.instrument.remote_files_for_period(time, kind=self.kind),
        )

    def load(
        self,
        time: TimeRange | None = None,
        *,
        download: DownloadMode | None = None,
        missing: MissingMode | None = None,
        cache: CacheMode = "use",
        calibration: PaceCalibration | Literal["auto"] | None = None,
    ) -> Any:
        _ = calibration
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        _validate_cache_mode(cache)
        if cache == "use":
            cached = _read_cached_lrs_array(
                self.instrument.mission.store,
                self.dataset_id,
                layer=_lrs_cache_layer(self.name),
                schema=self._schema,
                time=time,
            )
            if cached is not None:
                return cached
        data = self.instrument.load(
            time,
            kind=self.kind,
            download=download,
            missing=missing or "empty",
        )
        product = getattr(data, self.name)
        if cache != "never" and data.missing_reason is None:
            _write_lrs_array_cache(self, product, data, time=time)
        return product


class LmagInstrument(KaguyaInstrument):
    def __init__(self, mission: Kaguya, *, version: str = "1.0") -> None:
        self.version = version
        super().__init__(mission, "LMAG")
        self.magnetic_field = VariableEndpoint(
            self,
            KAGUYA_LMAG_SCHEMA.variable("magnetic_field"),
            dataset_id="kaguya.lmag.magnetic_field",
        )
        self.b = self.magnetic_field
        self.magnetic_field_gse = VariableEndpoint(
            self,
            KAGUYA_LMAG_SCHEMA.variable("magnetic_field_gse"),
            dataset_id="kaguya.lmag.magnetic_field_gse",
        )
        self.bgse = self.magnetic_field_gse
        self.magnetic_field_magnitude = VariableEndpoint(
            self,
            KAGUYA_LMAG_SCHEMA.variable("magnetic_field_magnitude"),
            dataset_id="kaguya.lmag.magnetic_field_magnitude",
        )
        self.bmag = self.magnetic_field_magnitude
        self.magnetic_connection = LmagConnectionEndpoint(self)

    def info(self) -> InfoPage:
        return InfoPage(
            title="KAGUYA.LMAG",
            lines=(
                "magnetic_field: KAGUYA LMAG magnetic field vector in MOON_ME",
                "magnetic_field_gse: KAGUYA LMAG magnetic field vector in GSE",
                "magnetic_field_magnitude: KAGUYA LMAG |B| time series",
                "alias: b, bgse, bmag",
                "example: kg.lmag.magnetic_field.load(time)",
            ),
        )

    def schema(self) -> Any:
        return KAGUYA_LMAG_SCHEMA

    def guide(self, *, language: str = "ja") -> GuidePage:
        return _read_guide(
            "README.md",
            title="KAGUYA LMAG",
            language=language,
        ).with_schema(KAGUYA_LMAG_SCHEMA)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        return _example_page(
            "KAGUYA LMAG Example",
            """# KAGUYA LMAG Example

```python
import sopran as spn

kg = spn.Kaguya()
time = spn.day("2008-01-01")

b = kg.lmag.magnetic_field.load(time)
item = kg.lmag.magnetic_field.lines(time, components="xyz")
plot_result = spn.stack(item).plot()
```
""",
        )

    def remote_files(self, start: object, stop: object | None = None) -> list[str]:
        paths: list[str] = []
        for template in lmag_public_templates(version=self.version):
            paths.extend(iter_public_paths(template, start, stop))
        return paths

    def remote_files_for_period(self, time: TimeRange) -> list[str]:
        paths: list[str] = []
        for time_day in time.days():
            paths.extend(self.remote_files(time_day))
        return paths

    def is_optional_missing_file(self, remote_file: str, exc: HTTPError) -> bool:
        return exc.code == 404 and "/optional/" in remote_file.replace("\\", "/")

    def load(
        self,
        time: TimeRange | None = None,
        *,
        download: DownloadMode | None = None,
        missing: MissingMode = "empty",
    ) -> KaguyaLmagData:
        if time is None:
            raise _missing_time_error("Kaguya.LMAG")
        _validate_missing_mode(missing)
        files: list[Path] = []
        missing_remote_files: list[str] = []
        for time_day in time.days():
            query = self.select(time_day)
            day_files = query.files(download=download)
            files.extend(day_files)
            if not day_files:
                missing_remote_files.extend(query.remote_files())
        missing_reason = None
        if missing_remote_files:
            missing_reason = (
                _missing_raw_files_message(self, time)
                if not files
                else _missing_partial_raw_files_message(self, time, missing_remote_files)
            )
            if missing == "error":
                raise FileNotFoundError(missing_reason)
            if missing == "warn":
                warnings.warn(missing_reason, UserWarning, stacklevel=2)
        return read_lmag_public(files, time=time, missing_reason=missing_reason)


class LmagConnectionEndpoint:
    def __init__(self, instrument: LmagInstrument) -> None:
        self.instrument = instrument
        self.name = "magnetic_connection"
        self.dataset_id = "kaguya.lmag.magnetic_connection"

    def schema(self) -> Any:
        return connection_schema()

    def info(self) -> InfoPage:
        return InfoPage(
            title="KAGUYA.LMAG.magnetic_connection",
            lines=(
                "field_model: straight_local_field_line",
                "surface: sphere",
                "frame: MOON_ME",
                "plots: footpoint, altitude, incidence, distance",
                "example: kg.lmag.magnetic_connection.load(time, cache='use')",
            ),
        )

    def load(
        self,
        time: TimeRange | None = None,
        *,
        radius_km: float = MOON_MEAN_RADIUS_KM,
        direction: str = "both",
        cache: CacheMode = "use",
        download: DownloadMode | None = None,
        missing: MissingMode = "empty",
    ) -> Any:
        if time is None:
            raise _missing_time_error("Kaguya.LMAG.magnetic_connection")
        _validate_cache_mode(cache)
        _validate_connection_direction(direction)
        variant_id = connection_variant_id(
            radius_km=radius_km,
            direction=direction,  # type: ignore[arg-type]
        )
        if cache == "use":
            cached = _read_cached_connection(
                self.instrument.mission.store,
                self.dataset_id,
                variant_id=variant_id,
                time=time,
                radius_km=radius_km,
                direction=direction,
            )
            if cached is not None:
                return cached
        data = self.instrument.load(time, download=download, missing=missing)
        product = lmag_magnetic_connection(
            data,
            radius_km=radius_km,
            direction=direction,  # type: ignore[arg-type]
        )
        if cache != "never" and data.missing_reason is None:
            self.instrument.mission.store.write_parquet_dataset(
                dataset_id=self.dataset_id,
                variant_id=variant_id,
                variant=variant_metadata(
                    radius_km=radius_km,
                    direction=direction,  # type: ignore[arg-type]
                ),
                layer="features",
                mission="kaguya",
                instrument="lmag",
                product="magnetic_connection",
                schema=connection_schema(),
                time_coverage=time,
                frame=product.to_polars(),
                source_files=tuple(str(path) for path in data.files),
                source_datasets=("kaguya.lmag.magnetic_field", "kaguya.orbit.position"),
                overwrite=True,
                producer="sopran.kaguya.lmag.magnetic_connection",
            )
        return product

    def plot(
        self,
        time: TimeRange | None = None,
        *,
        kind: str = "footpoint",
        radius_km: float = MOON_MEAN_RADIUS_KM,
        direction: str = "both",
        cache: CacheMode = "use",
        download: DownloadMode | None = None,
        missing: MissingMode = "empty",
    ) -> Any:
        return self.load(
            time,
            radius_km=radius_km,
            direction=direction,
            cache=cache,
            download=download,
            missing=missing,
        ).plot(kind=kind)


def _validate_cache_mode(cache: str) -> None:
    if cache not in {"use", "refresh", "never"}:
        raise ValueError("cache must be 'use', 'refresh', or 'never'")


def _validate_connection_direction(direction: str) -> None:
    if direction not in {"plus", "minus", "both"}:
        raise ValueError("direction must be 'plus', 'minus', or 'both'")


def _read_cached_array(
    store: Store,
    dataset_id: str,
    *,
    variant_id: str,
    schema: VariableSchema,
    time: TimeRange,
) -> Any:
    try:
        record = store.dataset(dataset_id, layer="features", variant_id=variant_id)
    except DatasetNotFoundError:
        return None
    if not _record_covers_time_range(record, time):
        return None
    frame = _filter_frame_by_time(record.scan(dataset_id=dataset_id).collect(), time)
    return array_from_polars(frame, schema=schema, time_range=time)


def _read_cached_lrs_array(
    store: Store,
    dataset_id: str,
    *,
    layer: str,
    schema: VariableSchema,
    time: TimeRange,
) -> Any:
    try:
        record = store.dataset(dataset_id, layer=layer)
    except DatasetNotFoundError:
        return None
    if not _record_covers_time_range(record, time):
        return None
    manifest = record.manifest()
    parameters = manifest.get("parameters") or {}
    source_files = tuple(Path(path) for path in manifest.get("source_files") or ())
    frame = _filter_frame_by_time(record.scan(dataset_id=dataset_id).collect(), time)
    return lrs_array_from_polars(
        frame,
        schema=schema,
        time_range=time,
        files=source_files,
        coordinates=parameters.get("coordinates") or {},
        attrs=parameters.get("attrs") or {},
    )


def _read_cached_connection(
    store: Store,
    dataset_id: str,
    *,
    variant_id: str,
    time: TimeRange,
    radius_km: float,
    direction: str,
) -> Any:
    try:
        record = store.dataset(dataset_id, layer="features", variant_id=variant_id)
    except DatasetNotFoundError:
        return None
    if not _record_covers_time_range(record, time):
        return None
    frame = _filter_frame_by_time(record.scan(dataset_id=dataset_id).collect(), time)
    from sopran.missions.kaguya.geometry import KaguyaMagneticConnectionData

    return KaguyaMagneticConnectionData.from_polars(
        frame,
        time_range=time,
        radius_km=radius_km,
        direction=direction,  # type: ignore[arg-type]
    )


def _record_covers_time_range(record: Any, time: TimeRange) -> bool:
    coverage = record.manifest().get("time_coverage") or {}
    return _coverage_contains_time_range(coverage, time)


def _coverage_contains_time_range(coverage: dict[str, object], time: TimeRange) -> bool:
    start = str(coverage.get("start") or "")
    stop = str(coverage.get("stop") or "")
    if not start or not stop:
        return False
    try:
        covered = period(start, stop)
    except (TypeError, ValueError):
        return False
    return covered.start <= time.start and covered.stop >= time.stop


def _write_lrs_array_cache(
    endpoint: LrsVariableEndpoint,
    product: Any,
    data: KaguyaLrsData,
    *,
    time: TimeRange,
) -> None:
    array = product.to_xarray()
    layout = "array" if len(tuple(array.dims)) > 1 else "long"
    endpoint.instrument.mission.store.write_parquet_dataset(
        dataset_id=endpoint.dataset_id,
        layer=_lrs_cache_layer(endpoint.name),
        mission="kaguya",
        instrument="lrs",
        product=endpoint.name,
        schema=KAGUYA_LRS_SCHEMA,
        time_coverage=time,
        frame=product.to_polars(layout=layout, max_rows=None, allow_large=True),
        source_files=tuple(str(path) for path in data.files),
        source_datasets=("kaguya.lrs.raw",),
        overwrite=True,
        producer=f"sopran.kaguya.lrs.{endpoint.name}",
        parameters={
            "kind": endpoint.kind,
            "coordinates": _lrs_cache_coordinates(array),
            "attrs": _jsonable_metadata(dict(array.attrs)),
        },
    )


def _lrs_cache_layer(name: str) -> str:
    if name in {
        "wfc_gain",
        "wfc_ex_field",
        "wfc_ey_field",
        "wfc_ex_power_spectral_density",
        "wfc_ey_power_spectral_density",
        "wfc_xymode",
        "wfc_fband",
        "wfc_omode",
    }:
        return "features"
    return "normalized"


def _lrs_cache_coordinates(array: Any) -> dict[str, object]:
    if "frequency" not in getattr(array, "coords", {}):
        return {}
    coordinate = array.coords["frequency"]
    metadata: dict[str, object] = {"frequency": coordinate.values.tolist()}
    units = getattr(coordinate, "attrs", {}).get("units")
    if units is not None:
        metadata["frequency_units"] = str(units)
    return metadata


def _jsonable_metadata(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable_metadata(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable_metadata(item) for item in value]
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return _jsonable_metadata(tolist())
    return str(value)


def _missing_time_error(endpoint: str) -> ValueError:
    example = _kaguya_endpoint_example(endpoint)
    return ValueError(
        f"Time range is required for {endpoint}.\n\n"
        'Examples:\n  time = spn.period("2008-02-01", "2008-02-02")\n'
        f"  {example}.load(time)\n\n"
        f"Or use a Project case:\n  case.kaguya.{example.removeprefix('kg.')}.load()"
    )


def _kaguya_endpoint_example(endpoint: str) -> str:
    parts = endpoint.split(".")
    if len(parts) >= 2 and parts[0] == "Kaguya":
        return ".".join(("kg", *(part.lower() for part in parts[1:])))
    return "kg.esa1.energy_flux"


def _endpoint_path(endpoint: VariableEndpoint) -> str:
    return f"kg.{endpoint.instrument.name.lower()}.{endpoint.name}"


def _endpoint_plot_metadata(
    endpoint: VariableEndpoint,
    loaded: Any,
    *,
    download: DownloadMode | None,
    missing: MissingMode | None,
    cache: CacheMode | None = None,
) -> dict[str, Any]:
    resolved_download = (
        endpoint.instrument.mission.download if download is None else download
    )
    metadata = {
        "mission": "kaguya",
        "instrument": endpoint.instrument.name,
        "variable": endpoint.name,
        "endpoint": _endpoint_path(endpoint),
        "download": resolved_download,
        "source": "darts-pds3",
        "source_files": [str(path) for path in loaded.files],
        "remote_files": endpoint.plan(loaded.time).remote_files,
        "schema": endpoint.schema().to_metadata(),
    }
    if _instrument_load_accepts_missing(endpoint.instrument):
        metadata["missing"] = missing or "empty"
    if cache is not None:
        metadata["cache"] = cache
    return metadata


def _instrument_load_accepts_missing(instrument: EndpointInstrument) -> bool:
    try:
        return "missing" in signature(instrument.load).parameters
    except (TypeError, ValueError):
        return False


def _load_endpoint(
    endpoint: VariableEndpoint,
    time: TimeRange | None,
    *,
    download: DownloadMode | None,
    missing: MissingMode | None,
    cache: CacheMode | None,
    calibration: PaceCalibration | Literal["auto"] | None = None,
) -> Any:
    kwargs: dict[str, Any] = {"download": download, "missing": missing}
    if endpoint.name == "energy_flux":
        kwargs["calibration"] = calibration
    if cache is not None:
        parameters = signature(endpoint.load).parameters
        if "cache" not in parameters:
            raise TypeError(f"{_endpoint_path(endpoint)} does not support cache")
        _validate_cache_mode(cache)
        kwargs["cache"] = cache
    return endpoint.load(time, **kwargs)


def _load_endpoint_for_coverage(
    endpoint: VariableEndpoint,
    time: TimeRange,
    *,
    download: DownloadMode | None,
    missing: MissingMode | None,
    calibration: PaceCalibration | Literal["auto"] | None,
) -> Any:
    if isinstance(endpoint.instrument, PaceInstrument):
        kwargs: dict[str, Any] = {
            "download": download,
            "missing": missing or "empty",
        }
        if endpoint.name == "energy_flux":
            kwargs["calibration"] = calibration
        data = endpoint.instrument.load(time, **kwargs)
        return getattr(data, endpoint.name)
    return _load_endpoint(
        endpoint,
        time,
        download=download,
        missing=missing,
        cache=None,
        calibration=calibration,
    )


def _expected_remote_file_counts(
    instrument: EndpointInstrument,
    bins: tuple[Any, ...],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in bins:
        time = TimeRange(item.start, item.stop)
        counts[item.start_iso] = len(instrument.remote_files_for_period(time))
    return counts


def _available_source_file_counts(
    instrument: EndpointInstrument,
    files: tuple[Path, ...],
    bins: tuple[Any, ...],
) -> dict[str, int]:
    source_files = tuple(path.as_posix().replace("\\", "/") for path in files)
    counts: dict[str, int] = {}
    for item in bins:
        time = TimeRange(item.start, item.stop)
        count = 0
        for remote_file in instrument.remote_files_for_period(time):
            remote = Path(remote_file).as_posix().replace("\\", "/")
            if any(source.endswith(remote) for source in source_files):
                count += 1
        counts[item.start_iso] = count
    return counts


def _merge_metadata(
    base: dict[str, Any],
    extra: dict[str, Any] | None,
) -> dict[str, Any]:
    if not extra:
        return base
    merged = dict(base)
    merged.update(extra)
    return merged


def _endpoint_plot_example(endpoint: VariableEndpoint) -> str:
    dims = endpoint.schema().dims
    path = _endpoint_path(endpoint)
    if "energy" in dims and "time" in dims:
        return f'item = {path}.spectrogram(time, y="energy")'
    if "component" in dims and "time" in dims:
        return f'item = {path}.lines(time, components="xyz")'
    x = "time" if "time" in dims else dims[0]
    return f'item = {path}.line(time, x="{x}")'


def _schema_variable_suggestion(
    name: str,
    *,
    schema: InstrumentSchema = KAGUYA_ESA1_SCHEMA,
) -> str:
    aliases: dict[str, str] = {
        alias: variable.name
        for variable in schema.variables
        for alias in variable.aliases
    }
    aliases["flux"] = "energy_flux"
    canonical_names = tuple(variable.name for variable in schema.variables)
    candidates = (*canonical_names, *aliases)
    matches = get_close_matches(name, candidates, n=1, cutoff=0.4)
    if matches:
        return aliases.get(matches[0], matches[0])
    return canonical_names[0]


def _read_guide(name: str, *, title: str, language: str = "ja") -> GuidePage:
    if language not in _GUIDE_LANGUAGES:
        raise ValueError(f"KAGUYA guide language is not available: {language}")
    package = files("sopran.missions.kaguya")
    resource_name = _guide_resource_name(name, language)
    resource = package.joinpath(resource_name)
    if not resource.is_file():
        resource_name = name
        resource = package.joinpath(name)
    markdown = resource.read_text(encoding="utf-8")
    translations = {}
    sources = {}
    for available_language in _GUIDE_LANGUAGES:
        if available_language == language:
            continue
        translation_name = _guide_resource_name(name, available_language)
        translation = package.joinpath(translation_name)
        if not translation.is_file():
            translation_name = name
            translation = package.joinpath(name)
        translations[available_language] = translation.read_text(encoding="utf-8")
        sources[available_language] = f"sopran.missions.kaguya/{translation_name}"
    return GuidePage(
        title=title,
        markdown=markdown,
        source=f"sopran.missions.kaguya/{resource_name}",
        url=_PUBLIC_DOC_URLS.get(name),
        language=language,
        available_languages=_GUIDE_LANGUAGES,
        translations=translations,
        sources=sources,
    )


def _guide_resource_name(name: str, language: str) -> str:
    if language == "en":
        return name
    path = Path(name)
    return f"{path.stem}.{language}{path.suffix}"


def _example_page(title: str, markdown: str) -> GuidePage:
    return GuidePage(
        title=title,
        markdown=markdown,
        source="sopran.missions.kaguya.examples",
    )


def _pipeline_variable(pipeline: Pipeline) -> str:
    for stage in pipeline.stages:
        if stage.name == "select_variables":
            names = stage.parameters.get("names", ())
            if len(names) != 1:
                raise NotImplementedError("KAGUYA PACE pipeline run expects one selected variable")
            return str(names[0])
    if pipeline.default_variable is not None:
        return pipeline.default_variable
    if pipeline.output_dataset:
        return pipeline.output_dataset.split(".")[-1]
    return "counts"


def _pipeline_calibration(
    pipeline: Pipeline,
    *,
    variable: str,
) -> PaceCalibration | Literal["auto"] | None:
    for stage in pipeline.stages:
        if stage.name != "calibrate":
            continue
        name = str(stage.parameters.get("name", ""))
        if name != "energy_flux":
            raise NotImplementedError(
                "KAGUYA PACE pipeline currently supports calibrate('energy_flux') only"
            )
        if variable != "energy_flux":
            raise ValueError(
                "KAGUYA PACE calibrate('energy_flux') must be paired with "
                "the energy_flux endpoint or select_variables('energy_flux')"
            )
        return cast(
            PaceCalibration | Literal["auto"] | None,
            stage.parameters.get("calibration", "auto"),
        )
    if variable == "energy_flux":
        raise ValueError(
            "KAGUYA PACE pipeline writing energy_flux requires "
            ".calibrate(calibration='auto') on kg.esa1.energy_flux.pipeline(...), "
            "or .calibrate('energy_flux', calibration='auto') before "
            "select_variables('energy_flux')."
        )
    return None


def _pipeline_source_layer(pipeline: Pipeline) -> str:
    if any(stage.name == "from_normalized" for stage in pipeline.stages):
        return "normalized"
    raise ValueError("Pipeline.scan() requires from_normalized() or write(..., layer=...)")
