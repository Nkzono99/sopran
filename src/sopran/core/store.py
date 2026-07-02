from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from sopran.core.errors import DatasetNotFoundError
from sopran.core.schema import InstrumentSchema
from sopran.core.time import TimeRange, period

_LAYERS = ("raw", "normalized", "features", "databases")
_DATASET_SCHEMA_VERSION = "0.1"


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

    def registry_path(self, *parts: str) -> Path:
        return self.root.joinpath("registry", *parts)

    def database(self, name: str):
        from sopran.core.database import Database

        if not name:
            raise ValueError("database name must not be empty")
        return Database(name=name, root=self.database_path(name), store=self)

    def dataset_path(self, dataset_id: str, *, layer: str) -> Path:
        return self._layer_path(layer, *_dataset_parts(dataset_id))

    def dataset(self, dataset_id: str, *, layer: str | None = None) -> DatasetRecord:
        if layer is not None:
            record = DatasetRecord(root=self.dataset_path(dataset_id, layer=layer))
            if record.manifest_path.exists():
                return record
            raise DatasetNotFoundError(f"Dataset not found: {dataset_id} ({layer})")

        matches = []
        for candidate_layer in _LAYERS:
            record = DatasetRecord(root=self.dataset_path(dataset_id, layer=candidate_layer))
            if record.manifest_path.exists():
                matches.append(record)
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise DatasetNotFoundError(f"Dataset not found: {dataset_id}")
        raise DatasetNotFoundError(f"Dataset exists in multiple layers: {dataset_id}")

    def register_dataset(
        self,
        *,
        dataset_id: str,
        layer: str,
        mission: str,
        instrument: str,
        product: str,
        schema: InstrumentSchema,
        time_coverage: TimeRange | None,
        source_files: tuple[str, ...] = (),
        shards: tuple[dict[str, Any], ...] = (),
        producer: str = "sopran",
        provenance: dict[str, Any] | None = None,
    ) -> DatasetRecord:
        record = DatasetRecord(root=self.dataset_path(dataset_id, layer=layer))
        record.root.mkdir(parents=True, exist_ok=True)
        manifest = {
            "dataset_id": dataset_id,
            "layer": layer,
            "mission": mission,
            "instrument": instrument,
            "product": product,
            "schema_version": _DATASET_SCHEMA_VERSION,
            "time_coverage": _time_coverage_to_json(time_coverage),
            "source_files": list(source_files),
            "producer": producer,
            "software": _software_metadata(),
        }
        if provenance is not None:
            manifest["provenance"] = provenance
        _write_json(
            record.manifest_path,
            manifest,
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
        overwrite: bool = False,
        append: bool = False,
        producer: str = "sopran",
        provenance: dict[str, Any] | None = None,
    ) -> DatasetRecord:
        if append and overwrite:
            raise ValueError("append and overwrite cannot both be true")

        record = DatasetRecord(root=self.dataset_path(dataset_id, layer=layer))
        existing_shards = _read_catalog_shards(record.catalog_path) if append else ()
        manifest_time_coverage = (
            _merge_time_coverage(record.manifest_path, time_coverage) if append else time_coverage
        )
        manifest_source_files = (
            _merge_source_files(record.manifest_path, source_files) if append else source_files
        )
        if append and shard_path == "shards/part-000.parquet":
            shard_path = _next_shard_path(existing_shards)
        target = _resolve_child(record.root, shard_path)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Parquet shard already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(target, compression=compression)

        return self.register_dataset(
            dataset_id=dataset_id,
            layer=layer,
            mission=mission,
            instrument=instrument,
            product=product,
            schema=schema,
            time_coverage=manifest_time_coverage,
            source_files=manifest_source_files,
            shards=(
                *existing_shards,
                {
                    "path": Path(shard_path).as_posix(),
                    "start": time_coverage.start_iso,
                    "stop": time_coverage.stop_iso,
                    "row_count": _frame_row_count(frame),
                    "checksum": _sha256_file(target),
                    "status": "complete",
                },
            ),
            producer=producer,
            provenance=provenance,
        )

    def scan_dataset(self, dataset_id: str, *, layer: str):
        record = DatasetRecord(root=self.dataset_path(dataset_id, layer=layer))
        if not record.catalog_path.exists():
            raise DatasetNotFoundError(f"Dataset not found: {dataset_id} ({layer})")
        return record.scan(dataset_id=dataset_id)

    def rebuild_registry(self):
        path = self.registry_path("datasets.parquet")
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = _dataset_index_frame(_dataset_index_rows(self.root))
        frame.write_parquet(path)
        return frame.sort(["layer", "dataset_id"])

    def datasets(
        self,
        *,
        layer: str | None = None,
        mission: str | None = None,
        instrument: str | None = None,
        product: str | None = None,
        refresh: bool = False,
    ):
        import polars as pl

        index_path = self.registry_path("datasets.parquet")
        if refresh or not index_path.exists():
            frame = self.rebuild_registry()
        else:
            frame = pl.read_parquet(index_path)

        filters = {
            "layer": layer,
            "mission": mission,
            "instrument": instrument,
            "product": product,
        }
        for column, value in filters.items():
            if value is not None:
                frame = frame.filter(pl.col(column) == value)
        return frame.sort(["layer", "dataset_id"])

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

    def manifest(self) -> dict[str, Any]:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def schema(self) -> dict[str, Any]:
        return json.loads(self.schema_path.read_text(encoding="utf-8"))

    def catalog(self):
        import polars as pl

        return pl.read_parquet(self.catalog_path)

    def scan(self, *, dataset_id: str | None = None):
        import polars as pl

        catalog = self.catalog()
        paths = [
            _resolve_child(self.root, path)
            for path in catalog.select("path").to_series().to_list()
            if path
        ]
        if not paths:
            name = dataset_id or str(self.root)
            raise DatasetNotFoundError(f"Dataset has no parquet shards: {name}")
        return pl.scan_parquet([str(path) for path in paths])


