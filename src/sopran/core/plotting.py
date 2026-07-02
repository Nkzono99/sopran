from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np


PlotKind = Literal["line", "spectrogram"]


@dataclass(frozen=True)
class PlotItem:
    kind: PlotKind
    data: Any
    name: str
    x: str = "time"
    y: str | None = None


@dataclass(frozen=True)
class PlotPlan:
    panel_count: int
    items: tuple[str, ...]


@dataclass(frozen=True)
class PlotStack:
    items: tuple[PlotItem, ...]

    def plan(self) -> PlotPlan:
        return PlotPlan(
            panel_count=len(self.items),
            items=tuple(item.name for item in self.items),
        )

    def plot(self, *, figsize: tuple[float, float] | None = None) -> Any:
        if not self.items:
            raise ValueError("PlotStack requires at least one item")

        import matplotlib.pyplot as plt

        size = figsize or (8.0, max(2.0, 2.2 * len(self.items)))
        fig, axes_grid = plt.subplots(
            len(self.items),
            1,
            sharex=True,
            figsize=size,
            squeeze=False,
        )
        axes = axes_grid[:, 0]

        for axis, item in zip(axes, self.items, strict=True):
            if item.kind == "line":
                x_values, y_values = _line_xy(item)
                axis.plot(x_values, y_values)
            elif item.kind == "spectrogram":
                x_values, y_values, z_values = _spectrogram_xyz(item)
                axis.pcolormesh(x_values, y_values, z_values.T, shading="auto")
            else:
                raise ValueError(f"Unsupported plot item kind: {item.kind}")
            axis.set_ylabel(item.name)

        axes[-1].set_xlabel("time")
        fig.autofmt_xdate()
        fig.tight_layout()
        return fig


def stack(*items: PlotItem) -> PlotStack:
    return PlotStack(items=tuple(items))


def line(data: Any, *, x: str = "time", name: str | None = None) -> PlotItem:
    return PlotItem(
        kind="line",
        data=data,
        name=name or _data_name(data),
        x=x,
    )


def spectrogram(
    data: Any,
    *,
    y: str,
    x: str = "time",
    name: str | None = None,
) -> PlotItem:
    return PlotItem(
        kind="spectrogram",
        data=data,
        name=name or _data_name(data),
        x=x,
        y=y,
    )


def _line_xy(item: PlotItem) -> tuple[np.ndarray, np.ndarray]:
    data = item.data
    values = _values(data)
    if values.ndim != 1:
        raise ValueError(f"Line plot expects 1D data, got shape {values.shape}")
    return _coord(data, item.x, axis=0), values


def _spectrogram_xyz(item: PlotItem) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if item.y is None:
        raise ValueError("Spectrogram plot requires a y coordinate name")

    data = item.data
    if hasattr(data, "transpose") and hasattr(data, "dims"):
        data = data.transpose(item.x, item.y)

    values = _values(data)
    if values.ndim != 2:
        raise ValueError(f"Spectrogram plot expects 2D data, got shape {values.shape}")
    return _coord(data, item.x, axis=0), _coord(data, item.y, axis=1), values


def _values(data: Any) -> np.ndarray:
    if hasattr(data, "values"):
        return np.asarray(data.values)
    return np.asarray(data)


def _coord(data: Any, name: str, *, axis: int) -> np.ndarray:
    if hasattr(data, "coords") and name in data.coords:
        return np.asarray(data.coords[name].values)
    return np.arange(_values(data).shape[axis])


def _data_name(data: Any) -> str:
    name = getattr(data, "name", None)
    if name:
        return str(name)
    return "data"
