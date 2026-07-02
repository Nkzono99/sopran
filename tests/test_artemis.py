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
    assert art.p1.fgm.schema().instrument == "fgm"
    assert endpoint.schema().dims == ("time", "component")
    assert plan.dataset_id == "artemis.p1.fgm.magnetic_field"
    assert plan.time == time


def test_artemis_guides_return_markdown_pages() -> None:
    art = spn.Artemis()

    mission_guide = art.guide()
    fgm_guide = art.p1.fgm.guide()
    variable_guide = art.p1.fgm.magnetic_field.guide()

    assert mission_guide.language == "ja"
    assert "# ARTEMIS" in mission_guide.to_markdown()
    assert "ARTEMIS は" in mission_guide.to_markdown()
    assert "FGM" in fgm_guide.to_markdown()
    assert "| name | dims | units | dtype | frame | aliases | description |" in (
        fgm_guide.to_markdown()
    )
    assert "| magnetic_field | time, component | nT |" in fgm_guide.to_markdown()
    assert "b, fgm" in fgm_guide.to_markdown()
    assert art.help() == mission_guide
    assert art.p1.help() == mission_guide
    assert art.p1.fgm.help() == fgm_guide
    assert art.p1.fgm.magnetic_field.help() == variable_guide
    assert variable_guide.source == "sopran.missions.artemis/README.ja.md"
    assert mission_guide.url == "https://nkzono99.github.io/sopran/missions/artemis/"
    assert fgm_guide.url == mission_guide.url
    assert variable_guide.url == mission_guide.url


def test_artemis_guides_can_switch_language() -> None:
    art = spn.Artemis()

    mission_ja = art.guide(language="ja")
    mission_en = art.guide(language="en")
    fgm_ja = art.p1.fgm.guide(language="ja")
    variable_ja = art.p1.fgm.magnetic_field.guide(language="ja")

    assert mission_ja.language == "ja"
    assert mission_en.language == "en"
    assert mission_ja.available_languages == ("ja", "en")
    assert mission_ja.language_switcher() == "Lang: 日本語/English"
    assert mission_ja.with_language("en").url == (
        "https://nkzono99.github.io/sopran/missions/artemis/"
    )
    assert "ARTEMIS は" in mission_ja.to_markdown()
    assert "lunar-orbiting THEMIS probes" in mission_en.to_markdown()
    assert "FGM" in fgm_ja.to_markdown()
    assert "| name | dims | units | dtype | frame | aliases | description |" in (
        fgm_ja.to_markdown()
    )
    assert variable_ja == fgm_ja
    assert art.help(language="ja") == mission_ja
    assert art.p1.help(language="ja") == mission_ja
    assert art.p1.fgm.help(language="ja") == fgm_ja
    assert art.p1.fgm.magnetic_field.help(language="ja") == variable_ja
    with pytest.raises(ValueError, match="language"):
        art.guide(language="fr")


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


def test_guide_page_open_can_select_language_url(monkeypatch) -> None:
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    page = spn.GuidePage(
        title="SOPRAN docs",
        markdown="# SOPRAN docs",
        source="docs/ja/index.md",
        language="ja",
        available_languages=("ja", "en"),
        url="https://example.com/ja/",
        urls={
            "en": "https://example.com/en/",
        },
    )

    page.open(language="en")

    assert opened == ["https://example.com/en/"]
    with pytest.raises(ValueError, match="language"):
        page.open(language="fr")


def test_guide_page_tracks_language_switch_metadata() -> None:
    page = spn.GuidePage(
        title="SOPRAN docs",
        markdown="# SOPRAN docs",
        source="docs",
        language="ja",
        available_languages=("ja", "en"),
    )

    assert page.language == "ja"
    assert page.available_languages == ("ja", "en")
    assert page.language_switcher() == "Lang: 日本語/English"
    assert page.to_markdown().startswith("Lang: 日本語/English\n\n# SOPRAN docs")


