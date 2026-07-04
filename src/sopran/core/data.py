from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from sopran.core.pages import InfoPage
from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.core.time import TimeRange

DEFAULT_MAX_POLARS_ROWS = 10_000_000
PolarsLayout = Literal["auto", "array", "long"]
PlotMode = Literal["auto", "line", "spectrogram", "pitch", "energy", "raw"]


@dataclass(frozen=True)
class SopranArray:
    """Thin variable object for loaded SOPRAN data."""

    name: str
    time: TimeRange
    schema: VariableSchema
    files: tuple[Path, ...] = ()
    operations: tuple[dict[str, Any], ...] = ()
    xr: Any = None

    @property
    def trange(self) -> TimeRange:
        return self.time

    @property
    def metadata(self) -> dict[str, Any]:
        metadata = {
            "type": type(self).__name__,
            "name": self.name,
            "time_range": {
                "start": self.time.start_iso,
                "stop": self.time.stop_iso,
            },
            "schema": self.schema.to_metadata(),
            "source_files": [str(path) for path in self.files],
        }
        if self.operations:
            metadata["operations"] = [dict(operation) for operation in self.operations]
        return metadata

    def info(self) -> InfoPage:
        lines = [
            f"dims: {', '.join(self.schema.dims)}",
            f"time: {self.time.start_iso} to {self.time.stop_iso}",
        ]
        if self.schema.units is not None:
            lines.append(f"units: {self.schema.units}")
        if self.schema.description:
            lines.append(self.schema.description)
        if self.files:
            lines.append(f"files: {len(self.files)}")
        return InfoPage(title=self.name, lines=tuple(lines))

    def to_xarray(self) -> Any:
        if self.xr is None:
            raise ValueError(f"{self.name} is not loaded as an xarray DataArray")
        return self.xr

    def to_polars(
        self,
        *,
        layout: PolarsLayout = "auto",
        max_rows: int | None = DEFAULT_MAX_POLARS_ROWS,
        allow_large: bool = False,
    ):
        try:
            import numpy as np
            import polars as pl
        except ImportError as exc:
            raise RuntimeError("polars is required for SopranArray.to_polars()") from exc

        array = self.to_xarray()
        values = np.asarray(array.values)
        resolved_layout = _resolve_polars_layout(values, layout)
        if resolved_layout == "array":
            return _data_array_to_array_polars(array, self.name, np, pl)

        ensure_polars_row_limit(
            values.size,
            name=self.name,
            max_rows=max_rows,
            allow_large=allow_large,
        )
        return _data_array_to_long_polars(array, self.name, np, pl)

    def to_pandas(
        self,
        *,
        layout: PolarsLayout = "auto",
        max_rows: int | None = DEFAULT_MAX_POLARS_ROWS,
        allow_large: bool = False,
    ):
        return self.to_polars(
            layout=layout,
            max_rows=max_rows,
            allow_large=allow_large,
        ).to_pandas()

    def sel(self, *args: Any, **kwargs: Any) -> SopranArray:
        return self._with_xarray(self.to_xarray().sel(*args, **kwargs))

    def where(self, *args: Any, **kwargs: Any) -> SopranArray:
        return self._with_xarray(self.to_xarray().where(*args, **kwargs))

    def transform(
        self,
        frame: str,
        *,
        context: Any | None = None,
        source_frame: str | None = None,
        backend: str | None = None,
    ) -> SopranArray:
        if context is None:
            from sopran.frames import FrameContext

            context = FrameContext()
        transform_array = getattr(context, "transform_array", None)
        if not callable(transform_array):
            raise TypeError("context must expose transform_array(array, target_frame, ...)")
        return transform_array(
            self,
            frame,
            source_frame=source_frame,
            backend=backend,
        )

    def mean(self, *args: Any, **kwargs: Any) -> SopranArray:
        return self._with_xarray(self.to_xarray().mean(*args, **kwargs))

    def resample(self, *args: Any, **kwargs: Any) -> SopranArrayResampler:
        return SopranArrayResampler(
            parent=self,
            resampler=self.to_xarray().resample(*args, **kwargs),
            parameters={str(key): value for key, value in kwargs.items()},
        )

    def resample_like(
        self,
        target: Any,
        *,
        method: str = "nearest",
        tolerance: str | timedelta | None = None,
        time: str = "time",
    ) -> SopranArray:
        from sopran.core.resampling import resample_like

        return resample_like(
            self,
            target,
            method=method,  # type: ignore[arg-type]
            tolerance=tolerance,
            time=time,
        )

    def peak_trace(
        self,
        *,
        axis: str,
        time: str = "time",
        method: Literal["max", "prominence"] = "max",
        max_peaks: int = 1,
        min_value: float | None = None,
        min_prominence: float | None = None,
        reduction: str = "sum",
        name: str | None = None,
    ) -> SopranArray:
        if max_peaks < 1:
            raise ValueError("max_peaks must be at least 1")
        if method not in ("max", "prominence"):
            raise ValueError("method must be 'max' or 'prominence'")

        import numpy as np
        import xarray as xr

        array = self.to_xarray()
        _require_dims(array, (time, axis), "peak_trace")
        reduce_dims = tuple(dim for dim in _dims(array) if dim not in {time, axis})
        if reduce_dims:
            array = _reduce_xarray(array, reduce_dims, reduction)
        array = array.transpose(time, axis)
        values = np.asarray(array.values, dtype=float)
        if values.ndim != 2:
            raise ValueError(f"peak_trace expects 2D reduced data, got shape {values.shape}")

        axis_values = _numeric_coord_values(array, axis, np)
        peak_values = np.full((values.shape[0], max_peaks), np.nan, dtype=float)
        for index, row in enumerate(values):
            selected = _peak_indices(
                row,
                np,
                method=method,
                max_peaks=max_peaks,
                min_value=min_value,
                min_prominence=min_prominence,
            )
            peak_values[index, : len(selected)] = axis_values[selected]

        output_name = name or (
            f"{self.name}_{axis}_peak" if max_peaks == 1 else f"{self.name}_{axis}_peaks"
        )
        time_coord = array.coords[time] if hasattr(array, "coords") and time in array.coords else (
            time,
            np.arange(values.shape[0]),
        )
        dims: tuple[str, ...]
        if max_peaks == 1:
            xr_array = xr.DataArray(
                peak_values[:, 0],
                dims=(time,),
                coords={time: time_coord},
                name=output_name,
            )
            dims = (time,)
        else:
            xr_array = xr.DataArray(
                peak_values,
                dims=(time, "peak"),
                coords={time: time_coord, "peak": np.arange(max_peaks)},
                name=output_name,
            )
            dims = (time, "peak")
        schema = VariableSchema(
            name=output_name,
            dims=dims,
            units=_coord_units(array, axis),
            frame=self.schema.frame,
            description=f"{self.name} {axis} peak coordinate trace.",
        )
        return SopranArray(
            name=output_name,
            time=self.time,
            schema=schema,
            files=self.files,
            operations=(
                *self.operations,
                {
                    "operation": "peak_trace",
                    "parameters": {
                        "axis": axis,
                        "time": time,
                        "method": method,
                        "max_peaks": max_peaks,
                        "min_value": min_value,
                        "min_prominence": min_prominence,
                        "reduction": reduction,
                    },
                },
            ),
            xr=xr_array,
        )

    def detect_peaks(self, **kwargs: Any) -> SopranArray:
        return self.peak_trace(**kwargs)

    def write_parquet(
        self,
        store: Any,
        *,
        dataset_id: str | None = None,
        layer: str = "normalized",
        mission: str = "analysis",
        instrument: str = "loaded_array",
        product: str | None = None,
        shard_path: str = "shards/part-000.parquet",
        compression: str = "zstd",
        overwrite: bool = False,
        append: bool = False,
        source_datasets: tuple[str, ...] = (),
        producer: str = "sopran",
        provenance: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
        context: Any | None = None,
        status: str = "candidate",
        dataset_version: str = "1",
        partitioning: tuple[str, ...] = (),
    ):
        product_name = product or self.name
        schema = InstrumentSchema(
            mission=mission,
            instrument=instrument,
            variables=(self.schema,),
        )
        return store.write_parquet_dataset(
            dataset_id=dataset_id or f"{mission}.{instrument}.{product_name}",
            layer=layer,
            mission=mission,
            instrument=instrument,
            product=product_name,
            schema=schema,
            time_coverage=self.time,
            frame=self.to_polars(),
            source_files=tuple(str(path) for path in self.files),
            source_datasets=source_datasets,
            shard_path=shard_path,
            compression=compression,
            overwrite=overwrite,
            append=append,
            producer=producer,
            provenance=provenance,
            parameters=_metadata_with_operations(parameters, self.operations),
            context=context,
            status=status,
            dataset_version=dataset_version,
            partitioning=partitioning,
        )

    def plot(
        self,
        *args: Any,
        mode: PlotMode = "auto",
        backend: str = "matplotlib",
        dataset_id: str | None = None,
        time_range: Any | None = None,
        frame: str | None = None,
        aggregation: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        context: Any | None = None,
        figsize: tuple[float, float] | None = None,
        configure: Any | None = None,
        x: str = "time",
        y: str | None = None,
        pitch: Any | None = None,
        energy: Any | None = None,
        log_color: bool = False,
        reduction: str = "sum",
        **kwargs: Any,
    ) -> Any:
        if mode == "raw":
            if self.xr is not None and hasattr(self.xr, "plot"):
                return self.xr.plot(*args, **kwargs)
            return None
        if args or kwargs:
            raise TypeError(
                "SopranArray.plot(mode='auto') does not accept raw xarray plot "
                "arguments. Use mode='raw' for direct xarray plotting."
            )

        from sopran.core.plotting import stack

        return stack(
            *self.plot_items(
                mode=mode,
                x=x,
                y=y,
                pitch=pitch,
                energy=energy,
                log_color=log_color,
                reduction=reduction,
            )
        ).plot(
            backend=backend,  # type: ignore[arg-type]
            dataset_id=dataset_id or self.name,
            time_range=time_range or self.time,
            frame=frame or self.schema.frame,
            aggregation=aggregation,
            metadata=_metadata_with_operations(metadata, self.operations),
            context=context,
            figsize=figsize,
            configure=configure,
        )

    def plot_items(
        self,
        *,
        mode: PlotMode = "auto",
        x: str = "time",
        y: str | None = None,
        pitch: Any | None = None,
        energy: Any | None = None,
        log_color: bool = False,
        reduction: str = "sum",
        name: str | None = None,
    ) -> tuple[Any, ...]:
        if mode == "raw":
            raise ValueError("mode='raw' is only supported by SopranArray.plot()")
        if mode == "line":
            return (self.line(x=_line_x(self.to_xarray(), x), name=name),)
        if mode == "spectrogram":
            array = self.to_xarray()
            resolved_x = _plot_x(array, x)
            return (
                self.spectrogram(
                    x=resolved_x,
                    y=y or _infer_spectrogram_y(array, x=resolved_x),
                    name=name,
                    reduction=reduction,
                    log_color=log_color,
                ),
            )
        if mode == "pitch":
            return (
                self.pitch_spectrogram(
                    x=x,
                    energy=energy,
                    reduction=reduction,
                    log_color=log_color,
                    name=name,
                ),
            )
        if mode == "energy":
            return (
                self.energy_spectrogram(
                    x=x,
                    pitch=pitch,
                    reduction=reduction,
                    log_color=log_color,
                    name=name,
                ),
            )
        if mode != "auto":
            raise ValueError(
                "mode must be 'auto', 'line', 'spectrogram', 'pitch', 'energy', or 'raw'"
            )

        array = self.to_xarray()
        dims = _dims(array)
        if {"time", "energy", "pitch_angle"}.issubset(dims):
            return (
                self.pitch_spectrogram(
                    x=x,
                    energy=energy,
                    reduction=reduction,
                    log_color=log_color,
                    name=name or f"{self.name}_pitch",
                ),
                self.energy_spectrogram(
                    x=x,
                    pitch=pitch,
                    reduction=reduction,
                    log_color=log_color,
                    name=name or f"{self.name}_energy",
                ),
            )
        if len(dims) <= 1:
            return (self.line(x=_line_x(array, x), name=name),)
        return (
            self.spectrogram(
                x=_plot_x(array, x),
                y=y or _infer_spectrogram_y(array, x=_plot_x(array, x)),
                name=name,
                reduction=reduction,
                log_color=log_color,
            ),
        )

    def line(self, *, x: str = "time", name: str | None = None):
        from sopran.core.plotting import line

        return line(self.to_xarray(), x=x, name=name or self.name)

    def lines(
        self,
        *,
        x: str = "time",
        components: str | tuple[str, ...] | list[str] | None = None,
        component_dim: str = "component",
        name: str | None = None,
    ):
        from sopran.core.plotting import lines

        return lines(
            self.to_xarray(),
            x=x,
            components=components,
            component_dim=component_dim,
            name=name or self.name,
        )

    def histogram(self, *, bins: int | str = 50, name: str | None = None):
        from sopran.core.plotting import histogram

        return histogram(self.to_xarray(), bins=bins, name=name or self.name)

    def pitch_spectrogram(
        self,
        *,
        x: str = "time",
        pitch_dim: str = "pitch_angle",
        energy_dim: str = "energy",
        energy: Any | None = None,
        reduction: str = "sum",
        log_color: bool = False,
        name: str | None = None,
    ):
        from sopran.core.plotting import spectrogram

        array = self.to_xarray()
        _require_dims(array, (x, pitch_dim), "pitch_spectrogram")
        if energy is not None:
            array = _select_coordinate_range(array, energy_dim, energy)
        reduce_dims = tuple(dim for dim in _dims(array) if dim not in {x, pitch_dim})
        if reduce_dims:
            array = _reduce_xarray(array, reduce_dims, reduction)
        return spectrogram(
            array,
            x=x,
            y=pitch_dim,
            name=name or f"{self.name}_pitch",
            log_color=log_color,
        )

    def energy_spectrogram(
        self,
        *,
        x: str = "time",
        energy_dim: str = "energy",
        pitch_dim: str = "pitch_angle",
        pitch: Any | None = None,
        reduction: str = "sum",
        log_color: bool = False,
        name: str | None = None,
    ):
        from sopran.core.plotting import spectrogram

        array = self.to_xarray()
        _require_dims(array, (x, energy_dim), "energy_spectrogram")
        if pitch is not None:
            array = _select_coordinate_range(array, pitch_dim, pitch)
        reduce_dims = tuple(dim for dim in _dims(array) if dim not in {x, energy_dim})
        if reduce_dims:
            array = _reduce_xarray(array, reduce_dims, reduction)
        return spectrogram(
            array,
            x=x,
            y=energy_dim,
            name=name or f"{self.name}_energy",
            log_color=log_color,
        )

    def quicklook(
        self,
        name: str | None = None,
        *,
        root: str | Path = ".",
        formats: tuple[str, ...] = ("png",),
        backend: str = "matplotlib",
        x: str = "time",
        y: str | None = None,
        log_color: bool = False,
        reduce_dims: tuple[str, ...] | None = None,
        reduction: str = "sum",
        frame: str | None = None,
        aggregation: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        context: Any | None = None,
        figsize: tuple[float, float] | None = None,
        configure: Any | None = None,
        mode: PlotMode = "auto",
        pitch: Any | None = None,
        energy: Any | None = None,
    ):
        from sopran.core.plotting import stack

        quicklook_name = name or self.name
        items = (
            (
                self.spectrogram(
                    x=x,
                    y=y,
                    log_color=log_color,
                    reduce_dims=reduce_dims,
                    reduction=reduction,
                ),
            )
            if y is not None
            else self.plot_items(
                mode=mode,
                x=x,
                pitch=pitch,
                energy=energy,
                log_color=log_color,
                reduction=reduction,
            )
        )
        return stack(*items).quicklook(
            quicklook_name,
            root=root,
            formats=formats,
            backend=backend,  # type: ignore[arg-type]
            dataset_id=self.name,
            time_range=self.time,
            frame=frame or self.schema.frame,
            aggregation=aggregation,
            metadata=_metadata_with_operations(metadata, self.operations),
            context=context,
            figsize=figsize,
            configure=configure,
        )

    def spectrogram(
        self,
        *,
        y: str,
        x: str = "time",
        name: str | None = None,
        reduce_dims: tuple[str, ...] | None = None,
        reduction: str = "sum",
        log_color: bool = False,
    ):
        from sopran.core.plotting import spectrogram

        array = self.to_xarray()
        if reduce_dims is None and hasattr(array, "dims"):
            reduce_dims = tuple(dim for dim in array.dims if dim not in {x, y})
        if reduce_dims:
            array = getattr(array, reduction)(reduce_dims)
        return spectrogram(array, x=x, y=y, name=name or self.name, log_color=log_color)

    def _with_xarray(
        self,
        array: Any,
        *,
        operation: dict[str, Any] | None = None,
    ) -> SopranArray:
        name = str(getattr(array, "name", None) or self.name)
        dims = tuple(str(dim) for dim in getattr(array, "dims", self.schema.dims))
        schema = replace(self.schema, name=name, dims=dims)
        operations = self.operations if operation is None else (*self.operations, operation)
        return SopranArray(
            name=name,
            time=self.time,
            schema=schema,
            files=self.files,
            operations=operations,
            xr=array,
        )


