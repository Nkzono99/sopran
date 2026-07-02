from __future__ import annotations

import gzip
import json
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest

import sopran as spn
from sopran import Store
from sopran.missions.kaguya import pace_energy_counts, read_pace_pbf


def test_read_pace_pbf_type01_summarizes_energy_counts(tmp_path: Path) -> None:
    path = tmp_path / "IPACE_PBF1_080101_ESA1_V003.dat"
    _write_type01_pbf(path)

    pace = read_pace_pbf(path)

    assert pace.sensor == 0
    assert pace.sensor_name == "ESA-S1"
    assert pace.headers[0]["type"] == 0x01
    assert 0x01 in pace.records

    counts = pace_energy_counts(pace)

    assert counts.shape == (1, 32)
    assert np.all(counts == 64)


def test_read_pace_pbf_accepts_gzip_files(tmp_path: Path) -> None:
    path = tmp_path / "IPACE_PBF1_080101_ESA1_V003.dat"
    gz_path = tmp_path / "IPACE_PBF1_080101_ESA1_V003.dat.gz"
    _write_type01_pbf(path)
    with path.open("rb") as source, gzip.open(gz_path, "wb") as target:
        target.write(source.read())

    pace = read_pace_pbf(gz_path)

    assert pace.source_files == (gz_path,)
    assert pace_energy_counts(pace).shape == (1, 32)


