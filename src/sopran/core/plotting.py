from __future__ import annotations

import base64
import html
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np

PlotKind = Literal["line", "spectrogram", "histogram"]
OverlayKind = Literal["line"]


@dataclass(frozen=True)
class PlotOverlay:
    kind: OverlayKind
    data: Any
    name: str
    x: str = "time"
    color: str | None = None
    linestyle: str = "-"


@dataclass(frozen=True)
class PlotItem:
    kind: PlotKind
    data: Any
    name: str
    x: str = "time"
    y: str | None = None
    x_label: str | None = None
    y_label: str | None = None
    value_label: str | None = None
    log_color: bool = False
    yscale: str | None = None
    ylim: tuple[float, float] | None = None
    vmin: float | None = None
    vmax: float | None = None
    bins: int | str | None = None
    overlays: tuple[PlotOverlay, ...] = ()

    def overlay(
        self,
        overlay: PlotItem | Any,
        *,
        x: str | None = None,
        name: str | None = None,
        color: str | None = None,
        linestyle: str = "-",
    ) -> PlotItem:
        if isinstance(overlay, PlotItem):
            if overlay.kind != "line":
                raise ValueError("Only line PlotItem overlays are supported")
            item = PlotOverlay(
                kind="line",
                data=overlay.data,
                name=name or overlay.name,
                x=x or overlay.x,
                color=color,
                linestyle=linestyle,
            )
        else:
            item = PlotOverlay(
                kind="line",
                data=overlay,
                name=name or _data_name(overlay),
                x=x or self.x,
                color=color,
                linestyle=linestyle,
            )
        return replace(self, overlays=(*self.overlays, item))

    def with_overlay(self, *args: Any, **kwargs: Any) -> PlotItem:
        return self.overlay(*args, **kwargs)


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
    items: tuple[PlotItem, ...] = ()
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
        dataset_id: str | None = None,
        time_range: Any | None = None,
        frame: str | None = None,
        aggregation: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        context: Any | None = None,
        figsize: tuple[float, float] | None = None,
        configure: Any | None = None,
    ) -> PlotResult:
        if not self.items:
            raise ValueError("PlotStack requires at least one item")
        if backend != "matplotlib":
            raise ValueError("PlotStack.plot() currently supports only matplotlib")

        import matplotlib.pyplot as plt

        size = figsize or (8.0, max(2.0, 2.2 * len(self.items)))
        share_x_axis = all(item.kind != "histogram" for item in self.items)
        fig, axes_grid = plt.subplots(
            len(self.items),
            1,
            sharex=share_x_axis,
            figsize=size,
            squeeze=False,
        )
        axes = axes_grid[:, 0]

        rendered_panels: list[dict[str, Any]] = []
        last_x_label = "time"
        for axis, item in zip(axes, self.items, strict=True):
            if item.kind == "line":
                x_values, y_values = _line_xy(item)
                axis.plot(x_values, y_values)
                axis.set_ylabel(item.value_label or item.name)
                last_x_label = item.x_label or item.x
                panel_metadata = _panel_metadata_for(item)
            elif item.kind == "spectrogram":
                spectrogram_data = _spectrogram_data(item)
                mesh = axis.pcolormesh(
                    spectrogram_data.x_values,
                    spectrogram_data.y_values,
                    spectrogram_data.z_values.T,
                    norm=_color_norm(item),
                    shading="auto",
                )
                colorbar = fig.colorbar(mesh, ax=axis)
                colorbar.set_label(spectrogram_data.value_label)
                axis.set_ylabel(spectrogram_data.y_label)
                if item.yscale is not None:
                    axis.set_yscale(item.yscale)
                if item.ylim is not None:
                    axis.set_ylim(item.ylim)
                last_x_label = spectrogram_data.x_label
                panel_metadata = _panel_metadata_for(
                    item,
                    x_label=spectrogram_data.x_label,
                    y_label=spectrogram_data.y_label,
                    value_label=spectrogram_data.value_label,
                    colorbar_label=spectrogram_data.value_label,
                )
            elif item.kind == "histogram":
                values = _histogram_values(item)
                axis.hist(values, bins=item.bins or 50)
                axis.set_xlabel(item.name)
                axis.set_ylabel("count")
                panel_metadata = _panel_metadata_for(item)
            else:
                raise ValueError(f"Unsupported plot item kind: {item.kind}")
            _draw_overlays(axis, item)
            rendered_panels.append(panel_metadata)

        if all(item.kind != "histogram" for item in self.items):
            axes[-1].set_xlabel(last_x_label)
        fig.autofmt_xdate()
        fig.tight_layout()
        plan = self.plan()
        metadata_payload = {
            "backend": backend,
            "panel_count": plan.panel_count,
            "items": list(plan.items),
            "panel_kinds": _panel_kinds(self.items),
            "panels": rendered_panels,
            "time_axis": _time_axis_metadata(self.items),
        }
        if dataset_id is not None:
            metadata_payload["dataset_id"] = dataset_id
        if time_range is not None:
            metadata_payload["time_range"] = _time_range_metadata(time_range)
        if frame is not None:
            metadata_payload["frame"] = frame
        if aggregation is not None:
            metadata_payload["aggregation"] = _metadata_value(aggregation)
        if metadata:
            metadata_payload["metadata"] = _metadata_value(metadata)
        if context is not None:
            metadata_payload["context"] = _context_metadata(context)
        if configure is not None:
            metadata_payload["customized"] = True
        result = PlotResult(
            fig=fig,
            axes=tuple(axes),
            backend=backend,
            items=self.items,
            metadata=metadata_payload,
        )
        if configure is not None:
            configure(result)
        return result

    def explore(
        self,
        *,
        backend: Literal["panel"] = "panel",
        context: Any | None = None,
        figsize: tuple[float, float] | None = None,
    ) -> Any:
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
        configure: Any | None = None,
    ) -> QuicklookResult:
        target_root = Path(root)
        target_root.mkdir(parents=True, exist_ok=True)
        if backend != "matplotlib":
            raise ValueError("PlotStack.quicklook() currently supports only matplotlib")
        plot_result = self.plot(
            backend=backend,
            dataset_id=dataset_id,
            time_range=time_range,
            frame=frame,
            aggregation=aggregation,
            metadata=metadata,
            context=context,
            figsize=figsize,
            configure=configure,
        )
        fig = plot_result.fig
        plan = self.plan()
        artifacts = tuple(
            PlotArtifact(path=target_root / f"{name}.{format_name}", format=format_name)
            for format_name in formats
        )
        payload = {
            **plot_result.metadata,
            "name": name,
            "backend": backend,
            "panel_count": plan.panel_count,
            "items": list(plan.items),
            "panel_kinds": _panel_kinds(self.items),
            "artifacts": [artifact.path.name for artifact in artifacts],
            "artifact_formats": [artifact.format for artifact in artifacts],
        }
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


