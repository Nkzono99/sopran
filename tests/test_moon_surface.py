from __future__ import annotations

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


def test_moon_surface_guides_return_markdown_pages() -> None:
    moon = spn.Moon()

    assert "# Moon Surface Products" in moon.guide().to_markdown()
    assert "DEM" in moon.dem.guide().to_markdown()
    assert moon.help() == moon.guide()
    assert moon.dem.help() == moon.dem.guide()
