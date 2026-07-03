from __future__ import annotations

import os
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sopran.core.errors import ConfigError


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
