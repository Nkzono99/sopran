from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sopran.core.schema import InstrumentSchema
from sopran.core.store import DatasetRecord


@dataclass(frozen=True)
class ProductRef:
    dataset_id: str
    layer: str
    store: Any | None = field(default=None, repr=False, compare=False)

    @property
    def name(self) -> str:
        return self.dataset_id.split(".")[-1]

    def scan(self):
        if self.store is None:
            raise ValueError("ProductRef.scan() requires a Store-backed reference")
        return self.store.scan_dataset(self.dataset_id, layer=self.layer)


@dataclass(frozen=True)
class Database:
    name: str
    root: Path
    store: Any

    def create(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / "database.json"
        if not path.exists():
            path.write_text(
                json.dumps(
                    {"name": self.name, "products": []},
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

    def product(self, name: str) -> ProductRef:
        if not name:
            raise ValueError("database product name must not be empty")
        return ProductRef(
            dataset_id=f"{self.name}.{name}",
            layer="databases",
            store=self.store,
        )

    def metadata(self) -> dict[str, Any]:
        path = self.root / "database.json"
        if not path.exists():
            return {"name": self.name, "products": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def products(self) -> tuple[ProductRef, ...]:
        return tuple(
            ProductRef(
                dataset_id=str(item["dataset_id"]),
                layer=str(item.get("layer", "databases")),
                store=self.store,
            )
            for item in self.metadata().get("products", [])
        )

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

    def adopt_dataset(
        self,
        dataset: DatasetRecord,
        *,
        description: str = "",
    ) -> ProductRef:
        manifest = dataset.manifest()
        product = ProductRef(
            dataset_id=str(manifest["dataset_id"]),
            layer=str(manifest["layer"]),
            store=self.store,
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_metadata(product, description=description)
        return product

    def _write_metadata(self, product: ProductRef, *, description: str) -> None:
        path = self.root / "database.json"
        payload = self.metadata()
        entry = {
            "name": product.name,
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
