"""Pipeline backend of KAGUYA PACE: decode, calibrate, day shards, logs and replay.

``PaceInstrument.pipeline(time)`` builds a :class:`~sopran.core.pipeline.Pipeline`
whose backend is :class:`PacePipelineBackend`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal, cast

from sopran.core import Store
from sopran.core.config import DownloadMode
from sopran.core.errors import DatasetNotFoundError
from sopran.core.pipeline import (
    Pipeline,
    PipelineBackend,
    PipelineResult,
    PipelineStreamPartition,
)
from sopran.core.time import TimeRange, _filter_polars_time, day, period
from sopran.missions.kaguya.data import KaguyaPaceData
from sopran.missions.kaguya.mission import (
    _coerce_download_mode,
    _coverage_contains_time_range,
    _filter_frame_by_time,
)
from sopran.missions.kaguya.pace import PaceCalibration

if TYPE_CHECKING:
    from sopran.missions.kaguya.mission import PaceInstrument


class PacePipelineBackend(PipelineBackend):
    """Runs ``kg.esa1/esa2/ima/iea`` pipelines for one PACE sensor."""

    def __init__(self, instrument: PaceInstrument) -> None:
        self.instrument = instrument

    def scan_pipeline(self, pipeline: Pipeline) -> Any:
        variable = _pipeline_variable(pipeline)
        sensor = self.instrument.sensor.lower()
        dataset_id = pipeline.output_dataset or f"kaguya.{sensor}.{variable}"
        layer = pipeline.output_layer or _pipeline_source_layer(pipeline)
        lazy = self.instrument.mission.store.scan_dataset(dataset_id, layer=layer)
        return _filter_lazy_by_time(lazy, pipeline.time)

    def stream_pipeline(
        self, pipeline: Pipeline, *, partition: PipelineStreamPartition
    ) -> Iterator[Any]:
        if partition == "shard":
            return cast(Iterator[Any], _stream_pipeline_shards(self.instrument, pipeline))
        return super().stream_pipeline(pipeline, partition=partition)

    def run_pipeline(
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
        download = (
            self.instrument.mission.download
            if download is None
            else _coerce_download_mode(download)
        )

        started = perf_counter()
        started_at = _utc_now_iso()
        if resume:
            existing = _complete_pipeline_output(self.instrument.mission.store, pipeline)
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
            existing = _failed_pipeline_output(self.instrument.mission.store, pipeline)
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
                self.instrument,
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
                    self.instrument,
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
                    self.instrument,
                    pipeline,
                    variable=variable,
                    mode=mode,
                    run_id=run_id,
                    download=download,
                    calibration=calibration,
                )
            else:
                loaded = _load_pace_pipeline_data(
                    self.instrument,
                    pipeline.time,
                    download=download,
                    calibration=calibration,
                )
                _ensure_pipeline_input_files(loaded, self.instrument, pipeline.time)
                data = loaded
                output = data.write_parquet(
                    self.instrument.mission.store,
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
                self.instrument,
                self.instrument.mission.store,
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
                    self.instrument,
                    pipeline.time,
                    download=download,
                    calibration=calibration,
                )
                _ensure_pipeline_input_files(data, self.instrument, pipeline.time)
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


def _filter_lazy_by_time(lazy: Any, time: TimeRange) -> Any:
    return _filter_polars_time(lazy, time)


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
