from __future__ import annotations

from email.message import Message
from io import BytesIO

import numpy as np
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


def test_artemis_probe_esa_endpoint_exposes_schema_and_plan() -> None:
    art = spn.Artemis()
    time = spn.day("2011-07-01")

    endpoint = art.p1.esa.ion_energy_flux
    plan = endpoint.plan(time)

    assert "esa" in str(art.p1.info())
    assert "ion_energy_flux" in str(art.p1.esa.info())
    assert art.p1.esa.schema().instrument == "esa"
    assert endpoint.schema().dims == ("time", "energy_bin")
    assert endpoint.schema().units == "eV/(cm^2 s sr eV)"
    assert plan.dataset_id == "artemis.p1.esa.ion_energy_flux"
    assert plan.time == time


def test_artemis_variable_endpoint_info_lists_aliases() -> None:
    art = spn.Artemis()

    fgm_info = str(art.p1.fgm.magnetic_field.info())
    esa_info = str(art.p1.esa.ion_energy_flux.info())

    assert "aliases: b, fgm" in fgm_info
    assert "aliases: ion_eflux, esa" in esa_info


def test_artemis_fgm_unknown_variable_error_lists_available_variables() -> None:
    art = spn.Artemis()

    with pytest.raises(AttributeError) as exc:
        _ = art.p1.fgm.field

    message = str(exc.value)
    assert "ARTEMIS.P1.FGM has no variable 'field'" in message
    assert "Available variables:" in message
    assert "magnetic_field" in message
    assert "Did you mean:" in message
    assert "art.p1.fgm.info()" in message
    assert "art.p1.fgm.magnetic_field.load(time)" in message


def test_artemis_esa_unknown_variable_error_lists_available_variables() -> None:
    art = spn.Artemis()

    with pytest.raises(AttributeError) as exc:
        _ = art.p1.esa.energy_flux

    message = str(exc.value)
    assert "ARTEMIS.P1.ESA has no variable 'energy_flux'" in message
    assert "Available variables:" in message
    assert "ion_energy_flux" in message
    assert "Did you mean:" in message
    assert "art.p1.esa.info()" in message
    assert "art.p1.esa.ion_energy_flux.load(time)" in message


def test_artemis_endpoint_load_requires_time_with_actionable_message() -> None:
    art = spn.Artemis()

    with pytest.raises(ValueError) as exc:
        art.p1.fgm.magnetic_field.load()

    message = str(exc.value)
    assert "Time range is required for ARTEMIS.P1.FGM.magnetic_field" in message
    assert 'time = spn.period("2011-07-01", "2011-07-02")' in message
    assert "art.p1.fgm.magnetic_field.load(time)" in message
    assert "case.artemis.p1.fgm.magnetic_field.load()" in message


def test_artemis_endpoint_plan_requires_time_with_actionable_message() -> None:
    art = spn.Artemis()

    with pytest.raises(ValueError) as exc:
        art.p1.esa.ion_energy_flux.plan()

    message = str(exc.value)
    assert "Time range is required for ARTEMIS.P1.ESA.ion_energy_flux" in message
    assert "art.p1.esa.ion_energy_flux.load(time)" in message
    assert "case.artemis.p1.esa.ion_energy_flux.load()" in message


def test_artemis_endpoint_line_requires_time_with_actionable_message() -> None:
    art = spn.Artemis()

    with pytest.raises(ValueError) as exc:
        art.p1.fgm.magnetic_field.line()

    message = str(exc.value)
    assert "Time range is required for ARTEMIS.P1.FGM.magnetic_field" in message
    assert "art.p1.fgm.magnetic_field.load(time)" in message
    assert "case.artemis.p1.fgm.magnetic_field.load()" in message


def test_artemis_endpoint_spectrogram_requires_time_with_actionable_message() -> None:
    art = spn.Artemis()

    with pytest.raises(ValueError) as exc:
        art.p1.esa.ion_energy_flux.spectrogram()

    message = str(exc.value)
    assert "Time range is required for ARTEMIS.P1.ESA.ion_energy_flux" in message
    assert "art.p1.esa.ion_energy_flux.load(time)" in message
    assert "case.artemis.p1.esa.ion_energy_flux.load()" in message


