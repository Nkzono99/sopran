from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any, Literal

from sopran.core.alignment import _parse_duration
from sopran.core.data import SopranArray
from sopran.core.time import TimeRange

ResampleLikeMethod = Literal["nearest", "previous", "next", "linear"]
_METHODS = ("nearest", "previous", "next", "linear")


def resample_like(
    source: Any,
    target: Any,
    *,
    method: ResampleLikeMethod = "nearest",
    tolerance: str | timedelta | None = None,
    time: str = "time",
) -> Any:
    """Resample a time-indexed object onto another object's time coordinate."""

    if method not in _METHODS:
        allowed = ", ".join(_METHODS)
        raise ValueError(f"method must be one of: {allowed}")
    tolerance_delta = _parse_duration(tolerance) if tolerance is not None else None
    target_times = _normalize_time_values(_target_time_values(target, time=time))

    if isinstance(source, SopranArray):
        resampled = _resample_xarray_like(
            source.to_xarray(),
            target_times,
            method=method,
            tolerance=tolerance_delta,
            time=time,
        )
        return _wrap_sopran_array(
            source,
            target,
            resampled,
            target_times=target_times,
            operation=_operation_metadata(
                target,
                target_times,
                method=method,
                tolerance=tolerance_delta,
            ),
        )
    if _is_xarray_like(source):
        return _resample_xarray_like(
            source,
            target_times,
            method=method,
            tolerance=tolerance_delta,
            time=time,
        )
    if _is_pandas_frame(source):
        return _resample_pandas_like(
            source,
            target_times,
            method=method,
            tolerance=tolerance_delta,
            time=time,
        )
    if _is_polars_frame(source):
        return _resample_polars_like(
            source,
            target_times,
            method=method,
            tolerance=tolerance_delta,
            time=time,
        )
    if hasattr(source, "to_xarray"):
        return _resample_xarray_like(
            source.to_xarray(),
            target_times,
            method=method,
            tolerance=tolerance_delta,
            time=time,
        )
    raise TypeError(
        "resample_like() expects a SopranArray, xarray object, pandas DataFrame, "
        "polars DataFrame, or object exposing to_xarray()"
    )


def _resample_xarray_like(
    source: Any,
    target_times: Any,
    *,
    method: ResampleLikeMethod,
    tolerance: timedelta | None,
    time: str,
) -> Any:
    if time not in getattr(source, "coords", {}):
        raise ValueError(f"source has no {time!r} coordinate")
    _ensure_unique_source_times(source.coords[time].values)
    if method == "linear":
        result = source.interp({time: target_times})
        mask = _linear_tolerance_mask(source.coords[time].values, target_times, tolerance)
        if mask is None:
            return result
        import xarray as xr

        return result.where(xr.DataArray(mask, dims=(time,), coords={time: target_times}))
    reindex_method = {
        "nearest": "nearest",
        "previous": "ffill",
        "next": "bfill",
    }[method]
    kwargs: dict[str, Any] = {"method": reindex_method}
    if tolerance is not None:
        kwargs["tolerance"] = tolerance
    return source.reindex({time: target_times}, **kwargs)


def _resample_pandas_like(
    source: Any,
    target_times: Any,
    *,
    method: ResampleLikeMethod,
    tolerance: timedelta | None,
    time: str,
) -> Any:
    import pandas as pd

    _ensure_unique_columns(source.columns, role="source")
    if time not in source.columns:
        raise ValueError(f"source has no {time!r} column")
    target = pd.DataFrame({time: pd.to_datetime(target_times)})
    source_sorted = source.copy()
    source_sorted[time] = _normalize_time_values(source_sorted[time])
    if source_sorted[time].duplicated().any():
        raise ValueError("source time values must be unique")
    source_sorted = source_sorted.sort_values(time)
    target_sorted = target.assign(_sopran_order=range(len(target))).sort_values(time)
    if method == "linear":
        return _interpolate_pandas_like(
            source_sorted,
            target_sorted,
            time=time,
            tolerance=tolerance,
        )
    direction: Literal["backward", "forward", "nearest"]
    if method == "nearest":
        direction = "nearest"
    elif method == "previous":
        direction = "backward"
    else:
        direction = "forward"
    result = pd.merge_asof(
        target_sorted,
        source_sorted,
        on=time,
        direction=direction,
        tolerance=tolerance,
    )
    return (
        result.sort_values("_sopran_order")
        .drop(columns=["_sopran_order"])
        .reset_index(drop=True)
    )


