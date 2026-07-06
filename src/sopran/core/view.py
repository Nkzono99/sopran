from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, cast

from sopran.core.plotting import PlotItem, PlotStack, line, lines, spectrogram, stack
from sopran.core.time import TimeRange, day, period
from sopran.frames import FrameContext
from sopran.maps import Region

DownloadMode = Literal["never", "missing", "always"]


@dataclass(frozen=True)
class ViewSelection:
    """Scientific subset selected by a SOPRAN view."""

    time: TimeRange | None = None
    region: Region | None = None
    mission: tuple[str, ...] = ()
    instrument: tuple[str, ...] = ()
    product: tuple[str, ...] = ()
    quality: str | None = None

    def metadata(self) -> dict[str, Any]:
        return {
            "time": _time_metadata(self.time),
            "region": self.region.to_metadata() if self.region is not None else None,
            "mission": list(self.mission),
            "instrument": list(self.instrument),
            "product": list(self.product),
            "quality": self.quality,
        }


@dataclass(frozen=True)
class ViewContext:
    """Execution context for delegated libraries and derived products."""

    frame: str | None = None
    cache: bool = False
    download: str | None = None
    backend_policy: str = "auto"
    backends: Mapping[str, str] = field(default_factory=dict)
    spice_kernels: tuple[str | Path, ...] = ()
    time_scale: str = "utc"

    def __post_init__(self) -> None:
        object.__setattr__(self, "backend_policy", str(self.backend_policy))
        object.__setattr__(self, "backends", dict(self.backends))
        object.__setattr__(
            self,
            "spice_kernels",
            tuple(Path(path) for path in self.spice_kernels),
        )
        object.__setattr__(self, "time_scale", self.time_scale.lower())

    def metadata(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "cache": self.cache,
            "download": self.download,
            "backend_policy": self.backend_policy,
            "backends": dict(self.backends),
            "spice_kernels": [path.as_posix() for path in self._spice_kernels],
            "time_scale": self.time_scale,
        }

    @property
    def _spice_kernels(self) -> tuple[Path, ...]:
        return cast(tuple[Path, ...], self.spice_kernels)


@dataclass(frozen=True)
class View:
    """A lightweight lens that binds selection and context to the data tree."""

    project: Any
    selection: ViewSelection = field(default_factory=ViewSelection)
    context: ViewContext = field(default_factory=ViewContext)

    @property
    def time(self) -> TimeRange | None:
        return self.selection.time

    @property
    def region(self) -> Region | None:
        return self.selection.region

    @property
    def frame(self) -> str | None:
        return self.context.frame

    @property
    def cache(self) -> bool:
        return self.context.cache

    @property
    def kaguya(self) -> Any:
        from sopran.missions.kaguya import Kaguya

        return BoundNode(
            Kaguya(store=self.project.store, download=_download_mode(self.context.download)),
            self,
        )

    @property
    def artemis(self) -> Any:
        from sopran.missions.artemis import Artemis

        return BoundNode(Artemis(store=self.project.store), self)

    @property
    def moon(self) -> Any:
        from sopran.bodies import Moon

        return BoundMoon(Moon(), self)

    def with_time(self, time: object, stop: object | None = None) -> View:
        return replace(
            self,
            selection=replace(self.selection, time=_coerce_time_range(time, stop)),
        )

    def with_region(self, region: Region | None) -> View:
        return replace(self, selection=replace(self.selection, region=region))

    def with_context(
        self,
        *,
        frame: str | None = None,
        cache: bool | None = None,
        download: str | None = None,
        backend: str | Mapping[str, str] | None = None,
        spice_kernels: tuple[str | Path, ...] | None = None,
        time_scale: str | None = None,
    ) -> View:
        backends = dict(self.context.backends)
        backends.update(_backend_mapping(backend))
        return replace(
            self,
            context=replace(
                self.context,
                frame=self.context.frame if frame is None else frame,
                cache=self.context.cache if cache is None else bool(cache),
                download=self.context.download if download is None else download,
                backends=backends,
                spice_kernels=(
                    self.context.spice_kernels
                    if spice_kernels is None
                    else spice_kernels
                ),
                time_scale=self.context.time_scale if time_scale is None else time_scale,
            ),
        )

    def frame_context(self) -> FrameContext:
        return FrameContext(
            spice_kernels=self.context._spice_kernels,
            time_scale=self.context.time_scale,
            default_backend=self.context.backends.get("frames"),
        )

    def stack(self, *items: PlotItem) -> PlotStack:
        return stack(*items)

    def metadata(self) -> dict[str, Any]:
        return {
            "project_root": str(self.project.root),
            "store": {
                "root": str(self.project.store.root),
                "cache_root": str(self.project.store.cache_root),
            },
            "selection": self.selection.metadata(),
            "context": self.context.metadata(),
        }


