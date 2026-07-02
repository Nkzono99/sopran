from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sopran.bodies import Moon
from sopran.core.errors import ConfigError
from sopran.core.plotting import PlotItem, PlotStack, stack
from sopran.core.store import Store
from sopran.core.time import TimeRange, period
from sopran.maps import Region
from sopran.missions.artemis import Artemis
from sopran.missions.kaguya import Kaguya


@dataclass(frozen=True)
class ProjectArtifact:
    path: Path
    metadata_path: Path
    metadata: dict[str, Any]


class Project:
    """Analysis workspace that supplies case context to mission objects."""

    def __init__(self, root: Path | str, *, store: Store | None = None) -> None:
        self.root = Path(root)
        self.store = store or self._configured_store()

    def save(
        self,
        value: Any,
        name: str | Path,
        *,
        format: str = "netcdf",
        overwrite: bool = False,
    ) -> ProjectArtifact:
        if format != "netcdf":
            raise ValueError("Project.save() currently supports format='netcdf' only")
        target = _project_child_path(self.root, name, suffix=".nc")
        if target.exists() and not overwrite:
            raise FileExistsError(f"Project artifact already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)

        array = value.to_xarray() if hasattr(value, "to_xarray") else value
        if not hasattr(array, "to_netcdf"):
            raise TypeError("Project.save() expects an xarray object or to_xarray() value")
        array.to_netcdf(target)

        metadata = _artifact_metadata(value, array, target, root=self.root, format=format)
        metadata_path = target.with_suffix(".json")
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return ProjectArtifact(path=target, metadata_path=metadata_path, metadata=metadata)

    def case(
        self,
        name: str,
        *,
        start: object | None = None,
        stop: object | None = None,
    ) -> Case:
        config: dict[str, Any] = {}
        case_config: dict[str, Any] = {}
        config_path = self.root / "sopran.toml"
        if config_path.exists() or start is None or stop is None:
            config = self._read_config()
        if config:
            case_config = config.get("cases", {}).get(name, {})
        if (start is None or stop is None) and not case_config:
            raise KeyError(f"Case {name!r} is not defined in {config_path}")
        if start is None or stop is None:
            start = case_config["start"] if start is None else start
            stop = case_config["stop"] if stop is None else stop
        return Case(
            project=self,
            name=name,
            time=period(start, stop),
            defaults=config.get("defaults", {}),
            region=_case_region(config.get("defaults", {}), case_config),
        )

    def _read_config(self) -> dict[str, Any]:
        path = self.root / "sopran.toml"
        with path.open("rb") as handle:
            return tomllib.load(handle)

    def _configured_store(self) -> Store:
        config = self._read_config() if (self.root / "sopran.toml").exists() else {}
        store_config = config.get("store", {})
        root = _configured_path(
            self.root,
            os.environ.get("SOPRAN_DATA_ROOT") or store_config.get("data_root"),
            default=self.root / "data",
        )
        cache_root = _configured_path(
            self.root,
            os.environ.get("SOPRAN_CACHE_ROOT") or store_config.get("cache_root"),
            default=None,
        )
        return Store(root=root, cache_root=cache_root)


class Case:
    def __init__(
        self,
        *,
        project: Project,
        name: str,
        time: TimeRange,
        defaults: dict[str, Any] | None = None,
        region: Region | None = None,
    ) -> None:
        self.project = project
        self.name = name
        self.time = time
        defaults = defaults or {}
        self.defaults = dict(defaults)
        self.frame = defaults.get("frame")
        self.cache = bool(defaults.get("cache", False))
        self.region = region
        self.kaguya = CaseKaguya(Kaguya(store=project.store), self)
        self.artemis = CaseMission(Artemis(store=project.store), self)
        self.moon = Moon()

    def metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "name": self.name,
            "project_root": str(self.project.root),
            "store": {
                "root": str(self.project.store.root),
                "cache_root": str(self.project.store.cache_root),
            },
            "time": {
                "start": self.time.start_iso,
                "stop": self.time.stop_iso,
            },
            "frame": self.frame,
            "cache": self.cache,
            "defaults": dict(self.defaults),
            "region": self.region.to_metadata() if self.region is not None else None,
        }
        return metadata

    def stack(self, *items: PlotItem) -> PlotStack:
        return stack(*items)


class CaseKaguya:
    def __init__(self, mission: Kaguya, case: Case) -> None:
        self._mission = mission
        self._case = case

    def __getattr__(self, name: str):
        value = getattr(self._mission, name)
        if hasattr(value, "load"):
            return CaseInstrument(value, self._case)
        return value


