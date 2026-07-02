from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from sopran.core.time import TimeRange

PipelineRunMode = Literal["create", "append", "replace"]
PipelineStreamPartition = Literal["all", "day", "shard", "orbit"]


@dataclass(frozen=True)
class PipelineStage:
    name: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class PipelinePlan:
    source: str
    time: TimeRange
    stages: tuple[PipelineStage, ...]
    output_dataset: str | None = None
    output_layer: str | None = None

    @property
    def stage_names(self) -> tuple[str, ...]:
        return tuple(stage.name for stage in self.stages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "start": self.time.start_iso,
            "stop": self.time.stop_iso,
            "output_dataset": self.output_dataset,
            "output_layer": self.output_layer,
            "stages": [
                {
                    "name": stage.name,
                    "parameters": _jsonable(stage.parameters),
                }
                for stage in self.stages
            ],
        }

    def to_text(self) -> str:
        lines = [
            "SOPRAN pipeline plan",
            f"source: {self.source}",
            f"time: {self.time.start_iso} .. {self.time.stop_iso}",
            f"output: {_format_output(self.output_dataset, self.output_layer)}",
            "stages:",
        ]
        lines.extend(
            f"- {stage.name}{_format_parameters(stage.parameters)}"
            for stage in self.stages
        )
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.to_text()


@dataclass(frozen=True)
class PipelineResult:
    plan: PipelinePlan
    status: str
    message: str
    outputs: tuple[Any, ...] = ()
    run_id: str = ""
    log_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "run_id": self.run_id,
            "log_path": str(self.log_path) if self.log_path is not None else None,
            "plan": self.plan.to_dict(),
        }

    def to_text(self) -> str:
        lines = [
            "SOPRAN pipeline result",
            f"status: {self.status}",
            f"run_id: {self.run_id}",
            f"message: {self.message}",
        ]
        if self.log_path is not None:
            lines.append(f"log: {self.log_path}")
        lines.extend(("", self.plan.to_text()))
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.to_text()


@dataclass(frozen=True)
class Pipeline:
    source: str
    time: TimeRange
    stages: tuple[PipelineStage, ...] = ()
    output_dataset: str | None = None
    output_layer: str | None = None
    context: Any = None

    def download(self) -> Pipeline:
        return self._with_stage("download")

    def decode(self) -> Pipeline:
        return self._with_stage("decode")

    def normalize(self) -> Pipeline:
        return self._with_stage("normalize")

    def from_normalized(self) -> Pipeline:
        return self._with_stage("from_normalized")

    def select_variables(self, *names: str) -> Pipeline:
        return self._with_stage("select_variables", names=names)

    def derive(self, name: str, **parameters: Any) -> Pipeline:
        return self._with_stage("derive", name=name, **parameters)

    def quicklook(
        self,
        name: str,
        *,
        formats: tuple[str, ...] = ("png",),
        root: str | None = None,
        y: str = "energy",
        backend: str = "matplotlib",
    ) -> Pipeline:
        parameters = {
            "quicklook_name": name,
            "formats": tuple(formats),
            "y": y,
            "backend": backend,
        }
        if root is not None:
            parameters["root"] = root
        return self._with_stage("quicklook", **parameters)

    def write(self, dataset: str | Any, *, layer: str | None = None) -> Pipeline:
        dataset_id, output_layer = _write_target(dataset, layer)
        return Pipeline(
            source=self.source,
            time=self.time,
            stages=(
                *self.stages,
                PipelineStage("write", {"dataset": dataset_id, "layer": output_layer}),
            ),
            output_dataset=dataset_id,
            output_layer=output_layer,
            context=self.context,
        )

    def plan(self) -> PipelinePlan:
        return PipelinePlan(
            source=self.source,
            time=self.time,
            stages=self.stages,
            output_dataset=self.output_dataset,
            output_layer=self.output_layer,
        )

    def scan(self):
        scanner = getattr(self.context, "_scan_pipeline", None)
        if scanner is not None:
            return scanner(self)
        raise NotImplementedError("Pipeline.scan() backend is not implemented yet")

    def collect(self):
        return self.scan().collect()

    def stream(self, *, partition: PipelineStreamPartition = "all"):
        streamer = getattr(self.context, "_stream_pipeline", None)
        if streamer is not None:
            yield from streamer(self, partition=partition)
            return

        if partition == "all":
            yield self.collect()
            return
        if partition == "day":
            yield from _stream_frame_by_day(self.collect())
            return
        raise NotImplementedError(
            "Pipeline.stream() partition='shard' and partition='orbit' require a backend"
        )

    def run(
        self,
        *,
        dry_run: bool = False,
        mode: PipelineRunMode = "create",
        resume: bool = False,
    ) -> PipelineResult:
        if mode not in ("create", "append", "replace"):
            raise ValueError("mode must be 'create', 'append', or 'replace'")
        if resume and mode != "create":
            raise ValueError("resume=True requires mode='create'")
        plan = self.plan()
        run_id = _new_pipeline_run_id()
        if dry_run:
            return PipelineResult(
                plan=plan,
                status="planned",
                message="Dry run only; no pipeline stages were executed.",
                run_id=run_id,
            )
        runner = getattr(self.context, "_run_pipeline", None)
        if runner is not None:
            return runner(self, mode=mode, run_id=run_id, resume=resume)
        raise NotImplementedError("Pipeline.run() execution backend is not implemented yet")

    def _with_stage(self, name: str, **parameters: Any) -> Pipeline:
        return Pipeline(
            source=self.source,
            time=self.time,
            stages=(*self.stages, PipelineStage(name, parameters)),
            output_dataset=self.output_dataset,
            output_layer=self.output_layer,
            context=self.context,
        )


def _write_target(dataset: str | Any, layer: str | None) -> tuple[str, str]:
    if isinstance(dataset, str):
        if layer is None:
            raise TypeError("Pipeline.write() requires layer=... for string dataset IDs")
        return dataset, layer

    dataset_id = getattr(dataset, "dataset_id", None)
    output_layer = layer or getattr(dataset, "layer", None)
    if dataset_id is None or output_layer is None:
        raise TypeError("Pipeline.write() expects a dataset ID string or ProductRef")
    return str(dataset_id), str(output_layer)


def _new_pipeline_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"run_{stamp}_{uuid4().hex[:8]}"


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _format_output(dataset: str | None, layer: str | None) -> str:
    if dataset is None:
        return "(not set)"
    if layer is None:
        return dataset
    return f"{dataset} ({layer})"


def _format_parameters(parameters: dict[str, Any]) -> str:
    if not parameters:
        return ""
    normalized = _jsonable(parameters)
    if not isinstance(normalized, dict):
        return f" {normalized!r}"
    return " " + " ".join(f"{key}={value!r}" for key, value in normalized.items())


def _stream_frame_by_day(frame: Any):
    import polars as pl

    if "time" not in frame.columns:
        raise ValueError("Pipeline.stream(partition='day') requires a 'time' column")
    day_column = "__sopran_stream_day"
    indexed = frame.with_columns(
        pl.col("time").cast(pl.Utf8).str.slice(0, 10).alias(day_column)
    )
    days = indexed.select(day_column).unique(maintain_order=True).to_series().to_list()
    for day in days:
        yield indexed.filter(pl.col(day_column) == day).drop(day_column)
