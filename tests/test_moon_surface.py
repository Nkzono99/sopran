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
    sza_plan = moon.sza.plan(
        time="2008-02-01T12:00:00Z",
        region=normalized,
        geometry_source="spice",
    )

    assert normalized.lon == (-10.0, 10.0)
    assert dem_plan.body == "moon"
    assert dem_plan.product == "dem"
    assert dem_plan.parameters["source"] == "kaguya.tc.dem"
    assert dem_plan.parameters["resolution"] == "512ppd"
    assert dem_plan.parameters["projection"] == "native"
    assert dem_plan.parameters["area_or_point"] == "area"
    assert dem_plan.parameters["shape"] == "spherical"
    assert shadow_plan.product == "shadow"
    assert sza_plan.product == "sza"
    assert sza_plan.parameters["geometry"] == "spice"
    assert sza_plan.parameters["geometry_source"] == "spice"
    assert "Moon" in str(moon.info())
    assert "DEM" in str(moon.dem.info())


def test_moon_surface_endpoints_list_stable_source_ids() -> None:
    moon = spn.Moon()

    assert "kaguya.tc.dem" in moon.dem.sources()
    assert "lro.lola.dem" in moon.dem.sources()
    assert moon.svm.sources() == ("kaguya.lism.svm",)
    assert "legacy.shadowmap_sza" in moon.shadow.sources()
    assert moon.sza.sources() == ("computed.spice.sza",)


def test_moon_sza_plan_normalizes_geometry_source_alias() -> None:
    moon = spn.Moon()

    plan = moon.sza.plan(time="2008-02-01T12:00:00Z", geometry_source="naif_spice")

    assert plan.parameters["geometry_source"] == "naif_spice"
    assert plan.parameters["geometry"] == "naif_spice"


def test_surface_plan_normalizes_geometry_aliases_when_provided() -> None:
    moon = spn.Moon()

    illumination = moon.illumination.plan(
        time="2008-02-01T12:00:00Z",
        geometry_source="naif_spice",
    )
    shadow = moon.shadow.plan(
        time="2008-02-01T12:00:00Z",
        geometry="spice",
    )

    assert illumination.parameters["geometry_source"] == "naif_spice"
    assert illumination.parameters["geometry"] == "naif_spice"
    assert shadow.parameters["geometry_source"] == "spice"
    assert shadow.parameters["geometry"] == "spice"


def test_surface_plan_normalizes_ephemeris_as_geometry_source() -> None:
    moon = spn.Moon()

    plan = moon.sza.plan(time="2008-02-01T12:00:00Z", ephemeris="kaguya.spice")

    assert plan.parameters["ephemeris"] == "kaguya.spice"
    assert plan.parameters["geometry_source"] == "kaguya.spice"
    assert plan.parameters["geometry"] == "kaguya.spice"


def test_moon_map_returns_surface_endpoint_by_name() -> None:
    moon = spn.Moon()

    assert moon.map("svm") is moon.svm
    assert moon.map("dem") is moon.dem
    assert moon.map("sza") is moon.sza
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
                        "lon_direction": "east_positive",
                        "lat_type": "planetocentric",
                    },
                    "resolution": "512ppd",
                    "lon_domain": "-180_180",
                    "lon_direction": "east_positive",
                    "lat_type": "planetocentric",
                    "shape": "spherical",
                    "projection": "native",
                    "area_or_point": "area",
                },
            },
            "model": "sphere",
            "lon_domain": "-180_180",
            "lon_direction": "east_positive",
            "lat_type": "planetocentric",
            "shape": "spherical",
            "projection": "native",
            "area_or_point": "area",
        },
    }


def test_moon_surface_guides_return_markdown_pages() -> None:
    moon = spn.Moon()

    assert moon.guide().language == "ja"
    assert "月面プロダクト" in moon.guide().to_markdown()
    assert "DEM" in moon.dem.guide().to_markdown()
    assert moon.guide().url == "https://nkzono99.github.io/sopran/surface/moon/"
    assert moon.dem.guide().url == moon.guide().url
    assert moon.help() == moon.guide()
    assert moon.dem.help() == moon.dem.guide()


def test_moon_surface_endpoints_expose_schema_objects() -> None:
    moon = spn.Moon()

    schema = moon.schema()
    dem_schema = moon.dem.schema()
    shadow_schema = moon.shadow.schema()
    sza_schema = moon.sza.schema()

    assert schema.mission == "moon"
    assert schema.instrument == "surface"
    assert schema.variable("dem") == dem_schema
    assert schema.variable("shadow_map") == shadow_schema
    assert schema.variable("solar_zenith_angle") == sza_schema
    assert dem_schema.dims == ("lat", "lon")
    assert dem_schema.units == "m"
    assert dem_schema.frame == "Moon body-fixed"
    assert "terrain-aware" in shadow_schema.description
    assert sza_schema.units == "deg"


