from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProductRef:
    dataset_id: str
    layer: str


@dataclass(frozen=True)
class Database:
    name: str
    root: Path

    def product(self, name: str) -> ProductRef:
        if not name:
            raise ValueError("database product name must not be empty")
        return ProductRef(dataset_id=f"{self.name}.{name}", layer="databases")
