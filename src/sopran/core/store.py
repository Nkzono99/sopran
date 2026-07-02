from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from sopran.core.errors import DatasetNotFoundError
from sopran.core.schema import InstrumentSchema
from sopran.core.time import TimeRange


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

    def dataset_path(self, dataset_id: str, *, layer: str) -> Path:
        return self._layer_path(layer, *_dataset_parts(dataset_id))

    def register_dataset(
        self,
        *,
        dataset_id: str,
        layer: str,
        mission: str,
        instrument: str,
        product: str,
        schema: InstrumentSchema,
        time_coverage: TimeRange,
        source_files: tuple[str, ...] = (),
        shards: tuple[dict[str, Any], ...] = (),
        producer: str = "sopran",
    ) -> DatasetRecord:
        record = DatasetRecord(root=self.dataset_path(dataset_id, layer=layer))
        record.root.mkdir(parents=True, exist_ok=True)
        _write_json(
            record.manifest_path,
            {
                "dataset_id": dataset_id,
                "layer": layer,
                "mission": mission,
                "instrument": instrument,
                "product": product,
                "time_coverage": {
                    "start": time_coverage.start_iso,
                    "stop": time_coverage.stop_iso,
                },
                "source_files": list(source_files),
                "producer": producer,
            },
        )
        _write_json(record.schema_path, _schema_to_json(schema))
        _write_catalog(record.catalog_path, shards)
        return record

    def write_parquet_dataset(
        self,
        *,
        dataset_id: str,
        layer: str,
        mission: str,
        instrument: str,
        product: str,
        schema: InstrumentSchema,
        time_coverage: TimeRange,
        frame: Any,
        source_files: tuple[str, ...] = (),
        shard_path: str = "shards/part-000.parquet",
        compression: str = "zstd",
        producer: str = "sopran",
    ) -> DatasetRecord:
        record = DatasetRecord(root=self.dataset_path(dataset_id, layer=layer))
        target = _resolve_child(record.root, shard_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(target, compression=compression)

        return self.register_dataset(
            dataset_id=dataset_id,
            layer=layer,
            mission=mission,
            instrument=instrument,
            product=product,
            schema=schema,
            time_coverage=time_coverage,
            source_files=source_files,
            shards=(
                {
                    "path": Path(shard_path).as_posix(),
                    "row_count": _frame_row_count(frame),
                    "checksum": _sha256_file(target),
                    "status": "complete",
                },
            ),
            producer=producer,
        )

    def scan_dataset(self, dataset_id: str, *, layer: str):
        import polars as pl

        record = DatasetRecord(root=self.dataset_path(dataset_id, layer=layer))
        catalog = pl.read_parquet(record.catalog_path)
        paths = [
            _resolve_child(record.root, path)
            for path in catalog.select("path").to_series().to_list()
            if path
        ]
        if not paths:
            raise DatasetNotFoundError(f"Dataset has no parquet shards: {dataset_id}")
        return pl.scan_parquet([str(path) for path in paths])

    def _layer_path(self, layer: str, *parts: str) -> Path:
        if layer == "raw":
            return self.raw_path(*parts)
        if layer == "normalized":
            return self.normalized_path(*parts)
        if layer == "features":
            return self.features_path(*parts)
        if layer == "databases":
            return self.database_path(*parts)
        raise ValueError("layer must be raw, normalized, features, or databases")


@dataclass(frozen=True)
class DatasetRecord:
    root: Path

    @property
    def manifest_path(self) -> Path:
        return self.root / "dataset.json"

    @property
    def schema_path(self) -> Path:
        return self.root / "schema.json"

    @property
    def catalog_path(self) -> Path:
        return self.root / "catalog.parquet"


def _dataset_parts(dataset_id: str) -> tuple[str, ...]:
    return tuple(part for part in dataset_id.split(".") if part)


def _schema_to_json(schema: InstrumentSchema) -> dict[str, Any]:
    return {
        "mission": schema.mission,
        "instrument": schema.instrument,
        "variables": [
            {
                "name": variable.name,
                "dims": list(variable.dims),
                "units": variable.units,
                "description": variable.description,
                "aliases": list(variable.aliases),
            }
            for variable in schema.variables
        ],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_catalog(path: Path, shards: tuple[dict[str, Any], ...]) -> None:
    import polars as pl

    rows = [
        {
            "path": shard.get("path", ""),
            "row_count": int(shard.get("row_count", 0)),
            "checksum": shard.get("checksum", ""),
            "status": shard.get("status", "pending"),
        }
        for shard in shards
    ]
    if not rows:
        rows = [{"path": "", "row_count": 0, "checksum": "", "status": "empty"}]
    pl.DataFrame(rows).write_parquet(path)


def _resolve_child(root: Path, child: str) -> Path:
    target = (root / child).resolve()
    resolved_root = root.resolve()
    if not target.is_relative_to(resolved_root):
        raise ValueError(f"Path escapes dataset root: {child}")
    return target


def _frame_row_count(frame: Any) -> int:
    height = getattr(frame, "height", None)
    if height is not None:
        return int(height)
    if isinstance(frame, Mapping):
        return len(frame)
    return int(len(frame))


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
