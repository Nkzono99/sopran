from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl
import pytest

import sopran as spn
from sopran.core.pipeline import Pipeline, PipelinePlan, PipelineResult, PipelineStage


def test_pipeline_stream_partitions_scanned_rows_by_day() -> None:
    class ScanContext:
        def _scan_pipeline(self, pipeline: Pipeline):
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
        context=ScanContext(),
    )

    chunks = list(pipe.stream(partition="day"))

    assert [chunk.select("counts").to_series().to_list() for chunk in chunks] == [
        [1, 2],
        [3],
    ]


def test_pipeline_stream_delegates_to_backend_when_available() -> None:
    class StreamContext:
        def _stream_pipeline(self, pipeline: Pipeline, *, partition: str):
            yield {"source": pipeline.source, "partition": partition}

    pipe = Pipeline(
        source="test.source",
        time=spn.day("2008-02-01"),
        context=StreamContext(),
    )

    assert list(pipe.stream(partition="orbit")) == [
        {"source": "test.source", "partition": "orbit"}
    ]


def test_pipeline_run_forwards_on_error_policy_to_backend() -> None:
    class RunContext:
        def _run_pipeline(self, pipeline: Pipeline, *, on_error: str, **kwargs):
            return {"source": pipeline.source, "on_error": on_error, "kwargs": kwargs}

    pipe = Pipeline(
        source="test.source",
        time=spn.day("2008-02-01"),
        context=RunContext(),
    )

    result = pipe.run(on_error="continue")

    assert result["source"] == "test.source"
    assert result["on_error"] == "continue"
    assert result["kwargs"]["mode"] == "create"


def test_pipeline_run_validates_on_error_policy() -> None:
    pipe = Pipeline(source="test.source", time=spn.day("2008-02-01"))

    with pytest.raises(ValueError, match="on_error"):
        pipe.run(on_error="skip")


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
            ),
        ),
    )

    payload = result.to_dict()

    assert payload["outputs"] == [
        {
            "type": "_OutputWithManifest",
            "root": str(tmp_path / "normalized" / "kaguya.esa1.counts"),
            "manifest_path": str(
                tmp_path / "normalized" / "kaguya.esa1.counts" / "dataset.json"
            ),
            "manifest": {
                "dataset_id": "kaguya.esa1.counts",
                "layer": "normalized",
                "status": "complete",
            },
        },
        {
            "type": "_OutputWithMetadata",
            "metadata_path": str(tmp_path / "preview" / "counts.json"),
            "metadata": {
                "dataset_id": "kaguya.esa1.counts",
                "items": ["counts"],
            },
        },
    ]