def _dataset_parts(dataset_id: str) -> tuple[str, ...]:
    return tuple(part for part in dataset_id.split(".") if part)


def _schema_to_json(schema: InstrumentSchema) -> dict[str, Any]:
    return {
        "mission": schema.mission,
        "instrument": schema.instrument,
        "schema_version": _DATASET_SCHEMA_VERSION,
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


def _software_metadata() -> dict[str, str]:
    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "sopran": _sopran_version(),
    }


def _sopran_version() -> str:
    try:
        return version("sopran")
    except PackageNotFoundError:
        return "0.0.0"


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
            "schema_version": shard.get("schema_version", _DATASET_SCHEMA_VERSION),
            "start": shard.get("start", ""),
            "stop": shard.get("stop", ""),
            "row_count": int(shard.get("row_count", 0)),
            "checksum": shard.get("checksum", ""),
            "status": shard.get("status", "pending"),
        }
        for shard in shards
    ]
    if not rows:
        rows = [
            {
                "path": "",
                "schema_version": _DATASET_SCHEMA_VERSION,
                "start": "",
                "stop": "",
                "row_count": 0,
                "checksum": "",
                "status": "empty",
            }
        ]
    pl.DataFrame(rows).write_parquet(path)


def _time_coverage_to_json(time_coverage: TimeRange | None) -> dict[str, str] | None:
    if time_coverage is None:
        return None
    return {
        "start": time_coverage.start_iso,
        "stop": time_coverage.stop_iso,
    }


def _merge_time_coverage(path: Path, new: TimeRange | None) -> TimeRange | None:
    if new is None or not path.exists():
        return new
    existing = json.loads(path.read_text(encoding="utf-8")).get("time_coverage")
    if not existing:
        return new
    start = min(str(existing["start"]), new.start_iso)
    stop = max(str(existing["stop"]), new.stop_iso)
    return period(start, stop)


def _merge_source_files(path: Path, new: tuple[str, ...]) -> tuple[str, ...]:
    if not path.exists():
        return new
    manifest = json.loads(path.read_text(encoding="utf-8"))
    merged = []
    for source in (*manifest.get("source_files", []), *new):
        if source not in merged:
            merged.append(str(source))
    return tuple(merged)


def _read_catalog_shards(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()

    import polars as pl

    rows = []
    for row in pl.read_parquet(path).iter_rows(named=True):
        shard_path = str(row.get("path") or "")
        if not shard_path:
            continue
        rows.append(
            {
                "path": shard_path,
                "start": str(row.get("start") or ""),
                "stop": str(row.get("stop") or ""),
                "row_count": int(row.get("row_count") or 0),
                "checksum": str(row.get("checksum") or ""),
                "status": str(row.get("status") or "complete"),
            }
        )
    return tuple(rows)


def _next_shard_path(shards: tuple[dict[str, Any], ...]) -> str:
    existing = {str(shard.get("path") or "") for shard in shards}
    index = 0
    while True:
        candidate = f"shards/part-{index:03d}.parquet"
        if candidate not in existing:
            return candidate
        index += 1


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


def _dataset_index_rows(root: Path) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for layer in _LAYERS:
        layer_root = root / layer
        if not layer_root.exists():
            continue
        for manifest_path in sorted(layer_root.rglob("dataset.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            time_coverage = manifest.get("time_coverage") or {}
            dataset_root = manifest_path.parent
            rows.append(
                {
                    "dataset_id": str(manifest.get("dataset_id") or ""),
                    "layer": str(manifest.get("layer") or layer),
                    "mission": str(manifest.get("mission") or ""),
                    "instrument": str(manifest.get("instrument") or ""),
                    "product": str(manifest.get("product") or ""),
                    "schema_version": str(
                        manifest.get("schema_version") or _DATASET_SCHEMA_VERSION
                    ),
                    "start": str(time_coverage.get("start") or ""),
                    "stop": str(time_coverage.get("stop") or ""),
                    "path": dataset_root.relative_to(root).as_posix(),
                }
            )
    return tuple(rows)


def _dataset_index_frame(rows: tuple[dict[str, Any], ...]):
    import polars as pl

    schema = {
        "dataset_id": pl.Utf8,
        "layer": pl.Utf8,
        "mission": pl.Utf8,
        "instrument": pl.Utf8,
        "product": pl.Utf8,
        "schema_version": pl.Utf8,
        "start": pl.Utf8,
        "stop": pl.Utf8,
        "path": pl.Utf8,
    }
    if not rows:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(rows, schema=schema)
