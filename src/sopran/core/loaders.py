from __future__ import annotations

from typing import Any

from sopran.core.errors import DatasetNotFoundError
from sopran.core.sources import source_names
from sopran.core.store import Store
from sopran.core.time import TimeRange


def load(dataset_id: str, time: TimeRange, *, store: Store | None = None, **kwargs: Any) -> Any:
    """Load a dataset by stable string ID.

    The ID is the attribute path below a registered source, so
    ``load("kaguya.esa1.counts", time)`` equals ``spn.kaguya.esa1.counts.load(time)``.
    The object API remains the primary interface; this helper is for CLI, batch,
    and power-user dispatch.
    """

    from sopran.core.project import Project

    parts = tuple(part for part in dataset_id.split(".") if part)
    if not parts or parts[0] not in source_names():
        raise DatasetNotFoundError(
            f"Unknown SOPRAN dataset ID: {dataset_id}. "
            f"Sources: {', '.join(source_names()) or 'none'}"
        )
    target: Any = Project.default(store=store).view().source(parts[0])
    for depth, part in enumerate(parts[1:], start=2):
        try:
            target = getattr(target, part)
        except AttributeError as exc:
            prefix = ".".join(parts[:depth - 1])
            raise DatasetNotFoundError(
                f"Unknown SOPRAN dataset ID: {dataset_id} ({prefix} has no {part!r})"
            ) from exc
    loader = getattr(target, "load", None)
    if len(parts) < 2 or not callable(loader):
        raise DatasetNotFoundError(
            f"SOPRAN dataset ID {dataset_id} does not name a loadable product"
        )
    return loader(time, **kwargs)