@dataclass(frozen=True)
class SopranArrayResampler:
    parent: SopranArray
    resampler: Any
    parameters: dict[str, Any]

    def mean(self, *args: Any, **kwargs: Any) -> SopranArray:
        return self._reduce("mean", *args, **kwargs)

    def sum(self, *args: Any, **kwargs: Any) -> SopranArray:
        return self._reduce("sum", *args, **kwargs)

    def median(self, *args: Any, **kwargs: Any) -> SopranArray:
        return self._reduce("median", *args, **kwargs)

    def max(self, *args: Any, **kwargs: Any) -> SopranArray:
        return self._reduce("max", *args, **kwargs)

    def first(self, *args: Any, **kwargs: Any) -> SopranArray:
        return self._reduce("first", *args, **kwargs)

    def last(self, *args: Any, **kwargs: Any) -> SopranArray:
        return self._reduce("last", *args, **kwargs)

    def _reduce(self, method: str, *args: Any, **kwargs: Any) -> SopranArray:
        reduction = getattr(self.resampler, method)
        return self.parent._with_xarray(
            reduction(*args, **kwargs),
            operation={
                "operation": "resample",
                "parameters": dict(self.parameters),
                "reducer": method,
            },
        )


def _metadata_with_operations(
    metadata: dict[str, Any] | None,
    operations: tuple[dict[str, Any], ...],
) -> dict[str, Any] | None:
    if not operations:
        return metadata
    merged = dict(metadata or {})
    merged.setdefault("operations", [dict(operation) for operation in operations])
    return merged


