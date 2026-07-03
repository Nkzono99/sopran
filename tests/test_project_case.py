from __future__ import annotations

import json

import numpy as np
import pytest
import xarray as xr
import sopran as spn
from sopran import Store
from sopran.core.data import SopranArray
from sopran.missions.kaguya.data import KaguyaESA1Data


def test_project_case_reads_defaults_and_exposes_moon_context(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[defaults]
frame = "SSE"
cache = true

[cases.wake]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"

[cases.wake.region]
body = "moon"
lon = [350, 10]
lat = [-5, 5]
lon_domain = "0_360"
""".strip(),
        encoding="utf-8",
    )

    case = spn.Project(project_root, store=Store(tmp_path / "store")).case("wake")
    plan = case.moon.dem.plan(source="kaguya.tc.dem", resolution="512ppd")

    assert case.frame == "SSE"
    assert case.cache is True
    assert case.region == spn.Region(lon=(350.0, 10.0), lat=(-5.0, 5.0), body="moon")
    assert plan.body == "moon"
    assert plan.product == "dem"
    assert plan.parameters["source"] == "kaguya.tc.dem"
    assert plan.parameters["region"] == case.region


def test_project_case_supplies_region_and_time_to_moon_surface_plans(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[cases.wake]
start = "2008-02-01T12:00:00"
stop = "2008-02-01T13:00:00"

[cases.wake.region]
body = "moon"
lon = [120, 160]
lat = [-45, -10]
lon_domain = "0_360"
""".strip(),
        encoding="utf-8",
    )

    case = spn.Project(project_root, store=Store(tmp_path / "store")).case("wake")

    dem_plan = case.moon.dem.plan(source="kaguya.tc.dem")
    shadow_plan = case.moon.shadow.plan(dem=dem_plan)
    sza_plan = case.moon.sza.plan()

    assert dem_plan.parameters["region"] == case.region
    assert shadow_plan.parameters["region"] == case.region
    assert shadow_plan.parameters["time"] == "2008-02-01T12:00:00Z"
    assert sza_plan.parameters["region"] == case.region
    assert sza_plan.parameters["time"] == "2008-02-01T12:00:00Z"
    assert sza_plan.parameters["geometry"] == "spice"
    assert sza_plan.parameters["geometry_source"] == "spice"


def test_project_case_exports_json_ready_context_metadata(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[defaults]
frame = "SSE"
cache = true
level = "l2"

[cases.wake]
start = "2008-02-01T00:00:00"
stop = "2008-02-01T12:00:00"

[cases.wake.region]
body = "moon"
lon = [350, 10]
lat = [-5, 5]
lon_domain = "-180_180"
lon_direction = "east_positive"
lat_type = "planetocentric"
""".strip(),
        encoding="utf-8",
    )
    store = Store(tmp_path / "store")

    metadata = spn.Project(project_root, store=store).case("wake").metadata()

    assert metadata == {
        "name": "wake",
        "project_root": str(project_root),
        "store": {
            "root": str(store.root),
            "cache_root": str(store.cache_root),
        },
        "time": {
            "start": "2008-02-01T00:00:00Z",
            "stop": "2008-02-01T12:00:00Z",
        },
        "frame": "SSE",
        "cache": True,
        "defaults": {
            "cache": True,
            "frame": "SSE",
            "level": "l2",
        },
        "region": {
            "body": "moon",
            "lon": [-10.0, 10.0],
            "lat": [-5.0, 5.0],
            "lon_domain": "-180_180",
            "lon_direction": "east_positive",
            "lat_type": "planetocentric",
        },
    }


def test_project_case_allows_explicit_time_without_config_file(tmp_path) -> None:
    project_root = tmp_path / "ad_hoc_project"
    project_root.mkdir()

    case = spn.Project(project_root, store=Store(tmp_path / "store")).case(
        "ad_hoc",
        start="2008-02-01",
        stop="2008-02-02",
    )

    assert case.time.start_iso == "2008-02-01T00:00:00Z"
    assert case.frame is None
    assert case.cache is False
    assert case.region is None


def test_project_reads_store_roots_from_project_config(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[store]
data_root = "configured_data"
cache_root = "configured_cache"
""".strip(),
        encoding="utf-8",
    )

    project = spn.Project(project_root)

    assert project.store.root == project_root / "configured_data"
    assert project.store.cache_root == project_root / "configured_cache"


