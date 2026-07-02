from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sopran.core.time import TimeRange


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


@dataclass(frozen=True)
class Pipeline:
    source: str
    time: TimeRange
    stages: tuple[PipelineStage, ...] = ()
    output_dataset: str | None = None
    output_layer: str | None = None

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

    def write(self, dataset: str, *, layer: str) -> Pipeline:
        return Pipeline(
            source=self.source,
            time=self.time,
            stages=(*self.stages, PipelineStage("write", {"dataset": dataset, "layer": layer})),
            output_dataset=dataset,
            output_layer=layer,
        )

    def plan(self) -> PipelinePlan:
        return PipelinePlan(
            source=self.source,
            time=self.time,
            stages=self.stages,
            output_dataset=self.output_dataset,
            output_layer=self.output_layer,
        )

    def run(self, *, dry_run: bool = False) -> PipelineResult:
        plan = self.plan()
        if dry_run:
            return PipelineResult(
                plan=plan,
                status="planned",
                message="Dry run only; no pipeline stages were executed.",
            )
        raise NotImplementedError("Pipeline.run() execution backend is not implemented yet")

    def _with_stage(self, name: str, **parameters: Any) -> Pipeline:
        return Pipeline(
            source=self.source,
            time=self.time,
            stages=(*self.stages, PipelineStage(name, parameters)),
            output_dataset=self.output_dataset,
            output_layer=self.output_layer,
        )