def _dims(array: Any) -> tuple[str, ...]:
    return tuple(str(dim) for dim in getattr(array, "dims", ()))


def _plot_x(array: Any, requested: str) -> str:
    dims = _dims(array)
    if requested in dims or not dims:
        return requested
    return dims[0]


def _line_x(array: Any, requested: str) -> str:
    return _plot_x(array, requested)


def _infer_spectrogram_y(array: Any, *, x: str) -> str:
    dims = _dims(array)
    for preferred in ("energy", "pitch_angle", "look"):
        if preferred in dims and preferred != x:
            return preferred
    for dim in dims:
        if dim != x:
            return dim
    raise ValueError("spectrogram requires at least two dimensions")


def _numeric_coord_values(array: Any, dim: str, np: Any) -> Any:
    if hasattr(array, "coords") and dim in array.coords:
        values = array.coords[dim].values
    else:
        values = np.arange(array.shape[array.dims.index(dim)])
    try:
        return np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"peak_trace requires numeric coordinate values for {dim}") from exc


def _coord_units(array: Any, dim: str) -> str | None:
    if hasattr(array, "coords") and dim in array.coords:
        units = getattr(array.coords[dim], "attrs", {}).get("units")
        if units is not None:
            return str(units)
    return None


def _peak_indices(
    row: Any,
    np: Any,
    *,
    method: str,
    max_peaks: int,
    min_value: float | None,
    min_prominence: float | None,
) -> Any:
    if method == "prominence" or min_prominence is not None:
        candidates = _prominent_peak_indices(row, np, min_prominence=min_prominence)
    else:
        candidates = np.flatnonzero(np.isfinite(row))
    if min_value is not None:
        candidates = candidates[row[candidates] >= min_value]
    if candidates.size == 0:
        return candidates
    order = np.argsort(row[candidates])[::-1]
    return candidates[order[:max_peaks]]


