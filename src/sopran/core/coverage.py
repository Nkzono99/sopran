from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sopran.core.errors import DatasetNotFoundError
from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.core.time import TimeRange

CoverageFreq = Literal["day", "month"]


@dataclass(frozen=True)
class CoverageBin:
    start: datetime
    stop: datetime

    @property
    def start_iso(self) -> str:
        return _format_utc(self.start)

    @property
    def stop_iso(self) -> str:
        return _format_utc(self.stop)


def coverage_dataset_id(source_dataset_id: str) -> str:
    return f"{source_dataset_id}.coverage"


def coverage_variant_id(freq: str) -> str:
    validate_coverage_freq(freq)
    return f"freq_{freq}"


def validate_coverage_freq(freq: str) -> None:
    if freq not in {"day", "month"}:
        raise ValueError("freq must be 'day' or 'month'")


def coverage_schema(*, mission: str, instrument: str) -> InstrumentSchema:
    return InstrumentSchema(
        mission=mission,
        instrument=instrument,
        variables=(
            VariableSchema(
                name="sample_count",
                dims=("bin",),
                dtype="uint64",
                description="Total value cells in the time bin.",
            ),
            VariableSchema(
                name="finite_sample_count",
                dims=("bin",),
                dtype="uint64",
                description="Finite value cells in the time bin.",
            ),
            VariableSchema(
                name="sample_time_count",
                dims=("bin",),
                dtype="uint64",
                description="Distinct time samples in the time bin.",
            ),
            VariableSchema(
                name="valid_fraction",
                dims=("bin",),
                dtype="float64",
                description="finite_sample_count / sample_count.",
            ),
        ),
    )


def coverage_bins(time: TimeRange, *, freq: str) -> tuple[CoverageBin, ...]:
    validate_coverage_freq(freq)
    start = _floor_datetime(time.start, freq=freq)
    bins: list[CoverageBin] = []
    current = start
    while current < time.stop:
        stop = _advance_datetime(current, freq=freq)
        if stop > time.start:
            bins.append(CoverageBin(current, stop))
        current = stop
    return tuple(bins)


def coverage_frame_from_xarray(
    array: Any,
    *,
    time: TimeRange,
    freq: str,
    source_dataset_id: str,
    mission: str,
    instrument: str,
    product: str,
    expected_remote_files: Mapping[str, int] | None = None,
    available_source_files: Mapping[str, int] | None = None,
) -> Any:
    import numpy as np
    import polars as pl

    validate_coverage_freq(freq)
    dims = tuple(str(dim) for dim in getattr(array, "dims", ()))
    if "time" not in dims:
        raise ValueError("coverage() requires a variable with a time dimension")
    if not hasattr(array, "coords") or "time" not in array.coords:
        raise ValueError("coverage() requires a time coordinate")

    time_axis = dims.index("time")
    coordinate = np.asarray(array.coords["time"].values, dtype="datetime64[ns]")
    values = np.asarray(array.values)
    rows: list[dict[str, Any]] = []
    for item in coverage_bins(time, freq=freq):
        start = _datetime64(item.start, np)
        stop = _datetime64(item.stop, np)
        mask = (coordinate >= start) & (coordinate < stop)
        bin_values = np.compress(mask, values, axis=time_axis)
        sample_count = int(bin_values.size)
        finite_sample_count = int(np.isfinite(bin_values).sum()) if sample_count else 0
        sample_time_count = int(mask.sum())
        rows.append(
            {
                "bin_start": item.start_iso,
                "bin_stop": item.stop_iso,
                "freq": freq,
                "mission": mission,
                "instrument": instrument,
                "product": product,
                "source_dataset": source_dataset_id,
                "sample_count": sample_count,
                "finite_sample_count": finite_sample_count,
                "sample_time_count": sample_time_count,
                "valid_fraction": (
                    finite_sample_count / sample_count if sample_count else None
                ),
                "expected_remote_files": (expected_remote_files or {}).get(
                    item.start_iso,
                    0,
                ),
                "available_source_files": (available_source_files or {}).get(
                    item.start_iso,
                    0,
                ),
            }
        )
    return pl.DataFrame(rows, schema=_coverage_frame_schema())


def read_cached_coverage_frame(
    store: Any,
    *,
    dataset_id: str,
    layer: str,
    variant_id: str,
    time: TimeRange,
) -> Any | None:
    try:
        record = store.dataset(dataset_id, layer=layer, variant_id=variant_id)
    except DatasetNotFoundError:
        return None
    if not _record_covers_time_range(record, time):
        return None
    return filter_coverage_frame(record.scan(dataset_id=dataset_id).collect(), time)


def filter_coverage_frame(frame: Any, time: TimeRange) -> Any:
    import polars as pl

    start = time.start.replace(tzinfo=None)
    stop = time.stop.replace(tzinfo=None)
    bin_start = _parse_polars_utc(pl.col("bin_start"))
    bin_stop = _parse_polars_utc(pl.col("bin_stop"))
    return frame.filter((bin_start < stop) & (bin_stop > start)).sort("bin_start")


def _coverage_frame_schema() -> dict[str, Any]:
    import polars as pl

    return {
        "bin_start": pl.Utf8,
        "bin_stop": pl.Utf8,
        "freq": pl.Utf8,
        "mission": pl.Utf8,
        "instrument": pl.Utf8,
        "product": pl.Utf8,
        "source_dataset": pl.Utf8,
        "sample_count": pl.Int64,
        "finite_sample_count": pl.Int64,
        "sample_time_count": pl.Int64,
        "valid_fraction": pl.Float64,
        "expected_remote_files": pl.Int64,
        "available_source_files": pl.Int64,
    }


def _record_covers_time_range(record: Any, time: TimeRange) -> bool:
    coverage = record.manifest().get("time_coverage") or {}
    start = str(coverage.get("start") or "")
    stop = str(coverage.get("stop") or "")
    if not start or not stop:
        return False
    try:
        covered = TimeRange(_parse_utc(start), _parse_utc(stop))
    except (TypeError, ValueError):
        return False
    return covered.start <= time.start and covered.stop >= time.stop


def _floor_datetime(value: datetime, *, freq: str) -> datetime:
    value = value.astimezone(UTC)
    if freq == "day":
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if freq == "month":
        return datetime(value.year, value.month, 1, tzinfo=UTC)
    raise ValueError("freq must be 'day' or 'month'")


def _advance_datetime(value: datetime, *, freq: str) -> datetime:
    if freq == "day":
        from datetime import timedelta

        return value + timedelta(days=1)
    if freq == "month":
        if value.month == 12:
            return datetime(value.year + 1, 1, 1, tzinfo=UTC)
        return datetime(value.year, value.month + 1, 1, tzinfo=UTC)
    raise ValueError("freq must be 'day' or 'month'")


def _datetime64(value: datetime, np: Any) -> Any:
    return np.datetime64(value.astimezone(UTC).replace(tzinfo=None), "ns")


def _format_utc(value: datetime) -> str:
    normalized = value.astimezone(UTC).replace(tzinfo=None)
    return f"{normalized.isoformat(timespec='seconds')}Z"


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_polars_utc(expr: Any) -> Any:
    import polars as pl

    text = expr.cast(pl.Utf8)
    return pl.coalesce(
        text.str.strptime(pl.Datetime, format="%Y-%m-%dT%H:%M:%S%.fZ", strict=False),
        text.str.strptime(pl.Datetime, format="%Y-%m-%dT%H:%M:%S%.f", strict=False),
        text.str.strptime(pl.Date, format="%Y-%m-%d", strict=False).cast(pl.Datetime),
    )
