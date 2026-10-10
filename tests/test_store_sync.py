"""Store synchronization: shard sidecars, catalog rebuild, registries and rsync lists."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import polars as pl

import sopran as spn
from sopran import Store
from sopran.core import sync
from sopran.core.store import SHARD_SIDECAR_SUFFIX, SYNC_EXCLUDES, file_content_reference
from sopran.missions.kaguya.geometry import _path_tuple_token, orbit_variant_id
from sopran.missions.kaguya.schema import KAGUYA_ESA1_SCHEMA

DATASET = "kaguya.esa1.counts"


def _write_day(store: Store, day: str, *, append: bool = True, managed: bool = True, **kw):
    return store.write_parquet_dataset(
        dataset_id=DATASET,
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=spn.day(day),
        frame=pl.DataFrame({"time": [f"{day}T00:00:08Z"], "counts": [int(day[-2:])]}),
        shard_path=f"shards/day={day}.parquet",
        append=append,
        managed=managed,
        **kw,
    )


def _copy(source: Store, target: Store, relative: list[str]) -> None:
    """What ``rsync --files-from`` does with the listed root-relative paths."""
    for path in relative:
        destination = Path(target.root) / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(source.root) / path, destination)


def test_each_shard_has_a_sidecar_matching_the_catalog(tmp_path) -> None:
    store = Store(tmp_path / "store")
    record = _write_day(store, "2008-02-01")
    _write_day(store, "2008-02-02")
    for shard in record.shards():
        sidecar = record.root / (shard["path"] + SHARD_SIDECAR_SUFFIX)
        assert json.loads(sidecar.read_text()) == shard
    assert record.manifest()["managed"] is True
    assert record.verify_shards() == {
        "missing": [],
        "checksum": [],
        "catalog_only": [],
        "sidecar_only": [],
    }


def test_two_machines_merge_their_shards_after_sync_and_rebuild(tmp_path) -> None:
    local, cluster = Store(tmp_path / "local"), Store(tmp_path / "cluster")
    _write_day(local, "2008-02-01")
    _write_day(cluster, "2008-02-02")
    _write_day(cluster, "2008-02-03")
    _copy(cluster, local, sync.sync_list(cluster))
    record = local.dataset(DATASET, layer="normalized")
    # The copied catalog lists only the cluster's days; the local sidecar keeps its own.
    assert record.verify_shards()["sidecar_only"] == ["shards/day=2008-02-01.parquet"]
    result = local.rebuild()
    assert list(result.values())[0]["shards"] == 3
    days = record.scan().collect()["counts"].sort().to_list()
    assert days == [1, 2, 3]
    assert record.manifest()["time_coverage"] == {
        "start": "2008-02-01T00:00:00Z",
        "stop": "2008-02-04T00:00:00Z",
    }


def test_rebuild_restores_rows_lost_by_a_concurrent_catalog_write(tmp_path) -> None:
    store = Store(tmp_path / "store")
    record = _write_day(store, "2008-02-01")
    stale = record.catalog()
    _write_day(store, "2008-02-02")
    stale.write_parquet(record.catalog_path)  # another writer committed an older view
    assert len(record.shards()) == 1
    record.rebuild_catalog()
    assert [s["path"] for s in record.shards()] == [
        "shards/day=2008-02-01.parquet",
        "shards/day=2008-02-02.parquet",
    ]


def test_replacing_a_dataset_drops_other_sidecars_and_appends_keep_them(tmp_path) -> None:
    store = Store(tmp_path / "store")
    _write_day(store, "2008-02-01")
    record = _write_day(store, "2008-02-02", append=False, overwrite=True)
    record.rebuild_catalog()
    assert [s["path"] for s in record.shards()] == ["shards/day=2008-02-02.parquet"]


def test_datasets_written_before_sidecars_are_migrated_by_rebuild(tmp_path) -> None:
    store = Store(tmp_path / "store")
    record = _write_day(store, "2008-02-01")
    for sidecar in record.root.rglob(f"*{SHARD_SIDECAR_SUFFIX}"):
        sidecar.unlink()
    assert record.verify_shards()["catalog_only"] == ["shards/day=2008-02-01.parquet"]
    record.rebuild_catalog()
    assert record.verify_shards()["catalog_only"] == []
    assert len(record.shards()) == 1


def test_registry_refreshes_when_synced_manifests_arrive(tmp_path) -> None:
    local, cluster = Store(tmp_path / "local"), Store(tmp_path / "cluster")
    _write_day(local, "2008-02-01")
    assert local.datasets().height == 1
    cluster.write_parquet_dataset(
        dataset_id="kaguya.esa2.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa2",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=spn.day("2008-02-01"),
        frame=pl.DataFrame({"time": ["2008-02-01T00:00:08Z"], "counts": [1]}),
    )
    _copy(cluster, local, sync.sync_list(cluster, include_unmanaged=True))
    index = local.datasets()
    assert sorted(index["dataset_id"].to_list()) == ["kaguya.esa1.counts", "kaguya.esa2.counts"]
    assert index.filter(pl.col("dataset_id") == "kaguya.esa2.counts")["managed"].to_list() == [
        False
    ]


def test_sync_list_selects_managed_datasets_and_skips_local_files(tmp_path) -> None:
    store = Store(tmp_path / "store")
    record = _write_day(store, "2008-02-01")
    store.write_parquet_dataset(
        dataset_id="kaguya.scratch.counts",
        layer="features",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=spn.day("2008-02-01"),
        frame=pl.DataFrame({"time": ["2008-02-01T00:00:08Z"], "counts": [1]}),
    )
    (record.root / "work").mkdir()
    (record.root / "work" / "part-0000.parquet").write_text("partial")
    (record.root / "shards" / "day=2008-02-01.parquet.sopran-tmp0").write_text("temporary")
    raw = Path(store.root) / "raw" / "kaguya" / "a.dat"
    raw.parent.mkdir(parents=True)
    raw.write_text("raw")
    store.datasets()  # creates the machine-local registry
    listed = sync.sync_list(store, raw=["kaguya"])
    assert listed[0] == "raw/kaguya/a.dat"
    assert listed[-1] == "normalized/kaguya/esa1/counts/dataset.json"
    assert not any("scratch" in p or "work/" in p or "sopran-tmp" in p for p in listed)
    assert not any(p.startswith("registry/") for p in listed)
    assert "normalized/kaguya/esa1/counts/shards/day=2008-02-01.parquet.sopran.json" in listed
    named = sync.sync_list(store, dataset_ids=["kaguya.scratch"])
    assert named[-1] == "features/kaguya/scratch/counts/dataset.json"
    assert "*.sopran-tmp*" in SYNC_EXCLUDES


def test_verify_reports_missing_and_changed_shards(tmp_path) -> None:
    store = Store(tmp_path / "store")
    record = _write_day(store, "2008-02-01")
    _write_day(store, "2008-02-02")
    (record.root / "shards" / "day=2008-02-01.parquet").unlink()
    (record.root / "shards" / "day=2008-02-02.parquet").write_bytes(b"changed")
    problems = sync.verify(store, store.dataset_records())
    report = problems["normalized/kaguya/esa1/counts"]
    assert report["missing"] == ["shards/day=2008-02-01.parquet"]
    assert report["checksum"] == ["shards/day=2008-02-02.parquet"]


def test_file_references_and_kernel_tokens_do_not_depend_on_location(tmp_path) -> None:
    store = Store(tmp_path / "store")
    inside = Path(store.root) / "raw" / "spice" / "naif0012.tls"
    inside.parent.mkdir(parents=True)
    inside.write_text("kernel")
    outside = tmp_path / "elsewhere" / "naif0012.tls"
    outside.parent.mkdir()
    outside.write_text("kernel")
    assert store.file_reference(inside)["store_path"] == "raw/spice/naif0012.tls"
    assert "external_path" in store.file_reference(outside)
    assert file_content_reference(inside) == file_content_reference(outside)
    assert _path_tuple_token((inside,)) == _path_tuple_token((outside,))
    assert orbit_variant_id("sza", spice_kernels=(inside,)) == orbit_variant_id(
        "sza", spice_kernels=(outside,)
    )
    outside.write_text("other kernel")
    assert _path_tuple_token((inside,)) != _path_tuple_token((outside,))


def test_cli_lists_and_rebuilds(tmp_path, capsys) -> None:
    store = Store(tmp_path / "store")
    _write_day(store, "2008-02-01")
    assert sync.main(["--data-root", str(store.root), "sync-list"]) == 0
    assert "normalized/kaguya/esa1/counts/dataset.json" in capsys.readouterr().out
    assert sync.main(["--data-root", str(store.root), "rebuild"]) == 0
    assert json.loads(capsys.readouterr().out)["datasets"] == 1
    assert sync.main(["--data-root", str(store.root), "verify"]) == 0
    assert sync.main(["--data-root", str(store.root), "excludes"]) == 0
    assert "/registry/" in capsys.readouterr().out
