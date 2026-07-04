from __future__ import annotations

import json
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from sopran.bodies import Moon
from sopran.core.config import config_section, configured_path, read_user_config
from sopran.core.errors import ConfigError
from sopran.core.plotting import PlotItem, PlotStack, stack
from sopran.core.store import Store
from sopran.core.time import TimeRange, period
from sopran.core.view import View, ViewContext, ViewSelection, _backend_mapping, _coerce_time_range
from sopran.maps import Region
from sopran.missions.artemis import Artemis
from sopran.missions.kaguya import Kaguya

DownloadMode = Literal["never", "missing", "always"]


@dataclass(frozen=True)
class ProjectArtifact:
    path: Path
    metadata_path: Path
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ProjectCaseRecord:
    path: Path
    metadata_path: Path
    metadata: dict[str, Any]


class Project:
    """Analysis workspace that supplies case context to mission objects."""

    def __init__(
        self,
        root: Path | str,
        *,
        store: Store | None = None,
        artifact_root: Path | str | None = None,
    ) -> None:
        self.root = Path(root)
        self.store = store or self._configured_store()
        self.artifact_root = self._configured_artifact_root(artifact_root)

    @classmethod
    def default(
        cls,
        *,
        root: Path | str | None = None,
        store: Store | None = None,
        artifact_root: Path | str | None = None,
    ) -> Project:
        user_config, user_config_path = read_user_config()
        project_config = config_section(user_config, "project")
        resolved_root = (
            Path(root)
            if root is not None
            else configured_path(
                user_config_path.parent,
                project_config.get("root"),
                default=Path.cwd(),
            )
        )
        return cls(cast(Path, resolved_root), store=store, artifact_root=artifact_root)

    @property
    def kaguya(self) -> Kaguya:
        return Kaguya(
            store=self.store,
            download=_download_mode(self._merged_defaults().get("download")),
        )

    @property
    def artemis(self) -> Artemis:
        return Artemis(store=self.store)

    @property
    def moon(self) -> Moon:
        return Moon()

    def view(
        self,
        *,
        time: object | None = None,
        start: object | None = None,
        stop: object | None = None,
        region: Region | None = None,
        frame: str | None = None,
        cache: bool | None = None,
        download: str | None = None,
        backend: str | Mapping[str, str] | None = None,
        backends: Mapping[str, str] | None = None,
        spice_kernels: tuple[str | Path, ...] | None = None,
        time_scale: str | None = None,
        mission: str | tuple[str, ...] | list[str] = (),
        instrument: str | tuple[str, ...] | list[str] = (),
        product: str | tuple[str, ...] | list[str] = (),
        quality: str | None = None,
    ) -> View:
        if time is not None and (start is not None or stop is not None):
            raise ValueError("Use either time=... or start=/stop=..., not both")
        if start is None and stop is not None:
            raise ValueError("start is required when stop is provided")
        selected_time = _coerce_time_range(time, None) if time is not None else None
        if start is not None:
            selected_time = _coerce_time_range(start, stop)

        defaults = self._merged_defaults()
        selected_region = region if region is not None else _case_region(defaults, {})
        context_backends = self._merged_backends()
        context_backends.update(_backend_mapping(backend))
        if backends is not None:
            context_backends.update({str(key): str(value) for key, value in backends.items()})
        context = ViewContext(
            frame=frame if frame is not None else _optional_str(defaults.get("frame")),
            cache=bool(defaults.get("cache", False)) if cache is None else bool(cache),
            download=download if download is not None else _optional_str(defaults.get("download")),
            backend_policy="auto",
            backends=context_backends,
            spice_kernels=(
                tuple(defaults.get("spice_kernels", ()))
                if spice_kernels is None
                else spice_kernels
            ),
            time_scale=(
                str(defaults.get("time_scale", "utc"))
                if time_scale is None
                else time_scale
            ),
        )
        return View(
            project=self,
            selection=ViewSelection(
                time=selected_time,
                region=selected_region,
                mission=_string_tuple(mission),
                instrument=_string_tuple(instrument),
                product=_string_tuple(product),
                quality=quality if quality is not None else _optional_str(defaults.get("quality")),
            ),
            context=context,
        )

    def save(
        self,
        value: Any,
        name: str | Path,
        *,
        format: str = "netcdf",
        context: Any | None = None,
        overwrite: bool = False,
    ) -> ProjectArtifact:
        if format != "netcdf":
            raise ValueError("Project.save() currently supports format='netcdf' only")
        target = _project_child_path(self.artifact_root, name, suffix=".nc")
        if target.exists() and not overwrite:
            raise FileExistsError(f"Project artifact already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)

        array = value.to_xarray() if hasattr(value, "to_xarray") else value
        if not hasattr(array, "to_netcdf"):
            raise TypeError("Project.save() expects an xarray object or to_xarray() value")
        array.to_netcdf(target)

        metadata = _artifact_metadata(
            value,
            array,
            target,
            root=self.artifact_root,
            format=format,
            context=context,
        )
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
        defaults = self._case_defaults(config.get("defaults", {}), case_config)
        return Case(
            project=self,
            name=name,
            time=period(start, stop),
            defaults=defaults,
            region=_case_region(defaults, case_config),
        )

    def _read_config(self) -> dict[str, Any]:
        path = self.root / "sopran.toml"
        with path.open("rb") as handle:
            return tomllib.load(handle)

    def _configured_store(self) -> Store:
        config = self._read_config() if (self.root / "sopran.toml").exists() else {}
        user_config, user_config_path = read_user_config()
        store_config = config_section(config, "store")
        user_store_config = config_section(user_config, "store")
        root = _configured_path_by_precedence(
            os.environ.get("SOPRAN_DATA_ROOT"),
            (self.root, store_config.get("data_root")),
            (user_config_path.parent, user_store_config.get("data_root")),
            default=self.root / "data",
        )
        cache_root = _configured_path_by_precedence(
            os.environ.get("SOPRAN_CACHE_ROOT"),
            (self.root, store_config.get("cache_root")),
            (user_config_path.parent, user_store_config.get("cache_root")),
            default=None,
        )
        return Store(root=root, cache_root=cache_root)

    def _configured_artifact_root(self, artifact_root: Path | str | None) -> Path:
        config = self._read_config() if (self.root / "sopran.toml").exists() else {}
        user_config, user_config_path = read_user_config()
        project_config = config_section(config, "project")
        user_project_config = config_section(user_config, "project")
        explicit = Path(artifact_root) if artifact_root is not None else None
        if explicit is not None:
            return explicit if explicit.is_absolute() else self.root / explicit
        resolved = _configured_path_by_precedence(
            os.environ.get("SOPRAN_ARTIFACT_ROOT"),
            (self.root, project_config.get("artifact_root")),
            (user_config_path.parent, user_project_config.get("artifact_root")),
            default=self.root,
        )
        return self.root if resolved is None else resolved

    def _merged_defaults(self) -> dict[str, Any]:
        config = self._read_config() if (self.root / "sopran.toml").exists() else {}
        user_config, _ = read_user_config()
        return {
            **config_section(user_config, "defaults"),
            **config_section(config, "defaults"),
        }

    def _merged_backends(self) -> dict[str, str]:
        config = self._read_config() if (self.root / "sopran.toml").exists() else {}
        user_config, _ = read_user_config()
        backends = {
            **config_section(user_config, "backends"),
            **config_section(config, "backends"),
        }
        return {str(key): str(value) for key, value in backends.items()}

    def _case_defaults(
        self,
        project_defaults: dict[str, Any],
        case_config: dict[str, Any],
    ) -> dict[str, Any]:
        defaults = {
            **config_section(read_user_config()[0], "defaults"),
            **project_defaults,
        }
        case_context = case_config.get("context", {})
        if case_context is not None and not isinstance(case_context, Mapping):
            raise ConfigError("[cases.<name>.context] must be a table")
        defaults.update(case_context or {})
        for key in ("frame", "cache", "download", "quality", "time_scale"):
            if key in case_config:
                defaults[key] = case_config[key]
        return defaults

    def save_case(
        self,
        name: str,
        view: View,
        *,
        overwrite: bool = False,
        description: str | None = None,
    ) -> ProjectCaseRecord:
        if view.time is None:
            raise ValueError("Project.save_case() requires a view with a time range")
        self.root.mkdir(parents=True, exist_ok=True)
        config_path = self.root / "sopran.toml"
        existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        config = self._read_config() if config_path.exists() else {}
        if name in config.get("cases", {}) and not overwrite:
            raise FileExistsError(f"Case already exists: {name}")
        if overwrite and name in config.get("cases", {}):
            raise NotImplementedError("Project.save_case(overwrite=True) is not implemented yet")

        block = _case_toml_block(name, view, description=description)
        text = f"{existing.rstrip()}\n\n{block}\n" if existing.strip() else f"{block}\n"
        config_path.write_text(text, encoding="utf-8")

        metadata = view.metadata()
        metadata_path = self.root / "cases" / f"{_safe_case_filename(name)}.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return ProjectCaseRecord(
            path=config_path,
            metadata_path=metadata_path,
            metadata=metadata,
        )


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
        self.kaguya = CaseKaguya(
            Kaguya(store=project.store, download=_download_mode(defaults.get("download"))),
            self,
        )
        self.artemis = CaseMission(Artemis(store=project.store), self)
        self.moon = CaseMoon(Moon(), self)

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

    def to_view(self) -> View:
        return self.project.view(
            time=self.time,
            region=self.region,
            frame=self.frame,
            cache=self.cache,
            download=_optional_str(self.defaults.get("download")),
            backends=_case_backends(self.defaults),
        )

    def with_time(self, time: object, stop: object | None = None) -> View:
        return self.to_view().with_time(time, stop)

    def stack(self, *items: PlotItem) -> PlotStack:
        return stack(*items)


