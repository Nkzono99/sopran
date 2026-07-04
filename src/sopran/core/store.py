from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, cast

from sopran.core.config import config_section, configured_path, read_user_config
from sopran.core.errors import DatasetNotFoundError
from sopran.core.schema import InstrumentSchema, VariableSchema, validate_schema
from sopran.core.time import TimeRange, period

_LAYERS = ("raw", "normalized", "features", "models", "databases")
_DATASET_SCHEMA_VERSION = "0.1"
_DATASET_STATUSES = ("scratch", "candidate", "adopted", "deprecated")
_CATALOG_SHARD_STATUSES = ("pending", "running", "complete", "failed", "skipped")


@dataclass(frozen=True)
class Store:
    """Filesystem roots used by SOPRAN data discovery and products."""

    root: Path | str | None = None
    cache_root: Path | str | None = None

    def __post_init__(self) -> None:
        user_config, user_config_path = read_user_config()
        store_config = config_section(user_config, "store")
        config_base = user_config_path.parent

        env_root = os.environ.get("SOPRAN_DATA_ROOT")
        env_cache_root = os.environ.get("SOPRAN_CACHE_ROOT")
        root: Path
        if self.root is not None:
            root = Path(self.root)
        elif env_root:
            root = Path(env_root)
        else:
            root = cast(
                Path,
                configured_path(
                config_base,
                store_config.get("data_root"),
                default=Path("sopran_data"),
                ),
            )

        cache_root: Path | None
        if self.cache_root is not None:
            cache_root = Path(self.cache_root)
        elif env_cache_root:
            cache_root = Path(env_cache_root)
        else:
            cache_root = configured_path(
                config_base,
                store_config.get("cache_root"),
                default=None,
            )
        object.__setattr__(self, "root", Path(root))
        cache_path = Path(cache_root) if cache_root else Path(root) / "cache"
        object.__setattr__(self, "cache_root", cache_path)

    @property
    def _root(self) -> Path:
        return cast(Path, self.root)

    @property
    def _cache_root(self) -> Path:
        return cast(Path, self.cache_root)

    def raw_path(self, *parts: str) -> Path:
        return self._root.joinpath("raw", *parts)

    def normalized_path(self, *parts: str) -> Path:
        return self._root.joinpath("normalized", *parts)

    def features_path(self, *parts: str) -> Path:
        return self._root.joinpath("features", *parts)

    def models_path(self, *parts: str) -> Path:
        return self._root.joinpath("models", *parts)

    def database_path(self, *parts: str) -> Path:
        return self._root.joinpath("databases", *parts)

    def registry_path(self, *parts: str) -> Path:
        return self._root.joinpath("registry", *parts)

    def raw_file(self, path: Path | str) -> RawFileRecord:
        raw_file = _resolve_raw_file(self._root, path)
        manifest_path = raw_file.with_name(f"{raw_file.name}.sopran.json")
        if not raw_file.exists():
            raise FileNotFoundError(f"Raw file not found: {raw_file}")
        if not manifest_path.exists():
            raise FileNotFoundError(f"Raw file manifest not found: {manifest_path}")
        return RawFileRecord(path=raw_file, manifest_path=manifest_path)

    def register_raw_file(
        self,
        path: Path | str,
        *,
        mission: str,
        provider: str,
        provider_path: str | None = None,
        data_version: str | None = None,
        download_url: str | None = None,
        acquired_at: str | None = None,
    ) -> RawFileRecord:
        raw_file = _resolve_raw_file(self._root, path)
        if not raw_file.exists():
            raise FileNotFoundError(f"Raw file not found: {raw_file}")
        manifest_path = raw_file.with_name(f"{raw_file.name}.sopran.json")
        manifest = {
            "path": raw_file.relative_to(self._root).as_posix(),
            "filename": raw_file.name,
            "mission": mission,
            "provider": provider,
            "provider_path": provider_path,
            "version": data_version,
            "download_url": download_url,
            "acquired_at": acquired_at or _utc_now_iso(),
            "checksum": _sha256_file(raw_file),
            "size_bytes": raw_file.stat().st_size,
        }
        _write_json(manifest_path, manifest)
        return RawFileRecord(path=raw_file, manifest_path=manifest_path)

    def rebuild_raw_file_registry(self) -> Any:
        path = self.registry_path("raw_files.parquet")
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = _raw_file_index_frame(_raw_file_index_rows(self._root))
        frame.write_parquet(path)
        return frame.sort("path")

    def raw_files(
        self,
        *,
        mission: str | None = None,
        provider: str | None = None,
        filename: str | None = None,
        provider_path: str | None = None,
        data_version: str | None = None,
        acquired_after: str | None = None,
        acquired_before: str | None = None,
        refresh: bool = False,
    ) -> Any:
        import polars as pl

        index_path = self.registry_path("raw_files.parquet")
        if refresh or not index_path.exists():
            frame = self.rebuild_raw_file_registry()
        else:
            frame = pl.read_parquet(index_path)

        filters = {
            "mission": mission,
            "provider": provider,
            "filename": filename,
            "provider_path": provider_path,
            "version": data_version,
        }
        for column, value in filters.items():
            if value is not None:
                frame = frame.filter(pl.col(column) == value)
        if acquired_after is not None or acquired_before is not None:
            frame = frame.filter(pl.col("acquired_at") != "")
        if acquired_after is not None:
            frame = frame.filter(pl.col("acquired_at") >= acquired_after)
        if acquired_before is not None:
            frame = frame.filter(pl.col("acquired_at") < acquired_before)
        return frame.sort("path")

    def database(self, name: str, *, create: bool = False) -> Any:
        from sopran.core.database import Database

        if not name:
            raise ValueError("database name must not be empty")
        database = Database(name=name, root=self.database_path(name), store=self)
        if create:
            database.create()
        return database

    def dataset_path(
        self,
        dataset_id: str,
        *,
        layer: str,
        variant_id: str | None = None,
    ) -> Path:
        parts = _dataset_parts(dataset_id)
        if variant_id is not None:
            _validate_variant_id(variant_id)
            parts = (*parts, "variants", variant_id)
        return self._layer_path(layer, *parts)

    def dataset(
        self,
        dataset_id: str,
        *,
        layer: str | None = None,
        variant_id: str | None = None,
    ) -> DatasetRecord:
        if layer is not None:
            record = DatasetRecord(
                root=self.dataset_path(
                    dataset_id,
                    layer=layer,
                    variant_id=variant_id,
                )
            )
            if record.manifest_path.exists():
                return record
            suffix = f", variant={variant_id}" if variant_id is not None else ""
            raise DatasetNotFoundError(f"Dataset not found: {dataset_id} ({layer}{suffix})")

        matches = []
        for candidate_layer in _LAYERS:
            record = DatasetRecord(
                root=self.dataset_path(
                    dataset_id,
                    layer=candidate_layer,
                    variant_id=variant_id,
                )
            )
            if record.manifest_path.exists():
                matches.append(record)
        if len(matches) == 1:
            return matches[0]
        if not matches:
            suffix = f" (variant={variant_id})" if variant_id is not None else ""
            raise DatasetNotFoundError(f"Dataset not found: {dataset_id}{suffix}")
        raise DatasetNotFoundError(f"Dataset exists in multiple layers: {dataset_id}")

    def register_dataset(
        self,
        *,
        dataset_id: str,
        layer: str,
        variant_id: str | None = None,
        variant: dict[str, Any] | None = None,
        mission: str,
        instrument: str,
        product: str,
        schema: InstrumentSchema,
        time_coverage: TimeRange | None,
        source_files: tuple[str, ...] = (),
        source_datasets: tuple[str, ...] = (),
        shards: tuple[dict[str, Any], ...] = (),
        producer: str = "sopran",
        provenance: dict[str, Any] | None = None,
        status: str = "candidate",
        parameters: dict[str, Any] | None = None,
        context: Any | None = None,
        storage_layout: dict[str, Any] | None = None,
        dataset_version: str = "1",
        partitioning: tuple[str, ...] = (),
    ) -> DatasetRecord:
        _validate_dataset_status(status)
        source_files = _normalize_store_source_files(self._root, source_files)
        record = DatasetRecord(
            root=self.dataset_path(
                dataset_id,
                layer=layer,
                variant_id=variant_id,
            )
        )
        record.root.mkdir(parents=True, exist_ok=True)
        manifest = {
            "dataset_id": dataset_id,
            "layer": layer,
            "mission": mission,
            "instrument": instrument,
            "product": product,
            "version": dataset_version,
            "schema_version": _DATASET_SCHEMA_VERSION,
            "status": status,
            "created_at": _utc_now_iso(),
            "time_coverage": _time_coverage_to_json(time_coverage),
            "source_datasets": list(source_datasets),
            "source_files": list(source_files),
            "producer": producer,
            "software": _software_metadata(),
            "parameters": parameters or {},
            "partitioning": list(partitioning),
        }
        if storage_layout is not None:
            manifest["storage_layout"] = storage_layout
        if variant_id is not None:
            manifest["variant"] = {**(variant or {}), "id": variant_id}
        if provenance is not None:
            manifest["provenance"] = provenance
        if context is not None:
            manifest["context"] = _context_metadata(context)
        _write_dataset_metadata(
            record,
            manifest=manifest,
            schema_payload=_schema_to_json(schema),
            shards=shards,
        )
        return record

    def write_parquet_dataset(
        self,
        *,
        dataset_id: str,
        layer: str,
        variant_id: str | None = None,
        variant: dict[str, Any] | None = None,
        mission: str,
        instrument: str,
        product: str,
        schema: InstrumentSchema,
        time_coverage: TimeRange,
        frame: Any,
        source_files: tuple[str, ...] = (),
        source_datasets: tuple[str, ...] = (),
        shard_path: str = "shards/part-000.parquet",
        compression: str = "zstd",
        overwrite: bool = False,
        append: bool = False,
        producer: str = "sopran",
        provenance: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
        context: Any | None = None,
        status: str = "candidate",
        dataset_version: str = "1",
        partitioning: tuple[str, ...] = (),
    ) -> DatasetRecord:
        if append and overwrite:
            raise ValueError("append and overwrite cannot both be true")
        _validate_dataset_status(status)
        _validate_product_frame(frame, schema, product)

        record = DatasetRecord(
            root=self.dataset_path(
                dataset_id,
                layer=layer,
                variant_id=variant_id,
            )
        )
        existing_shards = _read_catalog_shards(record.catalog_path) if append else ()
        manifest_time_coverage = (
            _merge_time_coverage(record.manifest_path, time_coverage) if append else time_coverage
        )
        manifest_source_files = (
            _merge_source_files(record.manifest_path, source_files) if append else source_files
        )
        manifest_source_datasets = (
            _merge_source_datasets(record.manifest_path, source_datasets)
            if append
            else source_datasets
        )
        if append and shard_path == "shards/part-000.parquet":
            shard_path = _next_shard_path(existing_shards)
        target = _resolve_child(record.root, shard_path)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Parquet shard already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target_preexisting = target.exists()
        temp_target = target.with_name(f"{target.name}.tmp")
        backup_target = _sibling_temp_path(target, ".bak")
        if temp_target.exists():
            temp_target.unlink()
        new_target_written = False
        try:
            frame.write_parquet(temp_target, compression=compression)
            if target_preexisting:
                target.replace(backup_target)
            temp_target.replace(target)
            new_target_written = True
            written = self.register_dataset(
                dataset_id=dataset_id,
                layer=layer,
                variant_id=variant_id,
                variant=variant,
                mission=mission,
                instrument=instrument,
                product=product,
                schema=schema,
                time_coverage=manifest_time_coverage,
                source_files=manifest_source_files,
                source_datasets=manifest_source_datasets,
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
                parameters=parameters,
                context=context,
                storage_layout=_parquet_storage_layout(frame, schema, product),
                status=status,
                dataset_version=dataset_version,
                partitioning=partitioning,
            )
        except Exception:
            if new_target_written and target.exists():
                target.unlink()
            if target_preexisting and backup_target.exists():
                backup_target.replace(target)
            if temp_target.exists():
                temp_target.unlink()
            if backup_target.exists():
                backup_target.unlink()
            raise
        if backup_target.exists():
            backup_target.unlink()
        return written

    def scan_dataset(
        self,
        dataset_id: str,
        *,
        layer: str,
        variant_id: str | None = None,
    ) -> Any:
        record = DatasetRecord(
            root=self.dataset_path(
                dataset_id,
                layer=layer,
                variant_id=variant_id,
            )
        )
        if not record.catalog_path.exists():
            suffix = f", variant={variant_id}" if variant_id is not None else ""
            raise DatasetNotFoundError(f"Dataset not found: {dataset_id} ({layer}{suffix})")
        return record.scan(dataset_id=dataset_id)

    def dataset_source_files(
        self,
        dataset_id: str,
        *,
        layer: str | None = None,
        variant_id: str | None = None,
    ) -> tuple[RawFileRecord, ...]:
        manifest = self.dataset(
            dataset_id,
            layer=layer,
            variant_id=variant_id,
        ).manifest()
        return tuple(self.raw_file(path) for path in manifest.get("source_files", []))

    def verify_dataset(
        self,
        dataset_id: str,
        *,
        layer: str | None = None,
        variant_id: str | None = None,
        source_files: bool = True,
        shard_status: str | None = None,
    ) -> bool:
        record = self.dataset(dataset_id, layer=layer, variant_id=variant_id)
        if not record.verify_checksums(status=shard_status):
            return False
        if source_files:
            try:
                source_records = self.dataset_source_files(
                    dataset_id,
                    layer=layer,
                    variant_id=variant_id,
                )
            except FileNotFoundError:
                return False
            return all(raw_file.verify_checksum() for raw_file in source_records)
        return True

    def rebuild_registry(self) -> Any:
        path = self.registry_path("datasets.parquet")
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = _dataset_index_frame(_dataset_index_rows(self._root))
        frame.write_parquet(path)
        return frame.sort(["layer", "dataset_id"])

    def datasets(
        self,
        *,
        layer: str | None = None,
        mission: str | None = None,
        instrument: str | None = None,
        product: str | None = None,
        variant_id: str | None = None,
        schema_version: str | None = None,
        dataset_version: str | None = None,
        status: str | None = None,
        time_range: TimeRange | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        refresh: bool = False,
    ) -> Any:
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
            "variant_id": variant_id,
            "schema_version": schema_version,
            "version": dataset_version,
            "status": status,
        }
        for column, value in filters.items():
            if value is not None:
                frame = frame.filter(pl.col(column) == value)
        if time_range is not None:
            rows = [
                row
                for row in frame.to_dicts()
                if _time_coverage_intersects(
                    str(row.get("start") or ""),
                    str(row.get("stop") or ""),
                    time_range,
                )
            ]
            frame = pl.DataFrame(rows, schema=frame.schema)
        if created_after is not None or created_before is not None:
            frame = frame.filter(pl.col("created_at") != "")
        if created_after is not None:
            frame = frame.filter(pl.col("created_at") >= created_after)
        if created_before is not None:
            frame = frame.filter(pl.col("created_at") < created_before)
        return frame.sort(["layer", "dataset_id"])

    def _layer_path(self, layer: str, *parts: str) -> Path:
        if layer == "raw":
            return self.raw_path(*parts)
        if layer == "normalized":
            return self.normalized_path(*parts)
        if layer == "features":
            return self.features_path(*parts)
        if layer == "models":
            return self.models_path(*parts)
        if layer == "databases":
            return self.database_path(*parts)
        raise ValueError("layer must be raw, normalized, features, models, or databases")


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
        return cast(dict[str, Any], json.loads(self.manifest_path.read_text(encoding="utf-8")))

    def schema(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.schema_path.read_text(encoding="utf-8")))

    def catalog(self) -> Any:
        import polars as pl

        return pl.read_parquet(self.catalog_path)

    def shards(self, *, status: str | None = None) -> tuple[dict[str, Any], ...]:
        if status is not None:
            _validate_catalog_shard_status(status)
        shards = _read_catalog_shards(self.catalog_path)
        if status is None:
            return shards
        return tuple(shard for shard in shards if shard.get("status") == status)

    def failed_shards(self) -> tuple[dict[str, Any], ...]:
        return self.shards(status="failed")

    def replace_shard(
        self,
        shard_path: str | Path,
        *,
        frame: Any,
        time_coverage: TimeRange,
        compression: str = "zstd",
    ) -> DatasetRecord:
        import polars as pl

        path_text = Path(shard_path).as_posix()
        catalog = self.catalog()
        if path_text not in catalog.select("path").to_series().to_list():
            raise KeyError(f"Shard not found in catalog: {path_text}")

        target = _resolve_child(self.root, path_text)
        target.parent.mkdir(parents=True, exist_ok=True)
        backup_target = _sibling_temp_path(target, ".bak")
        temp_target = _sibling_temp_path(target, ".tmp")
        try:
            frame.write_parquet(temp_target, compression=compression)
            if target.exists():
                target.replace(backup_target)
            temp_target.replace(target)
            row_count = _frame_row_count(frame)
            checksum = _sha256_file(target)
            updated = catalog.with_columns(
                [
                    pl.when(pl.col("path") == path_text)
                    .then(pl.lit(time_coverage.start_iso))
                    .otherwise(pl.col("start"))
                    .alias("start"),
                    pl.when(pl.col("path") == path_text)
                    .then(pl.lit(time_coverage.stop_iso))
                    .otherwise(pl.col("stop"))
                    .alias("stop"),
                    pl.when(pl.col("path") == path_text)
                    .then(pl.lit(row_count))
                    .otherwise(pl.col("row_count"))
                    .alias("row_count"),
                    pl.when(pl.col("path") == path_text)
                    .then(pl.lit(checksum))
                    .otherwise(pl.col("checksum"))
                    .alias("checksum"),
                    pl.when(pl.col("path") == path_text)
                    .then(pl.lit("complete"))
                    .otherwise(pl.col("status"))
                    .alias("status"),
                ]
            )
            updated_shards = tuple(updated.to_dicts())
            manifest = self.manifest()
            manifest["time_coverage"] = _time_coverage_to_json(
                _time_coverage_from_shards(updated_shards)
            )
            _write_dataset_metadata(
                self,
                manifest=manifest,
                schema_payload=self.schema(),
                shards=updated_shards,
            )
        except Exception:
            if target.exists():
                target.unlink()
            if backup_target.exists():
                backup_target.replace(target)
            if temp_target.exists():
                temp_target.unlink()
            raise
        if backup_target.exists():
            backup_target.unlink(missing_ok=True)
        return self

    def scan(self, *, dataset_id: str | None = None) -> Any:
        import polars as pl

        paths = [
            _resolve_child(self.root, str(shard["path"]))
            for shard in self.shards(status="complete")
            if shard.get("path")
        ]
        if not paths:
            name = dataset_id or str(self.root)
            raise DatasetNotFoundError(f"Dataset has no complete parquet shards: {name}")
        return pl.scan_parquet([str(path) for path in paths])

    def verify_checksums(self, *, status: str | None = None) -> bool:
        for row in self.shards(status=status):
            shard_path = str(row.get("path") or "")
            expected = str(row.get("checksum") or "")
            if not shard_path:
                continue
            target = _resolve_child(self.root, shard_path)
            if not target.exists() or expected != _sha256_file(target):
                return False
        return True

    def update_shard_status(self, shard_path: str | Path, status: str) -> DatasetRecord:
        _validate_catalog_shard_status(status)
        import polars as pl

        path_text = Path(shard_path).as_posix()
        catalog = self.catalog()
        if path_text not in catalog.select("path").to_series().to_list():
            raise KeyError(f"Shard not found in catalog: {path_text}")
        updated = catalog.with_columns(
            pl.when(pl.col("path") == path_text)
            .then(pl.lit(status))
            .otherwise(pl.col("status"))
            .alias("status")
        )
        _write_parquet(updated, self.catalog_path)
        return self


