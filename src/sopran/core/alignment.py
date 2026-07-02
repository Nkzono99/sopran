from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from sopran.core.schema import InstrumentSchema, VariableSchema
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
PartialPolicy = Literal["error", "keep", "drop", "custom"]
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
        if self.partial == "custom":
            return tuple(False for _ in self.durations_seconds)
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
class FeatureMatrix:
    values: Any
    columns: tuple[str, ...]
    time: tuple[str, ...]
    metadata: dict[str, Any]

    @property
    def shape(self) -> tuple[int, ...]:
        return tuple(self.values.shape)

    def to_pandas(self, *, include_time: bool = False):
        import pandas as pd

        frame = pd.DataFrame(self.values, columns=list(self.columns))
        if include_time:
            frame.insert(0, "time", list(self.time))
        return frame

    def to_polars(self, *, include_time: bool = False):
        import polars as pl

        frame = pl.DataFrame(self.values, schema=list(self.columns), orient="row")
        if include_time:
            frame.insert_column(0, pl.Series("time", list(self.time)))
        return frame

    def select(self, *columns: str) -> FeatureMatrix:
        indices = []
        for column in columns:
            try:
                indices.append(self.columns.index(column))
            except ValueError as exc:
                raise KeyError(column) from exc
        metadata = dict(self.metadata)
        metadata["columns"] = list(columns)
        if "features" in metadata:
            features_by_column = {
                feature.get("column"): feature
                for feature in metadata["features"]
            }
            metadata["features"] = [
                features_by_column[column]
                for column in columns
                if column in features_by_column
            ]
        return FeatureMatrix(
            values=self.values[:, indices],
            columns=tuple(columns),
            time=self.time,
            metadata=metadata,
        )

    def write_npz(self, path: str | Path) -> Path:
        import numpy as np

        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            output,
            values=self.values,
            columns=np.array(self.columns, dtype=str),
            time=np.array(self.time, dtype=str),
            metadata_json=json.dumps(self.metadata, sort_keys=True),
        )
        sidecar = output.with_suffix(".metadata.json")
        sidecar.write_text(
            json.dumps(
                {
                    "columns": list(self.columns),
                    "format": "npz",
                    "metadata": self.metadata,
                    "path": output.name,
                    "rows": int(self.values.shape[0]),
                    "time": list(self.time),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return output

    @classmethod
    def read_npz(cls, path: str | Path) -> FeatureMatrix:
        import numpy as np

        with np.load(Path(path), allow_pickle=False) as data:
            metadata_json = str(data["metadata_json"].item())
            return cls(
                values=data["values"],
                columns=tuple(str(column) for column in data["columns"].tolist()),
                time=tuple(str(time) for time in data["time"].tolist()),
                metadata=json.loads(metadata_json),
            )


@dataclass(frozen=True)
class AlignmentResult:
    grid: TimeBins
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    method: AlignmentMethod
    join: JoinMode = "outer"
    fill: Any | None = None
    quality_mask: bool = False
    feature_rules: tuple[dict[str, Any], ...] = ()

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

    def to_feature_frame(self, *, include_time: bool = False):
        columns = ("time", *self.columns) if include_time else self.columns
        return self.to_polars(layout="wide").select(list(columns))

    def to_feature_matrix(self) -> FeatureMatrix:
        return FeatureMatrix(
            values=self.to_feature_frame().to_numpy(),
            columns=self.columns,
            time=tuple(row["time"] for row in self.rows),
            metadata=self.feature_metadata(),
        )

    def write_parquet(self, path: str | Path, *, layout: TableLayout = "wide") -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.to_polars(layout=layout).write_parquet(output)
        return output

    def write_dataset(
        self,
        target: Any,
        dataset_id: str | None = None,
        *,
        layer: str | None = None,
        mission: str = "analysis",
        instrument: str = "alignment",
        product: str | None = None,
        layout: TableLayout = "wide",
        source_files: tuple[str, ...] = (),
        source_datasets: tuple[str, ...] = (),
        shard_path: str = "shards/part-000.parquet",
        compression: str = "zstd",
        overwrite: bool = False,
        append: bool = False,
        producer: str = "sopran.align",
        provenance: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
        context: Any | None = None,
        status: str = "candidate",
        dataset_version: str = "1",
        partitioning: tuple[str, ...] = (),
    ):
        store, output_dataset_id, output_layer = _dataset_write_target(
            target,
            dataset_id,
            layer,
        )
        dataset_parameters = dict(parameters or {})
        dataset_parameters["layout"] = layout
        dataset_parameters["alignment"] = self.metadata()
        return store.write_parquet_dataset(
            dataset_id=output_dataset_id,
            layer=output_layer,
            mission=mission,
            instrument=instrument,
            product=product or _default_product_name(output_dataset_id),
            schema=_alignment_schema(
                mission=mission,
                instrument=instrument,
                columns=self.columns,
                layout=layout,
                feature_rules=self.feature_rules,
            ),
            time_coverage=self.grid.time,
            frame=self.to_polars(layout=layout),
            source_files=source_files,
            source_datasets=source_datasets,
            shard_path=shard_path,
            compression=compression,
            overwrite=overwrite,
            append=append,
            producer=producer,
            provenance=provenance
            or {
                "pipeline": {
                    "source": "sopran.align",
                    "stages": ["align", "write_dataset"],
                }
            },
            parameters=dataset_parameters,
            context=context,
            status=status,
            dataset_version=dataset_version,
            partitioning=partitioning,
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns),
            "features": list(self.feature_rules),
            "fill": self.fill,
            "grid": self.grid.metadata(),
            "join": self.join,
            "method": self.method,
            "quality_mask": self.quality_mask,
        }

    def feature_metadata(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns),
            "features": list(self.feature_rules),
            "grid": self.grid.metadata(),
            "rows": len(self.rows),
            "time_column": "time",
        }


def time_bins(
    time: TimeRange | None = None,
    *,
    cadence: str | timedelta | None = None,
    edges: Sequence[object] | None = None,
    label: Literal["center"] = "center",
    closed: Literal["left"] = "left",
    partial: PartialPolicy = "error",
) -> TimeBins:
    if label != "center":
        raise ValueError("time_bins() currently supports label='center' only")
    if closed != "left":
        raise ValueError("time_bins() currently supports closed='left' only")
    if edges is not None:
        if cadence is not None:
            raise ValueError("time_bins() accepts either edges or cadence, not both")
        parsed_edges = tuple(_parse_datetime(edge) for edge in edges)
        if len(parsed_edges) < 2:
            raise ValueError("time_bins(edges=...) requires at least two edges")
        if any(
            stop <= start
            for start, stop in zip(
                parsed_edges[:-1],
                parsed_edges[1:],
                strict=True,
            )
        ):
            raise ValueError("time_bins(edges=...) requires strictly increasing edges")
        if time is None:
            time = TimeRange(parsed_edges[0], parsed_edges[-1])
        elif time.start != parsed_edges[0] or time.stop != parsed_edges[-1]:
            raise ValueError("time must match the first and last custom edges")
        return TimeBins(
            time=time,
            edges=parsed_edges,
            label=label,
            closed=closed,
            partial="custom",
        )
    if time is None:
        raise ValueError("time_bins() requires time when edges are not provided")
    if cadence is None:
        raise ValueError("time_bins() requires cadence when edges are not provided")
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
            units=feature.units,
            frame=feature.frame,
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
                units=feature.units,
                frame=feature.frame,
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
    units: str | None = None
    frame: str | None = None


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
        feature_rules=tuple(_feature_rule(feature) for feature in features),
    )