def test_artemis_guides_return_markdown_pages() -> None:
    art = spn.Artemis()

    mission_guide = art.guide()
    fgm_guide = art.p1.fgm.guide()
    esa_guide = art.p1.esa.guide()
    variable_guide = art.p1.fgm.magnetic_field.guide()

    assert mission_guide.language == "ja"
    assert "# ARTEMIS" in mission_guide.to_markdown()
    assert "ARTEMISは" in mission_guide.to_markdown()
    assert "FGM" in fgm_guide.to_markdown()
    assert "| name | dims | units | dtype | frame | aliases | description |" in (
        fgm_guide.to_markdown()
    )
    assert "| magnetic_field | time, component | nT |" in fgm_guide.to_markdown()
    assert "b, fgm" in fgm_guide.to_markdown()
    assert "| ion_energy_flux | time, energy_bin | eV/(cm^2 s sr eV) |" in (
        esa_guide.to_markdown()
    )
    assert art.help() == mission_guide
    assert art.p1.help() == mission_guide
    assert art.p1.fgm.help() == fgm_guide
    assert art.p1.fgm.magnetic_field.help() == variable_guide
    assert variable_guide.source == "sopran.missions.artemis/README.ja.md"
    assert mission_guide.url == "https://nkzono99.github.io/sopran/data/artemis/"
    assert fgm_guide.url == mission_guide.url
    assert variable_guide.url == mission_guide.url


def test_artemis_examples_return_markdown_pages() -> None:
    art = spn.Artemis()

    mission_example = art.example().to_markdown()
    fgm_example = art.p1.fgm.example().to_markdown()
    esa_example = art.p1.esa.example().to_markdown()
    variable_example = art.p1.esa.ion_energy_flux.example().to_markdown()

    assert "ARTEMIS Example" in mission_example
    assert "spn.artemis" in mission_example
    assert "ARTEMIS P1 FGM Example" in fgm_example
    assert "magnetic_field" in fgm_example
    assert "ARTEMIS P1 ESA Example" in esa_example
    assert "ion_energy_flux" in esa_example
    assert "ARTEMIS P1 ESA ion_energy_flux Example" in variable_example
    assert "spectrogram" in variable_example


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
        "https://nkzono99.github.io/sopran/en/data/artemis/"
    )
    assert "ARTEMISは" in mission_ja.to_markdown()
    assert "in lunar orbit" in mission_en.to_markdown()
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


def _write_cdf(path, variables) -> None:
    from cdflib.cdfwrite import CDF as CdfWriter

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = CdfWriter(str(path), cdf_spec={"Compressed": False})
    for name, (data_type, values, attrs) in variables.items():
        array = np.asarray(values)
        writer.write_var(
            {
                "Variable": name,
                "Data_Type": data_type,
                "Num_Elements": 1,
                "Rec_Vary": True,
                "Dim_Sizes": list(array.shape[1:]),
            },
            var_attrs=attrs,
            var_data=array,
        )
    writer.close()


def _unix(text: str) -> float:
    return float(np.datetime64(text, "ns").astype("int64")) / 1e9


def _write_artemis_day(store: spn.Store, day: str = "2011-07-01", *, version: int = 1) -> None:
    from cdflib.cdfwrite import CDF as CdfWriter

    stamp = day.replace("-", "")
    times = np.array([_unix(f"{day}T00:00:00"), _unix(f"{day}T00:00:00.5"), _unix(f"{day}T12:00")])
    fgm_dir = store.raw_path("artemis", "themis", "thb", "l2", "fgm", day[:4])
    _write_cdf(
        fgm_dir / f"thb_l2_fgm_{stamp}_v{version:02d}.cdf",
        {
            "thb_fgs_time": (CdfWriter.CDF_DOUBLE, times, {"UNITS": "sec"}),
            "thb_fgs_gse": (
                CdfWriter.CDF_FLOAT,
                np.array([[1, 2, 3], [-1e30, -1e30, -1e30], [4, 5, 6]], dtype=np.float32),
                {"FILLVAL": np.float32(-1e30), "UNITS": "nT GSE"},
            ),
        },
    )
    energy = np.array([[3000.0, 300.0], [3100.0, 310.0], [3200.0, np.nan]], dtype=np.float32)
    flux = np.array([[10.0, 30.0], [11.0, 31.0], [12.0, np.nan]])
    esa = {}
    for species in ("i", "e"):
        prefix = f"thb_pe{species}r"
        scale = 1.0 if species == "i" else 100.0
        esa[f"{prefix}_time"] = (CdfWriter.CDF_DOUBLE, times, {})
        esa[f"{prefix}_en_eflux"] = (CdfWriter.CDF_DOUBLE, flux * scale, {"FILLVAL": np.nan})
        esa[f"{prefix}_en_eflux_yaxis"] = (CdfWriter.CDF_FLOAT, energy, {})
        esa[f"{prefix}_density"] = (CdfWriter.CDF_DOUBLE, np.array([4.0, 4.5, 5.0]) * scale, {})
        esa[f"{prefix}_velocity_gse"] = (
            CdfWriter.CDF_DOUBLE,
            np.array([[-400.0, 10.0, 5.0], [-410.0, 11.0, 6.0], [np.nan] * 3]),
            {},
        )
    esa["thb_peif_time"] = (CdfWriter.CDF_DOUBLE, times[:1], {})
    esa["thb_peif_en_eflux"] = (CdfWriter.CDF_DOUBLE, flux[:1] * 2, {})
    esa["thb_peif_en_eflux_yaxis"] = (CdfWriter.CDF_FLOAT, energy[:1], {})
    esa_dir = store.raw_path("artemis", "themis", "thb", "l2", "esa", day[:4])
    _write_cdf(esa_dir / f"thb_l2_esa_{stamp}_v{version:02d}.cdf", esa)


