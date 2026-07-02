from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
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

    def write_parquet(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.to_polars().write_parquet(output)
        return output


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
    features = tuple(
        feature
        for index, array in enumerate(arrays)
        for feature in _features(array, index)
    )
    columns = tuple(feature.name for feature in features)
    rows = []
    for bin_index, center in enumerate(grid.centers):
        row: dict[str, Any] = {"time": _format_utc(center)}
        for feature in features:
            if method == "nearest":
                row[feature.name] = _nearest_value(feature.samples, center, tolerance_delta)
            elif method == "mean":
                row[feature.name] = _mean_value(
                    feature.samples,
                    grid.edges[bin_index],
                    grid.edges[bin_index + 1],
                )
            else:
                raise ValueError("method must be 'nearest' or 'mean'")
        rows.append(row)
    return AlignmentResult(grid=grid, columns=columns, rows=tuple(rows), method=method)


@dataclass(frozen=True)
class _FeatureSeries:
    name: str
    samples: tuple[tuple[datetime, float], ...]


def _features(array: Any, index: int) -> tuple[_FeatureSeries, ...]:
    if hasattr(array, "to_xarray"):
        array = array.to_xarray()
    if not hasattr(array, "dims"):
        raise ValueError("align() expects xarray-like data with dims")
    dims = tuple(array.dims)
    times = array.coords["time"].values
    name = _array_name(array, index)
    if dims == ("time",):
        return (
            _FeatureSeries(
                name=name,
                samples=_sample_values(times, array.values),
            ),
        )
    if len(dims) == 2 and dims[0] == "time":
        component_dim = dims[1]
        values = array.values
        return tuple(
            _FeatureSeries(
                name=f"{name}_{_coord_label(component)}",
                samples=_sample_values(times, values[:, component_index]),
            )
            for component_index, component in enumerate(array.coords[component_dim].values)
        )
    raise ValueError("align() currently supports 1D time series or 2D time x component arrays")


def _sample_values(times: Any, values: Any) -> tuple[tuple[datetime, float], ...]:
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


def _coord_label(value: Any) -> str:
    text = str(value)
    return "".join(character if character.isalnum() else "_" for character in text).strip("_")


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
