from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sopran.core.pages import InfoPage
from sopran.core.schema import InstrumentSchema
from sopran.core.store import DatasetRecord


@dataclass(frozen=True)
class ProductRef:
    dataset_id: str
    layer: str
    store: Any | None = field(default=None, repr=False, compare=False)
    database_name: str | None = field(default=None, repr=False, compare=False)
    description: str = ""

    @property
    def name(self) -> str:
        return self.dataset_id.split(".")[-1]

    def scan(self):
        if self.store is None:
            raise ValueError("ProductRef.scan() requires a Store-backed reference")
        return self.store.scan_dataset(self.dataset_id, layer=self.layer)

    def manifest(self) -> dict[str, Any]:
        return self._record().manifest()

    def schema(self) -> dict[str, Any]:
        return self._record().schema()

    def info(self) -> InfoPage:
        manifest = self.manifest()
        time_coverage = manifest.get("time_coverage")
        lines = [
            f"dataset_id: {self.dataset_id}",
            f"layer: {self.layer}",
            f"product: {manifest.get('product', self.name)}",
            f"status: {manifest.get('status', 'unknown')}",
        ]
        if self.database_name is not None:
            lines.insert(1, f"database: {self.database_name}")
        if self.description:
            lines.append(f"description: {self.description}")
        if isinstance(time_coverage, dict):
            lines.append(
                f"time: {time_coverage.get('start')} to {time_coverage.get('stop')}"
            )
        return InfoPage(title=f"ProductRef {self.dataset_id}", lines=tuple(lines))

    def adopt_dataset(
        self,
        dataset: DatasetRecord,
        *,
        description: str | None = None,
    ) -> ProductRef:
        if self.store is None:
            raise ValueError(
                "ProductRef.adopt_dataset() requires a Store-backed reference"
            )
        if self.database_name is None:
            return self
        database = Database(
            name=self.database_name,
            root=self.store.database_path(self.database_name),
            store=self.store,
        )
        return database.adopt_dataset(
            dataset,
            description=self.description if description is None else description,
        )

    def _record(self) -> DatasetRecord:
        if self.store is None:
            raise ValueError("ProductRef metadata requires a Store-backed reference")
        return self.store.dataset(self.dataset_id, layer=self.layer)


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

    def product(self, name: str, *, description: str = "") -> ProductRef:
        if not name:
            raise ValueError("database product name must not be empty")
        return ProductRef(
            dataset_id=f"{self.name}.{name}",
            layer="databases",
            store=self.store,
            database_name=self.name,
            description=description,
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
                database_name=self.name,
                description=str(item.get("description") or ""),
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
            database_name=self.name,
            description=description,
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