@dataclass(frozen=True)
class RawFileRecord:
    path: Path
    manifest_path: Path

    def manifest(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.manifest_path.read_text(encoding="utf-8")))

    def verify_checksum(self) -> bool:
        return self.manifest().get("checksum") == _sha256_file(self.path)


def _dataset_parts(dataset_id: str) -> tuple[str, ...]:
    return tuple(part for part in dataset_id.split(".") if part)


def _validate_variant_id(variant_id: str) -> None:
    if not variant_id:
        raise ValueError("variant_id must not be empty")
    invalid = [
        character
        for character in variant_id
        if not (character.isalnum() or character in {"-", "_", "."})
    ]
    if invalid:
        raise ValueError("variant_id may only contain letters, numbers, '-', '_', or '.'")


def _schema_to_json(schema: InstrumentSchema) -> dict[str, Any]:
    return schema.to_metadata(schema_version=_DATASET_SCHEMA_VERSION)


def _validate_product_frame(frame: Any, schema: InstrumentSchema, product: str) -> None:
    try:
        schema.variable(product)
    except KeyError:
        return
    validate_schema(frame, schema, variables=(product,))


def _parquet_storage_layout(
    frame: Any,
    schema: InstrumentSchema,
    product: str,
) -> dict[str, Any]:
    columns = _frame_columns(frame)
    try:
        variable = schema.variable(product)
    except KeyError:
        return {
            "format": "parquet",
            "layout": "table",
            "index_columns": [],
            "value_columns": columns,
            "encoded_dims": [],
        }
    value_name = _variable_column_name(columns, variable)
    index_columns = [dim for dim in variable.dims if dim in columns]
    encoded_dims = [dim for dim in variable.dims if dim not in index_columns]
    value_columns = [value_name] if value_name is not None else [
        column for column in columns if column not in index_columns
    ]
    if not encoded_dims and value_name is not None:
        layout = "long"
    elif value_name is not None and _column_stores_array(frame, value_name):
        layout = "array"
    else:
        layout = "table"
    return {
        "format": "parquet",
        "layout": layout,
        "index_columns": index_columns,
        "value_columns": value_columns,
        "encoded_dims": encoded_dims,
    }


