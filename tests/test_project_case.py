from __future__ import annotations

import sopran as spn
from sopran import Store


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
""".strip(),
        encoding="utf-8",
    )

    case = spn.Project(project_root, store=Store(tmp_path / "store")).case("wake")
    plan = case.moon.dem.plan(source="kaguya.tc.dem", resolution="512ppd")

    assert case.frame == "SSE"
    assert case.cache is True
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
