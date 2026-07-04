from __future__ import annotations

import json

import numpy as np
import pytest

import sopran as spn
from sopran.core import BackendError, DownloadError


def test_moon_svm_default_is_tsunakawa2015_endpoint() -> None:
    moon = spn.Moon()

    assert moon.svm is moon.svm_tsunakawa2015
    assert moon.map("svm") is moon.svm_tsunakawa2015
    assert moon.map("svm_tsunakawa2015") is moon.svm_tsunakawa2015

    plan = moon.svm.plan()

    assert plan.product == "svm"
    assert plan.parameters["source"] == "kaguya.lmag.svm_tsunakawa2015"
    assert plan.parameters["model"] == "tsunakawa2015"
    assert moon.svm.schema().units == "nT"
    assert moon.svm.schema().dtype == "float64"


def test_moon_dem_loads_geotiff_with_rasterio(tmp_path) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    path = tmp_path / "dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        transform=from_origin(10.0, 2.0, 1.0, 1.0),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(np.array([[1.0, 2.0], [3.0, 4.0]], dtype="float32"), 1)

    layer = spn.Moon().dem.load(path=path, source="local.dem")

    assert layer.product == "dem"
    assert layer.units == "m"
    assert layer.source == "local.dem"
    assert layer.lon.tolist() == [10.5, 11.5]
    assert layer.lat.tolist() == [1.5, 0.5]
    assert layer.sample(lat=1.5, lon=10.5) == pytest.approx(1.0)
    assert layer.sample(lat=0.5, lon=11.5) == pytest.approx(4.0)


def test_raster_layer_sample_normalizes_longitude_domain() -> None:
    positive = spn.RasterLayer(
        [[1.0, 2.0], [3.0, 4.0]],
        lon=[350.0, 10.0],
        lat=[-1.0, 1.0],
        product="dem",
        variable="elevation",
        source="synthetic",
    )
    minus180 = spn.RasterLayer(
        [[1.0, 2.0], [3.0, 4.0]],
        lon=[-10.0, 10.0],
        lat=[-1.0, 1.0],
        product="dem",
        variable="elevation",
        source="synthetic",
    )

    assert positive.sample(lat=-1.0, lon=-10.0) == pytest.approx(1.0)
    assert minus180.sample(lat=-1.0, lon=350.0) == pytest.approx(1.0)


def test_moon_dem_loads_geotiff_window_for_region(tmp_path) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    path = tmp_path / "dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        transform=from_origin(10.0, 4.0, 1.0, 1.0),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(
            np.array(
                [
                    [1.0, 2.0, 3.0, 4.0],
                    [5.0, 6.0, 7.0, 8.0],
                    [9.0, 10.0, 11.0, 12.0],
                    [13.0, 14.0, 15.0, 16.0],
                ],
                dtype="float32",
            ),
            1,
        )

    region = spn.Region(lon=(11.0, 13.0), lat=(1.0, 3.0), body="moon")

    layer = spn.Moon().dem.load(path=path, source="local.dem", region=region)

    assert layer.shape == (2, 2)
    assert layer.values.tolist() == [[6.0, 7.0], [10.0, 11.0]]
    assert layer.lon.tolist() == [11.5, 12.5]
    assert layer.lat.tolist() == [2.5, 1.5]
    assert layer.metadata["windowed"] is True
    assert layer.metadata["source_width"] == 4
    assert layer.metadata["source_height"] == 4
    assert layer.metadata["width"] == 2
    assert layer.metadata["height"] == 2
    assert layer.metadata["window"] == {
        "col_off": 1,
        "row_off": 1,
        "width": 2,
        "height": 2,
    }


def test_moon_dem_window_converts_region_to_raster_lon_domain(tmp_path) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    path = tmp_path / "minus180_dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=4,
        count=1,
        dtype="float32",
        transform=from_origin(-180.0, 2.0, 1.0, 1.0),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(
            np.array([[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]], dtype="float32"),
            1,
        )

    region = spn.Region(
        lon=(181.0, 183.0),
        lat=(0.0, 2.0),
        body="moon",
        lon_domain="0_360",
    )

    layer = spn.Moon().dem.load(path=path, source="local.dem", region=region)

    assert layer.shape == (2, 2)
    assert layer.values.tolist() == [[2.0, 3.0], [6.0, 7.0]]
    assert layer.lon.tolist() == [-178.5, -177.5]
    assert layer.metadata["windowed"] is True


