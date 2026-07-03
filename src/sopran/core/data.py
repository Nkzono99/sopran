from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sopran.core.pages import InfoPage
from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.core.time import TimeRange


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

    def to_polars(self):
        try:
            import numpy as np
            import polars as pl
        except ImportError as exc:
            raise RuntimeError("polars is required for SopranArray.to_polars()") from exc

        array = self.to_xarray()
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
        columns[self.name] = values.reshape(-1)
        return pl.DataFrame(columns)

    def to_pandas(self):
        return self.to_polars().to_pandas()

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

    def plot(self, *args: Any, **kwargs: Any) -> Any:
        if self.xr is not None and hasattr(self.xr, "plot"):
            return self.xr.plot(*args, **kwargs)
        return None

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
    ):
        from sopran.core.plotting import stack

        quicklook_name = name or self.name
        item = (
            self.spectrogram(
                x=x,
                y=y,
                log_color=log_color,
                reduce_dims=reduce_dims,
                reduction=reduction,
            )
            if y is not None
            else self.line(x=x)
        )
        return stack(item).quicklook(
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
