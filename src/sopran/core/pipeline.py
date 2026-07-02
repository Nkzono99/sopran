from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sopran.core.time import TimeRange

PipelineRunMode = Literal["create", "append", "replace"]


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


@dataclass(frozen=True)
class PipelineResult:
    plan: PipelinePlan
    status: str
    message: str
    outputs: tuple[Any, ...] = ()


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

    def run(
        self,
        *,
        dry_run: bool = False,
        mode: PipelineRunMode = "create",
    ) -> PipelineResult:
        if mode not in ("create", "append", "replace"):
            raise ValueError("mode must be 'create', 'append', or 'replace'")
        plan = self.plan()
        if dry_run:
            return PipelineResult(
                plan=plan,
                status="planned",
                message="Dry run only; no pipeline stages were executed.",
            )
        runner = getattr(self.context, "_run_pipeline", None)
        if runner is not None:
            return runner(self, mode=mode)
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