def _resample_polars_like(
    source: Any,
    target_times: Any,
    *,
    method: ResampleLikeMethod,
    tolerance: timedelta | None,
    time: str,
) -> Any:
    import polars as pl

    pandas_result = _resample_pandas_like(
        _polars_to_pandas(source),
        target_times,
        method=method,
        tolerance=tolerance,
        time=time,
    )
    return pl.from_pandas(pandas_result)


def _interpolate_pandas_like(
    source: Any,
    target: Any,
    *,
    time: str,
    tolerance: timedelta | None,
) -> Any:
    import pandas as pd

    numeric_columns = [
        column
        for column in source.columns
        if column != time and pd.api.types.is_numeric_dtype(source[column])
    ]
    indexed = source[[time, *numeric_columns]].set_index(time).sort_index()
    combined_index = indexed.index.union(pd.DatetimeIndex(target[time])).sort_values()
    interpolated = indexed.reindex(combined_index).interpolate(
        method="time",
        limit_area="inside",
    )
    result = interpolated.reindex(pd.DatetimeIndex(target[time])).reset_index()
    result = result.rename(columns={"index": time})
    result.insert(0, "_sopran_order", target["_sopran_order"].to_numpy())
    mask = _linear_tolerance_mask(indexed.index, target[time], tolerance)
    if mask is not None:
        result.loc[~mask, numeric_columns] = pd.NA
    return (
        result.sort_values("_sopran_order")
        .drop(columns=["_sopran_order"])
        .reset_index(drop=True)
    )


def _linear_tolerance_mask(
    source_times: Any,
    target_times: Any,
    tolerance: timedelta | None,
) -> Any | None:
    if tolerance is None:
        return None
    import numpy as np

    source_index = _datetime_index_ns(source_times).drop_duplicates().sort_values()
    target_index = _datetime_index_ns(target_times)
    source_ns = source_index.asi8
    target_ns = target_index.asi8
    if len(source_ns) == 0:
        return np.zeros(len(target_ns), dtype=bool)
    tolerance_ns = int(tolerance.total_seconds() * 1_000_000_000)
    positions = np.searchsorted(source_ns, target_ns, side="left")
    mask = np.zeros(len(target_ns), dtype=bool)
    exact = (positions < len(source_ns)) & (
        source_ns[np.minimum(positions, len(source_ns) - 1)] == target_ns
    )
    mask[exact] = True
    between = ~exact
    left_positions = positions - 1
    right_positions = positions
    valid = (
        between
        & (left_positions >= 0)
        & (right_positions < len(source_ns))
    )
    if valid.any():
        left_delta = target_ns[valid] - source_ns[left_positions[valid]]
        right_delta = source_ns[right_positions[valid]] - target_ns[valid]
        mask[valid] = (left_delta <= tolerance_ns) & (right_delta <= tolerance_ns)
    return mask


def _datetime_index_ns(values: Any) -> Any:
    import pandas as pd

    return pd.DatetimeIndex(pd.to_datetime(values, utc=True)).tz_convert(None).astype(
        "datetime64[ns]"
    )


def _normalize_time_values(values: Any) -> Any:
    return _datetime_index_ns(values).to_numpy(dtype="datetime64[ns]")


def _ensure_unique_source_times(values: Any) -> None:
    if _datetime_index_ns(values).duplicated().any():
        raise ValueError("source time values must be unique")


def _ensure_unique_columns(columns: Any, *, role: str) -> None:
    labels = list(columns)
    duplicates = tuple(label for index, label in enumerate(labels) if label in labels[:index])
    if duplicates:
        names = ", ".join(str(label) for label in dict.fromkeys(duplicates))
        raise ValueError(f"{role} columns must be unique: {names}")