def test_project_store_environment_overrides_project_config(
    tmp_path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    env_data = tmp_path / "env_data"
    env_cache = tmp_path / "env_cache"
    monkeypatch.setenv("SOPRAN_DATA_ROOT", str(env_data))
    monkeypatch.setenv("SOPRAN_CACHE_ROOT", str(env_cache))
    (project_root / "sopran.toml").write_text(
        """
[store]
data_root = "configured_data"
cache_root = "configured_cache"
""".strip(),
        encoding="utf-8",
    )

    project = spn.Project(project_root)

    assert project.store.root == env_data
    assert project.store.cache_root == env_cache


def test_project_reads_artifact_root_from_project_config(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[project]
artifact_root = "configured_artifacts"
""".strip(),
        encoding="utf-8",
    )
    project = spn.Project(project_root, store=Store(tmp_path / "store"))
    data = KaguyaESA1Data(time=spn.day("2008-02-01")).quality

    artifact = project.save(data, "interim/kaguya_esa1_quality")

    assert project.artifact_root == project_root / "configured_artifacts"
    assert artifact.path == (
        project_root
        / "configured_artifacts"
        / "interim"
        / "kaguya_esa1_quality.nc"
    )
    assert artifact.metadata["path"] == "interim/kaguya_esa1_quality.nc"


def test_project_artifact_root_environment_overrides_project_config(
    tmp_path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    env_artifacts = tmp_path / "env_artifacts"
    monkeypatch.setenv("SOPRAN_ARTIFACT_ROOT", str(env_artifacts))
    (project_root / "sopran.toml").write_text(
        """
[project]
artifact_root = "configured_artifacts"
""".strip(),
        encoding="utf-8",
    )

    project = spn.Project(project_root, store=Store(tmp_path / "store"))

    assert project.artifact_root == env_artifacts


def test_project_invalid_region_config_raises_config_error(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[cases.bad_region]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"

[cases.bad_region.region]
lon = [120]
lat = [-45, -10]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(spn.ConfigError, match="case region lon and lat"):
        spn.Project(project_root).case("bad_region")


def test_project_save_writes_loaded_xarray_artifact_with_metadata(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    project = spn.Project(project_root, store=Store(tmp_path / "store"))
    data = KaguyaESA1Data(time=spn.day("2008-02-01")).quality

    artifact = project.save(data, "interim/kaguya_esa1_quality_wake")

    assert artifact.path == project_root / "interim" / "kaguya_esa1_quality_wake.nc"
    assert artifact.path.exists()
    assert artifact.metadata_path == project_root / "interim" / "kaguya_esa1_quality_wake.json"
    metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
    assert metadata["name"] == "quality"
    assert metadata["format"] == "netcdf"
    assert metadata["time_coverage"] == {
        "start": "2008-02-01T00:00:00Z",
        "stop": "2008-02-02T00:00:00Z",
    }

    import xarray as xr

    saved = xr.open_dataarray(artifact.path)
    try:
        assert saved.name == "quality"
        assert np.asarray(saved.values).shape == (0,)
    finally:
        saved.close()


def test_project_save_can_include_case_context_metadata(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[defaults]
frame = "SSE"
cache = true

[cases.wake]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"
""".strip(),
        encoding="utf-8",
    )
    store = Store(tmp_path / "store")
    project = spn.Project(project_root, store=store)
    case = project.case("wake")
    data = KaguyaESA1Data(time=case.time).quality

    artifact = project.save(
        data,
        "interim/kaguya_esa1_quality_wake_context",
        context=case,
    )

    metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
    assert metadata["context"] == case.metadata()


def test_project_save_accepts_loaded_array_as_context(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    project = spn.Project(project_root, store=Store(tmp_path / "store"))
    data = KaguyaESA1Data(time=spn.day("2008-02-01")).quality

    artifact = project.save(
        data,
        "interim/kaguya_esa1_quality_self_context",
        context=data,
    )

    metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
    assert metadata["context"] == data.metadata


def test_project_save_accepts_to_metadata_object_as_context(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    project = spn.Project(project_root, store=Store(tmp_path / "store"))
    data = KaguyaESA1Data(time=spn.day("2008-02-01")).quality
    region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

    artifact = project.save(
        data,
        "interim/kaguya_esa1_quality_region_context",
        context=region,
    )

    metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
    assert metadata["context"] == region.to_metadata()


def test_project_save_records_loaded_object_source_metadata(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    project = spn.Project(project_root, store=Store(tmp_path / "store"))
    times = np.array(
        [
            "2008-02-01T00:00:00",
            "2008-02-01T00:01:00",
            "2008-02-01T00:02:00",
            "2008-02-01T00:03:00",
        ],
        dtype="datetime64[ns]",
    )
    quality = xr.DataArray(
        np.array([1.0, 2.0, 3.0, 4.0]),
        dims=("time",),
        coords={"time": times},
        name="quality",
    )
    loaded = SopranArray(
        name="quality",
        time=spn.period("2008-02-01", "2008-02-02"),
        schema=spn.VariableSchema(name="quality", dims=("time",), units="flag"),
        xr=quality,
    )
    resampled = loaded.resample(time="2min").mean()

    artifact = project.save(resampled, "interim/quality_2min")

    metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_metadata"]["schema"] == resampled.metadata["schema"]
    assert metadata["source_metadata"]["operations"] == resampled.metadata["operations"]
    assert metadata["source_metadata"]["time_range"] == resampled.metadata["time_range"]
