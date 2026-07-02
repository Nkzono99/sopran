from __future__ import annotations

import base64
import html
from io import BytesIO
import json
from collections.abc import Mapping
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
    log_color: bool = False


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
        context: Any | None = None,
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
                axis.pcolormesh(
                    x_values,
                    y_values,
                    z_values.T,
                    norm=_color_norm(item),
                    shading="auto",
                )
            else:
                raise ValueError(f"Unsupported plot item kind: {item.kind}")
            axis.set_ylabel(item.name)

        axes[-1].set_xlabel("time")
        fig.autofmt_xdate()
        fig.tight_layout()
        plan = self.plan()
        metadata = {
            "backend": backend,
            "panel_count": plan.panel_count,
            "items": list(plan.items),
            "time_axis": _time_axis_metadata(self.items),
        }
        if context is not None:
            metadata["context"] = _context_metadata(context)
        return PlotResult(
            fig=fig,
            axes=tuple(axes),
            backend=backend,
            metadata=metadata,
        )

    def explore(
        self,
        *,
        backend: Literal["panel"] = "panel",
        context: Any | None = None,
        figsize: tuple[float, float] | None = None,
    ):
        if backend != "panel":
            raise ValueError("PlotStack.explore() currently supports only panel")

        import panel as pn

        plot_result = self.plot(
            backend="matplotlib",
            context=context,
            figsize=figsize,
        )
        metadata = dict(plot_result.metadata)
        metadata["explore_backend"] = backend
        return pn.Column(
            pn.pane.Matplotlib(plot_result.fig, tight=True),
            pn.pane.Markdown(
                "```json\n"
                + json.dumps(metadata, indent=2, sort_keys=True)
                + "\n```"
            ),
        )

    def quicklook(
        self,
        name: str,
        *,
        root: str | Path = ".",
        formats: tuple[str, ...] = ("png",),
        backend: Literal["matplotlib"] = "matplotlib",
        dataset_id: str | None = None,
        time_range: Any | None = None,
        frame: str | None = None,
        aggregation: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        context: Any | None = None,
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
            "time_axis": _time_axis_metadata(self.items),
            "artifacts": [artifact.path.name for artifact in artifacts],
            "artifact_formats": [artifact.format for artifact in artifacts],
        }
        if dataset_id is not None:
            payload["dataset_id"] = dataset_id
        if time_range is not None:
            payload["time_range"] = _time_range_metadata(time_range)
        if frame is not None:
            payload["frame"] = frame
        if aggregation is not None:
            payload["aggregation"] = _metadata_value(aggregation)
        if metadata:
            payload["metadata"] = _metadata_value(metadata)
        if context is not None:
            payload["context"] = _context_metadata(context)
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


def _time_axis_metadata(items: tuple[PlotItem, ...]) -> dict[str, Any]:
    coordinates = tuple(dict.fromkeys(item.x for item in items))
    metadata: dict[str, Any] = {
        "shared": True,
        "coordinates": list(coordinates),
        "cadence_policy": "native",
    }
    if "time" in coordinates:
        metadata["timezone"] = "UTC"
    return metadata


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
    log_color: bool = False,
) -> PlotItem:
    return PlotItem(
        kind="spectrogram",
        data=data,
        name=name or _data_name(data),
        x=x,
        y=y,
        log_color=log_color,
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


def _color_norm(item: PlotItem) -> Any | None:
    if not item.log_color:
        return None
    from matplotlib.colors import LogNorm

    return LogNorm()


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


def _time_range_metadata(time_range: Any) -> dict[str, str] | Any:
    if hasattr(time_range, "start_iso") and hasattr(time_range, "stop_iso"):
        return {
            "start": str(time_range.start_iso),
            "stop": str(time_range.stop_iso),
        }
    return _metadata_value(time_range)


def _metadata_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _metadata_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_metadata_value(item) for item in value]
    if hasattr(value, "start_iso") and hasattr(value, "stop_iso"):
        return _time_range_metadata(value)
    return value


def _context_metadata(context: Any) -> dict[str, Any]:
    if isinstance(context, Mapping):
        return _metadata_value(context)
    metadata = getattr(context, "metadata", None)
    if callable(metadata):
        metadata = metadata()
    if isinstance(metadata, Mapping):
        return _metadata_value(metadata)
    raise TypeError("context must be a metadata mapping or expose metadata")


def _data_name(data: Any) -> str:
    name = getattr(data, "name", None)
    if name:
        return str(name)
    return "data"
