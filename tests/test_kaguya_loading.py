from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

import sopran as spn
from sopran import Store
from sopran.missions.kaguya import Kaguya, normalize_sensors
from sopran.missions.kaguya.schema import KAGUYA_ESA1_SCHEMA


def test_normalize_sensors_accepts_spedas_ids_and_names() -> None:
    assert normalize_sensors([0, "ESA-S2", "lmag", "esa1"]) == ["ESA1", "ESA2", "LMAG"]


def test_kaguya_esa1_query_builds_public_pbf_paths(tmp_path) -> None:
    kaguya = Kaguya(store=Store(tmp_path / "store"))

    query = kaguya.esa1.select("2008-01-01", "2008-01-02")

    assert query.remote_files() == [
        "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz",
        "sln-l-pace-3-pbf1-v3.0/20080102/data/IPACE_PBF1_080102_ESA1_V003.dat.gz",
    ]


def test_kaguya_lmag_query_builds_nominal_and_optional_paths(tmp_path) -> None:
    kaguya = Kaguya(store=Store(tmp_path / "store"))

    query = kaguya.lmag.select("2008-11-01")

    assert query.remote_files() == [
        "sln-l-lmag-3-mag-ts-v1.0/nominal/20081101/data/MAG_TS20081101.dat",
        "sln-l-lmag-3-mag-ts-v1.0/optional/20081101/data/MAG_TSOP20081101.dat",
    ]


def test_kaguya_query_resolves_existing_files_from_fallback_cache(tmp_path) -> None:
    store = Store(tmp_path / "store")
    fallback = tmp_path / "legacy_public"
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = fallback / remote_file
    cached.parent.mkdir(parents=True)
    cached.write_text("cached", encoding="utf-8")

    kaguya = Kaguya(store=store, fallback_roots=[fallback])

    files = kaguya.esa1.select("2008-01-01").files(download="never")

    assert files == [cached]


def test_kaguya_query_download_never_omits_missing_files(tmp_path) -> None:
    kaguya = Kaguya(store=Store(tmp_path / "store"))

    files = kaguya.esa1.select("2008-01-01").files(download="never")

    assert files == []


def test_period_is_half_open_and_available_from_top_level() -> None:
    time = spn.period("2008-02-01", "2008-02-02")

    assert time.start_iso == "2008-02-01T00:00:00Z"
    assert time.stop_iso == "2008-02-02T00:00:00Z"
    assert time.days() == ["2008-02-01"]


def test_day_month_and_year_helpers_return_half_open_periods() -> None:
    assert spn.day("2008-02-01").days() == ["2008-02-01"]

    month = spn.month("2008-02")
    assert month.start_iso == "2008-02-01T00:00:00Z"
    assert month.stop_iso == "2008-03-01T00:00:00Z"

    year = spn.year("2008")
    assert year.start_iso == "2008-01-01T00:00:00Z"
    assert year.stop_iso == "2009-01-01T00:00:00Z"


def test_kaguya_esa1_energy_flux_endpoint_exposes_schema_info_and_plan(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))
    time = spn.period("2008-02-01", "2008-02-02")

    endpoint = kg.esa1.energy_flux

    assert kg.esa1.eflux is endpoint
    assert "KAGUYA.ESA1.energy_flux" in str(endpoint.info())
    assert endpoint.schema().name == "energy_flux"

    plan = endpoint.plan(time)

    assert plan.dataset_id == "kaguya.esa1.energy_flux"
    assert plan.time == time
    assert plan.remote_files == [
        "sln-l-pace-3-pbf1-v3.0/20080201/data/IPACE_PBF1_080201_ESA1_V003.dat.gz"
    ]


def test_kaguya_mission_and_esa1_instrument_are_discoverable(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))
    time = spn.period("2008-02-01", "2008-02-02")

    assert "KAGUYA" in str(kg.info())
    assert "esa1" in str(kg.info())

    assert kg.esa1.schema().instrument == "esa1"
    assert kg.esa1.plan(time).dataset_id == "kaguya.esa1"
    assert "energy_flux" in str(kg.esa1.info())


