from __future__ import annotations

import os
import re
import sys
import tomllib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from sopran.core.errors import ConfigError

_TOML_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_TRUTHY = frozenset({"1", "true", "yes", "on"})

DownloadMode = Literal["never", "missing", "always"]
DEFAULT_STORE_DIRNAME = "sopran_data"


@dataclass(frozen=True)
class SessionConfig:
    """Process-local SOPRAN defaults used by notebook-friendly shortcuts."""

    store_root: Path | None = None
    cache_root: Path | None = None
    project_root: Path | None = None
    artifact_root: Path | None = None
    download: str | None = None
    frame: str | None = None
    cache: bool | None = None
    backends: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "store_root",
            None if self.store_root is None else Path(self.store_root),
        )
        object.__setattr__(
            self,
            "cache_root",
            None if self.cache_root is None else Path(self.cache_root),
        )
        object.__setattr__(
            self,
            "project_root",
            None if self.project_root is None else Path(self.project_root),
        )
        object.__setattr__(
            self,
            "artifact_root",
            None if self.artifact_root is None else Path(self.artifact_root),
        )
        if self.download is not None:
            _validate_download(self.download)
        object.__setattr__(
            self,
            "backends",
            {str(key): str(value) for key, value in self.backends.items()},
        )

    def defaults(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {}
        if self.download is not None:
            defaults["download"] = self.download
        if self.frame is not None:
            defaults["frame"] = self.frame
        if self.cache is not None:
            defaults["cache"] = self.cache
        return defaults


_SESSION_CONFIG = SessionConfig()


def current_session_config() -> SessionConfig:
    """Return the active process-local config."""

    return _SESSION_CONFIG


def resolve_download_mode(
    value: str | None = None,
    *,
    case_value: object | None = None,
    project_root: Path | None = None,
) -> DownloadMode:
    """Resolve the download policy for every entry point in one order.

    An explicit value wins, then ``spn.config.use(download=...)``, then the
    environment (``SOPRAN_OFFLINE`` forces ``never``, else ``SOPRAN_DOWNLOAD_MODE``),
    then file settings: a project case, the project ``[defaults]``, and the user
    ``[defaults]``. The fallback is ``missing``. Environment variables outrank
    files so that an offline compute node stays offline whatever a config says.
    ``project_root`` defaults to :func:`default_project_root`.
    """

    if value is None:
        value = current_session_config().download
    if value is None:
        if os.environ.get("SOPRAN_OFFLINE", "").strip().lower() in _TRUTHY:
            value = "never"
        else:
            value = os.environ.get("SOPRAN_DOWNLOAD_MODE") or None
    if value is None and case_value is not None:
        value = str(case_value)
    if value is None:
        root = project_root if project_root is not None else default_project_root()
        configured = config_section(read_project_config(root), "defaults").get("download")
        value = None if configured is None else str(configured)
    if value is None:
        configured = config_section(read_user_config()[0], "defaults").get("download")
        value = None if configured is None else str(configured)
    if value is None:
        value = "missing"
    _validate_download(value)
    return cast(DownloadMode, value)


def discover_project_root(start: Path | None = None) -> Path | None:
    """Return the nearest directory holding ``sopran.toml``, from ``start`` upward."""

    current = (start if start is not None else Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "sopran.toml").exists():
            return candidate
    return None


def default_project_root() -> Path:
    """Root of the default project used by ``spn.kaguya``, ``spn.view()`` and ``Store()``.

    The session ``project=`` wins, then the nearest ``sopran.toml`` above the current
    directory, then ``[project].root`` in the user config, then the current directory.
    """

    session_root = current_session_config().project_root
    if session_root is not None:
        return session_root
    discovered = discover_project_root()
    if discovered is not None:
        return discovered
    user_config, user_path = read_user_config()
    configured = configured_path(
        user_path.parent,
        config_section(user_config, "project").get("root"),
        default=None,
    )
    return configured if configured is not None else Path.cwd()


def read_project_config(root: Path) -> dict[str, Any]:
    """Read ``<root>/sopran.toml``; an absent file is an empty config."""

    path = Path(root) / "sopran.toml"
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            config = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid SOPRAN project config: {path}") from exc
    return config


def resolve_store_roots(
    root: Path | str | None = None,
    cache_root: Path | str | None = None,
    *,
    project_root: Path | None = None,
) -> tuple[Path, Path]:
    """Resolve the Store data root and cache root for every entry point in one order.

    Each root is taken from the argument, the session (``spn.config.use``), the
    environment (``SOPRAN_DATA_ROOT`` / ``SOPRAN_CACHE_ROOT``), the project
    ``[store]`` table, and the user ``[store]`` table, in that order. The data root
    falls back to ``<project root>/sopran_data`` and the cache root to
    ``<data root>/cache``. ``project_root`` defaults to :func:`default_project_root`,
    so ``Store()`` and ``spn.kaguya`` resolve to the same Store.
    """

    session = current_session_config()
    user_config, user_path = read_user_config()
    user_store = config_section(user_config, "store")
    project: Path | None = project_root
    project_store: dict[str, Any] | None = None

    def project_store_config() -> tuple[Path, dict[str, Any]]:
        nonlocal project, project_store
        if project is None:
            project = default_project_root()
        if project_store is None:
            project_store = config_section(read_project_config(project), "store")
        return project, project_store

    def resolve(
        explicit: Path | str | None,
        session_value: Path | None,
        env_name: str,
        key: str,
    ) -> Path | None:
        if explicit is not None:
            return Path(explicit)
        if session_value is not None:
            return session_value
        env_value = os.environ.get(env_name)
        if env_value:
            return Path(env_value)
        base, store_config = project_store_config()
        if store_config.get(key) is not None:
            return configured_path(base, store_config.get(key), default=None)
        return configured_path(user_path.parent, user_store.get(key), default=None)

    data_root = resolve(root, session.store_root, "SOPRAN_DATA_ROOT", "data_root")
    if data_root is None:
        base, _ = project_store_config()
        data_root = base / DEFAULT_STORE_DIRNAME
    resolved_cache = resolve(cache_root, session.cache_root, "SOPRAN_CACHE_ROOT", "cache_root")
    return data_root, resolved_cache if resolved_cache is not None else data_root / "cache"


def reset_session_config() -> SessionConfig:
    """Clear process-local defaults."""

    global _SESSION_CONFIG
    _SESSION_CONFIG = SessionConfig()
    return _SESSION_CONFIG


def use_session_config(
    *,
    store: object | None = None,
    data_root: Path | str | None = None,
    cache_root: Path | str | None = None,
    project: Path | str | None = None,
    project_root: Path | str | None = None,
    artifact_root: Path | str | None = None,
    download: str | None = None,
    frame: str | None = None,
    cache: bool | None = None,
    backends: Mapping[str, str] | None = None,
) -> SessionConfig:
    """Update process-local defaults used by top-level shortcuts."""

    global _SESSION_CONFIG
    store_root, resolved_cache_root = _coerce_store_roots(
        store,
        data_root=data_root,
        cache_root=cache_root,
    )
    resolved_project_root = _coerce_project_root(project, project_root=project_root)
    if download is not None:
        _validate_download(download)
    current = _SESSION_CONFIG
    _SESSION_CONFIG = SessionConfig(
        store_root=store_root if store_root is not None else current.store_root,
        cache_root=(
            resolved_cache_root if resolved_cache_root is not None else current.cache_root
        ),
        project_root=(
            resolved_project_root
            if resolved_project_root is not None
            else current.project_root
        ),
        artifact_root=(
            Path(artifact_root) if artifact_root is not None else current.artifact_root
        ),
        download=download if download is not None else current.download,
        frame=frame if frame is not None else current.frame,
        cache=cache if cache is not None else current.cache,
        backends={**current.backends, **({} if backends is None else backends)},
    )
    return _SESSION_CONFIG


@contextmanager
def using_session_config(
    *,
    store: object | None = None,
    data_root: Path | str | None = None,
    cache_root: Path | str | None = None,
    project: Path | str | None = None,
    project_root: Path | str | None = None,
    artifact_root: Path | str | None = None,
    download: str | None = None,
    frame: str | None = None,
    cache: bool | None = None,
    backends: Mapping[str, str] | None = None,
) -> Iterator[SessionConfig]:
    """Temporarily update process-local defaults."""

    global _SESSION_CONFIG
    previous = _SESSION_CONFIG
    try:
        yield use_session_config(
            store=store,
            data_root=data_root,
            cache_root=cache_root,
            project=project,
            project_root=project_root,
            artifact_root=artifact_root,
            download=download,
            frame=frame,
            cache=cache,
            backends=backends,
        )
    finally:
        _SESSION_CONFIG = previous


def save_user_config(
    *,
    store: object | None = None,
    data_root: Path | str | None = None,
    cache_root: Path | str | None = None,
    project: Path | str | None = None,
    project_root: Path | str | None = None,
    artifact_root: Path | str | None = None,
    download: str | None = None,
    frame: str | None = None,
    cache: bool | None = None,
    backends: Mapping[str, str] | None = None,
) -> Path:
    """Persist user-level defaults to the configured SOPRAN config file."""

    config, path = read_user_config()
    updated = dict(config)
    store_root, resolved_cache_root = _coerce_store_roots(
        store,
        data_root=data_root,
        cache_root=cache_root,
    )
    resolved_project_root = _coerce_project_root(project, project_root=project_root)
    if download is not None:
        _validate_download(download)

    if store_root is not None or resolved_cache_root is not None:
        store_config = dict(config_section(updated, "store"))
        if store_root is not None:
            store_config["data_root"] = str(store_root)
        if resolved_cache_root is not None:
            store_config["cache_root"] = str(resolved_cache_root)
        updated["store"] = store_config

    if resolved_project_root is not None or artifact_root is not None:
        project_config = dict(config_section(updated, "project"))
        if resolved_project_root is not None:
            project_config["root"] = str(resolved_project_root)
        if artifact_root is not None:
            project_config["artifact_root"] = str(artifact_root)
        updated["project"] = project_config

    if download is not None or frame is not None or cache is not None:
        defaults = dict(config_section(updated, "defaults"))
        if download is not None:
            defaults["download"] = download
        if frame is not None:
            defaults["frame"] = frame
        if cache is not None:
            defaults["cache"] = cache
        updated["defaults"] = defaults

    if backends is not None:
        backend_config = dict(config_section(updated, "backends"))
        backend_config.update({str(key): str(value) for key, value in backends.items()})
        updated["backends"] = backend_config

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_toml_dumps(updated), encoding="utf-8")
    return path


