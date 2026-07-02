from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sopran.core.schema import InstrumentSchema
from sopran.core.store import DatasetRecord


@dataclass(frozen=True)
class ProductRef:
    dataset_id: str
    layer: str


@dataclass(frozen=True)
class Database:
    name: str
    root: Path
    store: Any

    def product(self, name: str) -> ProductRef:
        if not name:
            raise ValueError("database product name must not be empty")
        return ProductRef(dataset_id=f"{self.name}.{name}", layer="databases")

    def register_product(
        self,
        *,
        name: str,
        schema: InstrumentSchema,
        description: str = "",
    ) -> DatasetRecord:
        product = self.product(name)
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_metadata(product, description=description)
        return self.store.register_dataset(
            dataset_id=product.dataset_id,
            layer=product.layer,
            mission=self.name,
            instrument=self.name,
            product=name,
            schema=schema,
            time_coverage=None,
        )

    def _write_metadata(self, product: ProductRef, *, description: str) -> None:
        path = self.root / "database.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = {"name": self.name, "products": []}

        entry = {
            "name": product.dataset_id.split(".")[-1],
            "dataset_id": product.dataset_id,
            "layer": product.layer,
            "description": description,
        }
        products = [
            item
            for item in payload.get("products", [])
            if item.get("name") != entry["name"]
        ]
        products.append(entry)
        payload = {"name": self.name, "products": products}
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
