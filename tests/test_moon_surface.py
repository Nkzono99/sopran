from __future__ import annotations

import pytest

import sopran as spn


def test_moon_surface_endpoints_plan_body_first_products() -> None:
    moon = spn.Moon()
    region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")

    normalized = region.to_lon_domain("-180_180")
    dem_plan = moon.dem.plan(
        source="kaguya.tc.dem",
        region=normalized,
        resolution="512ppd",
    )
    shadow_plan = moon.shadow.plan(
        time="2008-02-01T12:00:00Z",
        dem=dem_plan,
    )

    assert normalized.lon == (-10.0, 10.0)
    assert dem_plan.body == "moon"
    assert dem_plan.product == "dem"
    assert dem_plan.parameters["source"] == "kaguya.tc.dem"
    assert dem_plan.parameters["resolution"] == "512ppd"
    assert shadow_plan.product == "shadow"
    assert "Moon" in str(moon.info())
    assert "DEM" in str(moon.dem.info())


def test_moon_surface_endpoints_list_stable_source_ids() -> None:
    moon = spn.Moon()

    assert "kaguya.tc.dem" in moon.dem.sources()
    assert "lro.lola.dem" in moon.dem.sources()
    assert moon.svm.sources() == ("kaguya.lism.svm",)
    assert "legacy.shadowmap_sza" in moon.shadow.sources()


def test_moon_map_returns_surface_endpoint_by_name() -> None:
    moon = spn.Moon()

    assert moon.map("svm") is moon.svm
    assert moon.map("dem") is moon.dem
    with pytest.raises(ValueError, match="Unknown Moon surface product"):
        moon.map("unknown")


def test_surface_plan_exports_json_ready_metadata() -> None:
    moon = spn.Moon()
    region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon").to_lon_domain(
        "-180_180"
    )
    dem_plan = moon.dem.plan(
        source="kaguya.tc.dem",
        region=region,
        resolution="512ppd",
    )
    shadow_plan = moon.shadow.plan(
        time="2008-02-01T12:00:00Z",
        dem=dem_plan,
        model="sphere",
    )

    assert shadow_plan.to_metadata() == {
        "body": "moon",
        "product": "shadow",
        "parameters": {
            "time": "2008-02-01T12:00:00Z",
            "dem": {
                "body": "moon",
                "product": "dem",
                "parameters": {
                    "source": "kaguya.tc.dem",
                    "region": {
                        "body": "moon",
                        "lon": [-10.0, 10.0],
                        "lat": [-5.0, 5.0],
                        "lon_domain": "-180_180",
                    },
                    "resolution": "512ppd",
                },
            },
            "model": "sphere",
        },
    }


def test_moon_surface_guides_return_markdown_pages() -> None:
    moon = spn.Moon()

    assert "# Moon Surface Products" in moon.guide().to_markdown()
    assert "DEM" in moon.dem.guide().to_markdown()
    assert moon.help() == moon.guide()
    assert moon.dem.help() == moon.dem.guide()


def test_moon_surface_guides_can_switch_language() -> None:
    moon = spn.Moon()

    moon_ja = moon.guide(language="ja")
    moon_en = moon.guide(language="en")
    dem_ja = moon.dem.guide(language="ja")
    shadow_ja = moon.shadow.guide(language="ja")

    assert moon_ja.language == "ja"
    assert moon_en.language == "en"
    assert moon_ja.available_languages == ("ja", "en")
    assert moon_ja.language_switcher() == "Lang: 日本語/English"
    assert "月面プロダクト" in moon_ja.to_markdown()
    assert "Moon Surface Products" in moon_en.to_markdown()
    assert "DEM" in dem_ja.to_markdown()
    assert "shadow" in shadow_ja.to_markdown().lower()
    assert moon.help(language="ja") == moon_ja
    assert moon.dem.help(language="ja") == dem_ja
    with pytest.raises(ValueError, match="language"):
        moon.guide(language="fr")