def _prominent_peak_indices(row: Any, np: Any, *, min_prominence: float | None) -> Any:
    try:
        from scipy.signal import find_peaks  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "scipy is required for peak_trace(method='prominence'). "
            "Use method='max' or install sopran[full]."
        ) from exc
    finite_row = np.asarray(row, dtype=float)
    finite_row = np.where(np.isfinite(finite_row), finite_row, -np.inf)
    peaks, _ = find_peaks(finite_row, prominence=min_prominence)
    return peaks


def _require_dims(array: Any, required: tuple[str, ...], method: str) -> None:
    dims = set(_dims(array))
    missing = [dim for dim in required if dim not in dims]
    if missing:
        raise ValueError(
            f"{method} requires dimensions {', '.join(required)}; "
            f"missing {', '.join(missing)}"
        )


def _select_coordinate_range(array: Any, dim: str, selection: Any) -> Any:
    _require_dims(array, (dim,), "coordinate range selection")
    if isinstance(selection, slice):
        return array.sel({dim: selection})
    try:
        start, stop = selection
    except TypeError as exc:
        raise TypeError("range selection must be a slice or a two-value tuple") from exc
    if start > stop:
        start, stop = stop, start
    return array.sel({dim: slice(start, stop)})


def _reduce_xarray(array: Any, dims: tuple[str, ...], reduction: str) -> Any:
    reducer = getattr(array, reduction, None)
    if not callable(reducer):
        raise ValueError(f"Unsupported reduction: {reduction}")
    return reducer(dims)


