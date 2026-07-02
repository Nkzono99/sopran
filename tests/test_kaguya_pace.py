from __future__ import annotations

import gzip
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
    assert result.outputs[0].manifest()["dataset_id"] == "kaguya.esa1.counts"
    assert result.outputs[0].scan().collect().height == 2048


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