def test_moon_lro_lola_dem_source_applies_catalog_scale_when_geotiff_has_none(
    tmp_path,
) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    path = tmp_path / "lola_dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=1,
        width=1,
        count=1,
        dtype="int16",
        transform=from_origin(0.0, 1.0, 1.0, 1.0),
    ) as dataset:
        dataset.write(np.array([[2]], dtype="int16"), 1)

    layer = spn.Moon().dem.load(path=path, source="lro.lola.dem_118m")

    assert layer.sample(lat=0.5, lon=0.5) == pytest.approx(1.0)


def test_moon_dem_load_guides_to_rasterio_when_backend_is_missing(
    tmp_path, monkeypatch
) -> None:
    import sopran.maps.raster as raster

    real_import_module = raster.importlib.import_module

    def missing_rasterio(name):
        if name == "rasterio":
            raise ModuleNotFoundError("No module named 'rasterio'")
        return real_import_module(name)

    monkeypatch.setattr(raster.importlib, "import_module", missing_rasterio)

    with pytest.raises(BackendError, match=r"rasterio.*pip install -e"):
        spn.Moon().dem.load(path=tmp_path / "missing.tif")


def test_moon_svm_tsunakawa2015_loads_text_grid(tmp_path) -> None:
    path = tmp_path / "LunarSVM_000_02_v02.dat"
    path.write_text(
        "\n".join(
            [
                *(f"# header {index}" for index in range(12)),
                "0.0 -0.5 0 0 0 1.0",
                "1.0 -0.5 0 0 0 2.0",
                "0.0 0.5 0 0 0 3.0",
                "1.0 0.5 0 0 0 4.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    layer = spn.Moon().svm_tsunakawa2015.load(path=path)

    assert layer.product == "svm"
    assert layer.variable == "svm_tsunakawa2015"
    assert layer.units == "nT"
    assert layer.source == "kaguya.lmag.svm_tsunakawa2015"
    assert layer.lon.tolist() == [0.0, 1.0]
    assert layer.lat.tolist() == [-0.5, 0.5]
    assert layer.sample(lat=-0.5, lon=0.0) == pytest.approx(1.0)
    assert layer.sample(lat=0.5, lon=1.0) == pytest.approx(4.0)


def test_moon_dem_download_registers_raw_file(tmp_path, monkeypatch) -> None:
    import sopran.bodies.moon as moon_module

    store = spn.Store(tmp_path / "store")
    calls = []

    def fake_download_file(url, target, *, overwrite=False):
        calls.append((url, target, overwrite))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"downloaded")

    monkeypatch.setattr(moon_module, "_download_file", fake_download_file)

    path = spn.Moon().dem.download(source="lro.lola.dem_118m", store=store)

    assert path == store.raw_path(
        "moon", "dem", "Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif"
    )
    assert calls == [
        (
            "https://planetarymaps.usgs.gov/mosaic/Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif",
            path,
            False,
        )
    ]
    manifest = json.loads(path.with_name(f"{path.name}.sopran.json").read_text())
    assert manifest["provider"] == "usgs_astrogeology"
    assert manifest["download_url"] == calls[0][0]


def test_moon_download_file_removes_partial_file_on_failure(tmp_path, monkeypatch) -> None:
    import sopran.bodies.moon as moon_module

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_copyfileobj(response, output):
        output.write(b"partial")
        raise OSError("network interrupted")

    monkeypatch.setattr(moon_module.urllib.request, "urlopen", lambda url: FakeResponse())
    monkeypatch.setattr(moon_module.shutil, "copyfileobj", fake_copyfileobj)
    target = tmp_path / "moon" / "dem.tif"

    with pytest.raises(OSError, match="network interrupted"):
        moon_module._download_file("https://example.invalid/dem.tif", target)

    assert not target.exists()
    assert list(target.parent.glob(f"{target.name}.*.tmp")) == []


def test_moon_download_file_overwrite_failure_preserves_existing_file(
    tmp_path,
    monkeypatch,
) -> None:
    import sopran.bodies.moon as moon_module

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_copyfileobj(response, output):
        output.write(b"partial")
        raise OSError("network interrupted")

    monkeypatch.setattr(moon_module.urllib.request, "urlopen", lambda url: FakeResponse())
    monkeypatch.setattr(moon_module.shutil, "copyfileobj", fake_copyfileobj)
    target = tmp_path / "moon" / "dem.tif"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing")

    with pytest.raises(OSError, match="network interrupted"):
        moon_module._download_file(
            "https://example.invalid/dem.tif",
            target,
            overwrite=True,
        )

    assert target.read_bytes() == b"existing"
    assert list(target.parent.glob(f"{target.name}.*.tmp")) == []


def test_moon_svm_download_requires_manual_acquisition(tmp_path) -> None:
    store = spn.Store(tmp_path / "store")
    moon = spn.Moon()

    with pytest.raises(DownloadError, match="LunarSVM_000_02_v02.dat"):
        moon.svm.download(store=store)

    guide = moon.svm.acquisition_guide().to_markdown()

    assert "LunarSVM_000_02_v02.dat" in guide
    assert "Tsunakawa" in guide
    assert "http://www.geo.titech.ac.jp/lab/tsunakawa/Kaguya_LMAG" in guide
    assert "web.archive.org" not in guide


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


def test_moon_surface_info_includes_schema_and_sources() -> None:
    moon = spn.Moon()

    mission_info = str(moon.info())
    dem_info = str(moon.dem.info())
    shadow_info = str(moon.shadow.info())
    sza_info = str(moon.sza.info())

    assert "schema: dem, svm, shadow, illumination, sza" in mission_info
    assert "sources: lro.lola.dem_118m" in dem_info
    assert "dims: lat, lon" in dem_info
    assert "units: m" in dem_info
    assert "frame: Moon body-fixed" in dem_info
    assert "aliases: elevation, height" in dem_info
    assert "sources: legacy.shadowmap_sza" in shadow_info
    assert "aliases: shadow_map, shadow_fraction" in shadow_info
    assert "sources: computed.spice.sza" in sza_info
    assert "units: deg" in sza_info


def test_moon_surface_endpoints_list_stable_source_ids() -> None:
    moon = spn.Moon()

    assert "kaguya.tc.dem" in moon.dem.sources()
    assert "lro.lola.dem" in moon.dem.sources()
    assert "kaguya.lmag.svm_tsunakawa2015" in moon.svm.sources()
    assert "kaguya.lism.svm" in moon.svm.sources()
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


def test_surface_plan_normalizes_shadow_method_model_aliases() -> None:
    moon = spn.Moon()

    shadow = moon.shadow.plan(
        time="2008-02-01T12:00:00Z",
        method="terrain_ray",
    )
    illumination = moon.illumination.plan(
        time="2008-02-01T12:00:00Z",
        model="local_slope",
    )

    assert shadow.parameters["method"] == "terrain_ray"
    assert shadow.parameters["model"] == "terrain_ray"
    assert illumination.parameters["method"] == "local_slope"
    assert illumination.parameters["model"] == "local_slope"


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
    assert moon.map("elevation") is moon.dem
    assert moon.map("height") is moon.dem
    assert moon.map("shadow_map") is moon.shadow
    assert moon.map("shadow_fraction") is moon.shadow
    assert moon.map("solar_zenith_angle") is moon.sza
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
            "method": "sphere",
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
    assert "月面マップ" in moon.guide().to_markdown()
    assert "DEM" in moon.dem.guide().to_markdown()
    assert "| name | dims | units | dtype | frame | aliases | description |" in (
        moon.guide().to_markdown()
    )
    assert "| dem | lat, lon | m | float64 | Moon body-fixed |" in (
        moon.dem.guide().to_markdown()
    )
    assert moon.guide().url == "https://nkzono99.github.io/sopran/maps/moon/"
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

    assert "Moon Maps Example" in mission_example
    assert "spn.Moon" in mission_example
    assert "spn.Region" in mission_example
    assert "Moon DEM Example" in dem_example
    assert "lro.lola.dem_118m" in dem_example
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
        "https://nkzono99.github.io/sopran/maps/moon/"
    )
    assert "月面マップ" in moon_ja.to_markdown()
    assert "Moon Maps" in moon_en.to_markdown()
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
