from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from time import perf_counter
from typing import Literal

from sopran.core import Store
from sopran.core.errors import DatasetNotFoundError
from sopran.core.pages import GuidePage, InfoPage
from sopran.core.pipeline import Pipeline, PipelineResult
from sopran.core.schema import VariableSchema
from sopran.core.time import TimeRange, day, period
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
_GUIDE_LANGUAGES = ("ja", "en")
_PUBLIC_DOC_URLS = {
    "README.md": "https://nkzono99.github.io/sopran/missions/kaguya/",
    "ESA1.md": "https://nkzono99.github.io/sopran/missions/kaguya-esa1/",
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

    def guide(self, topic: str | None = None, *, language: str = "en") -> GuidePage:
        if topic is None:
            return _read_guide("README.md", title="KAGUYA/SELENE", language=language)
        normalized = topic.lower().replace("-", "").replace("_", "")
        if normalized in {"esa1", "esas1", "paceesa1"}:
            return self.esa1.guide(language=language)
        raise KeyError(f"Unknown KAGUYA guide topic: {topic}")

    def help(self, topic: str | None = None, *, language: str = "en") -> GuidePage:
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
                path = self.instrument.mission.source.download(remote_file, overwrite=False)
            elif download == "always":
                path = self.instrument.mission.source.download(remote_file, overwrite=True)
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

    def guide(self, *, language: str = "en") -> GuidePage:
        return self.instrument.guide(language=language)

    def help(self, *, language: str = "en") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        return _example_page(
            f"KAGUYA {self.instrument.name} {self.name} Example",
            f"""# KAGUYA {self.instrument.name} {self.name} Example

```python
import sopran as spn

kg = spn.Kaguya()
time = spn.day("2008-01-01")

{self.name} = kg.esa1.{self.name}.load(time)

stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy"),
    kg.esa1.quality.load(time).line(),
)
fig = stack.plot()
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

    def load(self, time: TimeRange | None = None, *, download: DownloadMode | None = None):
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        data = self.instrument.load(time, download=download)
        return getattr(data, self.name)

    def plot(
        self,
        time: TimeRange | None = None,
        *,
        download: DownloadMode | None = None,
        **kwargs,
    ):
        return self.load(time, download=download).plot(**kwargs)

    def line(
        self,
        time: TimeRange | None = None,
        *,
        x: str = "time",
        name: str | None = None,
        download: DownloadMode | None = None,
    ):
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        from sopran.core.plotting import line

        return line(
            lambda: self.load(time, download=download).to_xarray(),
            x=x,
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
    ):
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.instrument.name}.{self.name}")
        from sopran.core.plotting import spectrogram

        return spectrogram(
            lambda: _load_endpoint_plot_array(
                self,
                time,
                download=download,
                x=x,
                y=y,
                reduce_dims=reduce_dims,
                reduction=reduction,
            ),
            x=x,
            y=y,
            name=name or self.name,
        )


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
        return Pipeline(source=f"kaguya.{self.sensor.lower()}", time=time, context=self)

    def _scan_pipeline(self, pipeline: Pipeline):
        if self.sensor != "ESA1":
            raise NotImplementedError(f"pipeline scan is not implemented for {self.sensor}")
        variable = _pipeline_variable(pipeline)
        dataset_id = pipeline.output_dataset or f"kaguya.esa1.{variable}"
        layer = pipeline.output_layer or _pipeline_source_layer(pipeline)
        lazy = self.mission.store.scan_dataset(dataset_id, layer=layer)
        return _filter_lazy_by_time(lazy, pipeline.time)

    def _stream_pipeline(self, pipeline: Pipeline, *, partition: str):
        if self.sensor != "ESA1":
            raise NotImplementedError(f"pipeline stream is not implemented for {self.sensor}")
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
            "KAGUYA ESA1 pipeline stream currently supports partition='all', "
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
    ) -> PipelineResult:
        if self.sensor != "ESA1":
            raise NotImplementedError(f"pipeline run is not implemented for {self.sensor}")
        if pipeline.output_dataset is None or pipeline.output_layer is None:
            raise ValueError("Pipeline.write(dataset, layer=...) is required before run()")

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
                )
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
                )
                return PipelineResult(
                    plan=pipeline.plan(),
                    status="skipped",
                    message=f"Skipped {pipeline.output_dataset}; no failed shards found.",
                    outputs=(existing,),
                    run_id=run_id,
                    log_path=log_path,
                )
            variable = _pipeline_variable(pipeline)
            replayed_count = _replay_failed_pipeline_shards(
                self,
                existing,
                variable=variable,
            )
            _update_pipeline_dataset_provenance(
                existing,
                pipeline,
                variable=variable,
                mode=mode,
                run_id=run_id,
            )
            quicklooks = ()
            if _pipeline_has_quicklook(pipeline):
                data = self.load(pipeline.time, download="never")
                quicklooks = _write_pipeline_quicklooks(
                    data,
                    existing,
                    pipeline=pipeline,
                    variable=variable,
                    run_id=run_id,
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
            )
            return PipelineResult(
                plan=pipeline.plan(),
                status="complete",
                message=f"Replayed {replayed_count} failed shard(s) for {pipeline.output_dataset}",
                outputs=(existing, *quicklooks),
                run_id=run_id,
                log_path=log_path,
            )

        variable = _pipeline_variable(pipeline)
        partition = _pipeline_partition(pipeline)
        data = None
        try:
            if partition == "day":
                output = _write_daily_partitioned_pipeline_output(
                    self,
                    pipeline,
                    variable=variable,
                    mode=mode,
                    run_id=run_id,
                )
            else:
                loaded = self.load(pipeline.time, download="never")
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
                    ),
                )
        except FileExistsError:
            raise
        except Exception as exc:
            if on_error != "continue":
                raise
            stage = "load" if data is None else "write"
            output = _write_failed_pipeline_output(
                self.mission.store,
                pipeline,
                variable=variable,
                mode=mode,
                run_id=run_id,
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
        quicklooks = ()
        if _pipeline_has_quicklook(pipeline):
            if data is None:
                data = self.load(pipeline.time, download="never")
                _ensure_pipeline_input_files(data, self, pipeline.time)
            quicklooks = _write_pipeline_quicklooks(
                data,
                output,
                pipeline=pipeline,
                variable=variable,
                run_id=run_id,
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
        )
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
                for variable in KAGUYA_ESA1_SCHEMA.variables
            )
            if self.sensor == "ESA1"
            else (),
        )

    def guide(self, *, language: str = "en") -> GuidePage:
        if self.sensor == "ESA1":
            return _read_guide(
                "ESA1.md",
                title="PACE ESA1",
                language=language,
            ).with_schema(KAGUYA_ESA1_SCHEMA)
        return _read_guide("README.md", title=f"KAGUYA {self.sensor}", language=language)

    def help(self, *, language: str = "en") -> GuidePage:
        return self.guide(language=language)

    def example(self) -> GuidePage:
        if self.sensor != "ESA1":
            return _example_page(
                f"KAGUYA {self.sensor} Example",
                f"""# KAGUYA {self.sensor} Example

`load()` is not implemented for KAGUYA {self.sensor} yet.
""",
            )
        return _example_page(
            "KAGUYA ESA1 Example",
            """# KAGUYA ESA1 Example

```python
import sopran as spn

kg = spn.Kaguya()
time = spn.day("2008-01-01")

esa1 = kg.esa1.load(time)
counts = kg.esa1.counts.load(time)

stack = spn.stack(
    counts.spectrogram(y="energy"),
    kg.esa1.quality.load(time).line(),
)
fig = stack.plot()
```
""",
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
        download: DownloadMode | None = None,
    ) -> KaguyaESA1Data:
        if time is None:
            raise _missing_time_error(f"Kaguya.{self.name}")
        if self.sensor != "ESA1":
            raise NotImplementedError(f"load() is not implemented for {self.sensor}")
        files: list[Path] = []
        for day in time.days():
            files.extend(self.select(day).files(download=download))
        return KaguyaESA1Data(time=time, files=tuple(files))


def _filter_lazy_by_time(lazy, time: TimeRange):
    import polars as pl

    dtype = lazy.collect_schema().get("time")
    if dtype == pl.Datetime or dtype == pl.Date:
        start = time.start.replace(tzinfo=None)
        stop = time.stop.replace(tzinfo=None)
    else:
        start = time.start_iso
        stop = time.stop_iso
    return lazy.filter(
        (pl.col("time") >= start)
        & (pl.col("time") < stop)
    )


def _filter_frame_by_time(frame, time: TimeRange):
    import polars as pl

    dtype = frame.schema.get("time")
    if dtype == pl.Datetime or dtype == pl.Date:
        start = time.start.replace(tzinfo=None)
        stop = time.stop.replace(tzinfo=None)
    else:
        start = time.start_iso
        stop = time.stop_iso
    return frame.filter((pl.col("time") >= start) & (pl.col("time") < stop))


def _validate_download_mode(download: str) -> None:
    if download not in ("never", "missing", "always"):
        raise ValueError("download must be 'never', 'missing', or 'always'")


def _default_download_mode(download: DownloadMode | None) -> DownloadMode:
    if download is None:
        if _truthy_env("SOPRAN_OFFLINE"):
            download = "never"
        else:
            download = os.environ.get("SOPRAN_DOWNLOAD_MODE", "never")
    _validate_download_mode(download)
    return download


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _load_endpoint_plot_array(
    endpoint: VariableEndpoint,
    time: TimeRange,
    *,
    download: DownloadMode | None,
    x: str,
    y: str,
    reduce_dims: tuple[str, ...] | None,
    reduction: str,
):
    array = endpoint.load(time, download=download).to_xarray()
    dims = getattr(array, "dims", ())
    dims_to_reduce = reduce_dims
    if dims_to_reduce is None:
        dims_to_reduce = tuple(dim for dim in dims if dim not in {x, y})
    if dims_to_reduce:
        array = getattr(array, reduction)(dims_to_reduce)
    return array


def _write_pipeline_quicklooks(
    data: KaguyaESA1Data,
    output,
    *,
    pipeline: Pipeline,
    variable: str,
    run_id: str,
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
        item = _pipeline_plot_item(data, variable, y=str(stage.parameters.get("y", "energy")))
        results.append(
            stack(item).quicklook(
                name,
                root=root,
                formats=formats,
                metadata=_pipeline_quicklook_metadata(pipeline, variable, run_id=run_id),
            )
        )
    return tuple(results)


def _pipeline_plot_item(data: KaguyaESA1Data, variable: str, *, y: str):
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
) -> dict[str, object]:
    return {
        "pipeline": {
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
) -> dict[str, object]:
    return {
        "pipeline": {
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
    store: Store,
    pipeline: Pipeline,
    *,
    variable: str,
    mode: str,
    run_id: str,
):
    return store.register_dataset(
        dataset_id=str(pipeline.output_dataset),
        layer=str(pipeline.output_layer),
        mission="kaguya",
        instrument="esa1",
        product=variable,
        schema=KAGUYA_ESA1_SCHEMA,
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
        ),
    )


def _write_daily_partitioned_pipeline_output(
    instrument: PaceInstrument,
    pipeline: Pipeline,
    *,
    variable: str,
    mode: str,
    run_id: str,
):
    if mode == "replace":
        raise NotImplementedError(
            "KAGUYA ESA1 partition='day' does not support mode='replace' yet"
        )

    output = None
    for index, chunk_time in enumerate(_daily_time_ranges(pipeline.time)):
        data = instrument.load(chunk_time, download="never")
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
            ),
        )
    if output is None:
        raise ValueError("Pipeline time range did not produce any daily shard")
    return output


def _update_pipeline_dataset_provenance(
    output,
    pipeline: Pipeline,
    *,
    variable: str,
    mode: str,
    run_id: str,
) -> None:
    manifest = output.manifest()
    manifest["provenance"] = _pipeline_dataset_provenance(
        pipeline,
        variable=variable,
        mode=mode,
        run_id=run_id,
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


def _stream_pipeline_shards(instrument: PaceInstrument, pipeline: Pipeline):
    import polars as pl

    variable = _pipeline_variable(pipeline)
    dataset_id = pipeline.output_dataset or f"kaguya.esa1.{variable}"
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


def _complete_pipeline_output(store: Store, pipeline: Pipeline):
    try:
        output = store.dataset(str(pipeline.output_dataset), layer=str(pipeline.output_layer))
    except DatasetNotFoundError:
        return None
    if not _catalog_is_complete(output):
        return None
    if not _record_covers_time(output, pipeline):
        return None
    return output


def _failed_pipeline_output(store: Store, pipeline: Pipeline):
    try:
        output = store.dataset(str(pipeline.output_dataset), layer=str(pipeline.output_layer))
    except DatasetNotFoundError:
        return None
    if not _record_covers_time(output, pipeline):
        return None
    return output


def _catalog_is_complete(output) -> bool:
    shards = output.shards()
    if not shards:
        return False
    return all(str(shard.get("status") or "") == "complete" for shard in shards)


def _failed_shard_count(output) -> int:
    return len(output.failed_shards())


def _replay_failed_pipeline_shards(
    instrument: PaceInstrument,
    output,
    *,
    variable: str,
) -> int:
    replayed = 0
    for shard in output.failed_shards():
        shard_time = _shard_time_range(shard)
        data = instrument.load(shard_time, download="never")
        _ensure_pipeline_input_files(data, instrument, shard_time)
        output.replace_shard(
            str(shard["path"]),
            frame=data.to_polars(variable),
            time_coverage=shard_time,
        )
        replayed += 1
    return replayed


def _ensure_pipeline_input_files(
    data: KaguyaESA1Data,
    instrument: PaceInstrument,
    time: TimeRange,
) -> None:
    if data.files:
        return
    expected = ", ".join(instrument.remote_files_for_period(time))
    raise FileNotFoundError(
        f"No local KAGUYA ESA1 raw files found for {time.start_iso} .. {time.stop_iso}. "
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


def _record_covers_time(output, pipeline: Pipeline) -> bool:
    coverage = output.manifest().get("time_coverage") or {}
    start = str(coverage.get("start") or "")
    stop = str(coverage.get("stop") or "")
    return start <= pipeline.time.start_iso and stop >= pipeline.time.stop_iso


def _write_pipeline_log(
    output,
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
    errors: tuple[dict[str, str], ...] = (),
) -> Path:
    shards = [_jsonable(row) for row in output.catalog().iter_rows(named=True)]
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
    path = output.root / "logs" / f"{run_id}.json"
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


def _read_guide(name: str, *, title: str, language: str = "en") -> GuidePage:
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
                raise NotImplementedError("KAGUYA ESA1 pipeline run expects one selected variable")
            return str(names[0])
    if pipeline.output_dataset:
        return pipeline.output_dataset.split(".")[-1]
    return "counts"


def _pipeline_source_layer(pipeline: Pipeline) -> str:
    if any(stage.name == "from_normalized" for stage in pipeline.stages):
        return "normalized"
    raise ValueError("Pipeline.scan() requires from_normalized() or write(..., layer=...)")
