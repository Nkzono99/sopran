from __future__ import annotations

import json

import polars as pl

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
    assert catalog.select("checksum").to_series().to_list()[0].startswith("sha256:")
