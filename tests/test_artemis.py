from __future__ import annotations

import pytest

import sopran as spn


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
