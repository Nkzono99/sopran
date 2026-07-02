from __future__ import annotations

import polars as pl
import pytest

import sopran as spn
from sopran.core.schema import InstrumentSchema
from sopran.missions.artemis.mission import ARTEMIS_MAGNETIC_FIELD


def test_artemis_probe_fgm_endpoint_exposes_schema_and_plan() -> None:
    art = spn.Artemis()
    time = spn.day("2011-07-01")

    endpoint = art.p1.fgm.magnetic_field
    plan = endpoint.plan(time)

    assert "ARTEMIS" in str(art.info())
    assert "p1" in str(art.info())
    assert "magnetic_field" in str(art.p1.fgm.info())
    assert endpoint.schema().dims == ("time", "component")
    assert plan.dataset_id == "artemis.p1.fgm.magnetic_field"
    assert plan.time == time


def test_artemis_guides_return_markdown_pages() -> None:
    art = spn.Artemis()

    mission_guide = art.guide()
    fgm_guide = art.p1.fgm.guide()
    variable_guide = art.p1.fgm.magnetic_field.guide()

    assert "# ARTEMIS" in mission_guide.to_markdown()
    assert "FGM" in fgm_guide.to_markdown()
    assert variable_guide.source == "sopran.missions.artemis/README.md"


def test_guide_page_open_uses_public_url(monkeypatch) -> None:
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    page = spn.GuidePage(
        title="SOPRAN docs",
        markdown="# SOPRAN docs",
        source="docs",
        url="https://example.com/sopran",
    )

    page.open()

    assert opened == ["https://example.com/sopran"]


def test_artemis_load_is_explicitly_not_implemented_yet() -> None:
    art = spn.Artemis()

    with pytest.raises(NotImplementedError) as exc:
        art.p1.fgm.magnetic_field.load(spn.day("2011-07-01"))

    assert "ARTEMIS P1 FGM" in str(exc.value)


def test_artemis_load_reads_normalized_magnetic_field_from_store(tmp_path) -> None:
    store = spn.Store(tmp_path / "store")
    time = spn.day("2011-07-01")
    _write_artemis_fgm_dataset(store, time)

    magnetic_field = spn.Artemis(store=store).p1.fgm.magnetic_field.load(time)
    array = magnetic_field.to_xarray()

    assert magnetic_field.name == "magnetic_field"
    assert array.dims == ("time", "component")
    assert array.coords["component"].values.tolist() == ["x", "y", "z"]
    assert array.values.tolist() == [[1.0, 2.0, 3.0]]


def test_top_level_load_reads_artemis_dataset_from_store(tmp_path) -> None:
    store = spn.Store(tmp_path / "store")
    time = spn.day("2011-07-01")
    _write_artemis_fgm_dataset(store, time)

    magnetic_field = spn.load("artemis.p1.fgm.magnetic_field", time, store=store)

    assert magnetic_field.to_xarray().values.tolist() == [[1.0, 2.0, 3.0]]


def test_project_case_artemis_uses_project_store_for_load(tmp_path) -> None:
    store = spn.Store(tmp_path / "store")
    time = spn.day("2011-07-01")
    _write_artemis_fgm_dataset(store, time)
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[cases.wake]
start = "2011-07-01T00:00:00"
stop = "2011-07-02T00:00:00"
""".strip(),
        encoding="utf-8",
    )

    magnetic_field = spn.Project(project_root, store=store).case(
        "wake"
    ).artemis.p1.fgm.magnetic_field.load()

    assert magnetic_field.to_xarray().values.tolist() == [[1.0, 2.0, 3.0]]


def _write_artemis_fgm_dataset(store: spn.Store, time: spn.TimeRange) -> None:
    frame = pl.DataFrame(
        {
            "time": ["2011-07-01T00:00:00Z"] * 3,
            "component": ["x", "y", "z"],
            "magnetic_field": [1.0, 2.0, 3.0],
        }
    )
    store.write_parquet_dataset(
        dataset_id="artemis.p1.fgm.magnetic_field",
        layer="normalized",
        mission="artemis",
        instrument="p1.fgm",
        product="magnetic_field",
        schema=InstrumentSchema(
            mission="artemis",
            instrument="p1.fgm",
            variables=(ARTEMIS_MAGNETIC_FIELD,),
        ),
        time_coverage=time,
        frame=frame,
    )


def test_project_case_supplies_time_to_artemis_endpoint(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[cases.wake]
start = "2011-07-01T00:00:00"
stop = "2011-07-02T00:00:00"
""".strip(),
        encoding="utf-8",
    )

    case = spn.Project(project_root).case("wake")
    plan = case.artemis.p1.fgm.magnetic_field.plan()

    assert plan.dataset_id == "artemis.p1.fgm.magnetic_field"
    assert plan.time == case.time


def test_top_level_load_dispatches_artemis_dataset_id() -> None:
    with pytest.raises(NotImplementedError) as exc:
        spn.load("artemis.p1.fgm.magnetic_field", spn.day("2011-07-01"))

    assert "ARTEMIS P1 FGM" in str(exc.value)
