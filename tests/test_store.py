from __future__ import annotations

from datetime import UTC, datetime
import json
import sys

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
    assert manifest["version"] == "1"
    assert manifest["schema_version"] == "0.1"
    assert manifest["status"] == "candidate"
    assert manifest["created_at"].endswith("Z")
    created_at = datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
    assert created_at.tzinfo == UTC
    assert manifest["software"] == {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "sopran": spn.__version__,
    }
    assert manifest["parameters"] == {}
    assert manifest["partitioning"] == []
    assert manifest["source_datasets"] == []
    assert manifest["time_coverage"] == {
        "start": "2008-02-01T00:00:00Z",
        "stop": "2008-02-02T00:00:00Z",
    }

    schema = json.loads(dataset.schema_path.read_text(encoding="utf-8"))
    assert schema["schema_version"] == "0.1"
    assert schema["variables"][0]["name"] == "energy_flux"
    assert schema["variables"][0]["dims"] == ["time", "energy", "look"]

    catalog = pl.read_parquet(dataset.catalog_path)
    assert catalog.select("schema_version").to_series().to_list() == ["0.1"]
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


def test_store_writes_dataset_provenance_into_manifest(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.period("2008-02-01", "2008-02-02")

    dataset = store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=pl.DataFrame({"time": ["2008-02-01T00:00:08Z"], "counts": [64]}),
        provenance={
            "pipeline": {
                "source": "kaguya.esa1",
                "stages": ["decode", "select_variables", "write"],
            }
        },
    )

    assert dataset.manifest()["provenance"] == {
        "pipeline": {
            "source": "kaguya.esa1",
            "stages": ["decode", "select_variables", "write"],
        }
    }