def user_config_path() -> Path:
    """Return the SOPRAN user config path for the current platform."""

    override = os.environ.get("SOPRAN_CONFIG")
    if override:
        return Path(override)

    platform_path = _platform_user_config_dir() / "config.toml"
    legacy_path = Path.home() / ".sopran" / "config.toml"
    if legacy_path.exists() and not platform_path.exists():
        return legacy_path
    return platform_path


def read_user_config() -> tuple[dict[str, Any], Path]:
    path = user_config_path()
    if not path.exists():
        return {}, path
    try:
        with path.open("rb") as handle:
            config = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid SOPRAN config: {path}") from exc
    if not isinstance(config, dict):
        raise ConfigError(f"SOPRAN config must be a TOML table: {path}")
    return config, path


def config_section(config: Mapping[str, Any], name: str) -> dict[str, Any]:
    value = config.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"[{name}] must be a table")
    return {str(key): item for key, item in value.items()}


def configured_path(base: Path, value: object | None, *, default: Path | None) -> Path | None:
    if value is None:
        return default
    path = Path(str(value))
    if path.is_absolute():
        return path
    return base / path


def _coerce_store_roots(
    store: object | None,
    *,
    data_root: Path | str | None,
    cache_root: Path | str | None,
) -> tuple[Path | None, Path | None]:
    if store is not None and data_root is not None:
        raise ValueError("Use either store=... or data_root=..., not both")
    resolved_cache_root = Path(cache_root) if cache_root is not None else None
    if store is None:
        return (
            Path(data_root) if data_root is not None else None,
            resolved_cache_root,
        )
    if isinstance(store, str | Path):
        return Path(store), resolved_cache_root

    root = getattr(store, "root", None)
    if root is None:
        raise TypeError("store must be a path-like object or have a root attribute")
    if resolved_cache_root is None:
        store_cache_root = getattr(store, "cache_root", None)
        if store_cache_root is not None:
            resolved_cache_root = Path(store_cache_root)
    return Path(root), resolved_cache_root


