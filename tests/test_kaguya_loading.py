from __future__ import annotations

import sopran as spn
import pytest
from sopran import Store
from sopran.missions.kaguya import Kaguya, normalize_sensors


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

    assert "KAGUYA/SELENE" in str(mission_guide)
    assert "PACE ESA1" in str(esa1_guide)
    assert kg.guide("esa1") == esa1_guide
    assert "# KAGUYA/SELENE" in mission_guide._repr_markdown_()


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
        "write",
    )
    assert plan.output_dataset == "kaguya.esa1.normalized"
    assert plan.output_layer == "normalized"


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