class CaseKaguya:
    def __init__(self, mission: Kaguya, case: Case) -> None:
        self._mission = mission
        self._case = case

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._mission, name)
        if hasattr(value, "load"):
            return CaseInstrument(value, self._case)
        return value


class CaseMission:
    def __init__(self, mission: Any, case: Case) -> None:
        self._mission = mission
        self._case = case

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._mission, name)
        return CaseNode(value, self._case)


class CaseMoon:
    def __init__(self, moon: Moon, case: Case) -> None:
        self._moon = moon
        self._case = case

    def map(self, product: str) -> Any:
        return CaseSurfaceEndpoint(self._moon.map(product), self._case)

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._moon, name)
        if hasattr(value, "plan") and hasattr(value, "load"):
            return CaseSurfaceEndpoint(value, self._case)
        return value


class CaseSurfaceEndpoint:
    def __init__(self, endpoint: Any, case: Case) -> None:
        self._endpoint = endpoint
        self._case = case

    def plan(self, **parameters: Any) -> Any:
        return self._endpoint.plan(
            **_surface_parameters_with_case(self._endpoint, self._case, parameters)
        )

    def load(self, **parameters: Any) -> Any:
        return self._endpoint.load(
            **_surface_parameters_with_case(self._endpoint, self._case, parameters)
        )

    def compute(self, **parameters: Any) -> Any:
        return self._endpoint.compute(
            **_surface_parameters_with_case(self._endpoint, self._case, parameters)
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._endpoint, name)