class CaseMission:
    def __init__(self, mission, case: Case) -> None:
        self._mission = mission
        self._case = case

    def __getattr__(self, name: str):
        value = getattr(self._mission, name)
        return CaseNode(value, self._case)


class CaseNode:
    def __init__(self, value, case: Case) -> None:
        self._value = value
        self._case = case

    def load(self, time: TimeRange | None = None, **kwargs):
        return self._value.load(time or self._case.time, **kwargs)

    def plan(self, time: TimeRange | None = None, **kwargs):
        return self._value.plan(time or self._case.time, **kwargs)

    def plot(self, time: TimeRange | None = None, **kwargs):
        return self._value.plot(time or self._case.time, **kwargs)

    def line(self, time: TimeRange | None = None, **kwargs):
        line_method = getattr(self._value, "line", None)
        if line_method is not None:
            return line_method(time or self._case.time, **kwargs)
        from sopran.core.plotting import line

        return line(lambda: self.load(time).to_xarray(), **kwargs)

    def __getattr__(self, name: str):
        value = getattr(self._value, name)
        if hasattr(value, "load") or hasattr(value, "plan") or not callable(value):
            return CaseNode(value, self._case)
        return value


class CaseInstrument:
    def __init__(self, instrument, case: Case) -> None:
        self._instrument = instrument
        self._case = case

    def load(self, time: TimeRange | None = None, **kwargs):
        return self._instrument.load(time or self._case.time, **kwargs)

    def plan(self, time: TimeRange | None = None):
        return self._instrument.plan(time or self._case.time)

    def pipeline(self, time: TimeRange | None = None):
        return self._instrument.pipeline(time or self._case.time)

    def __getattr__(self, name: str):
        value = getattr(self._instrument, name)
        if hasattr(value, "load") and hasattr(value, "plan"):
            return CaseVariableEndpoint(value, self._case)
        return value


class CaseVariableEndpoint:
    def __init__(self, endpoint, case: Case) -> None:
        self._endpoint = endpoint
        self._case = case

    def load(self, time: TimeRange | None = None, **kwargs):
        return self._endpoint.load(time or self._case.time, **kwargs)

    def plan(self, time: TimeRange | None = None):
        return self._endpoint.plan(time or self._case.time)

    def plot(self, time: TimeRange | None = None, **kwargs):
        return self._endpoint.plot(time or self._case.time, **kwargs)

    def line(self, time: TimeRange | None = None, **kwargs):
        return self._endpoint.line(time or self._case.time, **kwargs)

    def spectrogram(self, time: TimeRange | None = None, **kwargs):
        return self._endpoint.spectrogram(time or self._case.time, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._endpoint, name)


def _case_region(
    defaults: dict[str, Any],
    case_config: dict[str, Any],
) -> Region | None:
    region = case_config.get("region") or defaults.get("region")
    if region is None:
        return None
    lon = tuple(float(value) for value in region["lon"])
    lat = tuple(float(value) for value in region["lat"])
    if len(lon) != 2 or len(lat) != 2:
        raise ConfigError("case region lon and lat must each contain two values")
    return Region(
        lon=lon,
        lat=lat,
        body=str(region.get("body", "moon")),
        lon_domain=region.get("lon_domain", "0_360"),
        lon_direction=region.get("lon_direction", "east_positive"),
        lat_type=region.get("lat_type", "planetocentric"),
    )


def _project_child_path(root: Path, name: str | Path, *, suffix: str) -> Path:
    path = Path(name)
    if path.suffix != suffix:
        path = path.with_suffix(suffix)
    target = (root / path).resolve()
    resolved_root = root.resolve()
    if not target.is_relative_to(resolved_root):
        raise ValueError(f"Project artifact path escapes project root: {name}")
    return target


def _configured_path(
    project_root: Path,
    value: object | None,
    *,
    default: Path | None,
) -> Path | None:
    if value is None:
        return default
    path = Path(str(value))
    if path.is_absolute():
        return path
    return project_root / path


def _artifact_metadata(
    value: Any,
    array: Any,
    path: Path,
    *,
    root: Path,
    format: str,
) -> dict[str, Any]:
    time = getattr(value, "time", None)
    metadata: dict[str, Any] = {
        "format": format,
        "name": str(getattr(value, "name", None) or getattr(array, "name", None) or ""),
        "path": path.relative_to(root).as_posix(),
        "type": type(value).__name__,
    }
    if time is not None:
        metadata["time_coverage"] = {
            "start": time.start_iso,
            "stop": time.stop_iso,
        }
    files = getattr(value, "files", ())
    if files:
        metadata["source_files"] = [str(file) for file in files]
    return metadata