def test_store_writes_dataset_parameters_into_manifest(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.period("2008-02-01", "2008-02-02")

    dataset = store.write_parquet_dataset(
        dataset_id="kaguya.esa1.energy_flux",
        layer="features",
        mission="kaguya",
        instrument="esa1",
        product="energy_flux",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=pl.DataFrame({"time": ["2008-02-01T00:00:08Z"], "energy_flux": [1.0]}),
        parameters={
            "binning": "none",
            "quality_mask": ["valid_energy", "valid_look_direction"],
        },
    )

    assert dataset.manifest()["parameters"] == {
        "binning": "none",
        "quality_mask": ["valid_energy", "valid_look_direction"],
    }


def test_store_writes_source_datasets_into_manifest(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.period("2008-02-01", "2008-02-02")

    dataset = store.write_parquet_dataset(
        dataset_id="kaguya.esa1.pitch_angle_distribution",
        layer="features",
        mission="kaguya",
        instrument="esa1",
        product="pitch_angle_distribution",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=pl.DataFrame({"time": ["2008-02-01T00:00:08Z"], "pad": [1.0]}),
        source_datasets=("kaguya.esa1.counts", "kaguya.orbit.position"),
    )

    assert dataset.manifest()["source_datasets"] == [
        "kaguya.esa1.counts",
        "kaguya.orbit.position",
    ]


def test_store_writes_dataset_version_and_partitioning_into_manifest(tmp_path) -> None:
    store = Store(tmp_path / "store")
    day = spn.day("2008-02-01")

    dataset = store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=day,
        frame=pl.DataFrame({"time": [day.start_iso], "counts": [64]}),
        shard_path="shards/year=2008/month=02/day=01/part-000.parquet",
        dataset_version="2026.07",
        partitioning=("year", "month", "day"),
    )

    assert dataset.manifest()["version"] == "2026.07"
    assert dataset.manifest()["partitioning"] == ["year", "month", "day"]


def test_store_rejects_unknown_dataset_status(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.period("2008-02-01", "2008-02-02")

    with pytest.raises(ValueError, match="status must be"):
        store.register_dataset(
            dataset_id="kaguya.esa1.counts",
            layer="normalized",
            mission="kaguya",
            instrument="esa1",
            product="counts",
            schema=KAGUYA_ESA1_SCHEMA,
            time_coverage=time,
            status="ready",
        )


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


def test_store_registers_raw_file_manifest(tmp_path) -> None:
    store = Store(tmp_path / "store")
    raw_file = store.raw_path("kaguya", "l2", "example.dat")
    raw_file.parent.mkdir(parents=True)
    raw_file.write_bytes(b"raw payload")

    record = store.register_raw_file(
        "kaguya/l2/example.dat",
        mission="kaguya",
        provider="darts",
        provider_path="/pub/pds3/sln-l-pace-3-rdr-v1.0/data/example.dat",
        data_version="v1.0",
        download_url="https://example.invalid/kaguya/l2/example.dat",
    )

    manifest = record.manifest()
    assert record.path == raw_file
    assert record.manifest_path == raw_file.with_name("example.dat.sopran.json")
    assert manifest["path"] == "raw/kaguya/l2/example.dat"
    assert manifest["filename"] == "example.dat"
    assert manifest["mission"] == "kaguya"
    assert manifest["provider"] == "darts"
    assert manifest["provider_path"] == "/pub/pds3/sln-l-pace-3-rdr-v1.0/data/example.dat"
    assert manifest["version"] == "v1.0"
    assert manifest["download_url"] == "https://example.invalid/kaguya/l2/example.dat"
    assert manifest["checksum"].startswith("sha256:")
    assert manifest["size_bytes"] == len(b"raw payload")
    assert manifest["acquired_at"].endswith("Z")


def test_raw_file_record_verifies_checksum(tmp_path) -> None:
    store = Store(tmp_path / "store")
    raw_file = store.raw_path("kaguya", "l2", "example.dat")
    raw_file.parent.mkdir(parents=True)
    raw_file.write_bytes(b"raw payload")
    record = store.register_raw_file("kaguya/l2/example.dat", mission="kaguya", provider="darts")

    assert record.verify_checksum()

    raw_file.write_bytes(b"changed payload")

    assert not record.verify_checksum()


def test_store_finds_registered_raw_file_record(tmp_path) -> None:
    store = Store(tmp_path / "store")
    raw_file = store.raw_path("kaguya", "l2", "example.dat")
    raw_file.parent.mkdir(parents=True)
    raw_file.write_bytes(b"raw payload")
    registered = store.register_raw_file(
        "kaguya/l2/example.dat",
        mission="kaguya",
        provider="darts",
    )

    found = store.raw_file("kaguya/l2/example.dat")

    assert found.path == registered.path
    assert found.manifest_path == registered.manifest_path
    assert found.manifest()["provider"] == "darts"
    assert found.verify_checksum()


def test_store_rebuilds_raw_file_registry(tmp_path) -> None:
    store = Store(tmp_path / "store")
    first = store.raw_path("kaguya", "l2", "first.dat")
    second = store.raw_path("artemis", "cdf", "second.cdf")
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"kaguya")
    second.write_bytes(b"artemis")
    store.register_raw_file(
        "kaguya/l2/first.dat",
        mission="kaguya",
        provider="darts",
        provider_path="/pub/kaguya/first.dat",
        data_version="v1",
        acquired_at="2026-07-02T12:00:00Z",
    )
    store.register_raw_file(
        "artemis/cdf/second.cdf",
        mission="artemis",
        provider="spdf",
        acquired_at="2026-07-01T00:00:00Z",
    )

    index = store.raw_files(refresh=True)
    spdf = store.raw_files(provider="spdf")
    first_dat = store.raw_files(filename="first.dat")
    darts_v1 = store.raw_files(provider="darts", data_version="v1")
    provider_path = store.raw_files(provider_path="/pub/kaguya/first.dat")
    acquired_on_second = store.raw_files(
        acquired_after="2026-07-02T00:00:00Z",
        acquired_before="2026-07-03T00:00:00Z",
    )
    before_second = store.raw_files(acquired_before="2026-07-02T00:00:00Z")

    assert store.registry_path("raw_files.parquet").exists()
    assert index.select("path").to_series().to_list() == [
        "raw/artemis/cdf/second.cdf",
        "raw/kaguya/l2/first.dat",
    ]
    assert index.select("mission").to_series().to_list() == ["artemis", "kaguya"]
    assert index.select("provider").to_series().to_list() == ["spdf", "darts"]
    assert index.select("filename").to_series().to_list() == ["second.cdf", "first.dat"]
    assert index.select("version").to_series().to_list() == ["", "v1"]
    assert all(value.startswith("sha256:") for value in index.select("checksum").to_series())
    assert spdf.select("path").to_series().to_list() == ["raw/artemis/cdf/second.cdf"]
    assert first_dat.select("path").to_series().to_list() == ["raw/kaguya/l2/first.dat"]
    assert darts_v1.select("path").to_series().to_list() == ["raw/kaguya/l2/first.dat"]
    assert provider_path.select("path").to_series().to_list() == ["raw/kaguya/l2/first.dat"]
    assert acquired_on_second.select("path").to_series().to_list() == [
        "raw/kaguya/l2/first.dat"
    ]
    assert before_second.select("path").to_series().to_list() == [
        "raw/artemis/cdf/second.cdf"
    ]


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


def test_store_creates_database_metadata_when_requested(tmp_path) -> None:
    store = Store(tmp_path / "store")

    database = store.database("my_project", create=True)

    assert database.metadata() == {"name": "my_project", "products": []}
    assert (database.root / "database.json").exists()


def test_database_lists_registered_products_from_metadata(tmp_path) -> None:
    store = Store(tmp_path / "store")
    database = store.database("my_project")

    database.register_product(
        name="event_table",
        schema=KAGUYA_ESA1_SCHEMA,
        description="hand-curated lunar wake events",
    )
    database.register_product(
        name="esa1_context",
        schema=KAGUYA_ESA1_SCHEMA,
        description="context around each event",
    )

    products = database.products()

    assert [product.name for product in products] == ["event_table", "esa1_context"]
    assert products[0].dataset_id == "my_project.event_table"
    assert products[0].layer == "databases"
    assert database.metadata()["products"][1]["description"] == "context around each event"


def test_database_product_reference_scans_dataset(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.day("2008-02-01")
    product = store.database("wake_events").product("raw_counts")
    store.write_parquet_dataset(
        dataset_id=product.dataset_id,
        layer=product.layer,
        mission="wake_events",
        instrument="wake_events",
        product=product.name,
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=pl.DataFrame({"time": [time.start_iso], "counts": [64]}),
    )

    scanned = product.scan().collect()

    assert scanned.select("counts").to_series().to_list() == [64]


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


def test_store_resolves_dataset_source_file_records(tmp_path) -> None:
    store = Store(tmp_path / "store")
    raw_file = store.raw_path("kaguya", "l2", "source.dat")
    raw_file.parent.mkdir(parents=True)
    raw_file.write_bytes(b"raw payload")
    store.register_raw_file("kaguya/l2/source.dat", mission="kaguya", provider="darts")
    time = spn.period("2008-02-01", "2008-02-02")
    store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=pl.DataFrame({"time": ["2008-02-01T00:00:08Z"], "counts": [64]}),
        source_files=("raw/kaguya/l2/source.dat",),
    )

    records = store.dataset_source_files("kaguya.esa1.counts", layer="normalized")

    assert [record.path for record in records] == [raw_file]
    assert records[0].verify_checksum()


def test_store_verifies_dataset_integrity_with_source_files(tmp_path) -> None:
    store = Store(tmp_path / "store")
    raw_file = store.raw_path("kaguya", "l2", "source.dat")
    raw_file.parent.mkdir(parents=True)
    raw_file.write_bytes(b"raw payload")
    store.register_raw_file("kaguya/l2/source.dat", mission="kaguya", provider="darts")
    time = spn.period("2008-02-01", "2008-02-02")
    dataset = store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=pl.DataFrame({"time": ["2008-02-01T00:00:08Z"], "counts": [64]}),
        source_files=("raw/kaguya/l2/source.dat",),
    )

    assert store.verify_dataset("kaguya.esa1.counts", layer="normalized")

    raw_file.write_bytes(b"changed raw payload")

    assert not store.verify_dataset("kaguya.esa1.counts", layer="normalized")
    assert store.verify_dataset("kaguya.esa1.counts", layer="normalized", source_files=False)

    (dataset.root / "shards" / "part-000.parquet").write_bytes(b"changed shard")

    assert not store.verify_dataset("kaguya.esa1.counts", layer="normalized", source_files=False)