class BoundNode:
    def __init__(self, value: Any, view: View) -> None:
        self._value = value
        self._view = view

    def load(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        return self._call_with_time("load", time, kwargs)

    def plan(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        return self._call_with_time("plan", time, kwargs)

    def plot(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        return self._call_with_time("plot", time, kwargs)

    def pipeline(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        return self._call_with_time("pipeline", time, kwargs)

    def line(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        line_method = getattr(self._value, "line", None)
        if line_method is not None:
            return self._call_with_time("line", time, kwargs)
        return line(lambda: self.load(time).to_xarray(), **kwargs)

    def lines(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        lines_method = getattr(self._value, "lines", None)
        if lines_method is not None:
            return self._call_with_time("lines", time, kwargs)
        return lines(lambda: self.load(time).to_xarray(), **kwargs)

    def spectrogram(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        spectrogram_method = getattr(self._value, "spectrogram", None)
        if spectrogram_method is not None:
            return self._call_with_time("spectrogram", time, kwargs)
        return spectrogram(lambda: self.load(time).to_xarray(), **kwargs)

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._value, name)
        if hasattr(value, "load") or hasattr(value, "plan") or not callable(value):
            return BoundNode(value, self._view)
        return value

    def _call_with_time(self, name: str, time: TimeRange | None, kwargs: dict[str, Any]) -> Any:
        method = getattr(self._value, name)
        call_kwargs = dict(kwargs)
        if (
            self._view.context.download is not None
            and "download" not in call_kwargs
            and _accepts_keyword(method, "download")
        ):
            call_kwargs["download"] = self._view.context.download
        if "context" not in call_kwargs and _accepts_keyword(method, "context"):
            call_kwargs["context"] = self._view.context
        if (
            "spice_kernels" not in call_kwargs
            and self._view.context._spice_kernels
            and _accepts_keyword(method, "spice_kernels")
        ):
            call_kwargs["spice_kernels"] = tuple(
                path.as_posix() for path in self._view.context._spice_kernels
            )
        selected_time = time or self._view.time
        if selected_time is None:
            return method(**call_kwargs)
        return method(selected_time, **call_kwargs)


class BoundMoon:
    def __init__(self, moon: Any, view: View) -> None:
        self._moon = moon
        self._view = view

    def map(self, product: str) -> Any:
        return BoundSurfaceEndpoint(self._moon.map(product), self._view)

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._moon, name)
        if hasattr(value, "plan") and hasattr(value, "load"):
            return BoundSurfaceEndpoint(value, self._view)
        return value


class BoundSurfaceEndpoint:
    def __init__(self, endpoint: Any, view: View) -> None:
        self._endpoint = endpoint
        self._view = view

    def plan(self, **parameters: Any) -> Any:
        return self._endpoint.plan(
            **_surface_parameters_with_view(self._endpoint, self._view, parameters)
        )

    def load(self, **parameters: Any) -> Any:
        return self._endpoint.load(
            **_surface_parameters_with_view(self._endpoint, self._view, parameters)
        )

    def compute(self, **parameters: Any) -> Any:
        return self._endpoint.compute(
            **_surface_parameters_with_view(self._endpoint, self._view, parameters)
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._endpoint, name)


def view(**parameters: Any) -> View:
    from sopran.core.project import Project

    return Project.default().view(**parameters)


def _coerce_time_range(value: object | None, stop: object | None = None) -> TimeRange | None:
    if value is None:
        return None
    if isinstance(value, TimeRange) and stop is None:
        return value
    if stop is not None:
        return period(value, stop)
    return day(value)


def _backend_mapping(value: str | Mapping[str, str] | None) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, str):
        return {"frames": value}
    return {str(key): str(item) for key, item in value.items()}


def _download_mode(value: str | None) -> DownloadMode | None:
    if value is None:
        return None
    if value not in ("never", "missing", "always"):
        raise ValueError("download must be 'never', 'missing', or 'always'")
    return cast(DownloadMode, value)


def _time_metadata(time: TimeRange | None) -> dict[str, str] | None:
    if time is None:
        return None
    return {
        "start": time.start_iso,
        "stop": time.stop_iso,
    }


def _surface_parameters_with_view(
    endpoint: Any,
    view: View,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(parameters)
    if "region" not in normalized and view.region is not None:
        normalized["region"] = view.region
    if (
        getattr(endpoint, "product", None) in {"shadow", "illumination", "sza"}
        and "time" not in normalized
        and view.time is not None
    ):
        normalized["time"] = view.time.start_iso
    if (
        getattr(endpoint, "product", None) in {"shadow", "illumination", "sza"}
        and "spice_kernels" not in normalized
        and view.context._spice_kernels
    ):
        normalized["spice_kernels"] = tuple(
            path.as_posix() for path in view.context._spice_kernels
        )
    return normalized


def _accepts_keyword(method: Any, name: str) -> bool:
    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD or parameter.name == name
        for parameter in parameters
    )


__all__ = ["View", "ViewContext", "ViewSelection", "view"]