def test_moon_surface_examples_return_markdown_pages() -> None:
    moon = spn.Moon()

    mission_example = moon.example().to_markdown()
    dem_example = moon.dem.example().to_markdown()
    shadow_example = moon.shadow.example().to_markdown()
    sza_example = moon.sza.example().to_markdown()

    assert "Moon Surface Example" in mission_example
    assert "spn.Moon" in mission_example
    assert "spn.Region" in mission_example
    assert "Moon DEM Example" in dem_example
    assert "kaguya.tc.dem" in dem_example
    assert "Moon Shadow Example" in shadow_example
    assert "moon.shadow.plan" in shadow_example
    assert "Moon Solar Zenith Angle Example" in sza_example
    assert "geometry_source" in sza_example


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
    assert moon_ja.with_language("en").url == (
        "https://nkzono99.github.io/sopran/surface/moon/"
    )
    assert "月面プロダクト" in moon_ja.to_markdown()
    assert "Moon Surface Products" in moon_en.to_markdown()
    assert "DEM" in dem_ja.to_markdown()
    assert "shadow" in shadow_ja.to_markdown().lower()
    assert moon.help(language="ja") == moon_ja
    assert moon.dem.help(language="ja") == dem_ja
    with pytest.raises(ValueError, match="language"):
        moon.guide(language="fr")


def test_moon_surface_plan_normalizes_projection_metadata() -> None:
    moon = spn.Moon()

    plan = moon.dem.plan(
        source="kaguya.tc.dem",
        projection="polar_stereo",
        area_or_point="point",
    )

    assert plan.parameters["projection"] == "polar_stereographic"
    assert plan.parameters["area_or_point"] == "point"
    assert plan.to_metadata()["parameters"]["projection"] == "polar_stereographic"
    with pytest.raises(ValueError, match="projection"):
        moon.dem.plan(source="kaguya.tc.dem", projection="unknown")
    with pytest.raises(ValueError, match="area_or_point"):
        moon.dem.plan(source="kaguya.tc.dem", area_or_point="cell")


def test_surface_plan_records_coordinate_conventions_from_region_and_dem() -> None:
    moon = spn.Moon()
    region = spn.Region(
        lon=(120, 160),
        lat=(-45, -10),
        body="moon",
        lon_domain="-180_180",
        lon_direction="west_positive",
        lat_type="planetographic",
    )

    dem_plan = moon.dem.plan(source="kaguya.tc.dem", region=region)
    shadow_plan = moon.shadow.plan(time="2008-02-01T12:00:00Z", dem=dem_plan)

    assert dem_plan.parameters["lon_domain"] == "-180_180"
    assert dem_plan.parameters["lon_direction"] == "west_positive"
    assert dem_plan.parameters["lat_type"] == "planetographic"
    assert shadow_plan.parameters["lon_domain"] == "-180_180"
    assert shadow_plan.parameters["lon_direction"] == "west_positive"
    assert shadow_plan.parameters["lat_type"] == "planetographic"


def test_surface_plan_normalizes_coordinate_convention_aliases() -> None:
    moon = spn.Moon()

    plan = moon.dem.plan(
        source="kaguya.tc.dem",
        lon_domain="minus180_180",
        lon_direction="east_positive",
        lat_type="planetocentric",
    )

    assert plan.parameters["lon_domain"] == "-180_180"
    assert plan.parameters["lon_direction"] == "east_positive"
    assert plan.parameters["lat_type"] == "planetocentric"
    with pytest.raises(ValueError, match="lon_domain"):
        moon.dem.plan(source="kaguya.tc.dem", lon_domain="west_360")
    with pytest.raises(ValueError, match="lon_direction"):
        moon.dem.plan(source="kaguya.tc.dem", lon_direction="north_positive")
    with pytest.raises(ValueError, match="lat_type"):
        moon.dem.plan(source="kaguya.tc.dem", lat_type="geodetic")


def test_surface_plan_records_shape_and_inherits_datum_from_dem() -> None:
    moon = spn.Moon()

    dem_plan = moon.dem.plan(
        source="kaguya.tc.dem",
        shape="sphere",
        datum="mean_radius",
    )
    shadow_plan = moon.shadow.plan(time="2008-02-01T12:00:00Z", dem=dem_plan)

    assert dem_plan.parameters["shape"] == "spherical"
    assert dem_plan.parameters["datum"] == "mean_radius"
    assert shadow_plan.parameters["shape"] == "spherical"
    assert shadow_plan.parameters["datum"] == "mean_radius"


def test_surface_plan_inherits_projection_and_area_from_dem() -> None:
    moon = spn.Moon()

    dem_plan = moon.dem.plan(
        source="kaguya.tc.dem",
        projection="polar_stereo",
        area_or_point="point",
    )
    shadow_plan = moon.shadow.plan(time="2008-02-01T12:00:00Z", dem=dem_plan)
    illumination_plan = moon.illumination.plan(
        time="2008-02-01T12:00:00Z",
        dem=dem_plan,
        projection="orthographic",
    )

    assert shadow_plan.parameters["projection"] == "polar_stereographic"
    assert shadow_plan.parameters["area_or_point"] == "point"
    assert illumination_plan.parameters["projection"] == "orthographic"
    assert illumination_plan.parameters["area_or_point"] == "point"


def test_surface_plan_rejects_unknown_shape_model() -> None:
    moon = spn.Moon()

    with pytest.raises(ValueError, match="shape"):
        moon.dem.plan(source="kaguya.tc.dem", shape="flat")