def test_kaguya_guides_return_markdown_pages(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    mission_guide = kg.guide()
    esa1_guide = kg.esa1.guide()
    energy_flux_guide = kg.esa1.energy_flux.guide()

    assert "KAGUYA/SELENE" in str(mission_guide)
    assert "PACE ESA1" in str(esa1_guide)
    assert "energy_flux" in energy_flux_guide.to_markdown()
    assert kg.guide("esa1") == esa1_guide
    assert kg.help() == mission_guide
    assert kg.help("esa1") == esa1_guide
    assert kg.esa1.help() == esa1_guide
    assert kg.esa1.energy_flux.help() == energy_flux_guide
    assert energy_flux_guide.source == "sopran.missions.kaguya/ESA1.md"
    assert "# KAGUYA/SELENE" in mission_guide._repr_markdown_()


def test_kaguya_guides_can_switch_language(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    mission_ja = kg.guide(language="ja")
    mission_en = kg.guide(language="en")
    esa1_ja = kg.esa1.guide(language="ja")
    energy_flux_ja = kg.esa1.energy_flux.guide(language="ja")

    assert mission_ja.language == "ja"
    assert mission_en.language == "en"
    assert mission_ja.available_languages == ("ja", "en")
    assert mission_ja.language_switcher() == "Lang: 日本語/English"
    assert mission_ja.source == "sopran.missions.kaguya/README.ja.md"
    assert mission_ja.with_language("en").source == "sopran.missions.kaguya/README.md"
    assert "KAGUYA/SELENE は SOPRAN" in mission_ja.to_markdown()
    assert "vertical slice" in mission_en.to_markdown()
    assert "PACE ESA1 は" in esa1_ja.to_markdown()
    assert "energy_flux" in energy_flux_ja.to_markdown()
    assert "vertical slice" in mission_ja.to_markdown(language="en")
    assert kg.help(language="ja") == mission_ja
    assert kg.guide("esa1", language="ja") == esa1_ja
    assert kg.help("esa1", language="ja") == esa1_ja
    assert kg.esa1.help(language="ja") == esa1_ja
    assert kg.esa1.energy_flux.help(language="ja") == energy_flux_ja
    with pytest.raises(ValueError, match="language"):
        kg.guide(language="fr")


def test_kaguya_examples_return_markdown_pages(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    mission_example = kg.example().to_markdown()
    instrument_example = kg.esa1.example().to_markdown()
    variable_example = kg.esa1.counts.example().to_markdown()

    assert "kg = spn.Kaguya" in mission_example
    assert "kg.esa1.counts.load(time)" in instrument_example
    assert "kg.esa1.counts.load(time)" in variable_example
    assert "spn.stack" in variable_example


def test_kaguya_esa1_load_returns_typed_data_object_without_downloading(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))
    time = spn.period("2008-02-01", "2008-02-02")

    esa1 = kg.esa1.load(time)
    flux = kg.esa1.energy_flux.load(time)

    assert esa1.instrument == "ESA1"
    assert esa1.time == time
    assert esa1.energy_flux.name == "energy_flux"
    assert esa1.eflux is esa1.energy_flux
    assert flux.name == "energy_flux"
    assert flux.time == time


def test_kaguya_uses_mission_default_download_policy(tmp_path) -> None:
    class FakeSource:
        def __init__(self, root):
            self.root = root
            self.downloaded = []

        def local_path(self, remote_file):
            return self.root / remote_file

        def download(self, remote_file, *, overwrite=False):
            self.downloaded.append((remote_file, overwrite))
            path = self.local_path(remote_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"downloaded")
            return path

    source = FakeSource(tmp_path / "raw")
    kg = spn.Kaguya(store=Store(tmp_path / "store"), source=source, download="missing")

    data = kg.esa1.load(spn.day("2008-01-01"))

    assert data.files == (source.local_path(source.downloaded[0][0]),)
    assert source.downloaded[0][1] is False


def test_kaguya_reads_default_download_policy_from_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SOPRAN_DOWNLOAD_MODE", "missing")

    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    assert kg.download == "missing"

    monkeypatch.setenv("SOPRAN_OFFLINE", "1")

    offline = spn.Kaguya(store=Store(tmp_path / "store"))

    assert offline.download == "never"


def test_kaguya_esa1_exposes_core_variable_endpoints(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))
    time = spn.period("2008-02-01", "2008-02-02")

    assert kg.esa1.counts.schema().dims == ("time", "energy", "look")
    assert kg.esa1.energy.schema().dims == ("energy",)
    assert kg.esa1.quality.schema().dims == ("time",)
    assert kg.esa1.counts.load(time).name == "counts"


def test_kaguya_esa1_to_xarray_returns_schema_backed_empty_dataset(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))
    time = spn.period("2008-02-01", "2008-02-02")

    ds = kg.esa1.load(time).to_xarray()

    assert ds.attrs["mission"] == "kaguya"
    assert ds.attrs["instrument"] == "ESA1"
    assert set(ds.data_vars) == {"energy_flux", "counts", "quality"}
    assert "energy" in ds.coords


