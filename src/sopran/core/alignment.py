from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sopran.core.time import TimeRange, _format_utc, _parse_datetime

AlignMethod = Literal["nearest", "mean"]


@dataclass(frozen=True)
class TimeBins:
    time: TimeRange
    edges: tuple[datetime, ...]
    label: Literal["center"] = "center"
    closed: Literal["left"] = "left"

    @property
    def count(self) -> int:
        return len(self.edges) - 1

    @property
    def start_iso(self) -> str:
        return _format_utc(self.edges[0])

    @property
    def stop_iso(self) -> str:
        return _format_utc(self.edges[-1])

    @property
    def centers(self) -> tuple[datetime, ...]:
        return tuple(
            start + (stop - start) / 2
            for start, stop in zip(self.edges[:-1], self.edges[1:], strict=True)
        )

    @property
    def centers_iso(self) -> tuple[str, ...]:
        return tuple(_format_utc(center) for center in self.centers)


@dataclass(frozen=True)
class AlignmentResult:
    grid: TimeBins
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    method: AlignMethod

    def to_polars(self):
        import polars as pl

        return pl.DataFrame(list(self.rows))


def time_bins(
    time: TimeRange,
    *,
    cadence: str | timedelta,
    label: Literal["center"] = "center",
    closed: Literal["left"] = "left",
) -> TimeBins:
    if label != "center":
        raise ValueError("time_bins() currently supports label='center' only")
    if closed != "left":
        raise ValueError("time_bins() currently supports closed='left' only")
    step = _parse_duration(cadence)
    edges = [time.start]
    current = time.start
    while current < time.stop:
        current = current + step
        if current > time.stop:
            raise ValueError("cadence must divide the requested time range exactly")
        edges.append(current)
    return TimeBins(time=time, edges=tuple(edges), label=label, closed=closed)


def align(
    *arrays: Any,
    grid: TimeBins,
    method: AlignMethod,
    tolerance: str | timedelta | None = None,
) -> AlignmentResult:
    if not arrays:
        raise ValueError("align() requires at least one array")
    tolerance_delta = _parse_duration(tolerance) if tolerance is not None else None
    columns = tuple(_array_name(array, index) for index, array in enumerate(arrays))
    rows = []
    for bin_index, center in enumerate(grid.centers):
        row: dict[str, Any] = {"time": _format_utc(center)}
        for column, array in zip(columns, arrays, strict=True):
            samples = _samples(array)
            if method == "nearest":
                row[column] = _nearest_value(samples, center, tolerance_delta)
            elif method == "mean":
                row[column] = _mean_value(samples, grid.edges[bin_index], grid.edges[bin_index + 1])
            else:
                raise ValueError("method must be 'nearest' or 'mean'")
        rows.append(row)
    return AlignmentResult(grid=grid, columns=columns, rows=tuple(rows), method=method)


def _samples(array: Any) -> tuple[tuple[datetime, float], ...]:
    if hasattr(array, "to_xarray"):
        array = array.to_xarray()
    if not hasattr(array, "dims") or tuple(array.dims) != ("time",):
        raise ValueError("align() currently supports 1D arrays with dims=('time',)")

    times = array.coords["time"].values
    values = array.values
    return tuple(
        (_parse_datetime(str(time_value)), float(value))
        for time_value, value in zip(times, values, strict=True)
    )


def _nearest_value(
    samples: tuple[tuple[datetime, float], ...],
    target: datetime,
    tolerance: timedelta | None,
) -> float | None:
    if not samples:
        return None
    nearest_time, nearest = min(samples, key=lambda item: abs(item[0] - target))
    if tolerance is not None and abs(nearest_time - target) > tolerance:
        return None
    return nearest


def _mean_value(
    samples: tuple[tuple[datetime, float], ...],
    start: datetime,
    stop: datetime,
) -> float | None:
    values = [value for timestamp, value in samples if start <= timestamp < stop]
    if not values:
        return None
    return float(sum(values) / len(values))


def _array_name(array: Any, index: int) -> str:
    name = getattr(array, "name", None)
    if name:
        return str(name)
    return f"value_{index}"


def _parse_duration(value: str | timedelta | None) -> timedelta:
    if isinstance(value, timedelta):
        return value
    if value is None:
        raise TypeError("duration value is required")
    text = value.strip().lower()
    if text.endswith("ms"):
        return timedelta(milliseconds=float(text[:-2]))
    if text.endswith("s"):
        return timedelta(seconds=float(text[:-1]))
    if text.endswith("m"):
        return timedelta(minutes=float(text[:-1]))
    if text.endswith("h"):
        return timedelta(hours=float(text[:-1]))
    raise ValueError("duration must end with ms, s, m, or h")
