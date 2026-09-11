from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from sopran.core.coverage import coverage_bins, validate_coverage_freq
from sopran.core.errors import DatasetNotFoundError
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

_EVENT_STRING_COLUMNS = (
    "mission",
    "instrument",
    "phenomenon",
    "detector",
    "detector_version",
    "event_id",
    "interval_id",
    "detector_run_id",
    "detector_config_id",
    "feature_spec_id",
    "feature_spec_hash",
    "source_dataset",
    "component",
    "review_status",
    "quality_flags",
)

_NON_NULL_ID_COLUMNS = (
    "event_id",
    "interval_id",
    "detector_run_id",
    "detector_config_id",
    "feature_spec_id",
    "feature_spec_hash",
    "source_dataset",
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
        frame = _normalize_event_frame(frame)
        _validate_event_frame(frame)
        frame = frame.drop("_time_start_utc", "_time_stop_utc")
        self.create()
        existing = self._existing_record() if append else None
        if existing is not None:
            _validate_append_schema(existing, frame, dataset_id=self.dataset_id)
            if "event_id" in frame.columns:
                frame = _without_existing_event_ids(
                    existing,
                    frame,
                    dataset_id=self.dataset_id,
                )
                if frame.height == 0:
                    return existing
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

    def _existing_record(self) -> Any | None:
        try:
            return self.store.dataset(self.dataset_id, layer="databases")
        except DatasetNotFoundError:
            return None

    def scan(self) -> Any:
        return self.store.scan_dataset(self.dataset_id, layer="databases")

    def counts(
        self,
        *,
        freq: str,
        by: tuple[str, ...] = (),
        time: TimeRange | None = None,
    ) -> Any:
        """Count event onsets, grouped into UTC calendar bins."""

        import polars as pl

        validate_coverage_freq(freq)
        frame = self.scan().collect()
        if time is not None:
            # Event rates count onsets.  Filtering and calendar-bin assignment
            # therefore both use the inclusive event start, not interval overlap.
            frame = _filter_polars_time(frame, time, column="time_start")
        for column in by:
            if column not in frame.columns:
                raise ValueError(f"event catalog has no column for grouping: {column}")
        if frame.height == 0:
            return pl.DataFrame(schema=_event_counts_schema(by, frame.schema))

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
            return pl.DataFrame(schema=_event_counts_schema(by, frame.schema))
        grouped = (
            pl.DataFrame(rows)
            .group_by(["bin_start", "bin_stop", "freq", *by])
            .agg(pl.len().alias("event_count"))
            .with_columns(pl.col("event_count").cast(pl.UInt64))
            .sort(["bin_start", *by])
        )
        return grouped

    def rates(
        self,
        exposure: Any,
        *,
        freq: str,
        by: tuple[str, ...] = ("phenomenon",),
        time: TimeRange | None = None,
        exposure_column: str = "exposure_seconds",
        scale: float = 3600.0,
    ) -> Any:
        """Join event counts to detector-specific exposure bins.

        ``exposure`` is a long table with ``bin_start``, ``bin_stop``, the
        requested grouping columns, and an exposure duration.  Exposure rows are
        the left side of the join so bins with zero detected events are retained.
        Events are counted by ``time_start``. When ``time`` is supplied it must
        cover complete calendar bins, because pre-aggregated exposure cannot be
        clipped safely to a partial bin.
        """

        import polars as pl

        validate_coverage_freq(freq)
        if not np.isfinite(scale) or scale <= 0:
            raise ValueError("scale must be a finite positive number")
        if isinstance(exposure, pl.LazyFrame):
            exposure = exposure.collect()
        if not isinstance(exposure, pl.DataFrame):
            raise TypeError("exposure must be a polars DataFrame or LazyFrame")
        required = {"bin_start", "bin_stop", exposure_column, *by}
        missing = sorted(required.difference(exposure.columns))
        if missing:
            raise ValueError("exposure frame is missing columns: " + ", ".join(missing))
        exposure = _normalize_interval_columns(exposure, "bin_start", "bin_stop")
        exposure = exposure.with_columns(
            pl.col(exposure_column).cast(pl.Float64, strict=True)
        )
        _validate_exposure_frame(exposure, exposure_column)
        if time is not None:
            _validate_complete_rate_bins(time, freq=freq)
            exposure = _filter_interval_overlap(
                exposure,
                time,
                start_column="bin_start",
                stop_column="bin_stop",
            )
        events = self.scan().collect()
        if time is not None:
            events = _filter_polars_time(events, time, column="time_start")
        events = _scope_events_to_exposure(events, exposure, by=by)
        _guard_detector_run_mixing(events, exposure, by=by)

        keys = ["bin_start", "bin_stop", "freq", *by]
        aggregations = [pl.col(exposure_column).sum()]
        if "eligible_window_count" in exposure.columns:
            aggregations.append(pl.col("eligible_window_count").cast(pl.UInt64).sum())
        binned = (
            exposure.with_columns(pl.lit(freq).alias("freq"))
            .group_by(keys)
            .agg(aggregations)
        )
        counts = self.counts(freq=freq, by=by, time=time)
        result = (
            binned.join(counts, on=keys, how="left")
            .with_columns(pl.col("event_count").fill_null(0).cast(pl.UInt64))
            .with_columns(
                pl.when(pl.col(exposure_column) > 0)
                .then(pl.col("event_count") * float(scale) / pl.col(exposure_column))
                .otherwise(None)
                .alias(f"events_per_{_rate_scale_label(scale)}")
            )
            .sort(["bin_start", *by])
        )
        return result


def event_catalog_schema(name: str) -> InstrumentSchema:
    return InstrumentSchema(
        mission=name,
        instrument="event_catalog",
        variables=(
            VariableSchema(
                name="time_start",
                dims=("event",),
                dtype="str",
                description="Inclusive UTC start of the half-open event interval.",
            ),
            VariableSchema(
                name="time_stop",
                dims=("event",),
                dtype="str",
                description="Exclusive UTC stop of the half-open event interval.",
            ),
            VariableSchema(name="mission", dims=("event",), dtype="str"),
            VariableSchema(name="instrument", dims=("event",), dtype="str"),
            VariableSchema(name="phenomenon", dims=("event",), dtype="str"),
            VariableSchema(
                name="confidence",
                dims=("event",),
                dtype="float64",
                units="1",
                description="Calibrated or explicitly heuristic confidence in [0, 1].",
            ),
            VariableSchema(name="detector", dims=("event",), dtype="str"),
            VariableSchema(name="detector_version", dims=("event",), dtype="str"),
            VariableSchema(
                name="event_id",
                dims=("event",),
                dtype="str",
                description="Stable identifier for one phenomenon-labelled event row.",
            ),
            VariableSchema(
                name="interval_id",
                dims=("event",),
                dtype="str",
                description="Stable interval identifier shared by simultaneous labels.",
            ),
            VariableSchema(
                name="detector_run_id",
                dims=("event",),
                dtype="str",
                description="Identifier scoping one reproducible detector execution.",
            ),
            VariableSchema(
                name="detector_config_id",
                dims=("event",),
                dtype="str",
                description="Hash of the canonical detector configuration.",
            ),
            VariableSchema(
                name="feature_spec_id",
                dims=("event",),
                dtype="str",
                description="Hash identifying the window-feature definition.",
            ),
            VariableSchema(
                name="source_dataset",
                dims=("event",),
                dtype="str",
                description="Dataset identifier from which detector features were derived.",
            ),
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

    import polars as pl

    for column in _EVENT_COLUMNS:
        if frame.select(pl.col(column).is_null().any()).item():
            raise ValueError(f"event catalog column contains null values: {column}")
    for column in (
        "mission",
        "instrument",
        "phenomenon",
        "detector",
        "detector_version",
        *[name for name in _NON_NULL_ID_COLUMNS if name in frame.columns],
    ):
        if frame.select(pl.col(column).is_null().any()).item():
            raise ValueError(f"event catalog column contains null values: {column}")
        if frame.select((pl.col(column).str.strip_chars() == "").any()).item():
            raise ValueError(f"event catalog column contains blank values: {column}")
    invalid_interval = frame.select(
        (pl.col("_time_stop_utc") <= pl.col("_time_start_utc")).any()
    ).item()
    if invalid_interval:
        raise ValueError("event catalog intervals must satisfy time_stop > time_start")
    invalid_confidence = frame.select(
        (
            ~pl.col("confidence").is_finite()
            | (pl.col("confidence") < 0)
            | (pl.col("confidence") > 1)
        ).any()
    ).item()
    if invalid_confidence:
        raise ValueError("event catalog confidence must be finite and in [0, 1]")
    if "event_id" in frame.columns and frame["event_id"].n_unique() != frame.height:
        raise ValueError("event_id values must be unique within an event frame")


def _event_counts_schema(
    by: tuple[str, ...],
    source_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import polars as pl

    schema: dict[str, Any] = {
        "bin_start": pl.Utf8,
        "bin_stop": pl.Utf8,
        "freq": pl.Utf8,
    }
    for column in by:
        schema[column] = (source_schema or {}).get(column, pl.Utf8)
    schema["event_count"] = pl.UInt64
    return schema


def _normalize_event_frame(frame: Any) -> Any:
    import polars as pl

    if isinstance(frame, pl.LazyFrame):
        frame = frame.collect()
    if not isinstance(frame, pl.DataFrame):
        raise TypeError("event catalog frame must be a polars DataFrame or LazyFrame")
    columns = set(frame.columns)
    missing = [column for column in _EVENT_COLUMNS if column not in columns]
    if missing:
        raise ValueError("event catalog frame is missing columns: " + ", ".join(missing))
    normalized = _normalize_interval_columns(frame, "time_start", "time_stop")
    string_columns = [column for column in _EVENT_STRING_COLUMNS if column in normalized.columns]
    normalized = normalized.with_columns(
        pl.col("confidence").cast(pl.Float64, strict=True),
        *(pl.col(column).cast(pl.Utf8, strict=True) for column in string_columns),
    )
    return normalized


def _normalize_interval_columns(frame: Any, start_column: str, stop_column: str) -> Any:
    import polars as pl

    try:
        normalized = frame.with_columns(
            pl.col(start_column)
            .cast(pl.Utf8)
            .str.to_datetime(time_zone="UTC", strict=True)
            .alias("_time_start_utc"),
            pl.col(stop_column)
            .cast(pl.Utf8)
            .str.to_datetime(time_zone="UTC", strict=True)
            .alias("_time_stop_utc"),
        )
    except Exception as exc:
        raise ValueError("event interval columns must contain parseable UTC timestamps") from exc
    if normalized.select(
        pl.any_horizontal(
            pl.col("_time_start_utc").is_null(),
            pl.col("_time_stop_utc").is_null(),
        ).any()
    ).item():
        raise ValueError("event interval columns must not contain null timestamps")
    return normalized.with_columns(
        pl.col("_time_start_utc")
        .dt.strftime("%Y-%m-%dT%H:%M:%S%.fZ")
        .alias(start_column),
        pl.col("_time_stop_utc")
        .dt.strftime("%Y-%m-%dT%H:%M:%S%.fZ")
        .alias(stop_column),
    )


def _filter_event_overlap(frame: Any, time: TimeRange) -> Any:
    normalized = _normalize_interval_columns(frame, "time_start", "time_stop")
    return _filter_interval_overlap(
        normalized,
        time,
        start_column="time_start",
        stop_column="time_stop",
    )


def _filter_interval_overlap(
    frame: Any,
    time: TimeRange,
    *,
    start_column: str,
    stop_column: str,
) -> Any:
    import polars as pl

    start = time.start
    stop = time.stop
    start_expr = (
        pl.col("_time_start_utc")
        if "_time_start_utc" in frame.columns
        else pl.col(start_column).cast(pl.Utf8).str.to_datetime(time_zone="UTC", strict=True)
    )
    stop_expr = (
        pl.col("_time_stop_utc")
        if "_time_stop_utc" in frame.columns
        else pl.col(stop_column).cast(pl.Utf8).str.to_datetime(time_zone="UTC", strict=True)
    )
    return frame.filter((start_expr < stop) & (stop_expr > start))


def _validate_append_schema(record: Any, frame: Any, *, dataset_id: str) -> None:
    existing_schema = record.scan(dataset_id=dataset_id).collect_schema()
    incoming_schema = frame.schema
    if list(existing_schema.items()) != list(incoming_schema.items()):
        raise ValueError(
            "event catalog append schema mismatch; migrate the existing catalog or "
            "write a new detector-run catalog before appending"
        )


def _without_existing_event_ids(record: Any, frame: Any, *, dataset_id: str) -> Any:
    import polars as pl

    incoming_ids = frame.get_column("event_id")
    existing = (
        record.scan(dataset_id=dataset_id)
        .filter(pl.col("event_id").is_in(incoming_ids.implode()))
        .collect()
    )
    if existing.height == 0:
        return frame
    if existing.get_column("event_id").n_unique() != existing.height:
        raise ValueError("existing event catalog contains duplicate event_id values")
    existing_rows = {str(row["event_id"]): row for row in existing.iter_rows(named=True)}
    for row in frame.iter_rows(named=True):
        event_id = str(row["event_id"])
        prior = existing_rows.get(event_id)
        if prior is not None and not _event_rows_equal(prior, row):
            raise ValueError(f"event_id conflicts with an existing event payload: {event_id}")
    return frame.filter(~pl.col("event_id").is_in(existing.get_column("event_id").implode()))


def _event_rows_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.keys() != right.keys():
        return False
    for key in left:
        left_value = left[key]
        right_value = right[key]
        if (
            isinstance(left_value, float)
            and isinstance(right_value, float)
            and np.isnan(left_value)
            and np.isnan(right_value)
        ):
            continue
        if left_value != right_value:
            return False
    return True


def _validate_exposure_frame(frame: Any, exposure_column: str) -> None:
    import polars as pl

    if frame.select(pl.col(exposure_column).is_null().any()).item():
        raise ValueError(f"{exposure_column} must not contain null values")
    if frame.select((~pl.col(exposure_column).is_finite()).any()).item():
        raise ValueError(f"{exposure_column} must contain only finite values")
    if frame.select((pl.col(exposure_column) < 0).any()).item():
        raise ValueError(f"{exposure_column} must be non-negative")
    if frame.select((pl.col("_time_stop_utc") <= pl.col("_time_start_utc")).any()).item():
        raise ValueError("exposure bins must satisfy bin_stop > bin_start")


def _validate_complete_rate_bins(time: TimeRange, *, freq: str) -> None:
    bins = coverage_bins(time, freq=freq)
    if not bins or bins[0].start != time.start or bins[-1].stop != time.stop:
        raise ValueError("rates time range must align to complete calendar bins")


def _scope_events_to_exposure(events: Any, exposure: Any, *, by: tuple[str, ...]) -> Any:
    if not by or events.height == 0 or exposure.height == 0:
        return events
    return events.join(exposure.select(by).unique(), on=list(by), how="semi")


def _guard_detector_run_mixing(events: Any, exposure: Any, *, by: tuple[str, ...]) -> None:
    import polars as pl

    event_has_run = "detector_run_id" in events.columns
    exposure_has_run = "detector_run_id" in exposure.columns
    if event_has_run != exposure_has_run and events.height and exposure.height:
        raise ValueError(
            "run-scoped rates require detector_run_id in both events and exposure"
        )
    if not event_has_run:
        return
    for frame in (events, exposure):
        if frame.select(pl.col("detector_run_id").is_null().any()).item():
            raise ValueError("detector_run_id must not contain null values for rates")
    if "detector_run_id" in by:
        return
    if events.height == 0 or exposure.height == 0:
        return
    event_runs = set(str(value) for value in events["detector_run_id"].unique())
    exposure_runs = set(str(value) for value in exposure["detector_run_id"].unique())
    if len(event_runs) > 1 or len(exposure_runs) > 1 or event_runs != exposure_runs:
        raise ValueError(
            "rates cannot mix detector runs; include detector_run_id in 'by' or select one run"
        )


def _rate_scale_label(scale: float) -> str:
    if scale == 3600.0:
        return "exposure_hour"
    return f"{scale:g}_exposure_seconds".replace(".", "p")


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
