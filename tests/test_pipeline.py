from __future__ import annotations

import polars as pl

import sopran as spn
from sopran.core.pipeline import Pipeline


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
