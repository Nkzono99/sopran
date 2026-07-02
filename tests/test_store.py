from __future__ import annotations

import json

import polars as pl
import pytest

import sopran as spn
from sopran import Store
from sopran.missions.kaguya.schema import KAGUYA_ESA1_SCHEMA


def test_store_registers_dataset_manifest_schema_and_catalog(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.period("2008-02-01", "2008-02-02")

    dataset = store.register_dataset(
        dataset_id="kaguya.esa1.energy_flux",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="energy_flux",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        source_files=("raw/kaguya/example.dat.gz",),
        shards=(
            {
                "path": "shards/year=2008/month=02/day=01/part-000.parquet",
                "row_count": 0,
                "checksum": "sha256:empty",
                "status": "complete",
            },
        ),
    )

    assert dataset.root == tmp_path / "store" / "normalized" / "kaguya" / "esa1" / "energy_flux"
    assert dataset.manifest_path.exists()
    assert dataset.schema_path.exists()
    assert dataset.catalog_path.exists()

    manifest = json.loads(dataset.manifest_path.read_text(encoding="utf-8"))
    assert manifest["dataset_id"] == "kaguya.esa1.energy_flux"
    assert manifest["layer"] == "normalized"
    assert manifest["time_coverage"] == {
        "start": "2008-02-01T00:00:00Z",
        "stop": "2008-02-02T00:00:00Z",
    }

    schema = json.loads(dataset.schema_path.read_text(encoding="utf-8"))
    assert schema["variables"][0]["name"] == "energy_flux"
    assert schema["variables"][0]["dims"] == ["time", "energy", "look"]

    catalog = pl.read_parquet(dataset.catalog_path)
    assert catalog.select("path").to_series().to_list() == [
        "shards/year=2008/month=02/day=01/part-000.parquet"
    ]


def test_store_writes_polars_frame_as_parquet_dataset(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.period("2008-02-01", "2008-02-02")
    frame = pl.DataFrame(
        {
            "time": ["2008-02-01T00:00:08Z"],
            "energy": [0],
            "counts": [64],
        }
    )

    dataset = store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=frame,
        source_files=("raw/kaguya/example.dat.gz",),
    )

    shard = dataset.root / "shards" / "part-000.parquet"
    catalog = pl.read_parquet(dataset.catalog_path)

    assert shard.exists()
    assert pl.read_parquet(shard).to_dicts() == frame.to_dicts()
    assert catalog.select("path").to_series().to_list() == ["shards/part-000.parquet"]
    assert catalog.select("row_count").to_series().to_list() == [1]
    assert catalog.select("start").to_series().to_list() == [time.start_iso]
    assert catalog.select("stop").to_series().to_list() == [time.stop_iso]
    assert catalog.select("checksum").to_series().to_list()[0].startswith("sha256:")


def test_store_parquet_writer_refuses_to_overwrite_existing_shard(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.period("2008-02-01", "2008-02-02")
    frame = pl.DataFrame({"time": ["2008-02-01T00:00:08Z"], "counts": [64]})
    kwargs = {
        "dataset_id": "kaguya.esa1.counts",
        "layer": "normalized",
        "mission": "kaguya",
        "instrument": "esa1",
        "product": "counts",
        "schema": KAGUYA_ESA1_SCHEMA,
        "time_coverage": time,
        "frame": frame,
    }
    store.write_parquet_dataset(**kwargs)

    with pytest.raises(FileExistsError):
        store.write_parquet_dataset(**kwargs)


def test_database_register_product_creates_metadata_and_empty_dataset(tmp_path) -> None:
    store = Store(tmp_path / "store")
    database = store.database("my_project")

    dataset = database.register_product(
        name="event_table",
        schema=KAGUYA_ESA1_SCHEMA,
        description="hand-curated lunar wake events",
    )

    metadata = json.loads((database.root / "database.json").read_text(encoding="utf-8"))
    assert metadata["name"] == "my_project"
    assert metadata["products"] == [
        {
            "name": "event_table",
            "dataset_id": "my_project.event_table",
            "layer": "databases",
            "description": "hand-curated lunar wake events",
        }
    ]
    assert dataset.root == store.database_path("my_project", "event_table")
    assert dataset.manifest()["dataset_id"] == "my_project.event_table"
    assert dataset.manifest()["layer"] == "databases"
    assert dataset.manifest()["time_coverage"] is None
    assert dataset.catalog().select("status").to_series().to_list() == ["empty"]


def test_store_scans_registered_parquet_dataset(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.period("2008-02-01", "2008-02-02")
    frame = pl.DataFrame({"time": ["2008-02-01T00:00:08Z"], "counts": [64]})
    store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=frame,
    )

    scanned = store.scan_dataset("kaguya.esa1.counts", layer="normalized").collect()

    assert scanned.to_dicts() == frame.to_dicts()


def test_store_dataset_finds_registered_dataset_without_layer(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.period("2008-02-01", "2008-02-02")
    frame = pl.DataFrame({"time": ["2008-02-01T00:00:08Z"], "counts": [64]})
    written = store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=frame,
    )

    dataset = store.dataset("kaguya.esa1.counts")

    assert dataset.root == written.root
    with pytest.raises(spn.DatasetNotFoundError):
        store.dataset("unknown.dataset")


def test_store_append_expands_manifest_time_coverage(tmp_path) -> None:
    store = Store(tmp_path / "store")
    first = spn.day("2008-02-01")
    second = spn.day("2008-02-02")
    kwargs = {
        "dataset_id": "kaguya.esa1.counts",
        "layer": "normalized",
        "mission": "kaguya",
        "instrument": "esa1",
        "product": "counts",
        "schema": KAGUYA_ESA1_SCHEMA,
    }
    store.write_parquet_dataset(
        **kwargs,
        time_coverage=first,
        frame=pl.DataFrame({"time": [first.start_iso], "counts": [1]}),
    )

    dataset = store.write_parquet_dataset(
        **kwargs,
        time_coverage=second,
        frame=pl.DataFrame({"time": [second.start_iso], "counts": [2]}),
        append=True,
    )

    assert dataset.manifest()["time_coverage"] == {
        "start": first.start_iso,
        "stop": second.stop_iso,
    }
    assert dataset.catalog().select("start").to_series().to_list() == [
        first.start_iso,
        second.start_iso,
    ]


def test_dataset_record_scans_its_catalog_shards(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.period("2008-02-01", "2008-02-02")
    frame = pl.DataFrame({"time": ["2008-02-01T00:00:08Z"], "counts": [64]})
    dataset = store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=frame,
    )

    scanned = dataset.scan().collect()

    assert scanned.to_dicts() == frame.to_dicts()


def test_dataset_record_reads_manifest_schema_and_catalog(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.period("2008-02-01", "2008-02-02")
    frame = pl.DataFrame({"time": ["2008-02-01T00:00:08Z"], "counts": [64]})
    dataset = store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=frame,
    )

    assert dataset.manifest()["dataset_id"] == "kaguya.esa1.counts"
    assert dataset.schema()["instrument"] == "esa1"
    assert dataset.catalog().select("row_count").to_series().to_list() == [1]
