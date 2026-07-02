from __future__ import annotations

import json

import numpy as np
import pytest
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
    result = stack.plot()

    assert plan.panel_count == 2
    assert plan.items == ("counts", "quality")
    assert isinstance(result, spn.PlotResult)
    assert result.backend == "matplotlib"
    assert len(result.fig.axes) == 2
    assert len(result.axes) == 2
    assert result.metadata["panel_count"] == 2
    assert result.metadata["items"] == ["counts", "quality"]


def test_plot_stack_line_accepts_vector_time_series() -> None:
    import matplotlib

    matplotlib.use("Agg")
    times = np.array(
        ["2008-01-01T00:00:00", "2008-01-01T00:01:00"],
        dtype="datetime64[ns]",
    )
    magnetic_field = xr.DataArray(
        np.array([[1.0, 2.0, 3.0], [1.5, 2.5, 3.5]]),
        dims=("time", "component"),
        coords={"time": times, "component": ["x", "y", "z"]},
        name="magnetic_field",
    )

    stack = spn.stack(spn.line(magnetic_field))
    fig = stack.plot()

    assert stack.plan().items == ("magnetic_field",)
    assert len(fig.axes) == 1
    assert len(fig.axes[0].lines) == 3


def test_plot_stack_accepts_matplotlib_backend_argument() -> None:
    import matplotlib

    matplotlib.use("Agg")
    times = np.array(
        ["2008-01-01T00:00:00", "2008-01-01T00:01:00"],
        dtype="datetime64[ns]",
    )
    quality = xr.DataArray(
        np.array([0, 1]),
        dims=("time",),
        coords={"time": times},
        name="quality",
    )
    stack = spn.stack(spn.line(quality))

    fig = stack.plot(backend="matplotlib")

    assert len(fig.axes) == 1
    with pytest.raises(ValueError, match="currently supports only matplotlib"):
        stack.plot(backend="hvplot")


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


def test_plot_stack_quicklook_writes_png_and_metadata(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    times = np.array(
        ["2008-01-01T00:00:00", "2008-01-01T00:01:00"],
        dtype="datetime64[ns]",
    )
    quality = xr.DataArray(
        np.array([0, 1]),
        dims=("time",),
        coords={"time": times},
        name="quality",
    )
    stack = spn.stack(spn.line(quality))

    result = stack.quicklook("wake_overview", root=tmp_path, backend="matplotlib")

    metadata = json.loads((tmp_path / "wake_overview.json").read_text(encoding="utf-8"))
    assert result.artifacts[0].path == tmp_path / "wake_overview.png"
    assert result.metadata_path == tmp_path / "wake_overview.json"
    assert (tmp_path / "wake_overview.png").exists()
    assert metadata["backend"] == "matplotlib"
    assert metadata["items"] == ["quality"]
    assert metadata["artifacts"] == ["wake_overview.png"]
