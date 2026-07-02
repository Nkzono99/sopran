from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

    def info(self) -> str:
        return f"{self.name}: dims={self.schema.dims}, units={self.schema.units}"

    def to_xarray(self) -> Any:
        if self.xr is None:
            raise ValueError(f"{self.name} is not loaded as an xarray DataArray")
        return self.xr

    def plot(self, *args: Any, **kwargs: Any) -> Any:
        if self.xr is not None and hasattr(self.xr, "plot"):
            return self.xr.plot(*args, **kwargs)
        return None

    def line(self, *, x: str = "time", name: str | None = None):
        from sopran.core.plotting import line

        return line(self.to_xarray(), x=x, name=name or self.name)

    def spectrogram(
        self,
        *,
        y: str,
        x: str = "time",
        name: str | None = None,
        reduce_dims: tuple[str, ...] | None = None,
        reduction: str = "sum",
    ):
        from sopran.core.plotting import spectrogram

        array = self.to_xarray()
        if reduce_dims is None and hasattr(array, "dims"):
            reduce_dims = tuple(dim for dim in array.dims if dim not in {x, y})
        if reduce_dims:
            array = getattr(array, reduction)(reduce_dims)
        return spectrogram(array, x=x, y=y, name=name or self.name)
