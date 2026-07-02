from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from sopran.core.time import TimeRange, _format_utc, _parse_datetime

AlignMethod = Literal["nearest", "center", "mean", "max", "median", "first", "last"]
AlignmentMethod = Literal[
    "nearest",
    "center",
    "mean",
    "max",
    "median",
    "first",
    "last",
    "mixed",
]
JoinMode = Literal["outer", "inner"]
TableLayout = Literal["wide", "long"]
PartialPolicy = Literal["error", "keep", "drop"]
_ALIGN_METHODS = ("nearest", "center", "mean", "max", "median", "first", "last")
_ALIGN_METHODS_TEXT = "'nearest', 'center', 'mean', 'max', 'median', 'first', or 'last'"
_JOIN_MODES = ("outer", "inner")
_PARTIAL_POLICIES = ("error", "keep", "drop")


@dataclass(frozen=True)
class TimeBins:
    time: TimeRange
    edges: tuple[datetime, ...]
    label: Literal["center"] = "center"
    closed: Literal["left"] = "left"
    partial: PartialPolicy = "error"

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

    @property
    def edges_iso(self) -> tuple[str, ...]:
        return tuple(_format_utc(edge) for edge in self.edges)

    @property
    def durations_seconds(self) -> tuple[float, ...]:
        return tuple(
            (stop - start).total_seconds()
            for start, stop in zip(self.edges[:-1], self.edges[1:], strict=True)
        )

    @property
    def is_partial(self) -> tuple[bool, ...]:
        durations = self.durations_seconds
        if not durations:
            return ()
        regular = durations[0]
        return tuple(duration < regular for duration in durations)

    def to_polars(self):
        import polars as pl

        return pl.DataFrame(
            [
                {
                    "index": index,
                    "start": _format_utc(start),
                    "stop": _format_utc(stop),
                    "center": _format_utc(center),
                    "duration_seconds": duration,
                    "is_partial": is_partial,
                }
                for index, (start, stop, center, duration, is_partial) in enumerate(
                    zip(
                        self.edges[:-1],
                        self.edges[1:],
                        self.centers,
                        self.durations_seconds,
                        self.is_partial,
                        strict=True,
                    )
                )
            ]
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "centers": list(self.centers_iso),
            "closed": self.closed,
            "count": self.count,
            "durations_seconds": list(self.durations_seconds),
            "edges": list(self.edges_iso),
            "is_partial": list(self.is_partial),
            "label": self.label,
            "partial": self.partial,
            "start": self.start_iso,
            "stop": self.stop_iso,
        }


@dataclass(frozen=True)
class AlignmentResult:
    grid: TimeBins
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    method: AlignmentMethod
    join: JoinMode = "outer"
    fill: Any | None = None
    quality_mask: bool = False

    def to_polars(self, *, layout: TableLayout = "wide"):
        import polars as pl

        if layout == "wide":
            return pl.DataFrame(list(self.rows))
        if layout == "long":
            return pl.DataFrame(
                [
                    {"time": row["time"], "feature": column, "value": row[column]}
                    for row in self.rows
                    for column in self.columns
                ]
            )
        raise ValueError("layout must be 'wide' or 'long'")

    def write_parquet(self, path: str | Path, *, layout: TableLayout = "wide") -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.to_polars(layout=layout).write_parquet(output)
        return output

    def metadata(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns),
            "fill": self.fill,
            "grid": self.grid.metadata(),
            "join": self.join,
            "method": self.method,
            "quality_mask": self.quality_mask,
        }


def time_bins(
    time: TimeRange,
    *,
    cadence: str | timedelta,
    label: Literal["center"] = "center",
    closed: Literal["left"] = "left",
    partial: PartialPolicy = "error",
) -> TimeBins:
    if label != "center":
        raise ValueError("time_bins() currently supports label='center' only")
    if closed != "left":
        raise ValueError("time_bins() currently supports closed='left' only")
    if partial not in _PARTIAL_POLICIES:
        raise ValueError("partial must be 'error', 'keep', or 'drop'")
    step = _parse_duration(cadence)
    edges = [time.start]
    current = time.start
    while current < time.stop:
        next_edge = current + step
        if next_edge > time.stop:
            if partial == "keep":
                edges.append(time.stop)
            elif partial == "error":
                raise ValueError("cadence must divide the requested time range exactly")
            break
        current = next_edge
        edges.append(current)
    return TimeBins(time=time, edges=tuple(edges), label=label, closed=closed, partial=partial)


def align(
    *arrays: Any,
    grid: TimeBins,
    method: AlignMethod,
    tolerance: str | timedelta | None = None,
    join: JoinMode = "outer",
    fill: Any | None = None,
    quality_mask: Any | None = None,
) -> AlignmentResult:
    if not arrays:
        raise ValueError("align() requires at least one array")
    _validate_join(join)
    tolerance_delta = _parse_duration(tolerance) if tolerance is not None else None
    requested_features = tuple(
        _RequestedFeature(
            name=feature.name,
            samples=feature.samples,
            method=method,
            tolerance=tolerance_delta,
        )
        for index, array in enumerate(arrays)
        for feature in _features(array, index)
    )
    return _collect_features(
        grid,
        requested_features,
        method=method,
        join=join,
        fill=fill,
        quality_mask_samples=(
            _quality_mask_samples(quality_mask) if quality_mask is not None else None
        ),
    )