@dataclass(frozen=True)
class _FeatureSeries:
    name: str
    samples: tuple[tuple[datetime, float], ...]
    units: str | None = None
    frame: str | None = None


def _feature_rule(feature: _RequestedFeature) -> dict[str, Any]:
    rule = {
        "column": feature.name,
        "method": feature.method,
        "tolerance_seconds": (
            feature.tolerance.total_seconds()
            if feature.tolerance is not None
            else None
        ),
    }
    if feature.units is not None:
        rule["units"] = feature.units
    if feature.frame is not None:
        rule["frame"] = feature.frame
    return rule


def _default_product_name(dataset_id: str) -> str:
    return next((part for part in reversed(dataset_id.split(".")) if part), "features")


def _dataset_write_target(
    target: Any,
    dataset_id: str | None,
    layer: str | None,
) -> tuple[Any, str, str]:
    if dataset_id is not None:
        return target, dataset_id, layer or "features"

    target_dataset_id = getattr(target, "dataset_id", None)
    target_layer = getattr(target, "layer", None)
    store = getattr(target, "store", None)
    if target_dataset_id is None or target_layer is None:
        raise TypeError("write_dataset() expects a Store plus dataset_id or a ProductRef")
    if store is None:
        raise ValueError("ProductRef target must be backed by a Store")
    return store, str(target_dataset_id), str(layer or target_layer)