def test_dataset_record_verifies_catalog_shard_checksums(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.period("2008-02-01", "2008-02-02")
    dataset = store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=pl.DataFrame({"time": ["2008-02-01T00:00:08Z"], "counts": [64]}),
    )

    assert dataset.verify_checksums()

    (dataset.root / "shards" / "part-000.parquet").write_bytes(b"changed")

    assert not dataset.verify_checksums()


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


def test_store_rebuilds_dataset_registry_index(tmp_path) -> None:
    store = Store(tmp_path / "store")
    day = spn.day("2008-02-01")
    store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=day,
        frame=pl.DataFrame({"time": [day.start_iso], "counts": [64]}),
    )
    store.write_parquet_dataset(
        dataset_id="kaguya.esa1.pitch_angle_distribution",
        layer="features",
        mission="kaguya",
        instrument="esa1",
        product="pitch_angle_distribution",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=day,
        frame=pl.DataFrame({"time": [day.start_iso], "pad": [1.0]}),
    )

    index = store.datasets(refresh=True)

    assert store.registry_path("datasets.parquet").exists()
    assert index.select("dataset_id").to_series().to_list() == [
        "kaguya.esa1.pitch_angle_distribution",
        "kaguya.esa1.counts",
    ]
    assert index.select("layer").to_series().to_list() == ["features", "normalized"]
    assert index.select("version").to_series().to_list() == ["1", "1"]
    assert index.select("schema_version").to_series().to_list() == ["0.1", "0.1"]
    assert index.select("status").to_series().to_list() == ["candidate", "candidate"]
    assert all(value.endswith("Z") for value in index.select("created_at").to_series().to_list())
    assert index.select("start").to_series().to_list() == [day.start_iso, day.start_iso]
    assert index.select("path").to_series().to_list() == [
        "features/kaguya/esa1/pitch_angle_distribution",
        "normalized/kaguya/esa1/counts",
    ]


