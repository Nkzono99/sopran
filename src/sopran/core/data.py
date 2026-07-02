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

    def plot(self, *args: Any, **kwargs: Any) -> Any:
        if self.xr is not None and hasattr(self.xr, "plot"):
            return self.xr.plot(*args, **kwargs)
        return None
