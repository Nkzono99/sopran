from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Store:
    """Filesystem roots used by SOPRAN data discovery and products."""

    root: Path | str | None = None
    cache_root: Path | str | None = None

    def __post_init__(self) -> None:
        root = self.root or os.environ.get("SOPRAN_DATA_ROOT") or "sopran_data"
        cache_root = self.cache_root or os.environ.get("SOPRAN_CACHE_ROOT")
        object.__setattr__(self, "root", Path(root))
        cache_path = Path(cache_root) if cache_root else Path(root) / "cache"
        object.__setattr__(self, "cache_root", cache_path)

    def raw_path(self, *parts: str) -> Path:
        return self.root.joinpath("raw", *parts)

    def normalized_path(self, *parts: str) -> Path:
        return self.root.joinpath("normalized", *parts)

    def features_path(self, *parts: str) -> Path:
        return self.root.joinpath("features", *parts)

    def database_path(self, *parts: str) -> Path:
        return self.root.joinpath("databases", *parts)
