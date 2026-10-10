from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl
import pytest

import sopran as spn
from sopran.core.pipeline import (
    Pipeline,
    PipelineBackend,
    PipelinePlan,
    PipelineResult,
    PipelineStage,
)


def test_pipeline_stream_partitions_scanned_rows_by_day() -> None:
    class ScanContext(PipelineBackend):
        def scan_pipeline(self, pipeline: Pipeline):
            return pl.DataFrame(
                {
                    "time": [
                        "2008-02-01T00:00:00Z",
                        "2008-02-01T00:00:10Z",
                        "2008-02-02T00:00:00Z",
                    ],
                    "counts": [1, 2, 3],
                }
            ).lazy()

    pipe = Pipeline(
        source="test.source",
        time=spn.period("2008-02-01", "2008-02-03"),
        backend=ScanContext(),
    )

    chunks = list(pipe.stream(partition="day"))

    assert [chunk.select("counts").to_series().to_list() for chunk in chunks] == [
        [1, 2],
        [3],
    ]


def test_pipeline_stream_delegates_to_backend_when_available() -> None:
    class StreamContext(PipelineBackend):
        def stream_pipeline(self, pipeline: Pipeline, *, partition):
            yield {"source": pipeline.source, "partition": partition}

    pipe = Pipeline(
        source="test.source",
        time=spn.day("2008-02-01"),
        backend=StreamContext(),
    )

    assert list(pipe.stream(partition="orbit")) == [
        {"source": "test.source", "partition": "orbit"}
    ]


def test_pipeline_run_forwards_on_error_policy_to_backend() -> None:
    class RunContext(PipelineBackend):
        def run_pipeline(self, pipeline: Pipeline, *, on_error, **kwargs):
            return {"source": pipeline.source, "on_error": on_error, "kwargs": kwargs}

    pipe = Pipeline(
        source="test.source",
        time=spn.day("2008-02-01"),
        backend=RunContext(),
    )

    result = pipe.run(on_error="continue")

    assert result["source"] == "test.source"
    assert result["on_error"] == "continue"
    assert result["kwargs"]["mode"] == "create"


def test_pipeline_run_forwards_download_policy_to_backend() -> None:
    class RunContext(PipelineBackend):
        def run_pipeline(self, pipeline: Pipeline, *, download, **kwargs):
            return {"source": pipeline.source, "download": download, "kwargs": kwargs}

    pipe = Pipeline(
        source="test.source",
        time=spn.day("2008-02-01"),
        backend=RunContext(),
    )

    result = pipe.run(download="always")

    assert result["source"] == "test.source"
    assert result["download"] == "always"
    assert result["kwargs"]["mode"] == "create"


def test_pipeline_without_backend_reports_how_to_build_one() -> None:
    pipe = Pipeline(source="test.source", time=spn.day("2008-02-01"))

    with pytest.raises(spn.PipelineError, match="endpoint.pipeline"):
        pipe.collect()
    with pytest.raises(spn.PipelineError, match="no execution backend"):
        pipe.run()


def test_pipeline_run_validates_on_error_policy() -> None:
    pipe = Pipeline(source="test.source", time=spn.day("2008-02-01"))

    with pytest.raises(ValueError, match="on_error"):
        pipe.run(on_error="skip")


def test_pipeline_run_validates_download_policy() -> None:
    pipe = Pipeline(source="test.source", time=spn.day("2008-02-01"))

    with pytest.raises(ValueError, match="download"):
        pipe.run(download="refresh")  # type: ignore[arg-type]


def test_pipeline_write_records_partition_policy() -> None:
    pipe = Pipeline(
        source="test.source",
        time=spn.day("2008-02-01"),
    ).write("test.dataset", layer="normalized", partition="day")

    assert pipe.stages[-1].parameters == {
        "dataset": "test.dataset",
        "layer": "normalized",
        "partition": "day",
    }


@dataclass(frozen=True)
class _OutputWithManifest:
    root: Path
    manifest_path: Path

    def manifest(self) -> dict[str, object]:
        return {
            "dataset_id": "kaguya.esa1.counts",
            "layer": "normalized",
            "status": "complete",
        }


@dataclass(frozen=True)
class _OutputWithMetadata:
    metadata_path: Path
    metadata: dict[str, object]
    artifacts: tuple[spn.PlotArtifact, ...] = ()


def test_pipeline_result_to_dict_summarizes_outputs(tmp_path) -> None:
    plan = PipelinePlan(
        source="kaguya.esa1",
        time=spn.day("2008-01-01"),
        stages=(
            PipelineStage("decode", {}),
            PipelineStage("write", {"dataset": "kaguya.esa1.counts"}),
        ),
        output_dataset="kaguya.esa1.counts",
        output_layer="normalized",
    )
    result = PipelineResult(
        plan=plan,
        status="complete",
        message="Wrote kaguya.esa1.counts",
        run_id="run_20080101T000000000000Z_deadbeef",
        log_path=tmp_path / "logs" / "run.json",
        outputs=(
            _OutputWithManifest(
                root=tmp_path / "normalized" / "kaguya.esa1.counts",
                manifest_path=tmp_path
                / "normalized"
                / "kaguya.esa1.counts"
                / "dataset.json",
            ),
            _OutputWithMetadata(
                metadata_path=tmp_path / "preview" / "counts.json",
                metadata={"dataset_id": "kaguya.esa1.counts", "items": ["counts"]},
                artifacts=(
                    spn.PlotArtifact(
                        path=tmp_path / "preview" / "counts.png",
                        format="png",
                    ),
                    spn.PlotArtifact(
                        path=tmp_path / "preview" / "counts.html",
                        format="html",
                    ),
                ),
            ),
        ),
    )

    payload = result.to_dict()

    assert payload["outputs"] == [
        {
            "type": "_OutputWithManifest",
            "root": (tmp_path / "normalized" / "kaguya.esa1.counts").as_posix(),
            "manifest_path": (
                tmp_path / "normalized" / "kaguya.esa1.counts" / "dataset.json"
            ).as_posix(),
            "manifest": {
                "dataset_id": "kaguya.esa1.counts",
                "layer": "normalized",
                "status": "complete",
            },
        },
        {
            "type": "_OutputWithMetadata",
            "metadata_path": (tmp_path / "preview" / "counts.json").as_posix(),
            "artifacts": [
                {
                    "path": (tmp_path / "preview" / "counts.png").as_posix(),
                    "format": "png",
                },
                {
                    "path": (tmp_path / "preview" / "counts.html").as_posix(),
                    "format": "html",
                },
            ],
            "metadata": {
                "dataset_id": "kaguya.esa1.counts",
                "items": ["counts"],
            },
        },
    ]


def test_endpoint_pipelines_attach_their_instrument_backend(tmp_path) -> None:
    from sopran.missions.kaguya.pipeline import PacePipelineBackend

    kg = spn.Kaguya(store=spn.Store(tmp_path / "store"), download="never")
    time = spn.day("2008-02-01")

    assert isinstance(kg.esa1.counts.pipeline(time).backend, PacePipelineBackend)
    assert isinstance(kg.esa1.pipeline(time).backend, PacePipelineBackend)
    lrs = kg.lrs.wfc_ey_power_spectral_density.pipeline(time)
    assert lrs.backend is None
    with pytest.raises(spn.PipelineError, match="no execution backend"):
        lrs.run()