def stack(*items: PlotItem | PlotResult) -> PlotStack:
    return PlotStack(items=tuple(_stack_plot_items(items)))


def _stack_plot_items(items: tuple[PlotItem | PlotResult, ...]) -> tuple[PlotItem, ...]:
    flattened: list[PlotItem] = []
    for item in items:
        if isinstance(item, PlotItem):
            flattened.append(item)
            continue
        if isinstance(item, PlotResult):
            if not item.items:
                raise ValueError("PlotResult cannot be stacked because it has no PlotItem metadata")
            flattened.extend(item.items)
            continue
        raise TypeError("spn.stack() expects PlotItem or PlotResult values")
    return tuple(flattened)


def _time_axis_metadata(items: tuple[PlotItem, ...]) -> dict[str, Any]:
    time_items = tuple(item for item in items if item.kind != "histogram")
    coordinates = tuple(dict.fromkeys(item.x for item in time_items))
    metadata: dict[str, Any] = {
        "shared": len(time_items) == len(items),
        "coordinates": list(coordinates),
        "cadence_policy": "native",
    }
    if len(time_items) != len(items):
        metadata["non_time_panels"] = [
            item.name for item in items if item.kind == "histogram"
        ]
    if "time" in coordinates:
        metadata["timezone"] = "UTC"
    return metadata


def _panel_kinds(items: tuple[PlotItem, ...]) -> list[str]:
    return [item.kind for item in items]


def _panel_metadata(items: tuple[PlotItem, ...]) -> list[dict[str, Any]]:
    return [_panel_metadata_for(item) for item in items]