def ensure_polars_row_limit(
    rows: int,
    *,
    name: str,
    max_rows: int | None = DEFAULT_MAX_POLARS_ROWS,
    allow_large: bool = False,
) -> None:
    if max_rows is None or allow_large or rows <= max_rows:
        return
    raise ValueError(
        f"{name}.to_polars() would create {rows} rows. "
        "Use to_xarray() for dense multidimensional data, reduce a dimension first, "
        "or pass allow_large=True if this long table is intentional."
    )


def _resolve_polars_layout(values: Any, layout: PolarsLayout) -> Literal["array", "long"]:
    if layout == "auto":
        return "array" if getattr(values, "ndim", 0) >= 3 else "long"
    if layout in ("array", "long"):
        return layout
    raise ValueError("layout must be 'auto', 'array', or 'long'")


def _data_array_to_array_polars(array: Any, name: str, np: Any, pl: Any):
    values = np.asarray(array.values)
    if values.ndim < 2:
        return _data_array_to_long_polars(array, name, np, pl)

    dims = tuple(array.dims)
    leading_dim = dims[0]
    leading_values = (
        np.asarray(array.coords[leading_dim].values)
        if hasattr(array, "coords") and leading_dim in array.coords
        else np.arange(values.shape[0])
    )
    dtype = pl.Array(_polars_inner_dtype(values, np, pl), shape=values.shape[1:])
    return pl.DataFrame(
        {
            leading_dim: leading_values,
            name: pl.Series(name, values, dtype=dtype),
        }
    )