class CaseNode:
    def __init__(self, value: Any, case: Case) -> None:
        self._value = value
        self._case = case

    def load(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        return self._value.load(time or self._case.time, **kwargs)

    def plan(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        return self._value.plan(time or self._case.time, **kwargs)

    def plot(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        return self._value.plot(time or self._case.time, **kwargs)

    def line(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        line_method = getattr(self._value, "line", None)
        if line_method is not None:
            return line_method(time or self._case.time, **kwargs)
        from sopran.core.plotting import line

        return line(lambda: self.load(time).to_xarray(), **kwargs)

    def lines(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        lines_method = getattr(self._value, "lines", None)
        if lines_method is not None:
            return lines_method(time or self._case.time, **kwargs)
        from sopran.core.plotting import lines

        return lines(lambda: self.load(time).to_xarray(), **kwargs)

    def spectrogram(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        spectrogram_method = getattr(self._value, "spectrogram", None)
        if spectrogram_method is not None:
            return spectrogram_method(time or self._case.time, **kwargs)
        from sopran.core.plotting import spectrogram

        return spectrogram(lambda: self.load(time).to_xarray(), **kwargs)

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._value, name)
        if hasattr(value, "load") or hasattr(value, "plan") or not callable(value):
            return CaseNode(value, self._case)
        return value


class CaseInstrument:
    def __init__(self, instrument: Any, case: Case) -> None:
        self._instrument = instrument
        self._case = case

    def load(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        return self._instrument.load(time or self._case.time, **kwargs)

    def plan(self, time: TimeRange | None = None) -> Any:
        return self._instrument.plan(time or self._case.time)

    def pipeline(self, time: TimeRange | None = None) -> Any:
        return self._instrument.pipeline(time or self._case.time)

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._instrument, name)
        if hasattr(value, "load") and hasattr(value, "plan"):
            return CaseVariableEndpoint(value, self._case)
        return value


class CaseVariableEndpoint:
    def __init__(self, endpoint: Any, case: Case) -> None:
        self._endpoint = endpoint
        self._case = case

    def load(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        return self._endpoint.load(time or self._case.time, **kwargs)

    def plan(self, time: TimeRange | None = None) -> Any:
        return self._endpoint.plan(time or self._case.time)

    def plot(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        return self._endpoint.plot(time or self._case.time, **kwargs)

    def line(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        return self._endpoint.line(time or self._case.time, **kwargs)

    def lines(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        return self._endpoint.lines(time or self._case.time, **kwargs)

    def spectrogram(self, time: TimeRange | None = None, **kwargs: Any) -> Any:
        return self._endpoint.spectrogram(time or self._case.time, **kwargs)

    def __getattr__(self, name: str) -> Any:
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
        lon=(lon[0], lon[1]),
        lat=(lat[0], lat[1]),
        body=str(region.get("body", "moon")),
        lon_domain=cast(Any, region.get("lon_domain", "0_360")),
        lon_direction=cast(Any, region.get("lon_direction", "east_positive")),
        lat_type=cast(Any, region.get("lat_type", "planetocentric")),
    )


def _surface_parameters_with_case(
    endpoint: Any,
    case: Case,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(parameters)
    if "region" not in normalized and case.region is not None:
        normalized["region"] = case.region
    if (
        getattr(endpoint, "product", None) in {"shadow", "illumination", "sza"}
        and "time" not in normalized
    ):
        normalized["time"] = case.time.start_iso
    return normalized


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


def _configured_path_by_precedence(
    env_value: str | None,
    project_value: tuple[Path, object | None],
    user_value: tuple[Path, object | None],
    *,
    default: Path | None,
) -> Path | None:
    if env_value:
        return Path(env_value)
    project_base, project_path = project_value
    if project_path is not None:
        return _configured_path(project_base, project_path, default=default)
    user_base, user_path = user_value
    if user_path is not None:
        return configured_path(user_base, user_path, default=default)
    return default


def _optional_str(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _download_mode(value: object | None) -> DownloadMode | None:
    if value is None:
        return None
    text = str(value)
    if text not in ("never", "missing", "always"):
        raise ConfigError("download must be 'never', 'missing', or 'always'")
    return cast(DownloadMode, text)


def _string_tuple(value: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _case_backends(defaults: Mapping[str, Any]) -> dict[str, str]:
    explicit = defaults.get("backends")
    backends = (
        {str(key): str(value) for key, value in explicit.items()}
        if isinstance(explicit, Mapping)
        else {}
    )
    for key, value in defaults.items():
        if str(key).startswith("backend_"):
            backend_key = str(key).removeprefix("backend_")
            if backend_key:
                backends[backend_key] = str(value)
    return backends


def _case_toml_block(
    name: str,
    view: View,
    *,
    description: str | None,
) -> str:
    time = view.time
    if time is None:
        raise ValueError("case TOML output requires a view with a time range")
    lines = [f"[cases.{_toml_key(name)}]"]
    if description:
        lines.append(f"description = {_toml_string(description)}")
    lines.append(f"start = {_toml_string(time.start_iso)}")
    lines.append(f"stop = {_toml_string(time.stop_iso)}")
    context_lines = _case_context_toml_lines(view.context)
    if context_lines:
        lines.extend(("", f"[cases.{_toml_key(name)}.context]", *context_lines))
    if view.region is not None:
        metadata = view.region.to_metadata()
        lines.extend(
            (
                "",
                f"[cases.{_toml_key(name)}.region]",
                f"body = {_toml_string(str(metadata['body']))}",
                f"lon = {_toml_array(metadata['lon'])}",
                f"lat = {_toml_array(metadata['lat'])}",
                f"lon_domain = {_toml_string(str(metadata['lon_domain']))}",
                f"lon_direction = {_toml_string(str(metadata['lon_direction']))}",
                f"lat_type = {_toml_string(str(metadata['lat_type']))}",
            )
        )
    return "\n".join(lines)


def _case_context_toml_lines(context: ViewContext) -> list[str]:
    lines: list[str] = []
    if context.frame is not None:
        lines.append(f"frame = {_toml_string(context.frame)}")
    if context.cache:
        lines.append("cache = true")
    if context.download is not None:
        lines.append(f"download = {_toml_string(context.download)}")
    if context.spice_kernels:
        lines.append(
            "spice_kernels = "
            + _toml_array([path.as_posix() for path in context._spice_kernels])
        )
    if context.time_scale != "utc":
        lines.append(f"time_scale = {_toml_string(context.time_scale)}")
    for key, value in sorted(context.backends.items()):
        lines.append(f"backend_{_toml_bare_key(key)} = {_toml_string(value)}")
    return lines


def _toml_key(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    return _toml_string(value)


def _toml_bare_key(value: str) -> str:
    key = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    if not key:
        raise ValueError("backend key cannot be empty")
    return key


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _toml_array(values: object) -> str:
    if not isinstance(values, (tuple, list)):
        raise TypeError("TOML array value must be a tuple or list")
    return "[" + ", ".join(_toml_value(value) for value in values) + "]"


def _toml_value(value: object) -> str:
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _safe_case_filename(name: str) -> str:
    filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    return filename or "case"


def _artifact_metadata(
    value: Any,
    array: Any,
    path: Path,
    *,
    root: Path,
    format: str,
    context: Any | None = None,
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
    source_metadata = _optional_metadata(value)
    if source_metadata is not None:
        metadata["source_metadata"] = source_metadata
    if context is not None:
        metadata["context"] = _context_metadata(context)
    return metadata


def _context_metadata(context: Any) -> dict[str, Any]:
    metadata = _optional_metadata(context)
    if metadata is not None:
        return metadata
    raise TypeError("context must be a metadata mapping or expose metadata")


def _optional_metadata(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return cast(dict[str, Any], _metadata_value(value))
    metadata = getattr(value, "metadata", None)
    if callable(metadata):
        metadata = metadata()
    if isinstance(metadata, Mapping):
        return cast(dict[str, Any], _metadata_value(metadata))
    to_metadata = getattr(value, "to_metadata", None)
    if callable(to_metadata):
        metadata = to_metadata()
    if isinstance(metadata, Mapping):
        return cast(dict[str, Any], _metadata_value(metadata))
    return None


def _metadata_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _metadata_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_metadata_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "to_metadata"):
        return _metadata_value(value.to_metadata())
    return value
