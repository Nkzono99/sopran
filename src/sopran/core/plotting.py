from __future__ import annotations

import base64
import html
from io import BytesIO
import json
from dataclasses import dataclass, field
from pathlib import Path
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
class PlotArtifact:
    path: Path
    format: str


@dataclass(frozen=True)
class PlotResult:
    fig: Any
    axes: tuple[Any, ...]
    backend: str
    artifacts: tuple[PlotArtifact, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QuicklookResult:
    name: str
    artifacts: tuple[PlotArtifact, ...]
    metadata_path: Path
    metadata: dict[str, Any]


@dataclass(frozen=True)
class PlotStack:
    items: tuple[PlotItem, ...]

    def plan(self) -> PlotPlan:
        return PlotPlan(
            panel_count=len(self.items),
            items=tuple(item.name for item in self.items),
        )

    def plot(
        self,
        *,
        backend: Literal["matplotlib"] = "matplotlib",
        figsize: tuple[float, float] | None = None,
    ) -> PlotResult:
        if not self.items:
            raise ValueError("PlotStack requires at least one item")
        if backend != "matplotlib":
            raise ValueError("PlotStack.plot() currently supports only matplotlib")

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
        plan = self.plan()
        return PlotResult(
            fig=fig,
            axes=tuple(axes),
            backend=backend,
            metadata={
                "backend": backend,
                "panel_count": plan.panel_count,
                "items": list(plan.items),
            },
        )

    def quicklook(
        self,
        name: str,
        *,
        root: str | Path = ".",
        formats: tuple[str, ...] = ("png",),
        backend: Literal["matplotlib"] = "matplotlib",
        metadata: dict[str, Any] | None = None,
        figsize: tuple[float, float] | None = None,
    ) -> QuicklookResult:
        target_root = Path(root)
        target_root.mkdir(parents=True, exist_ok=True)
        if backend != "matplotlib":
            raise ValueError("PlotStack.quicklook() currently supports only matplotlib")
        plot_result = self.plot(backend=backend, figsize=figsize)
        fig = plot_result.fig
        plan = self.plan()
        artifacts = tuple(
            PlotArtifact(path=target_root / f"{name}.{format_name}", format=format_name)
            for format_name in formats
        )
        payload = {
            "name": name,
            "backend": backend,
            "panel_count": plan.panel_count,
            "items": list(plan.items),
            "artifacts": [artifact.path.name for artifact in artifacts],
            "artifact_formats": [artifact.format for artifact in artifacts],
        }
        if metadata:
            payload["metadata"] = metadata
        for artifact in artifacts:
            if artifact.format == "png":
                fig.savefig(artifact.path)
            elif artifact.format == "html":
                artifact.path.write_text(
                    _html_quicklook(name=name, fig=fig, metadata=payload),
                    encoding="utf-8",
                )
            else:
                raise ValueError("PlotStack.quicklook() currently supports png and html")
        metadata_path = target_root / f"{name}.json"
        metadata_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return QuicklookResult(
            name=name,
            artifacts=artifacts,
            metadata_path=metadata_path,
            metadata=payload,
        )


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
    data = _materialize(item.data)
    if hasattr(data, "transpose") and hasattr(data, "dims") and item.x in data.dims:
        remaining_dims = [dim for dim in data.dims if dim != item.x]
        data = data.transpose(item.x, *remaining_dims)
    values = _values(data)
    if values.ndim not in (1, 2):
        raise ValueError(f"Line plot expects 1D or 2D data, got shape {values.shape}")
    return _coord(data, item.x, axis=0), values


def _spectrogram_xyz(item: PlotItem) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if item.y is None:
        raise ValueError("Spectrogram plot requires a y coordinate name")

    data = _materialize(item.data)
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


def _materialize(data: Any) -> Any:
    if callable(data):
        data = data()
    if hasattr(data, "to_xarray"):
        return data.to_xarray()
    return data


def _coord(data: Any, name: str, *, axis: int) -> np.ndarray:
    if hasattr(data, "coords") and name in data.coords:
        return np.asarray(data.coords[name].values)
    return np.arange(_values(data).shape[axis])


def _html_quicklook(*, name: str, fig: Any, metadata: dict[str, Any]) -> str:
    image_buffer = BytesIO()
    fig.savefig(image_buffer, format="png")
    encoded_image = base64.b64encode(image_buffer.getvalue()).decode("ascii")
    escaped_name = html.escape(name, quote=True)
    metadata_json = json.dumps(metadata, indent=2, sort_keys=True)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        f"  <title>{escaped_name}</title>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{escaped_name}</h1>\n"
        f'  <img alt="{escaped_name}" src="data:image/png;base64,{encoded_image}">\n'
        "  <h2>Metadata</h2>\n"
        f"  <pre>{html.escape(metadata_json)}</pre>\n"
        "</body>\n"
        "</html>\n"
    )


def _data_name(data: Any) -> str:
    name = getattr(data, "name", None)
    if name:
        return str(name)
    return "data"
