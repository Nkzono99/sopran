from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sopran.core.coverage import coverage_bins, validate_coverage_freq
from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.core.time import TimeRange, _filter_polars_time

_EVENT_COLUMNS = (
    "time_start",
    "time_stop",
    "mission",
    "instrument",
    "phenomenon",
    "confidence",
    "detector",
    "detector_version",
)


@dataclass(frozen=True)
class EventCatalog:
    name: str
    root: Path
    store: Any

    @property
    def dataset_id(self) -> str:
        return f"{self.name}.events"

    def create(self) -> None:
        self.store.database(self.name, create=True)

    def schema(self) -> InstrumentSchema:
        return event_catalog_schema(self.name)

    def write_events(
        self,
        frame: Any,
        *,
        time_coverage: TimeRange,
        overwrite: bool = False,
        append: bool = False,
        status: str = "candidate",
        description: str = "",
    ) -> Any:
        _validate_event_frame(frame)
        self.create()
        record = self.store.write_parquet_dataset(
            dataset_id=self.dataset_id,
            layer="databases",
            mission=self.name,
            instrument="event_catalog",
            product="event_table",
            schema=self.schema(),
            time_coverage=time_coverage,
            frame=frame,
            overwrite=overwrite,
            append=append,
            producer="sopran.events",
            status=status,
            parameters={
                "catalog": {
                    "type": "event_catalog",
                    "name": self.name,
                    "time_column": "time_start",
                },
            },
        )
        self.store.database(self.name, create=True).adopt_dataset(
            record,
            description=description or f"{self.name} event catalog",
        )
        return record

    def scan(self) -> Any:
        return self.store.scan_dataset(self.dataset_id, layer="databases")

    def counts(
        self,
        *,
        freq: str,
        by: tuple[str, ...] = (),
        time: TimeRange | None = None,
    ) -> Any:
        import polars as pl

        validate_coverage_freq(freq)
        frame = self.scan().collect()
        if time is not None:
            frame = _filter_polars_time(frame, time, column="time_start")
        for column in by:
            if column not in frame.columns:
                raise ValueError(f"event catalog has no column for grouping: {column}")
        if frame.height == 0:
            return pl.DataFrame(schema=_event_counts_schema(by))

        rows = []
        for row in frame.iter_rows(named=True):
            event_time = str(row["time_start"])
            # TimeRange is half-open and cannot have zero duration; use the bin helper via
            # an infinitesimal one-bin range around the parsed timestamp.
            event_bins = coverage_bins(_event_bin_range(event_time), freq=freq)
            if not event_bins:
                continue
            event_bin = event_bins[0]
            rows.append(
                {
                    "bin_start": event_bin.start_iso,
                    "bin_stop": event_bin.stop_iso,
                    "freq": freq,
                    **{column: row[column] for column in by},
                }
            )
        if not rows:
            return pl.DataFrame(schema=_event_counts_schema(by))
        grouped = (
            pl.DataFrame(rows)
            .group_by(["bin_start", "bin_stop", "freq", *by])
            .agg(pl.len().alias("event_count"))
            .sort(["bin_start", *by])
        )
        return grouped


def event_catalog_schema(name: str) -> InstrumentSchema:
    return InstrumentSchema(
        mission=name,
        instrument="event_catalog",
        variables=(
            VariableSchema(
                name="events",
                dims=("event",),
                description=(
                    "Curated or detector-produced event intervals with versioned "
                    "phenomenon criteria."
                ),
            ),
            VariableSchema(
                name="event_count",
                dims=("bin",),
                dtype="uint64",
                description="Number of event rows grouped into a calendar bin.",
            ),
        ),
    )


def _validate_event_frame(frame: Any) -> None:
    columns = set(str(column) for column in getattr(frame, "columns", ()))
    missing = [column for column in _EVENT_COLUMNS if column not in columns]
    if missing:
        raise ValueError("event catalog frame is missing columns: " + ", ".join(missing))


def _event_counts_schema(by: tuple[str, ...]) -> dict[str, Any]:
    import polars as pl

    schema: dict[str, Any] = {
        "bin_start": pl.Utf8,
        "bin_stop": pl.Utf8,
        "freq": pl.Utf8,
    }
    for column in by:
        schema[column] = pl.Utf8
    schema["event_count"] = pl.UInt32
    return schema


def _event_bin_range(value: str) -> TimeRange:
    from datetime import timedelta

    start = _parse_event_time(value)
    return TimeRange(start, start + timedelta(microseconds=1))


def _parse_event_time(value: str) -> Any:
    from datetime import UTC, datetime

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