def _data_array_to_long_polars(array: Any, name: str, np: Any, pl: Any):
    dims = tuple(array.dims)
    values = np.asarray(array.values)
    columns: dict[str, Any] = {}
    for axis, dim in enumerate(dims):
        coord_values = (
            np.asarray(array.coords[dim].values)
            if hasattr(array, "coords") and dim in array.coords
            else np.arange(values.shape[axis])
        )
        repeat = int(np.prod(values.shape[axis + 1 :], dtype=int))
        tile = int(np.prod(values.shape[:axis], dtype=int))
        columns[dim] = np.tile(np.repeat(coord_values, repeat), tile)
    columns[name] = values.reshape(-1)
    return pl.DataFrame(columns)


def _polars_inner_dtype(values: Any, np: Any, pl: Any):
    dtype = np.asarray(values).dtype
    if np.issubdtype(dtype, np.floating):
        return pl.Float32 if dtype == np.dtype("float32") else pl.Float64
    if np.issubdtype(dtype, np.signedinteger):
        if dtype.itemsize <= 1:
            return pl.Int8
        if dtype.itemsize <= 2:
            return pl.Int16
        if dtype.itemsize <= 4:
            return pl.Int32
        return pl.Int64
    if np.issubdtype(dtype, np.unsignedinteger):
        if dtype.itemsize <= 1:
            return pl.UInt8
        if dtype.itemsize <= 2:
            return pl.UInt16
        if dtype.itemsize <= 4:
            return pl.UInt32
        return pl.UInt64
    if np.issubdtype(dtype, np.bool_):
        return pl.Boolean
    return pl.Object