def _panel_metadata_for(
    item: PlotItem,
    *,
    x_label: str | None = None,
    y_label: str | None = None,
    value_label: str | None = None,
    colorbar_label: str | None = None,
) -> dict[str, Any]:
    panel: dict[str, Any] = {
        "name": item.name,
        "kind": item.kind,
        "x": item.x,
        "y": item.y,
        "log_color": item.log_color,
    }
    if item.kind == "spectrogram":
        panel["value"] = item.name
        panel["x_label"] = x_label or item.x_label or item.x
        panel["y_label"] = y_label or item.y_label or item.y
        panel["colorbar_label"] = colorbar_label or value_label or item.value_label or item.name
        if item.yscale is not None:
            panel["yscale"] = item.yscale
        if item.ylim is not None:
            panel["ylim"] = list(item.ylim)
        if item.vmin is not None:
            panel["vmin"] = item.vmin
        if item.vmax is not None:
            panel["vmax"] = item.vmax
    if item.kind == "histogram":
        panel["bins"] = item.bins
    if item.overlays:
        panel["overlays"] = [
            {
                "name": overlay.name,
                "kind": overlay.kind,
                "x": overlay.x,
            }
            for overlay in item.overlays
        ]
    return panel


def line(data: Any, *, x: str = "time", name: str | None = None) -> PlotItem:
    return PlotItem(
        kind="line",
        data=data,
        name=name or _data_name(data),
        x=x,
    )


def lines(
    data: Any,
    *,
    x: str = "time",
    components: str | tuple[str, ...] | list[str] | None = None,
    component_dim: str = "component",
    name: str | None = None,
) -> PlotItem:
    if components is None:
        return line(data, x=x, name=name)
    return PlotItem(
        kind="line",
        data=lambda: _select_components(data, component_dim, components),
        name=name or _data_name(data),
        x=x,
    )


def spectrogram(
    data: Any,
    *,
    y: str,
    x: str = "time",
    name: str | None = None,
    x_label: str | None = None,
    y_label: str | None = None,
    value_label: str | None = None,
    log_color: bool = False,
    yscale: str | None = None,
    ylim: tuple[float, float] | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
) -> PlotItem:
    return PlotItem(
        kind="spectrogram",
        data=data,
        name=name or _data_name(data),
        x=x,
        y=y,
        x_label=x_label,
        y_label=y_label,
        value_label=value_label,
        log_color=log_color,
        yscale=yscale,
        ylim=ylim,
        vmin=vmin,
        vmax=vmax,
    )


def histogram(
    data: Any,
    *,
    bins: int | str = 50,
    name: str | None = None,
) -> PlotItem:
    item_name = name or _data_name(data)
    return PlotItem(
        kind="histogram",
        data=data,
        name=item_name,
        x=item_name,
        bins=bins,
    )


def _line_xy(item: PlotItem) -> tuple[np.ndarray, np.ndarray]:
    return _line_xy_data(item.data, x=item.x)


def _draw_overlays(axis: Any, item: PlotItem) -> None:
    for overlay in item.overlays:
        if overlay.kind != "line":
            raise ValueError(f"Unsupported plot overlay kind: {overlay.kind}")
        x_values, y_values = _line_xy_data(overlay.data, x=overlay.x)
        axis.plot(
            x_values,
            y_values,
            label=overlay.name,
            color=overlay.color,
            linestyle=overlay.linestyle,
        )
    if item.overlays:
        axis.legend(loc="best")


def _line_xy_data(data: Any, *, x: str) -> tuple[np.ndarray, np.ndarray]:
    materialized = _materialize(data)
    if (
        hasattr(materialized, "transpose")
        and hasattr(materialized, "dims")
        and x in materialized.dims
    ):
        remaining_dims = [dim for dim in materialized.dims if dim != x]
        materialized = materialized.transpose(x, *remaining_dims)
    values = _values(materialized)
    if values.ndim not in (1, 2):
        raise ValueError(f"Line plot expects 1D or 2D data, got shape {values.shape}")
    return _coord(materialized, x, axis=0), values


@dataclass(frozen=True)
class _SpectrogramData:
    x_values: np.ndarray
    y_values: np.ndarray
    z_values: np.ndarray
    x_label: str
    y_label: str
    value_label: str