def _project_case(tmp_path, store: spn.Store):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[defaults]
download = "never"

[cases.wake]
start = "2011-07-01T00:00:00"
stop = "2011-07-02T00:00:00"
""".strip(),
        encoding="utf-8",
    )
    return spn.Project(project_root, store=store).case("wake")


def test_artemis_load_reads_fgm_field_in_gse_from_the_level2_file(tmp_path) -> None:
    store = spn.Store(tmp_path / "store")
    _write_artemis_day(store)

    magnetic_field = spn.Artemis(store=store, download="never").p1.fgm.magnetic_field.load(
        spn.day("2011-07-01")
    )
    array = magnetic_field.to_xarray()

    assert magnetic_field.name == "magnetic_field"
    assert array.dims == ("time", "component")
    assert array.attrs["frame"] == "GSE" and array.attrs["spacecraft"] == "thb"
    assert array.coords["component"].values.tolist() == ["x", "y", "z"]
    np.testing.assert_array_equal(array.values[0], [1.0, 2.0, 3.0])
    assert np.isnan(array.values[1]).all()  # FILLVAL -1e30 becomes NaN
    assert magnetic_field.files[0].name == "thb_l2_fgm_20110701_v01.cdf"


def test_artemis_load_keeps_the_half_open_time_range(tmp_path) -> None:
    store = spn.Store(tmp_path / "store")
    _write_artemis_day(store)

    magnetic_field = spn.Artemis(store=store, download="never").p1.fgm.magnetic_field.load(
        spn.period("2011-07-01T00:00:00Z", "2011-07-01T00:00:00.5Z")
    )

    assert magnetic_field.to_xarray().values.tolist() == [[1.0, 2.0, 3.0]]


def test_artemis_esa_energy_flux_keeps_the_per_record_energy_table(tmp_path) -> None:
    store = spn.Store(tmp_path / "store")
    _write_artemis_day(store)
    esa = spn.Artemis(store=store, download="never").p1.esa
    time = spn.day("2011-07-01")

    ion = esa.ion_energy_flux.load(time).to_xarray()
    electron = esa.electron_energy_flux.load(time).to_xarray()
    full = esa.ion_energy_flux.load(time, mode="full").to_xarray()

    assert ion.dims == ("time", "energy_bin")
    assert ion.coords["energy"].dims == ("time", "energy_bin")
    assert ion.coords["energy"].attrs["units"] == "eV"
    np.testing.assert_allclose(ion.coords["energy"].values[1], [3100.0, 310.0])
    np.testing.assert_allclose(ion.values[0], [10.0, 30.0])
    np.testing.assert_allclose(electron.values[0], [1000.0, 3000.0])
    assert ion.attrs["esa_mode"] == "reduced" and full.shape == (1, 2)


def test_artemis_esa_moments_load_with_units_and_frame(tmp_path) -> None:
    store = spn.Store(tmp_path / "store")
    _write_artemis_day(store)
    esa = spn.Artemis(store=store, download="never").p1.esa
    time = spn.day("2011-07-01")

    density = esa.ion_density.load(time)
    velocity = esa.ion_velocity.load(time).to_xarray()

    assert density.schema.units == "cm^-3"
    np.testing.assert_allclose(density.to_xarray().values, [4.0, 4.5, 5.0])
    assert velocity.attrs["frame"] == "GSE"
    np.testing.assert_allclose(velocity.values[0], [-400.0, 10.0, 5.0])
    np.testing.assert_allclose(esa.electron_density.load(time).to_xarray().values[0], 400.0)


def test_artemis_esa_endpoint_builds_spectrogram_plot_item(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    store = spn.Store(tmp_path / "store")
    _write_artemis_day(store)

    item = spn.Artemis(store=store, download="never").p1.esa.ion_energy_flux.spectrogram(
        spn.day("2011-07-01")
    )
    result = spn.stack(item).plot()

    assert item.kind == "spectrogram" and item.y == "energy"
    assert item.log_color is True and item.yscale == "log"
    assert result.axes[0].get_ylabel() == "energy [eV]"


def test_artemis_variable_endpoint_builds_line_plot_items(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    store = spn.Store(tmp_path / "store")
    _write_artemis_day(store)
    endpoint = spn.Artemis(store=store, download="never").p1.fgm.magnetic_field
    time = spn.day("2011-07-01")

    every = spn.stack(endpoint.line(time)).plot()
    some = spn.stack(endpoint.lines(time, components="xz")).plot()

    assert len(every.axes[0].lines) == 3
    assert len(some.axes[0].lines) == 2


def test_artemis_missing_days_follow_the_missing_option(tmp_path) -> None:
    art = spn.Artemis(store=spn.Store(tmp_path / "store"), download="never")
    time = spn.day("2011-07-01")

    empty = art.p1.fgm.magnetic_field.load(time)
    with pytest.warns(UserWarning, match="download='never'"):
        art.p1.fgm.magnetic_field.load(time, missing="warn")
    with pytest.raises(spn.DatasetNotFoundError, match="ARTEMIS P1 FGM"):
        art.p1.fgm.magnetic_field.load(time, missing="error")

    assert empty.to_xarray().shape == (0, 3)
    assert empty.files == ()


class _Response(BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = Message()
        self.headers["Content-Length"] = str(len(payload))

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def test_artemis_downloads_the_newest_version_and_registers_it(tmp_path, monkeypatch) -> None:
    from sopran.missions.artemis import cdaweb

    source_store = spn.Store(tmp_path / "source")
    _write_artemis_day(source_store, version=2)
    cdf_bytes = next(
        source_store.raw_path("artemis", "themis", "thb", "l2", "fgm", "2011").iterdir()
    ).read_bytes()
    listing = (
        b'<a href="thb_l2_fgm_20110701_v01.cdf">v1</a>'
        b'<a href="thb_l2_fgm_20110701_v02.cdf">v2</a>'
        b'<a href="thb_l2_fgm_20110702_v01.cdf">next day</a>'
    )
    urls: list[str] = []

    def fake_urlopen(url: str, timeout: float) -> _Response:
        urls.append(url)
        return _Response(listing if url.endswith("/") else cdf_bytes)

    monkeypatch.setattr(cdaweb, "urlopen", fake_urlopen)
    store = spn.Store(tmp_path / "store")
    endpoint = spn.Artemis(store=store, download="missing").p1.fgm.magnetic_field

    loaded = endpoint.load(spn.day("2011-07-01"))
    again = endpoint.load(spn.day("2011-07-01"))

    base = "https://spdf.gsfc.nasa.gov/pub/data/themis/thb/l2/fgm/2011/"
    assert urls == [base, base + "thb_l2_fgm_20110701_v02.cdf"]
    assert loaded.files[0].name == "thb_l2_fgm_20110701_v02.cdf"
    assert again.files == loaded.files
    registered = store.raw_files(mission="artemis", provider="nasa-spdf")
    assert registered.height == 1


def test_top_level_load_reads_artemis_files_from_the_store(tmp_path) -> None:
    store = spn.Store(tmp_path / "store")
    _write_artemis_day(store)

    magnetic_field = spn.load(
        "artemis.p1.fgm.magnetic_field", spn.day("2011-07-01"), store=store, download="never"
    )
    ion_flux = spn.load(
        "artemis.p1.esa.ion_energy_flux", spn.day("2011-07-01"), store=store, download="never"
    )

    assert magnetic_field.to_xarray().shape == (3, 3)
    assert ion_flux.to_xarray().shape == (3, 2)


def test_project_case_artemis_uses_the_project_store_and_policy(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    store = spn.Store(tmp_path / "store")
    _write_artemis_day(store)
    case = _project_case(tmp_path, store)

    assert case.artemis.download == "never"
    magnetic_field = case.artemis.p1.fgm.magnetic_field.load()
    stack = case.stack(
        case.artemis.p1.fgm.magnetic_field.lines(components="xz"),
        case.artemis.p1.esa.ion_energy_flux.spectrogram(),
    )

    assert magnetic_field.to_xarray().shape == (3, 3)
    assert stack.plan().items == ("magnetic_field", "ion_energy_flux")
    assert len(stack.plot().axes) == 2


def test_project_case_supplies_time_to_artemis_endpoint(tmp_path) -> None:
    case = _project_case(tmp_path, spn.Store(tmp_path / "store"))
    plan = case.artemis.p1.fgm.magnetic_field.plan()

    assert plan.dataset_id == "artemis.p1.fgm.magnetic_field"
    assert plan.time == case.time
    assert plan.remote_directories == (
        "https://spdf.gsfc.nasa.gov/pub/data/themis/thb/l2/fgm/2011/",
    )


def test_top_level_load_dispatches_artemis_dataset_id(tmp_path) -> None:
    with pytest.raises(spn.DatasetNotFoundError, match="ARTEMIS P1 FGM"):
        spn.load(
            "artemis.p1.fgm.magnetic_field",
            spn.day("2011-07-01"),
            store=spn.Store(tmp_path / "store"),
            download="never",
            missing="error",
        )
