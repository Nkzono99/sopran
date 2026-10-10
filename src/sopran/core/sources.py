"""Registry of the top-level data sources that a View binds.

Mission and body packages register themselves, so ``core`` never imports them.
``spn.kaguya``, ``view.kaguya``, ``case.kaguya`` and ``spn.load("kaguya...")``
all build their objects through this table.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sopran.core.view import View

_SOURCES: dict[str, str] = {}


def register_source(name: str, factory: str) -> None:
    """Register ``factory`` (``"module:attribute.path"``) as the source ``name``.

    The factory is imported on first use and called as ``factory(view)``. It must
    return a source object bound to that view's time, region and context.
    """

    if not name.isidentifier() or name.startswith("_"):
        raise ValueError(f"source name must be a public identifier: {name!r}")
    module, separator, attribute = factory.partition(":")
    if not module or not separator or not attribute:
        raise ValueError(f"source factory must look like 'module:attribute': {factory!r}")
    existing = _SOURCES.get(name)
    if existing is not None and existing != factory:
        raise ValueError(f"source {name!r} is already registered as {existing!r}")
    _SOURCES[name] = factory


def source_names() -> tuple[str, ...]:
    """Names of the registered sources, in registration order."""

    return tuple(_SOURCES)


def build_source(name: str, view: View) -> Any:
    """Build the registered source ``name`` bound to ``view``."""

    try:
        factory = _SOURCES[name]
    except KeyError:
        available = ", ".join(_SOURCES) or "none"
        raise KeyError(f"Unknown SOPRAN source {name!r}. Available sources: {available}") from None
    module, _, attribute = factory.partition(":")
    target: Any = import_module(module)
    for part in attribute.split("."):
        target = getattr(target, part)
    return target(view)


__all__ = ["build_source", "register_source", "source_names"]