def _alignment_schema(
    *,
    mission: str,
    instrument: str,
    columns: tuple[str, ...],
    layout: TableLayout,
    feature_rules: tuple[dict[str, Any], ...] = (),
) -> InstrumentSchema:
    feature_metadata = {
        str(feature.get("column")): feature
        for feature in feature_rules
        if feature.get("column") is not None
    }
    if layout == "wide":
        variables = (
            VariableSchema(
                name="time",
                dims=("time",),
                description="Feature table bin center time.",
            ),
            *(
                VariableSchema(
                    name=column,
                    dims=("time",),
                    units=_feature_metadata_value(feature_metadata, column, "units"),
                    frame=_feature_metadata_value(feature_metadata, column, "frame"),
                    description="Aligned feature column.",
                )
                for column in columns
            ),
        )
    elif layout == "long":
        variables = (
            VariableSchema(
                name="time",
                dims=("time",),
                description="Feature table bin center time.",
            ),
            VariableSchema(
                name="feature",
                dims=("time",),
                description="Aligned feature name.",
            ),
            VariableSchema(
                name="value",
                dims=("time",),
                description="Aligned feature value.",
            ),
        )
    else:
        raise ValueError("layout must be 'wide' or 'long'")
    return InstrumentSchema(mission=mission, instrument=instrument, variables=variables)


def _feature_metadata_value(
    feature_metadata: dict[str, dict[str, Any]],
    column: str,
    key: str,
) -> str | None:
    value = feature_metadata.get(column, {}).get(key)
    return str(value) if value is not None else None


def _features(array: Any, index: int) -> tuple[_FeatureSeries, ...]:
    if hasattr(array, "to_xarray"):
        array = array.to_xarray()
    if not hasattr(array, "dims"):
        raise ValueError("align() expects xarray-like data with dims")
    dims = tuple(array.dims)
    times = array.coords["time"].values
    name = _array_name(array, index)
    units = _array_attr(array, "units")
    frame = _array_attr(array, "frame")
    if dims == ("time",):
        return (
            _FeatureSeries(
                name=name,
                samples=_sample_values(times, array.values),
                units=units,
                frame=frame,
            ),
        )
    if len(dims) == 2 and dims[0] == "time":
        component_dim = dims[1]
        values = array.values
        return tuple(
            _FeatureSeries(
                name=f"{name}_{_coord_label(component)}",
                samples=_sample_values(times, values[:, component_index]),
                units=units,
                frame=frame,
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


def _array_attr(array: Any, name: str) -> str | None:
    value = getattr(array, "attrs", {}).get(name)
    return str(value) if value is not None else None


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