def _wrap_sopran_array(
    source: SopranArray,
    target: Any,
    array: Any,
    *,
    target_times: Any,
    operation: dict[str, Any],
) -> SopranArray:
    name = str(getattr(array, "name", None) or source.name)
    dims = tuple(str(dim) for dim in getattr(array, "dims", source.schema.dims))
    return SopranArray(
        name=name,
        time=_target_time_range(target, target_times=target_times, fallback=source.time),
        schema=replace(source.schema, name=name, dims=dims),
        files=source.files,
        operations=(*source.operations, operation),
        xr=array,
    )


def _target_time_values(target: Any, *, time: str) -> Any:
    if isinstance(target, SopranArray):
        array = target.to_xarray()
        if time not in array.coords:
            raise ValueError(f"target has no {time!r} coordinate")
        return array.coords[time].values
    if _is_xarray_like(target):
        if time not in target.coords:
            raise ValueError(f"target has no {time!r} coordinate")
        return target.coords[time].values
    if _is_pandas_frame(target):
        _ensure_unique_columns(target.columns, role="target")
        if time not in target.columns:
            raise ValueError(f"target has no {time!r} column")
        return target[time]
    if _is_polars_frame(target):
        if time not in _polars_columns(target):
            raise ValueError(f"target has no {time!r} column")
        return _polars_select_series(target, time).to_list()
    if hasattr(target, "to_xarray"):
        array = target.to_xarray()
        if time not in array.coords:
            raise ValueError(f"target has no {time!r} coordinate")
        return array.coords[time].values
    raise TypeError("target must expose a time coordinate or time column")


def _operation_metadata(
    target: Any,
    target_times: Any,
    *,
    method: ResampleLikeMethod,
    tolerance: timedelta | None,
) -> dict[str, Any]:
    times = list(target_times)
    return {
        "operation": "resample_like",
        "method": method,
        "tolerance_seconds": (
            tolerance.total_seconds() if tolerance is not None else None
        ),
        "target": {
            "type": type(target).__name__,
            "name": str(getattr(target, "name", "") or ""),
            "time_count": len(times),
            "time_start": str(times[0]) if times else None,
            "time_stop": str(times[-1]) if times else None,
        },
    }


def _target_time_range(
    target: Any,
    *,
    target_times: Any | None = None,
    fallback: TimeRange,
) -> TimeRange:
    target_time = getattr(target, "time", None)
    if isinstance(target_time, TimeRange):
        return target_time
    if target_times is None:
        try:
            target_times = _normalize_time_values(_target_time_values(target, time="time"))
        except Exception:
            return fallback
    try:
        normalized_times = _normalize_time_values(target_times)
    except Exception:
        return fallback
    if len(normalized_times) == 0:
        return fallback
    start = _datetime_from_datetime64(normalized_times.min())
    stop = _datetime_from_datetime64(normalized_times.max())
    stop = max(stop, start) + timedelta(microseconds=1)
    return TimeRange(start, stop)


def _is_xarray_like(value: Any) -> bool:
    return hasattr(value, "coords") and (
        hasattr(value, "dims") or hasattr(value, "data_vars")
    )


def _is_pandas_frame(value: Any) -> bool:
    return value.__class__.__module__.startswith("pandas") and hasattr(value, "columns")


def _is_polars_frame(value: Any) -> bool:
    return value.__class__.__module__.startswith("polars") and value.__class__.__name__ in {
        "DataFrame",
        "LazyFrame",
    }


def _polars_columns(value: Any) -> list[str]:
    collect_schema = getattr(value, "collect_schema", None)
    if callable(collect_schema):
        return [str(name) for name in collect_schema().names()]
    return [str(name) for name in value.columns]


def _polars_select_series(value: Any, column: str) -> Any:
    selected = value.select(column)
    collect = getattr(selected, "collect", None)
    if callable(collect):
        selected = collect()
    return selected.to_series()


def _polars_to_pandas(value: Any) -> Any:
    collect = getattr(value, "collect", None)
    if callable(collect):
        value = collect()
    return value.to_pandas()


def _datetime_from_datetime64(value: Any) -> Any:
    import pandas as pd

    return pd.Timestamp(value).tz_localize("UTC").to_pydatetime()
