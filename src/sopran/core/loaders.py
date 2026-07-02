from __future__ import annotations

from typing import Any

from sopran.core.store import Store
from sopran.core.time import TimeRange


def load(dataset_id: str, time: TimeRange, *, store: Store | None = None, **kwargs: Any):
    """Load a dataset by stable string ID.

    The object API remains the primary interface; this helper is for CLI, batch,
    and power-user dispatch.
    """

    parts = tuple(part for part in dataset_id.split(".") if part)
    if parts[:2] == ("kaguya", "esa1"):
        from sopran.missions.kaguya import Kaguya

        esa1 = Kaguya(store=store).esa1
        if len(parts) == 2:
            return esa1.load(time, **kwargs)
        if len(parts) == 3:
            return getattr(esa1, parts[2]).load(time, **kwargs)
    raise KeyError(f"Unknown SOPRAN dataset ID: {dataset_id}")