def _coerce_project_root(
    project: Path | str | None,
    *,
    project_root: Path | str | None,
) -> Path | None:
    if project is not None and project_root is not None:
        raise ValueError("Use either project=... or project_root=..., not both")
    root = project if project is not None else project_root
    return None if root is None else Path(root)


def _validate_download(value: str) -> None:
    if value not in {"never", "missing", "always"}:
        raise ValueError("download must be 'never', 'missing', or 'always'")


def _toml_dumps(config: Mapping[str, Any]) -> str:
    lines: list[str] = []
    _append_toml_table(lines, (), config)
    text = "\n".join(lines).rstrip()
    return f"{text}\n"


def _append_toml_table(
    lines: list[str],
    path: tuple[str, ...],
    table: Mapping[str, Any],
) -> None:
    scalar_items: list[tuple[str, Any]] = []
    table_items: list[tuple[str, Mapping[str, Any]]] = []
    for key, value in table.items():
        if value is None:
            continue
        if isinstance(value, Mapping):
            table_items.append((str(key), value))
        else:
            scalar_items.append((str(key), value))

    if path:
        lines.append(f"[{'.'.join(_toml_key(part) for part in path)}]")
    for key, value in scalar_items:
        lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
    if scalar_items and table_items:
        lines.append("")

    for index, (key, value) in enumerate(table_items):
        if lines and lines[-1] != "" and (path or scalar_items or index > 0):
            lines.append("")
        _append_toml_table(lines, (*path, key), value)


def _toml_key(value: str) -> str:
    if _TOML_BARE_KEY.match(value):
        return value
    return _toml_string(value)


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, Path):
        return _toml_string(str(value))
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, tuple | list):
        return f"[{', '.join(_toml_value(item) for item in value)}]"
    raise TypeError(f"Unsupported user config value: {value!r}")


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _platform_user_config_dir() -> Path:
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if root:
            return Path(root) / "sopran"
        return Path.home() / "AppData" / "Roaming" / "sopran"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "sopran"
    root = os.environ.get("XDG_CONFIG_HOME")
    if root:
        return Path(root) / "sopran"
    return Path.home() / ".config" / "sopran"