def _variable_column_name(columns: list[str], variable: VariableSchema) -> str | None:
    if variable.name in columns:
        return variable.name
    for alias in variable.aliases:
        if alias in columns:
            return alias
    return None


def _frame_columns(frame: Any) -> list[str]:
    if hasattr(frame, "collect_schema"):
        return [str(name) for name in frame.collect_schema().names()]
    if hasattr(frame, "columns"):
        return [str(column) for column in frame.columns]
    if isinstance(frame, Mapping):
        return [str(column) for column in frame]
    return []


def _column_stores_array(frame: Any, column: str) -> bool:
    dtype = _frame_column_dtype(frame, column)
    dtype_text = str(dtype).lower() if dtype is not None else ""
    if "array" in dtype_text or "list" in dtype_text:
        return True
    try:
        series = frame[column]
    except Exception:
        return False
    try:
        value = series[0]
    except Exception:
        return False
    return (
        isinstance(value, (list, tuple))
        or (
            hasattr(value, "shape")
            and not isinstance(value, (str, bytes, bytearray))
        )
    )


def _frame_column_dtype(frame: Any, column: str) -> Any | None:
    if hasattr(frame, "collect_schema"):
        return frame.collect_schema().get(column)
    if hasattr(frame, "schema") and isinstance(frame.schema, Mapping):
        return frame.schema.get(column)
    return None


