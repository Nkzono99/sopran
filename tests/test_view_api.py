from __future__ import annotations

import json

import pytest

import sopran as spn


def test_project_view_supplies_time_and_region_to_data_tree(tmp_path) -> None:
    project = spn.Project(tmp_path / "project", store=spn.Store(tmp_path / "store"))
    region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

    view = project.view(
        time=spn.day("2008-02-01"),
        region=region,
        frame="SSE",
        cache=True,
        backend={"frames": "spiceypy", "plot": "matplotlib"},
    )

    counts_plan = view.kaguya.esa1.counts.plan()
    sza_plan = view.moon.sza.plan()

    assert counts_plan.dataset_id == "kaguya.esa1.counts"
    assert counts_plan.time == view.time
    assert sza_plan.parameters["region"] == region
    assert sza_plan.parameters["time"] == "2008-02-01T00:00:00Z"
    assert view.metadata()["selection"] == {
        "time": {
            "start": "2008-02-01T00:00:00Z",
            "stop": "2008-02-02T00:00:00Z",
        },
        "region": region.to_metadata(),
        "mission": [],
        "instrument": [],
        "product": [],
        "quality": None,
    }
    assert view.metadata()["context"]["frame"] == "SSE"
    assert view.metadata()["context"]["cache"] is True
    assert view.metadata()["context"]["backends"] == {
        "frames": "spiceypy",
        "plot": "matplotlib",
    }


def test_project_view_defaults_to_auto_backend_selection(tmp_path) -> None:
    project = spn.Project(tmp_path / "project", store=spn.Store(tmp_path / "store"))

    view = project.view(time=spn.day("2008-02-01"))
    plan = view.frame_context().plan("MOON_ME", "SSE")

    assert view.context.backend_policy == "auto"
    assert view.context.backends == {}
    assert view.metadata()["context"]["backend_policy"] == "auto"
    assert plan.backend == "spiceypy"


def test_view_with_time_returns_derived_view_without_mutating_original(tmp_path) -> None:
    project = spn.Project(tmp_path / "project", store=spn.Store(tmp_path / "store"))
    view = project.view(time=spn.day("2008-02-01"), frame="SSE")

    zoom = view.with_time("2008-02-01T03:00:00", "2008-02-01T04:00:00")

    assert view.time.start_iso == "2008-02-01T00:00:00Z"
    assert view.time.stop_iso == "2008-02-02T00:00:00Z"
    assert zoom.time.start_iso == "2008-02-01T03:00:00Z"
    assert zoom.time.stop_iso == "2008-02-01T04:00:00Z"
    assert zoom.frame == "SSE"


def test_project_data_tree_is_available_without_binding_a_view(tmp_path) -> None:
    project = spn.Project(tmp_path / "project", store=spn.Store(tmp_path / "store"))

    endpoint = project.kaguya.esa1.counts

    assert endpoint.schema().name == "counts"
    with pytest.raises(ValueError, match="Time range is required"):
        endpoint.plan()


def test_top_level_view_uses_user_config_when_project_is_omitted(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[store]
data_root = "data"
cache_root = "cache"

[defaults]
frame = "SSE"
cache = true
download = "missing"

[backends]
frames = "spiceypy"
plot = "matplotlib"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("SOPRAN_CONFIG", str(config_path))
    monkeypatch.delenv("SOPRAN_DATA_ROOT", raising=False)
    monkeypatch.delenv("SOPRAN_CACHE_ROOT", raising=False)

    view = spn.view(time=spn.day("2008-02-01"))

    assert view.project.store.root == tmp_path / "data"
    assert view.project.store.cache_root == tmp_path / "cache"
    assert view.frame == "SSE"
    assert view.cache is True
    assert view.context.download == "missing"
    assert view.context.backends["frames"] == "spiceypy"


def test_project_save_case_persists_view_as_named_analysis_context(tmp_path) -> None:
    project_root = tmp_path / "project"
    project = spn.Project(project_root, store=spn.Store(tmp_path / "store"))
    region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon", lon_domain="-180_180")
    view = project.view(
        time=spn.period("2008-02-01", "2008-02-02"),
        region=region,
        frame="SSE",
        cache=True,
        download="missing",
        backend={"frames": "spiceypy"},
    )

    saved = project.save_case("wake_20080201", view)
    case = project.case("wake_20080201")

    assert saved.path == project_root / "sopran.toml"
    assert case.time == view.time
    assert case.region == region
    assert case.frame == "SSE"
    assert case.cache is True
    assert case.to_view().context.backends == {"frames": "spiceypy"}
    assert json.loads(saved.metadata_path.read_text(encoding="utf-8")) == view.metadata()