def test_store_filters_dataset_registry_index(tmp_path) -> None:
    store = Store(tmp_path / "store")
    day = spn.day("2008-02-01")
    next_day = spn.day("2008-02-02")
    store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=day,
        frame=pl.DataFrame({"time": [day.start_iso], "counts": [64]}),
        status="adopted",
        dataset_version="2026.07",
    )
    store.write_parquet_dataset(
        dataset_id="kaguya.esa1.pitch_angle_distribution",
        layer="features",
        mission="kaguya",
        instrument="esa1",
        product="pitch_angle_distribution",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=day,
        frame=pl.DataFrame({"time": [day.start_iso], "pad": [1.0]}),
    )
    store.write_parquet_dataset(
        dataset_id="artemis.p1.fgm.magnetic_field",
        layer="normalized",
        mission="artemis",
        instrument="fgm",
        product="magnetic_field",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=next_day,
        frame=pl.DataFrame({"time": [next_day.start_iso], "b_x": [1.0]}),
    )
    store.datasets(refresh=True)

    features = store.datasets(layer="features")
    adopted = store.datasets(status="adopted")
    schema_v01 = store.datasets(schema_version="0.1")
    dataset_v202607 = store.datasets(dataset_version="2026.07")
    overlapping = store.datasets(
        time_range=spn.period("2008-02-01T12:00:00Z", "2008-02-01T18:00:00Z")
    )
    boundary = store.datasets(
        time_range=spn.period("2008-02-02T00:00:00Z", "2008-02-02T06:00:00Z")
    )

    assert features.select("dataset_id").to_series().to_list() == [
        "kaguya.esa1.pitch_angle_distribution"
    ]
    assert adopted.select("dataset_id").to_series().to_list() == ["kaguya.esa1.counts"]
    assert schema_v01.select("dataset_id").to_series().to_list() == [
        "kaguya.esa1.pitch_angle_distribution",
        "artemis.p1.fgm.magnetic_field",
        "kaguya.esa1.counts",
    ]
    assert dataset_v202607.select("dataset_id").to_series().to_list() == ["kaguya.esa1.counts"]
    assert overlapping.select("dataset_id").to_series().to_list() == [
        "kaguya.esa1.pitch_angle_distribution",
        "kaguya.esa1.counts",
    ]
    assert boundary.select("dataset_id").to_series().to_list() == [
        "artemis.p1.fgm.magnetic_field"
    ]


def test_store_filters_dataset_registry_by_created_at(tmp_path) -> None:
    store = Store(tmp_path / "store")
    day = spn.day("2008-02-01")
    old = store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=day,
        frame=pl.DataFrame({"time": [day.start_iso], "counts": [64]}),
    )
    recent = store.write_parquet_dataset(
        dataset_id="kaguya.esa1.energy_flux",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="energy_flux",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=day,
        frame=pl.DataFrame({"time": [day.start_iso], "energy_flux": [1.0]}),
    )

    _set_created_at(old, "2026-07-01T00:00:00Z")
    _set_created_at(recent, "2026-07-02T12:00:00Z")
    store.datasets(refresh=True)

    created_on_second = store.datasets(
        created_after="2026-07-02T00:00:00Z",
        created_before="2026-07-03T00:00:00Z",
    )
    before_second = store.datasets(created_before="2026-07-02T00:00:00Z")

    assert created_on_second.select("dataset_id").to_series().to_list() == [
        "kaguya.esa1.energy_flux"
    ]
    assert before_second.select("dataset_id").to_series().to_list() == [
        "kaguya.esa1.counts"
    ]


def _set_created_at(record, created_at: str) -> None:
    manifest = record.manifest()
    manifest["created_at"] = created_at
    record.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


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
        source_files=("raw/first.dat",),
        source_datasets=("source.first",),
    )

    dataset = store.write_parquet_dataset(
        **kwargs,
        time_coverage=second,
        frame=pl.DataFrame({"time": [second.start_iso], "counts": [2]}),
        source_files=("raw/second.dat",),
        source_datasets=("source.second",),
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
    assert dataset.manifest()["source_files"] == ["raw/first.dat", "raw/second.dat"]
    assert dataset.manifest()["source_datasets"] == ["source.first", "source.second"]


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
