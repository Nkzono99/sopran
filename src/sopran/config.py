from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from pathlib import Path

from sopran.core.config import (
    SessionConfig,
    current_session_config,
    reset_session_config,
    save_user_config,
    use_session_config,
    using_session_config,
)


def use(
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
    """Set process-local defaults for ``spn.kaguya``, ``spn.view()``, and ``Store()``."""

    return use_session_config(
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


def using(
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
) -> AbstractContextManager[SessionConfig]:
    """Temporarily set process-local defaults inside a ``with`` block."""

    return using_session_config(
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


def current() -> SessionConfig:
    """Return the active process-local defaults."""

    return current_session_config()


def reset() -> SessionConfig:
    """Clear process-local defaults."""

    return reset_session_config()


def save_user(
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
    """Persist user-level defaults to the SOPRAN config file."""

    return save_user_config(
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


__all__ = [
    "SessionConfig",
    "current",
    "reset",
    "save_user",
    "use",
    "using",
]
