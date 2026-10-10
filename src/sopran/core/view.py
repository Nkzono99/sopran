from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sopran.core.plotting import PlotItem, PlotStack, stack
from sopran.core.sources import build_source, source_names
from sopran.core.time import TimeRange, day, period
from sopran.frames import FrameContext
from sopran.maps import Region

if TYPE_CHECKING:
    from sopran.bodies.moon import Moon
    from sopran.core.project import Project
    from sopran.missions.artemis import Artemis
    from sopran.missions.kaguya import Kaguya
    from sopran.missions.omni import Omni


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
    """A lightweight lens that binds selection and context to the data tree.

    ``view.kaguya`` and the other registered sources are real mission objects whose
    endpoints default to this view's time, region, download policy and SPICE kernels.
    """

    project: Project
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
    def kaguya(self) -> Kaguya:
        return cast("Kaguya", self.source("kaguya"))

    @property
    def artemis(self) -> Artemis:
        return cast("Artemis", self.source("artemis"))

    @property
    def omni(self) -> Omni:
        return cast("Omni", self.source("omni"))

    @property
    def moon(self) -> Moon:
        return cast("Moon", self.source("moon"))

    def source(self, name: str) -> Any:
        """Return the registered source ``name`` bound to this view's time and context."""

        cache = self.__dict__.setdefault("_sources", {})
        if name not in cache:
            cache[name] = build_source(name, self)
        return cache[name]

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name not in source_names():
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
        return self.source(name)

    def __dir__(self) -> list[str]:
        return sorted({*super().__dir__(), *source_names()})

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


def _time_metadata(time: TimeRange | None) -> dict[str, str] | None:
    if time is None:
        return None
    return {
        "start": time.start_iso,
        "stop": time.stop_iso,
    }


__all__ = ["View", "ViewContext", "ViewSelection", "view"]
