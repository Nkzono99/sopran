from __future__ import annotations

import json

import numpy as np
import pytest
import xarray as xr

import sopran as spn
from sopran.core.data import SopranArray


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


def test_plot_stack_spectrogram_supports_log_color_scale() -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.colors import LogNorm

    times = np.array(
        ["2008-01-01T00:00:00", "2008-01-01T00:01:00"],
        dtype="datetime64[ns]",
    )
    energy = np.array([10.0, 20.0, 30.0])
    counts = xr.DataArray(
        np.array([[1.0, 10.0, 100.0], [2.0, 20.0, 200.0]]),
        dims=("time", "energy"),
        coords={"time": times, "energy": energy},
        name="counts",
    )

    result = spn.stack(spn.spectrogram(counts, y="energy", log_color=True)).plot()

    assert isinstance(result.axes[0].collections[0].norm, LogNorm)


def test_loaded_array_spectrogram_preserves_log_color_option() -> None:
    times = np.array(
        ["2008-01-01T00:00:00", "2008-01-01T00:01:00"],
        dtype="datetime64[ns]",
    )
    energy = np.array([10.0, 20.0, 30.0])
    array = xr.DataArray(
        np.ones((2, 3)),
        dims=("time", "energy"),
        coords={"time": times, "energy": energy},
        name="counts",
    )
    loaded = SopranArray(
        name="counts",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="counts", dims=("time", "energy")),
        xr=array,
    )

    item = loaded.spectrogram(y="energy", log_color=True)

    assert item.log_color is True


def test_loaded_array_info_returns_info_page() -> None:
    loaded = SopranArray(
        name="counts",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(
            name="counts",
            dims=("time", "energy"),
            units="count",
            description="Raw counts.",
        ),
    )

    info = loaded.info()

    assert isinstance(info, spn.InfoPage)
    assert info.title == "counts"
    assert "dims: time, energy" in str(info)
    assert "units: count" in str(info)
    assert "Raw counts." in str(info)


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


def test_plot_stack_explore_returns_panel_view() -> None:
    import matplotlib
    import panel as pn

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

    view = stack.explore(backend="panel")

    assert isinstance(view, pn.Column)
    assert len(view) == 2
    with pytest.raises(ValueError, match="currently supports only panel"):
        stack.explore(backend="hvplot")


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


def test_plot_stack_plot_records_case_context_metadata(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[defaults]
frame = "SSE"
cache = true

[cases.wake]
start = "2008-01-01T00:00:00"
stop = "2008-01-01T00:02:00"
""".strip(),
        encoding="utf-8",
    )
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
    case = spn.Project(project_root).case("wake")

    result = spn.stack(spn.line(quality)).plot(context=case)

    assert result.metadata["context"] == case.metadata()


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


def test_plot_stack_quicklook_writes_html_report(tmp_path) -> None:
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

    result = stack.quicklook(
        "wake_overview",
        root=tmp_path,
        formats=("png", "html"),
        metadata={"case": "wake"},
        backend="matplotlib",
    )

    metadata = json.loads((tmp_path / "wake_overview.json").read_text(encoding="utf-8"))
    html = (tmp_path / "wake_overview.html").read_text(encoding="utf-8")
    assert [artifact.format for artifact in result.artifacts] == ["png", "html"]
    assert metadata["artifacts"] == ["wake_overview.png", "wake_overview.html"]
    assert metadata["artifact_formats"] == ["png", "html"]
    assert metadata["metadata"] == {"case": "wake"}
    assert '<img alt="wake_overview"' in html
    assert "data:image/png;base64," in html
    assert "&quot;artifact_formats&quot;: [" in html
    assert "wake_overview.html" in html
    assert "&quot;case&quot;: &quot;wake&quot;" in html


def test_plot_stack_quicklook_records_standard_provenance_metadata(tmp_path) -> None:
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

    result = stack.quicklook(
        "wake_overview",
        root=tmp_path,
        dataset_id="kaguya.esa1.quality",
        time_range=spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:02:00Z"),
        frame="SELENE_SC",
        aggregation={"cadence": "native"},
        metadata={"case": "wake"},
    )

    metadata = json.loads((tmp_path / "wake_overview.json").read_text(encoding="utf-8"))
    assert result.metadata["dataset_id"] == "kaguya.esa1.quality"
    assert metadata["time_range"] == {
        "start": "2008-01-01T00:00:00Z",
        "stop": "2008-01-01T00:02:00Z",
    }
    assert metadata["frame"] == "SELENE_SC"
    assert metadata["aggregation"] == {"cadence": "native"}
    assert metadata["metadata"] == {"case": "wake"}


def test_plot_stack_quicklook_records_case_context_metadata(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[defaults]
frame = "SSE"
cache = true

[cases.wake]
start = "2008-01-01T00:00:00"
stop = "2008-01-01T00:02:00"
""".strip(),
        encoding="utf-8",
    )
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
    case = spn.Project(project_root).case("wake")
    stack = spn.stack(spn.line(quality))

    result = stack.quicklook(
        "wake_overview",
        root=tmp_path,
        formats=("png", "html"),
        context=case,
    )

    metadata = json.loads((tmp_path / "wake_overview.json").read_text(encoding="utf-8"))
    html = (tmp_path / "wake_overview.html").read_text(encoding="utf-8")
    assert result.metadata["context"] == case.metadata()
    assert metadata["context"] == case.metadata()
    assert "&quot;context&quot;: {" in html
    assert "&quot;frame&quot;: &quot;SSE&quot;" in html
