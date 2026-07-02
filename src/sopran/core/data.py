from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sopran.core.pages import InfoPage
from sopran.core.schema import VariableSchema
from sopran.core.time import TimeRange


@dataclass(frozen=True)
class SopranArray:
    """Thin variable object for loaded SOPRAN data."""

    name: str
    time: TimeRange
    schema: VariableSchema
    files: tuple[Path, ...] = ()
    xr: Any = None

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

    def plot(self, *args: Any, **kwargs: Any) -> Any:
        if self.xr is not None and hasattr(self.xr, "plot"):
            return self.xr.plot(*args, **kwargs)
        return None

    def line(self, *, x: str = "time", name: str | None = None):
        from sopran.core.plotting import line

        return line(self.to_xarray(), x=x, name=name or self.name)

    def quicklook(
        self,
        name: str | None = None,
        *,
        root: str | Path = ".",
        formats: tuple[str, ...] = ("png",),
        backend: str = "matplotlib",
        x: str = "time",
        frame: str | None = None,
        aggregation: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        context: Any | None = None,
        figsize: tuple[float, float] | None = None,
    ):
        from sopran.core.plotting import stack

        quicklook_name = name or self.name
        return stack(self.line(x=x)).quicklook(
            quicklook_name,
            root=root,
            formats=formats,
            backend=backend,  # type: ignore[arg-type]
            dataset_id=self.name,
            time_range=self.time,
            frame=frame or self.schema.frame,
            aggregation=aggregation,
            metadata=metadata,
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
