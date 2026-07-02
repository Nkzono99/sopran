from __future__ import annotations

import json

import numpy as np
import sopran as spn
from sopran import Store
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