def _spectrogram_data(item: PlotItem) -> _SpectrogramData:
    if item.y is None:
        raise ValueError("Spectrogram plot requires a y coordinate name")

    data = _materialize(item.data)
    if hasattr(data, "transpose") and hasattr(data, "dims"):
        data = data.transpose(item.x, item.y)

    values = _values(data)
    if values.ndim != 2:
        raise ValueError(f"Spectrogram plot expects 2D data, got shape {values.shape}")
    return _SpectrogramData(
        x_values=_coord(data, item.x, axis=0),
        y_values=_coord(data, item.y, axis=1),
        z_values=values,
        x_label=item.x_label or _coordinate_label(data, item.x),
        y_label=item.y_label or _coordinate_label(data, item.y),
        value_label=item.value_label or _value_label(data, item.name),
    )


def _histogram_values(item: PlotItem) -> np.ndarray:
    data = _materialize(item.data)
    values = _values(data)
    if not np.issubdtype(values.dtype, np.number):
        raise ValueError("Histogram plot expects numeric data")
    flattened = np.asarray(values, dtype=float).reshape(-1)
    finite = flattened[np.isfinite(flattened)]
    if finite.size == 0:
        raise ValueError("Histogram plot has no finite numeric values")
    return cast(np.ndarray, finite)


def _color_norm(item: PlotItem) -> Any | None:
    if item.log_color:
        from matplotlib.colors import LogNorm

        if item.vmin is not None and item.vmin <= 0:
            raise ValueError("log_color=True requires vmin to be positive")
        if item.vmax is not None and item.vmax <= 0:
            raise ValueError("log_color=True requires vmax to be positive")
        return LogNorm(vmin=item.vmin, vmax=item.vmax)
    if item.vmin is None and item.vmax is None:
        return None
    from matplotlib.colors import Normalize

    return Normalize(vmin=item.vmin, vmax=item.vmax)


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


def _select_components(
    data: Any,
    component_dim: str,
    components: str | tuple[str, ...] | list[str],
) -> Any:
    materialized = _materialize(data)
    if not hasattr(materialized, "sel"):
        raise ValueError("component selection requires xarray-like data with sel()")
    selection = _component_selection(materialized, component_dim, components)
    return materialized.sel({component_dim: selection})


def _component_selection(
    data: Any,
    component_dim: str,
    components: str | tuple[str, ...] | list[str],
) -> list[str] | str:
    if not isinstance(components, str):
        return [str(component) for component in components]
    requested = components.strip()
    if not requested:
        return []
    coord_values = set()
    if hasattr(data, "coords") and component_dim in data.coords:
        coord_values = {str(value) for value in data.coords[component_dim].values}
    if requested in coord_values:
        return requested
    if "," in requested:
        return [part.strip() for part in requested.split(",") if part.strip()]
    return list(requested)


def _coord(data: Any, name: str, *, axis: int) -> np.ndarray:
    if hasattr(data, "coords") and name in data.coords:
        return cast(np.ndarray, np.asarray(data.coords[name].values))
    return np.arange(_values(data).shape[axis])


def _coordinate_label(data: Any, name: str) -> str:
    units = None
    if hasattr(data, "coords") and name in data.coords:
        units = getattr(data.coords[name], "attrs", {}).get("units")
    return _label_with_units(name, units)


def _value_label(data: Any, name: str) -> str:
    units = getattr(data, "attrs", {}).get("units") if hasattr(data, "attrs") else None
    return _label_with_units(name, units)


def _label_with_units(name: str, units: Any | None) -> str:
    if units is None or str(units) == "":
        return name
    return f"{name} [{units}]"


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
        return cast(dict[str, Any], _metadata_value(context))
    metadata = getattr(context, "metadata", None)
    if callable(metadata):
        metadata = metadata()
    if isinstance(metadata, Mapping):
        return cast(dict[str, Any], _metadata_value(metadata))
    to_metadata = getattr(context, "to_metadata", None)
    if callable(to_metadata):
        metadata = to_metadata()
    if isinstance(metadata, Mapping):
        return cast(dict[str, Any], _metadata_value(metadata))
    raise TypeError("context must be a metadata mapping or expose metadata")


def _data_name(data: Any) -> str:
    name = getattr(data, "name", None)
    if name:
        return str(name)
    return "data"