def test_kaguya_esa1_variable_typo_suggests_available_endpoint(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    with pytest.raises(AttributeError) as exc:
        _ = kg.esa1.flux

    message = str(exc.value)
    assert "Kaguya.ESA1 has no variable 'flux'" in message
    assert "energy_flux" in message
    assert "kg.esa1.info()" in message


def test_kaguya_esa1_load_without_time_explains_required_period(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    with pytest.raises(ValueError) as exc:
        kg.esa1.energy_flux.load()

    message = str(exc.value)
    assert "Time range is required for Kaguya.ESA1.energy_flux" in message
    assert 'time = spn.period("2008-02-01", "2008-02-02")' in message


def test_kaguya_esa1_pipeline_records_lazy_stage_plan(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))
    time = spn.month("2008-02")

    pipe = (
        kg.esa1.pipeline(time)
        .download()
        .decode()
        .normalize()
        .select_variables("energy_flux", "counts", "quality")
        .quicklook("esa1_counts")
        .write("kaguya.esa1.normalized", layer="normalized")
    )

    plan = pipe.plan()

    assert plan.source == "kaguya.esa1"
    assert plan.time == time
    assert plan.stage_names == (
        "download",
        "decode",
        "normalize",
        "select_variables",
        "quicklook",
        "write",
    )
    assert plan.output_dataset == "kaguya.esa1.normalized"
    assert plan.output_layer == "normalized"


def test_pipeline_write_accepts_database_product_reference(tmp_path) -> None:
    store = Store(tmp_path / "store")
    kg = spn.Kaguya(store=store)
    product = store.database("wake_events").product("raw_counts")

    pipe = (
        kg.esa1.pipeline(spn.month("2008-02"))
        .decode()
        .select_variables("counts")
        .write(product)
    )

    plan = pipe.plan()

    assert product.dataset_id == "wake_events.raw_counts"
    assert product.layer == "databases"
    assert plan.output_dataset == "wake_events.raw_counts"
    assert plan.output_layer == "databases"


def test_pipeline_scan_reads_stored_normalized_variable(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.day("2008-01-01")
    frame = pl.DataFrame(
        {
            "time": ["2008-01-01T00:00:08Z", "2008-01-02T00:00:08Z"],
            "energy": [0, 0],
            "counts": [64, 128],
        }
    )
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
    kg = spn.Kaguya(store=store)

    lazy = kg.esa1.pipeline(time).from_normalized().select_variables("counts").scan()

    assert lazy.collect().to_dicts() == [
        {"time": "2008-01-01T00:00:08Z", "energy": 0, "counts": 64}
    ]


def test_pipeline_scan_filters_datetime_time_column(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.day("2008-01-01")
    frame = pl.DataFrame(
        {
            "time": [
                datetime(2008, 1, 1, 0, 0, 8),
                datetime(2008, 1, 2, 0, 0, 8),
            ],
            "energy": [0, 0],
            "counts": [64, 128],
        }
    )
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
    kg = spn.Kaguya(store=store)

    rows = (
        kg.esa1.pipeline(time)
        .from_normalized()
        .select_variables("counts")
        .scan()
        .collect()
        .to_dicts()
    )

    assert len(rows) == 1
    assert rows[0]["counts"] == 64


def test_pipeline_collect_materializes_stored_normalized_data(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.day("2008-01-01")
    frame = pl.DataFrame({"time": ["2008-01-01T00:00:08Z"], "energy": [0], "counts": [64]})
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
    kg = spn.Kaguya(store=store)

    collected = kg.esa1.pipeline(time).from_normalized().select_variables("counts").collect()

    assert collected.to_dicts() == frame.to_dicts()


def test_pipeline_dry_run_returns_result_without_executing(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))
    time = spn.month("2008-02")
    pipe = (
        kg.esa1.pipeline(time)
        .download()
        .decode()
        .select_variables("counts")
        .write(
            "kaguya.esa1.counts",
            layer="normalized",
        )
    )

    result = pipe.run(dry_run=True)

    assert result.status == "planned"
    assert result.plan.stage_names == ("download", "decode", "select_variables", "write")
    assert result.plan.output_dataset == "kaguya.esa1.counts"
    assert result.plan.to_dict() == {
        "source": "kaguya.esa1",
        "start": "2008-02-01T00:00:00Z",
        "stop": "2008-03-01T00:00:00Z",
        "output_dataset": "kaguya.esa1.counts",
        "output_layer": "normalized",
        "stages": [
            {"name": "download", "parameters": {}},
            {"name": "decode", "parameters": {}},
            {"name": "select_variables", "parameters": {"names": ["counts"]}},
            {
                "name": "write",
                "parameters": {"dataset": "kaguya.esa1.counts", "layer": "normalized"},
            },
        ],
    }
    text = str(result)
    assert "SOPRAN pipeline result" in text
    assert "status: planned" in text
    assert "source: kaguya.esa1" in text
    assert "time: 2008-02-01T00:00:00Z .. 2008-03-01T00:00:00Z" in text
    assert "output: kaguya.esa1.counts (normalized)" in text
    assert "- select_variables names=['counts']" in text


def test_project_case_supplies_time_to_kaguya_endpoints(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[cases.wake_20080201]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"
""".strip(),
        encoding="utf-8",
    )

    project = spn.Project(project_root, store=Store(tmp_path / "store"))
    case = project.case("wake_20080201")

    esa1 = case.kaguya.esa1.load()
    flux = case.kaguya.esa1.energy_flux.load()
    plan = case.kaguya.esa1.energy_flux.plan()

    assert esa1.time == case.time
    assert flux.time == case.time
    assert plan.time == case.time
    assert plan.remote_files == [
        "sln-l-pace-3-pbf1-v3.0/20080201/data/IPACE_PBF1_080201_ESA1_V003.dat.gz"
    ]
