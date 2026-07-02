from __future__ import annotations

import numpy as np
import xarray as xr

import sopran as spn


def test_plot_stack_plans_and_plots_xarray_line_and_spectrogram() -> None:
    import matplotlib

    matplotlib.use("Agg")
    times = np.array(
        ["2008-01-01T00:00:00", "2008-01-01T00:01:00"],
        dtype="datetime64[ns]",
    )
    energy = np.array([10.0, 20.0, 30.0])
    counts = xr.DataArray(
        np.ones((2, 3)),
        dims=("time", "energy"),
        coords={"time": times, "energy": energy},
        name="counts",
    )
    quality = xr.DataArray(
        np.array([0, 1]),
        dims=("time",),
        coords={"time": times},
        name="quality",
    )

    stack = spn.stack(
        spn.spectrogram(counts, y="energy"),
        spn.line(quality),
    )

    plan = stack.plan()
    fig = stack.plot()

    assert plan.panel_count == 2
    assert plan.items == ("counts", "quality")
    assert len(fig.axes) == 2


def test_project_case_builds_plot_stack(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[cases.wake]
start = "2008-01-01T00:00:00"
stop = "2008-01-02T00:00:00"
""".strip(),
        encoding="utf-8",
    )
    quality = xr.DataArray(
        np.array([0, 1]),
        dims=("time",),
        coords={
            "time": np.array(
                ["2008-01-01T00:00:00", "2008-01-01T00:01:00"],
                dtype="datetime64[ns]",
            )
        },
        name="quality",
    )

    case = spn.Project(project_root).case("wake")

    stack = case.stack(spn.line(quality))

    assert stack.plan().items == ("quality",)