@dataclass(frozen=True)
class SampleSpec:
    """One input series and its alignment rule for a sampled feature table."""

    array: Any
    method: AlignMethod
    tolerance: str | timedelta | None = None


@dataclass(frozen=True)
class SampleTable:
    """Build a feature table with product-specific time alignment rules."""

    grid: TimeBins
    specs: tuple[SampleSpec, ...] = ()

    def add(
        self,
        array: Any,
        *,
        method: AlignMethod,
        tolerance: str | timedelta | None = None,
    ) -> SampleTable:
        if method not in _ALIGN_METHODS:
            raise ValueError(f"method must be {_ALIGN_METHODS_TEXT}")
        return SampleTable(
            grid=self.grid,
            specs=(
                *self.specs,
                SampleSpec(array=array, method=method, tolerance=tolerance),
            ),
        )

    def collect(
        self,
        *,
        join: JoinMode = "outer",
        fill: Any | None = None,
        quality_mask: Any | None = None,
    ) -> AlignmentResult:
        if not self.specs:
            raise ValueError("SampleTable.collect() requires at least one sample")
        _validate_join(join)
        requested_features = tuple(
            _RequestedFeature(
                name=feature.name,
                samples=feature.samples,
                method=spec.method,
                tolerance=(
                    _parse_duration(spec.tolerance)
                    if spec.tolerance is not None
                    else None
                ),
            )
            for index, spec in enumerate(self.specs)
            for feature in _features(spec.array, index)
        )
        return _collect_features(
            self.grid,
            requested_features,
            method="mixed",
            join=join,
            fill=fill,
            quality_mask_samples=(
                _quality_mask_samples(quality_mask)
                if quality_mask is not None
                else None
            ),
        )


@dataclass(frozen=True)
class _RequestedFeature:
    name: str
    samples: tuple[tuple[datetime, float], ...]
    method: AlignMethod
    tolerance: timedelta | None


def _collect_features(
    grid: TimeBins,
    features: tuple[_RequestedFeature, ...],
    *,
    method: AlignmentMethod,
    join: JoinMode,
    fill: Any | None,
    quality_mask_samples: tuple[tuple[datetime, float], ...] | None,
) -> AlignmentResult:
    columns = tuple(feature.name for feature in features)
    rows = []
    for bin_index, center in enumerate(grid.centers):
        start = grid.edges[bin_index]
        stop = grid.edges[bin_index + 1]
        if quality_mask_samples is not None and not _quality_mask_allows(
            quality_mask_samples,
            center,
            start,
            stop,
        ):
            continue
        row: dict[str, Any] = {"time": _format_utc(center)}
        for feature in features:
            if feature.method == "nearest":
                row[feature.name] = _nearest_value(
                    feature.samples,
                    center,
                    feature.tolerance,
                )
            elif feature.method in ("center", "mean", "max", "median", "first", "last"):
                row[feature.name] = _bin_value(
                    feature.samples,
                    center,
                    start,
                    stop,
                    feature.method,
                )
            else:
                raise ValueError(f"method must be {_ALIGN_METHODS_TEXT}")
        if join == "inner" and any(row[column] is None for column in columns):
            continue
        if fill is not None:
            row.update(
                {
                    column: fill
                    for column in columns
                    if row[column] is None
                }
            )
        rows.append(row)
    return AlignmentResult(
        grid=grid,
        columns=columns,
        rows=tuple(rows),
        method=method,
        join=join,
        fill=fill,
        quality_mask=quality_mask_samples is not None,
    )


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


def _quality_mask_samples(array: Any) -> tuple[tuple[datetime, float], ...]:
    features = _features(array, 0)
    if len(features) != 1:
        raise ValueError("quality_mask expects a 1D time series")
    return features[0].samples


def _quality_mask_allows(
    samples: tuple[tuple[datetime, float], ...],
    center: datetime,
    start: datetime,
    stop: datetime,
) -> bool:
    value = _bin_value(samples, center, start, stop, "center")
    return value is not None and value > 0


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


def _bin_value(
    samples: tuple[tuple[datetime, float], ...],
    center: datetime,
    start: datetime,
    stop: datetime,
    method: Literal["center", "mean", "max", "median", "first", "last"],
) -> float | None:
    items = [(timestamp, value) for timestamp, value in samples if start <= timestamp < stop]
    if not items:
        return None
    values = [value for _, value in items]
    if method == "center":
        return min(items, key=lambda item: abs(item[0] - center))[1]
    if method == "mean":
        return float(sum(values) / len(values))
    if method == "max":
        return float(max(values))
    if method == "first":
        return min(items, key=lambda item: item[0])[1]
    if method == "last":
        return max(items, key=lambda item: item[0])[1]
    midpoint = len(values) // 2
    sorted_values = sorted(values)
    if len(sorted_values) % 2:
        return float(sorted_values[midpoint])
    return float((sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2)


def _array_name(array: Any, index: int) -> str:
    name = getattr(array, "name", None)
    if name:
        return str(name)
    return f"value_{index}"


def _coord_label(value: Any) -> str:
    text = str(value)
    return "".join(character if character.isalnum() else "_" for character in text).strip("_")


def _validate_join(join: str) -> None:
    if join not in _JOIN_MODES:
        raise ValueError("join must be 'outer' or 'inner'")


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
