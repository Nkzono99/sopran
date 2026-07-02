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
