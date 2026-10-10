"""Synchronize Store datasets between machines with rsync.

The Store is synchronized as plain files under its root. Every reference inside it
is root-relative, shards are written atomically, and each shard carries a sidecar
(``<shard>.sopran.json``) that is the source of truth for the dataset catalog.
``registry/``, ``cache/``, dataset ``work/`` directories and temporary files are
machine-local and excluded.

Typical use (``sopran-store`` is ``python -m sopran.core.sync``)::

    sopran-store --data-root F:/sopran_data sync-list > files.txt
    rsync -av --delay-updates --files-from=files.txt F:/sopran_data/ host:/data/sopran_data/
    ssh host sopran-store --data-root /data/sopran_data rebuild
    ssh host sopran-store --data-root /data/sopran_data verify

Without ``--dataset`` the list holds every *managed* dataset (caches and products
that sopran creates itself). ``--dataset ID`` selects datasets by id or id prefix,
managed or not; ``--raw PREFIX`` adds raw files and their manifests.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sopran.core.store import SHARD_SIDECAR_SUFFIX, SYNC_EXCLUDES, DatasetRecord, Store

_METADATA_LAST = ("schema.json", "catalog.parquet", "dataset.json")


def _matches(dataset_id: str, selectors: Sequence[str]) -> bool:
    return any(dataset_id == s or dataset_id.startswith(s + ".") for s in selectors)


def select_datasets(
    store: Store,
    *,
    dataset_ids: Sequence[str] = (),
    layer: str | None = None,
    variant_id: str | None = None,
    include_unmanaged: bool = False,
) -> tuple[DatasetRecord, ...]:
    """Datasets to synchronize: named ones (any status) or, by default, managed ones."""
    selected = []
    for record in store.dataset_records(layer=layer):
        manifest = record.manifest()
        if variant_id is not None and (manifest.get("variant") or {}).get("id") != variant_id:
            continue
        if dataset_ids:
            if not _matches(str(manifest.get("dataset_id") or ""), dataset_ids):
                continue
        elif not (include_unmanaged or manifest.get("managed")):
            continue
        selected.append(record)
    return tuple(selected)


def dataset_files(record: DatasetRecord) -> list[Path]:
    """Files of one dataset with shards and sidecars first and the manifest last."""
    files = record.files()
    head = [f for f in files if f.name not in _METADATA_LAST]
    tail = [record.root / name for name in _METADATA_LAST if (record.root / name).exists()]
    return head + tail


def raw_files(store: Store, prefixes: Sequence[str]) -> list[Path]:
    root = Path(str(store.root))
    files: list[Path] = []
    for prefix in prefixes:
        base = root / "raw" / prefix
        if base.is_file():
            files.append(base)
        elif base.exists():
            files.extend(sorted(p for p in base.rglob("*") if p.is_file()))
    return files


def sync_list(
    store: Store,
    *,
    dataset_ids: Sequence[str] = (),
    layer: str | None = None,
    variant_id: str | None = None,
    include_unmanaged: bool = False,
    raw: Sequence[str] = (),
) -> list[str]:
    """Store-root-relative POSIX paths for ``rsync --files-from``."""
    root = Path(str(store.root))
    paths: list[Path] = raw_files(store, raw)
    for record in select_datasets(
        store,
        dataset_ids=dataset_ids,
        layer=layer,
        variant_id=variant_id,
        include_unmanaged=include_unmanaged,
    ):
        paths.extend(dataset_files(record))
    seen: dict[str, None] = {}
    for path in paths:
        seen.setdefault(path.relative_to(root).as_posix())
    return list(seen)


def verify(store: Store, records: Sequence[DatasetRecord]) -> dict[str, dict[str, list[str]]]:
    """Problems per dataset (missing or mismatched shards, catalog/sidecar drift)."""
    root = Path(str(store.root))
    problems = {}
    for record in records:
        report = record.verify_shards()
        if any(report.values()):
            problems[record.root.relative_to(root).as_posix()] = report
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sopran-store",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--data-root", help="Store root (default: SOPRAN_DATA_ROOT or config)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("sync-list", "print files to synchronize (for rsync --files-from)"),
        ("verify", "check shards against catalog and sidecars"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--dataset", action="append", default=[], help="dataset id or prefix")
        p.add_argument("--layer")
        p.add_argument("--variant")
        p.add_argument("--all", action="store_true", help="include unmanaged datasets")
        if name == "sync-list":
            p.add_argument("--raw", action="append", default=[], help="raw/ sub-path to add")
    p = sub.add_parser("rebuild", help="rebuild catalogs from sidecars and the registries")
    p.add_argument("--layer")
    sub.add_parser("excludes", help="print rsync exclude patterns (--exclude-from)")
    args = parser.parse_args(argv)
    store = Store(args.data_root) if args.data_root else Store()

    if args.command == "excludes":
        print("\n".join(SYNC_EXCLUDES))
    elif args.command == "sync-list":
        for path in sync_list(
            store,
            dataset_ids=args.dataset,
            layer=args.layer,
            variant_id=args.variant,
            include_unmanaged=args.all,
            raw=args.raw,
        ):
            print(path)
    elif args.command == "verify":
        records = select_datasets(
            store,
            dataset_ids=args.dataset,
            layer=args.layer,
            variant_id=args.variant,
            include_unmanaged=args.all or bool(args.dataset),
        )
        problems = verify(store, records)
        print(json.dumps({"datasets": len(records), "problems": problems}, indent=1))
        return 1 if problems else 0
    elif args.command == "rebuild":
        result: dict[str, Any] = store.rebuild(layer=args.layer)
        added = {k: v["added_from_sidecars"] for k, v in result.items() if v["added_from_sidecars"]}
        print(json.dumps({"datasets": len(result), "added_from_sidecars": added}, indent=1))
    return 0


__all__ = [
    "SHARD_SIDECAR_SUFFIX",
    "dataset_files",
    "main",
    "select_datasets",
    "sync_list",
    "verify",
]

if __name__ == "__main__":
    sys.exit(main())