def test_kaguya_esa1_to_xarray_decodes_cached_pbf_counts(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")

    kg = spn.Kaguya(store=store)

    ds = kg.esa1.load(spn.day("2008-01-01")).to_xarray()

    assert ds["counts"].shape == (1, 32, 64)
    assert int(ds["counts"].isel(time=0, energy=0).sum()) == 64
    assert ds["quality"].to_numpy().tolist() == [0]
    assert str(ds["time"].values[0]) == "2008-01-01T00:00:08.000000000"


def test_kaguya_esa1_to_xarray_filters_records_to_requested_time_range(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")

    kg = spn.Kaguya(store=store)

    ds = kg.esa1.load(
        spn.period("2008-01-01T00:00:09Z", "2008-01-01T00:00:10Z")
    ).to_xarray()

    assert ds["counts"].shape == (0, 0, 0)


def test_kaguya_esa1_variable_endpoint_returns_loaded_data_array(tmp_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")

    kg = spn.Kaguya(store=store)

    counts = kg.esa1.counts.load(spn.day("2008-01-01"))
    axes = counts.plot()

    assert counts.to_xarray().shape == (1, 32, 64)
    assert counts.xr is counts.to_xarray()
    assert axes is not None


def test_kaguya_esa1_variable_endpoint_can_plot_with_time(tmp_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")

    kg = spn.Kaguya(store=store)

    axes = kg.esa1.counts.plot(spn.day("2008-01-01"))

    assert axes is not None


def test_project_case_variable_endpoint_can_plot_with_case_time(tmp_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[cases.wake]
start = "2008-01-01T00:00:00"
stop = "2008-01-02T00:00:00"
""".strip(),
        encoding="utf-8",
    )
    case = spn.Project(project_root, store=store).case("wake")

    axes = case.kaguya.esa1.counts.plot()

    assert axes is not None


def test_loaded_sopran_array_builds_spectrogram_plot_item(tmp_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")

    kg = spn.Kaguya(store=store)
    counts = kg.esa1.counts.load(spn.day("2008-01-01"))
    quality = kg.esa1.quality.load(spn.day("2008-01-01"))

    stack = spn.stack(counts.spectrogram(y="energy"), quality.line())

    assert stack.plan().items == ("counts", "quality")
    assert len(stack.plot().axes) == 2


def test_kaguya_variable_endpoint_builds_lazy_plot_items(tmp_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")

    kg = spn.Kaguya(store=store)
    time = spn.day("2008-01-01")

    stack = spn.stack(
        kg.esa1.counts.spectrogram(time, y="energy"),
        kg.esa1.quality.line(time),
    )

    assert stack.plan().items == ("counts", "quality")
    assert len(stack.plot().axes) == 2


def test_project_case_variable_endpoint_builds_lazy_plot_items(tmp_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[cases.wake]
start = "2008-01-01T00:00:00"
stop = "2008-01-02T00:00:00"
""".strip(),
        encoding="utf-8",
    )

    case = spn.Project(project_root, store=store).case("wake")

    stack = case.stack(
        case.kaguya.esa1.counts.spectrogram(y="energy"),
        case.kaguya.esa1.quality.line(),
    )

    assert stack.plan().items == ("counts", "quality")
    assert len(stack.plot().axes) == 2


def test_top_level_load_dispatches_kaguya_variable_dataset_id(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")

    counts = spn.load("kaguya.esa1.counts", spn.day("2008-01-01"), store=store)

    assert counts.name == "counts"
    assert counts.to_xarray().shape == (1, 32, 64)


def test_kaguya_esa1_to_polars_sums_counts_by_energy(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")

    kg = spn.Kaguya(store=store)

    frame = kg.esa1.load(spn.day("2008-01-01")).to_polars("counts", reduce_look="sum")

    assert frame.columns == ["time", "energy", "counts"]
    assert frame.height == 32
    assert frame["counts"].to_list() == [64] * 32


def test_kaguya_esa1_to_pandas_wraps_polars_conversion(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")

    kg = spn.Kaguya(store=store)

    frame = kg.esa1.load(spn.day("2008-01-01")).to_pandas("counts", reduce_look="sum")

    assert list(frame.columns) == ["time", "energy", "counts"]
    assert len(frame) == 32
    assert frame["counts"].tolist() == [64] * 32


def test_kaguya_esa1_write_parquet_saves_counts_dataset(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")

    kg = spn.Kaguya(store=store)

    dataset = kg.esa1.load(spn.day("2008-01-01")).write_parquet(
        store,
        variable="counts",
        reduce_look="sum",
    )

    shard = dataset.root / "shards" / "part-000.parquet"

    assert dataset.root == store.normalized_path("kaguya", "esa1", "counts")
    assert shard.exists()
    assert pl.read_parquet(shard).height == 32


def test_kaguya_esa1_pipeline_run_writes_counts_dataset(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")
    kg = spn.Kaguya(store=store)

    result = (
        kg.esa1.pipeline(spn.day("2008-01-01"))
        .decode()
        .select_variables("counts")
        .write("kaguya.esa1.counts", layer="normalized")
        .run()
    )

    assert result.status == "complete"
    assert re.match(r"^run_\d{8}T\d{6}\d{6}Z_[0-9a-f]{8}$", result.run_id)
    manifest = result.outputs[0].manifest()
    assert manifest["dataset_id"] == "kaguya.esa1.counts"
    assert manifest["provenance"]["pipeline"] == {
        "mode": "create",
        "output_dataset": "kaguya.esa1.counts",
        "output_layer": "normalized",
        "run_id": result.run_id,
        "source": "kaguya.esa1",
        "stages": ["decode", "select_variables", "write"],
        "start": "2008-01-01T00:00:00Z",
        "stop": "2008-01-02T00:00:00Z",
    }
    assert manifest["provenance"]["variable"] == "counts"
    assert result.outputs[0].scan().collect().height == 2048
    assert result.log_path == result.outputs[0].root / "logs" / f"{result.run_id}.json"
    log = json.loads(result.log_path.read_text(encoding="utf-8"))
    assert log["run_id"] == result.run_id
    assert log["status"] == "complete"
    assert log["mode"] == "create"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", log["started_at"])
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", log["finished_at"])
    started_at = datetime.fromisoformat(log["started_at"].replace("Z", "+00:00"))
    finished_at = datetime.fromisoformat(log["finished_at"].replace("Z", "+00:00"))
    assert started_at <= finished_at
    assert log["plan"]["source"] == "kaguya.esa1"
    assert log["plan"]["output_dataset"] == "kaguya.esa1.counts"
    assert log["plan"]["output_layer"] == "normalized"
    assert log["stages"] == [
        {"name": "decode", "parameters": {}},
        {"name": "select_variables", "parameters": {"names": ["counts"]}},
        {
            "name": "write",
            "parameters": {"dataset": "kaguya.esa1.counts", "layer": "normalized"},
        },
    ]
    assert [stage["name"] for stage in log["stage_logs"]] == [
        "decode",
        "select_variables",
        "write",
    ]
    assert all(stage["status"] == "complete" for stage in log["stage_logs"])
    assert all(stage["elapsed_seconds"] >= 0 for stage in log["stage_logs"])
    assert all(stage["row_count"] == 2048 for stage in log["stage_logs"])
    assert all(stage["shard_count"] == 1 for stage in log["stage_logs"])
    assert all(
        re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", stage["started_at"])
        for stage in log["stage_logs"]
    )
    assert all(
        re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", stage["finished_at"])
        for stage in log["stage_logs"]
    )
    assert log["row_count"] == 2048
    assert log["shards"][0]["row_count"] == 2048
    assert log["elapsed_seconds"] >= 0


def test_kaguya_esa1_pipeline_run_writes_quicklook_preview(tmp_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")
    kg = spn.Kaguya(store=store)

    result = (
        kg.esa1.pipeline(spn.day("2008-01-01"))
        .decode()
        .select_variables("counts")
        .quicklook("counts")
        .write("kaguya.esa1.counts", layer="normalized")
        .run()
    )

    preview_root = result.outputs[0].root / "preview"
    assert (preview_root / "counts.png").exists()
    assert (preview_root / "counts.json").exists()
    assert result.outputs[1].metadata["items"] == ["counts"]
    assert result.outputs[1].metadata["metadata"]["pipeline"]["output_dataset"] == (
        "kaguya.esa1.counts"
    )
    assert result.outputs[1].metadata["metadata"]["pipeline"]["output_layer"] == "normalized"
    assert result.outputs[1].metadata["metadata"]["pipeline"]["run_id"] == result.run_id


def test_kaguya_esa1_pipeline_run_replace_overwrites_counts_dataset(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")
    kg = spn.Kaguya(store=store)
    pipe = (
        kg.esa1.pipeline(spn.day("2008-01-01"))
        .decode()
        .select_variables("counts")
        .write("kaguya.esa1.counts", layer="normalized")
    )
    pipe.run()

    with pytest.raises(FileExistsError):
        pipe.run()

    result = pipe.run(mode="replace")

    assert result.status == "complete"
    assert result.outputs[0].catalog().height == 1
    assert result.outputs[0].scan().collect().height == 2048


def test_kaguya_esa1_pipeline_run_append_adds_counts_shard(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")
    kg = spn.Kaguya(store=store)
    pipe = (
        kg.esa1.pipeline(spn.day("2008-01-01"))
        .decode()
        .select_variables("counts")
        .write("kaguya.esa1.counts", layer="normalized")
    )
    pipe.run()

    result = pipe.run(mode="append")

    catalog = result.outputs[0].catalog()
    assert catalog.select("path").to_series().to_list() == [
        "shards/part-000.parquet",
        "shards/part-001.parquet",
    ]
    assert result.outputs[0].scan().collect().height == 4096


def test_kaguya_esa1_pipeline_run_resume_skips_complete_dataset(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")
    kg = spn.Kaguya(store=store)
    pipe = (
        kg.esa1.pipeline(spn.day("2008-01-01"))
        .decode()
        .select_variables("counts")
        .write("kaguya.esa1.counts", layer="normalized")
    )
    first = pipe.run()

    result = pipe.run(resume=True)

    assert result.status == "skipped"
    assert result.outputs[0].root == first.outputs[0].root
    assert result.outputs[0].catalog().height == 1
    assert result.outputs[0].scan().collect().height == 2048
    assert result.log_path == result.outputs[0].root / "logs" / f"{result.run_id}.json"
    log = json.loads(result.log_path.read_text(encoding="utf-8"))
    assert log["status"] == "skipped"
    assert log["mode"] == "create"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", log["started_at"])
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", log["finished_at"])
    assert log["resume"] is True
    assert [stage["status"] for stage in log["stage_logs"]] == [
        "skipped",
        "skipped",
        "skipped",
    ]
    assert [stage["row_count"] for stage in log["stage_logs"]] == [2048, 2048, 2048]
    assert [stage["shard_count"] for stage in log["stage_logs"]] == [1, 1, 1]
    assert log["row_count"] == 2048
    assert log["shards"][0]["status"] == "complete"


def test_kaguya_esa1_pipeline_run_only_failed_skips_when_no_failed_shards(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    _write_type01_pbf_gzip(cached, tmp_path / "scratch.dat")
    kg = spn.Kaguya(store=store)
    pipe = (
        kg.esa1.pipeline(spn.day("2008-01-01"))
        .decode()
        .select_variables("counts")
        .write("kaguya.esa1.counts", layer="normalized")
    )
    first = pipe.run()

    result = pipe.run(only_failed=True)

    assert result.status == "skipped"
    assert result.outputs[0].root == first.outputs[0].root
    log = json.loads(result.log_path.read_text(encoding="utf-8"))
    assert log["status"] == "skipped"
    assert log["only_failed"] is True
    assert log["failed_shard_count"] == 0
    assert [stage["status"] for stage in log["stage_logs"]] == [
        "skipped",
        "skipped",
        "skipped",
    ]
    assert [stage["row_count"] for stage in log["stage_logs"]] == [2048, 2048, 2048]
    assert [stage["shard_count"] for stage in log["stage_logs"]] == [1, 1, 1]


def test_kaguya_esa1_pipeline_run_only_failed_requires_existing_catalog(
    tmp_path: Path,
) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))
    pipe = (
        kg.esa1.pipeline(spn.day("2008-01-01"))
        .decode()
        .select_variables("counts")
        .write("kaguya.esa1.counts", layer="normalized")
    )

    with pytest.raises(spn.DatasetNotFoundError):
        pipe.run(only_failed=True)


def _write_type01_pbf(path: Path) -> None:
    file_header = bytearray(1024)
    file_header[-1] = 0xEE

    header = np.zeros(64, dtype="<u4")
    header[0] = 0
    header[3] = 0x01
    header[5] = 16000
    header[6] = 16
    header[19] = 20080101
    header[20] = 0
    header[25] = 0

    event = np.arange(16, dtype="<u4")
    counts = np.ones((32, 4, 16), dtype="<u2")
    trash = np.zeros((32, 4, 2), dtype="<u2")

    with path.open("wb") as file:
        file.write(file_header)
        file.write(header.tobytes())
        file.write(event.tobytes())
        file.write(counts.tobytes())
        file.write(trash.tobytes())


def _write_type01_pbf_gzip(gzip_path: Path, scratch_path: Path) -> None:
    _write_type01_pbf(scratch_path)
    with scratch_path.open("rb") as source, gzip.open(gzip_path, "wb") as target:
        target.write(source.read())