def _software_metadata() -> dict[str, str]:
    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "sopran": _sopran_version(),
    }


def _context_metadata(context: Any) -> dict[str, Any]:
    if isinstance(context, Mapping):
        return dict(context)
    metadata = getattr(context, "metadata", None)
    if callable(metadata):
        metadata = metadata()
    if isinstance(metadata, Mapping):
        return dict(metadata)
    to_metadata = getattr(context, "to_metadata", None)
    if callable(to_metadata):
        metadata = to_metadata()
    if isinstance(metadata, Mapping):
        return dict(metadata)
    raise TypeError("context must be a metadata mapping or expose metadata")


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_dataset_status(status: str) -> None:
    if status not in _DATASET_STATUSES:
        allowed = ", ".join(_DATASET_STATUSES)
        raise ValueError(f"status must be one of: {allowed}")


def _validate_catalog_shard_status(status: str) -> None:
    if status not in _CATALOG_SHARD_STATUSES:
        allowed = ", ".join(_CATALOG_SHARD_STATUSES)
        raise ValueError(f"shard status must be one of: {allowed}")


def _sopran_version() -> str:
    try:
        return version("sopran")
    except PackageNotFoundError:
        return "0.0.0"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _sibling_temp_path(path, ".tmp")
    try:
        temp_path.write_text(text, encoding="utf-8")
        temp_path.replace(path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def _write_parquet(frame: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _sibling_temp_path(path, ".tmp")
    try:
        frame.write_parquet(temp_path)
        temp_path.replace(path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def _write_dataset_metadata(
    record: DatasetRecord,
    *,
    manifest: dict[str, Any],
    schema_payload: dict[str, Any],
    shards: tuple[dict[str, Any], ...],
) -> None:
    temp_manifest = _sibling_temp_path(record.manifest_path, ".tmp")
    temp_schema = _sibling_temp_path(record.schema_path, ".tmp")
    temp_catalog = _sibling_temp_path(record.catalog_path, ".tmp")
    temp_paths = (temp_manifest, temp_schema, temp_catalog)
    backups: list[tuple[Path, Path]] = []
    committed: list[Path] = []
    try:
        _write_json(temp_manifest, manifest)
        _write_json(temp_schema, schema_payload)
        _write_catalog(temp_catalog, shards)
        for target, temp in (
            (record.schema_path, temp_schema),
            (record.catalog_path, temp_catalog),
            (record.manifest_path, temp_manifest),
        ):
            backup = _sibling_temp_path(target, ".bak")
            if target.exists():
                target.replace(backup)
                backups.append((target, backup))
            temp.replace(target)
            committed.append(target)
    except Exception:
        for target in reversed(committed):
            if target.exists():
                target.unlink()
        for target, backup in reversed(backups):
            if backup.exists():
                backup.replace(target)
        for path in temp_paths:
            if path.exists():
                path.unlink()
        raise
    for _, backup in backups:
        if backup.exists():
            with suppress(OSError):
                backup.unlink(missing_ok=True)


def _write_catalog(path: Path, shards: tuple[dict[str, Any], ...]) -> None:
    import polars as pl

    schema = {
        "path": pl.Utf8,
        "schema_version": pl.Utf8,
        "start": pl.Utf8,
        "stop": pl.Utf8,
        "row_count": pl.Int64,
        "checksum": pl.Utf8,
        "status": pl.Utf8,
    }
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
    for row in rows:
        _validate_catalog_shard_status(str(row["status"]))
    if not rows:
        _write_parquet(pl.DataFrame(schema=schema), path)
        return
    _write_parquet(pl.DataFrame(rows, schema=schema), path)


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
    existing_range = _time_range_from_coverage(
        str(existing.get("start") or ""),
        str(existing.get("stop") or ""),
    )
    if existing_range is None:
        return new
    return TimeRange(
        min(existing_range.start, new.start),
        max(existing_range.stop, new.stop),
    )


def _time_range_from_coverage(start: str, stop: str) -> TimeRange | None:
    if not start or not stop:
        return None
    try:
        return period(start, stop)
    except (TypeError, ValueError):
        return None


def _time_coverage_intersects(start: str, stop: str, time_range: TimeRange) -> bool:
    coverage = _time_range_from_coverage(start, stop)
    if coverage is None:
        return False
    return coverage.start < time_range.stop and coverage.stop > time_range.start


def _time_coverage_from_shards(shards: tuple[dict[str, Any], ...]) -> TimeRange | None:
    ranges = [
        coverage
        for shard in shards
        if str(shard.get("status") or "") == "complete"
        for coverage in (
            _time_range_from_coverage(
                str(shard.get("start") or ""),
                str(shard.get("stop") or ""),
            ),
        )
        if coverage is not None
    ]
    if not ranges:
        return None
    return TimeRange(
        min(time_range.start for time_range in ranges),
        max(time_range.stop for time_range in ranges),
    )


def _merge_source_files(path: Path, new: tuple[str, ...]) -> tuple[str, ...]:
    if not path.exists():
        return new
    manifest = json.loads(path.read_text(encoding="utf-8"))
    merged = []
    for source in (*manifest.get("source_files", []), *new):
        if source not in merged:
            merged.append(str(source))
    return tuple(merged)


def _normalize_store_source_files(root: Path, source_files: tuple[str, ...]) -> tuple[str, ...]:
    if not source_files:
        return ()
    resolved_root = root.resolve()
    return tuple(_normalize_store_source_file(resolved_root, source) for source in source_files)


def _normalize_store_source_file(resolved_root: Path, source: str) -> str:
    path = Path(source)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(resolved_root).as_posix()
        except (OSError, ValueError):
            return str(path)
    return path.as_posix()


def _merge_source_datasets(path: Path, new: tuple[str, ...]) -> tuple[str, ...]:
    if not path.exists():
        return new
    manifest = json.loads(path.read_text(encoding="utf-8"))
    merged = []
    for source in (*manifest.get("source_datasets", []), *new):
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
                "schema_version": str(
                    row.get("schema_version") or _DATASET_SCHEMA_VERSION
                ),
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


def _sibling_temp_path(path: Path, suffix: str) -> Path:
    index = 0
    while True:
        candidate = path.with_name(f"{path.name}{suffix}{index}")
        if not candidate.exists():
            return candidate
        index += 1


def _resolve_raw_file(root: Path, path: Path | str) -> Path:
    raw_root = (root / "raw").resolve()
    candidate = Path(path)
    if candidate.is_absolute():
        target = candidate.resolve()
    else:
        parts = candidate.parts
        if parts and parts[0] == "raw":
            target = (root / candidate).resolve()
        else:
            target = (raw_root / candidate).resolve()
    if not target.is_relative_to(raw_root):
        raise ValueError(f"Raw file path escapes raw root: {path}")
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
            variant = manifest.get("variant") or {}
            dataset_root = manifest_path.parent
            rows.append(
                {
                    "dataset_id": str(manifest.get("dataset_id") or ""),
                    "layer": str(manifest.get("layer") or layer),
                    "mission": str(manifest.get("mission") or ""),
                    "instrument": str(manifest.get("instrument") or ""),
                    "product": str(manifest.get("product") or ""),
                    "variant_id": str(variant.get("id") or ""),
                    "version": str(manifest.get("version") or "1"),
                    "schema_version": str(
                        manifest.get("schema_version") or _DATASET_SCHEMA_VERSION
                    ),
                    "status": str(manifest.get("status") or ""),
                    "created_at": str(manifest.get("created_at") or ""),
                    "start": str(time_coverage.get("start") or ""),
                    "stop": str(time_coverage.get("stop") or ""),
                    "path": dataset_root.relative_to(root).as_posix(),
                }
            )
    return tuple(rows)


def _dataset_index_frame(rows: tuple[dict[str, Any], ...]) -> Any:
    import polars as pl

    schema = {
        "dataset_id": pl.Utf8,
        "layer": pl.Utf8,
        "mission": pl.Utf8,
        "instrument": pl.Utf8,
        "product": pl.Utf8,
        "variant_id": pl.Utf8,
        "version": pl.Utf8,
        "schema_version": pl.Utf8,
        "status": pl.Utf8,
        "created_at": pl.Utf8,
        "start": pl.Utf8,
        "stop": pl.Utf8,
        "path": pl.Utf8,
    }
    if not rows:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(rows, schema=schema)


def _raw_file_index_rows(root: Path) -> tuple[dict[str, Any], ...]:
    raw_root = root / "raw"
    if not raw_root.exists():
        return ()

    rows: list[dict[str, Any]] = []
    for manifest_path in sorted(raw_root.rglob("*.sopran.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows.append(
            {
                "path": str(manifest.get("path") or ""),
                "filename": str(manifest.get("filename") or ""),
                "mission": str(manifest.get("mission") or ""),
                "provider": str(manifest.get("provider") or ""),
                "provider_path": str(manifest.get("provider_path") or ""),
                "version": str(manifest.get("version") or ""),
                "download_url": str(manifest.get("download_url") or ""),
                "acquired_at": str(manifest.get("acquired_at") or ""),
                "checksum": str(manifest.get("checksum") or ""),
                "size_bytes": int(manifest.get("size_bytes") or 0),
            }
        )
    return tuple(rows)


def _raw_file_index_frame(rows: tuple[dict[str, Any], ...]) -> Any:
    import polars as pl

    schema = {
        "path": pl.Utf8,
        "filename": pl.Utf8,
        "mission": pl.Utf8,
        "provider": pl.Utf8,
        "provider_path": pl.Utf8,
        "version": pl.Utf8,
        "download_url": pl.Utf8,
        "acquired_at": pl.Utf8,
        "checksum": pl.Utf8,
        "size_bytes": pl.Int64,
    }
    if not rows:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(rows, schema=schema)