def test_guide_page_exports_language_metadata() -> None:
    page = spn.GuidePage(
        title="SOPRAN docs",
        markdown="# SOPRAN docs\n\n日本語の説明。",
        source="docs/ja/index.md",
        sources={"en": "docs/en/index.md"},
        language="ja",
        available_languages=("ja", "en"),
        url="https://example.com/ja/",
        urls={"en": "https://example.com/en/"},
        translations={"en": "# SOPRAN docs\n\nEnglish guide."},
    )

    assert page.to_metadata() == {
        "title": "SOPRAN docs",
        "language": "ja",
        "available_languages": ["ja", "en"],
        "fallback_language": "ja",
        "language_switcher": "Lang: 日本語/English",
        "source": "docs/ja/index.md",
        "sources": {
            "ja": "docs/ja/index.md",
            "en": "docs/en/index.md",
        },
        "url": "https://example.com/ja/",
        "urls": {
            "ja": "https://example.com/ja/",
            "en": "https://example.com/en/",
        },
    }
    assert page.to_metadata(language="en")["source"] == "docs/en/index.md"
    assert page.to_metadata(language="en")["url"] == "https://example.com/en/"
    with pytest.raises(ValueError, match="language"):
        page.to_metadata(language="fr")


def test_guide_page_can_switch_language_content() -> None:
    page = spn.GuidePage(
        title="SOPRAN docs",
        markdown="# SOPRAN docs\n\n日本語の説明。",
        source="docs/ja/index.md",
        sources={
            "en": "docs/en/index.md",
        },
        language="ja",
        available_languages=("ja", "en"),
        url="https://example.com/ja/",
        urls={
            "en": "https://example.com/en/",
        },
        translations={
            "en": "# SOPRAN docs\n\nEnglish guide.",
        },
    )

    english = page.with_language("en")

    assert page.to_markdown(language="ja").startswith(
        "Lang: 日本語/English\n\n# SOPRAN docs\n\n日本語の説明。"
    )
    assert page.to_markdown(language="en").startswith(
        "Lang: 日本語/English\n\n# SOPRAN docs\n\nEnglish guide."
    )
    assert english.language == "en"
    assert english.markdown == "# SOPRAN docs\n\nEnglish guide."
    assert english.source == "docs/en/index.md"
    assert english.url == "https://example.com/en/"
    assert english.to_markdown().startswith(
        "Lang: 日本語/English\n\n# SOPRAN docs\n\nEnglish guide."
    )
    with pytest.raises(ValueError, match="language"):
        page.with_language("fr")


def test_guide_page_can_append_schema_table_to_all_languages() -> None:
    schema = InstrumentSchema(
        mission="artemis",
        instrument="fgm",
        variables=(ARTEMIS_MAGNETIC_FIELD,),
    )
    page = spn.GuidePage(
        title="ARTEMIS FGM",
        markdown="# ARTEMIS FGM\n\n日本語の説明。",
        source="docs/ja/artemis-fgm.md",
        sources={"en": "docs/en/artemis-fgm.md"},
        language="ja",
        available_languages=("ja", "en"),
        translations={"en": "# ARTEMIS FGM\n\nEnglish description."},
    )

    page_with_schema = page.with_schema(schema)

    assert "| name | dims | units | dtype | frame | aliases | description |" in (
        page_with_schema.to_markdown(language="ja")
    )
    assert "| magnetic_field | time, component | nT |" in (
        page_with_schema.to_markdown(language="en")
    )
    assert page_with_schema.source == "docs/ja/artemis-fgm.md"
    assert page_with_schema.with_language("en").source == "docs/en/artemis-fgm.md"


def test_guide_page_show_includes_language_switcher(capsys) -> None:
    page = spn.GuidePage(
        title="SOPRAN docs",
        markdown="# SOPRAN docs",
        source="docs",
        language="ja",
        available_languages=("ja", "en"),
    )

    page.show()

    assert capsys.readouterr().out.startswith("Lang: 日本語/English\n\n# SOPRAN docs")


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


def test_artemis_variable_endpoint_builds_line_plot_item(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    store = spn.Store(tmp_path / "store")
    time = spn.day("2011-07-01")
    _write_artemis_fgm_dataset(store, time)

    item = spn.Artemis(store=store).p1.fgm.magnetic_field.line(time)
    fig = spn.stack(item).plot()

    assert item.name == "magnetic_field"
    assert len(fig.axes[0].lines) == 3


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


def test_project_case_artemis_endpoint_builds_line_plot_item(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
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
    case = spn.Project(project_root, store=store).case("wake")

    stack = case.stack(case.artemis.p1.fgm.magnetic_field.line())

    assert stack.plan().items == ("magnetic_field",)
    assert len(stack.plot().axes[0].lines) == 3


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
