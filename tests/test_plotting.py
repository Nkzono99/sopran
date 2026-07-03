from __future__ import annotations

import json

import numpy as np
import polars as pl
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
    assert result.metadata["panel_kinds"] == ["spectrogram", "line"]
    assert result.metadata["panels"] == [
        {
            "name": "counts",
            "kind": "spectrogram",
            "x": "time",
            "y": "energy",
            "log_color": False,
        },
        {
            "name": "quality",
            "kind": "line",
            "x": "time",
            "y": None,
            "log_color": False,
        },
    ]


def test_plot_stack_records_shared_native_time_axis_metadata() -> None:
    import matplotlib

    matplotlib.use("Agg")
    times = np.array(
        ["2008-01-01T00:00:00", "2008-01-01T00:01:00"],
        dtype="datetime64[ns]",
    )
    counts = xr.DataArray(
        np.array([10.0, 20.0]),
        dims=("time",),
        coords={"time": times},
        name="counts",
    )
    quality = xr.DataArray(
        np.array([0, 1]),
        dims=("time",),
        coords={"time": times},
        name="quality",
    )

    result = spn.stack(spn.line(counts), spn.line(quality)).plot()

    assert result.metadata["time_axis"] == {
        "shared": True,
        "coordinates": ["time"],
        "timezone": "UTC",
        "cadence_policy": "native",
    }


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


def test_plot_stack_histogram_plots_distribution_and_metadata() -> None:
    import matplotlib

    matplotlib.use("Agg")
    values = xr.DataArray(
        np.array([0.0, 1.0, 1.0, 2.0, np.nan]),
        dims=("time",),
        coords={"time": np.arange(5)},
        name="wave_power",
    )

    result = spn.stack(spn.histogram(values, bins=3)).plot()

    assert len(result.axes[0].patches) == 3
    assert result.metadata["panel_kinds"] == ["histogram"]
    assert result.metadata["panels"] == [
        {
            "name": "wave_power",
            "kind": "histogram",
            "x": "wave_power",
            "y": None,
            "log_color": False,
            "bins": 3,
        }
    ]
    assert result.metadata["time_axis"] == {
        "shared": False,
        "coordinates": [],
        "cadence_policy": "native",
        "non_time_panels": ["wave_power"],
    }


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


def test_loaded_array_to_polars_uses_array_layout_for_dense_data_by_default() -> None:
    array = xr.DataArray(
        np.ones((2, 3, 4)),
        dims=("time", "energy", "look"),
        coords={
            "time": np.array(["2008-01-01T00:00:00", "2008-01-01T00:01:00"], dtype="datetime64[ns]"),
            "energy": [10.0, 20.0, 30.0],
            "look": [0, 1, 2, 3],
        },
        name="counts",
    )
    loaded = SopranArray(
        name="counts",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="counts", dims=("time", "energy", "look")),
        xr=array,
    )

    frame = loaded.to_polars()

    assert frame.shape == (2, 2)
    assert frame.columns == ["time", "counts"]
    assert frame.schema["counts"] == pl.Array(pl.Float64, shape=(3, 4))


def test_loaded_array_to_polars_rejects_large_long_table_when_requested() -> None:
    array = xr.DataArray(
        np.ones((2, 3, 4)),
        dims=("time", "energy", "look"),
        coords={
            "time": np.array(["2008-01-01T00:00:00", "2008-01-01T00:01:00"], dtype="datetime64[ns]"),
            "energy": [10.0, 20.0, 30.0],
            "look": [0, 1, 2, 3],
        },
        name="counts",
    )
    loaded = SopranArray(
        name="counts",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="counts", dims=("time", "energy", "look")),
        xr=array,
    )

    with pytest.raises(ValueError, match="would create 24 rows"):
        loaded.to_polars(layout="long", max_rows=10)

    frame = loaded.to_polars(layout="long", max_rows=10, allow_large=True)

    assert frame.shape == (24, 4)


def test_loaded_array_histogram_returns_distribution_plot_item(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    array = xr.DataArray(
        np.array([1.0, 2.0, 2.0, 3.0]),
        dims=("time",),
        coords={"time": np.arange(4)},
        name="sza",
    )
    loaded = SopranArray(
        name="sza",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="sza", dims=("time",), units="deg"),
        xr=array,
    )

    result = spn.stack(loaded.histogram(bins=4)).quicklook("sza_distribution", root=tmp_path)
    metadata = json.loads((tmp_path / "sza_distribution.json").read_text(encoding="utf-8"))

    assert (tmp_path / "sza_distribution.png").exists()
    assert result.metadata["panel_kinds"] == ["histogram"]
    assert metadata["panels"][0]["bins"] == 4


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


def test_loaded_array_schema_is_callable_like_endpoint_schema() -> None:
    loaded = SopranArray(
        name="quality",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(
            name="quality",
            dims=("time",),
            units="flag",
        ),
    )

    schema = loaded.schema()

    assert schema is loaded.schema
    assert schema.name == "quality"
    assert schema.units == "flag"


def test_loaded_array_exposes_trange_and_json_ready_metadata(tmp_path) -> None:
    source = tmp_path / "raw" / "kaguya" / "esa1.pbf"
    loaded = SopranArray(
        name="quality",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(
            name="quality",
            dims=("time",),
            units="flag",
            frame="SELENE_SC",
            description="Quality flag.",
        ),
        files=(source,),
    )

    assert loaded.trange is loaded.time
    assert loaded.metadata == {
        "type": "SopranArray",
        "name": "quality",
        "time_range": {
            "start": "2008-01-01T00:00:00Z",
            "stop": "2008-01-02T00:00:00Z",
        },
        "schema": {
            "name": "quality",
            "dims": ["time"],
            "units": "flag",
            "dtype": None,
            "frame": "SELENE_SC",
            "description": "Quality flag.",
            "aliases": [],
        },
        "source_files": [str(source)],
    }


def test_loaded_array_delegates_sel_where_and_mean_to_xarray() -> None:
    array = xr.DataArray(
        np.array([[1.0, 2.0], [3.0, 4.0]]),
        dims=("time", "energy"),
        coords={"time": ["t0", "t1"], "energy": [10.0, 20.0]},
        name="counts",
    )
    loaded = SopranArray(
        name="counts",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(
            name="counts",
            dims=("time", "energy"),
            units="count",
            description="Raw counts.",
        ),
        xr=array,
    )

    selected = loaded.sel(energy=20.0)
    masked = loaded.where(loaded.to_xarray() >= 2.0)
    averaged = loaded.mean("energy")

    assert isinstance(selected, SopranArray)
    assert selected.schema.dims == ("time",)
    assert selected.to_xarray().dims == ("time",)
    assert selected.to_xarray().values.tolist() == [2.0, 4.0]
    assert masked.schema.dims == ("time", "energy")
    assert np.isnan(masked.to_xarray().values[0, 0])
    assert averaged.schema.dims == ("time",)
    assert averaged.to_xarray().values.tolist() == [1.5, 3.5]
    assert averaged.schema.units == "count"
    assert averaged.metadata["schema"]["dims"] == ["time"]


def test_loaded_array_resample_delegates_to_xarray_resampler() -> None:
    times = np.array(
        [
            "2008-01-01T00:00:00",
            "2008-01-01T00:01:00",
            "2008-01-01T00:02:00",
            "2008-01-01T00:03:00",
        ],
        dtype="datetime64[ns]",
    )
    array = xr.DataArray(
        np.array([1.0, 2.0, 3.0, 4.0]),
        dims=("time",),
        coords={"time": times},
        name="quality",
    )
    loaded = SopranArray(
        name="quality",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="quality", dims=("time",)),
        xr=array,
    )

    resampled = loaded.resample(time="2min").mean()

    assert isinstance(resampled, SopranArray)
    assert resampled.schema.dims == ("time",)
    assert resampled.to_xarray().dims == ("time",)
    assert resampled.to_xarray().values.tolist() == [1.5, 3.5]
    assert resampled.metadata["schema"]["dims"] == ["time"]
    assert resampled.metadata["operations"] == [
        {
            "operation": "resample",
            "parameters": {"time": "2min"},
            "reducer": "mean",
        }
    ]


def test_loaded_array_resampler_wraps_sum_and_median_reductions() -> None:
    times = np.array(
        [
            "2008-01-01T00:00:00",
            "2008-01-01T00:01:00",
            "2008-01-01T00:02:00",
            "2008-01-01T00:03:00",
        ],
        dtype="datetime64[ns]",
    )
    array = xr.DataArray(
        np.array([1.0, 2.0, 10.0, 20.0]),
        dims=("time",),
        coords={"time": times},
        name="counts",
    )
    loaded = SopranArray(
        name="counts",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="counts", dims=("time",), units="count"),
        xr=array,
    )

    summed = loaded.resample(time="2min").sum()
    median = loaded.resample(time="2min").median()

    assert isinstance(summed, SopranArray)
    assert summed.to_xarray().values.tolist() == [3.0, 30.0]
    assert summed.schema.units == "count"
    assert isinstance(median, SopranArray)
    assert median.to_xarray().values.tolist() == [1.5, 15.0]
    assert median.schema.dims == ("time",)


def test_loaded_array_resampler_wraps_max_first_and_last_reductions() -> None:
    times = np.array(
        [
            "2008-01-01T00:00:00",
            "2008-01-01T00:01:00",
            "2008-01-01T00:02:00",
            "2008-01-01T00:03:00",
        ],
        dtype="datetime64[ns]",
    )
    array = xr.DataArray(
        np.array([1.0, 2.0, 10.0, 20.0]),
        dims=("time",),
        coords={"time": times},
        name="counts",
    )
    loaded = SopranArray(
        name="counts",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="counts", dims=("time",), units="count"),
        xr=array,
    )

    maximum = loaded.resample(time="2min").max()
    first = loaded.resample(time="2min").first()
    last = loaded.resample(time="2min").last()

    assert isinstance(maximum, SopranArray)
    assert maximum.to_xarray().values.tolist() == [2.0, 20.0]
    assert first.to_xarray().values.tolist() == [1.0, 10.0]
    assert last.to_xarray().values.tolist() == [2.0, 20.0]
    assert last.schema.units == "count"


def test_loaded_array_resample_quicklook_records_operation_metadata(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    times = np.array(
        [
            "2008-01-01T00:00:00",
            "2008-01-01T00:01:00",
            "2008-01-01T00:02:00",
            "2008-01-01T00:03:00",
        ],
        dtype="datetime64[ns]",
    )
    array = xr.DataArray(
        np.array([1.0, 2.0, 3.0, 4.0]),
        dims=("time",),
        coords={"time": times},
        name="quality",
    )
    loaded = SopranArray(
        name="quality",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="quality", dims=("time",)),
        xr=array,
    )
    resampled = loaded.resample(time="2min").mean()

    result = resampled.quicklook("quality_2min", root=tmp_path)
    metadata = json.loads((tmp_path / "quality_2min.json").read_text(encoding="utf-8"))

    assert result.metadata["metadata"]["operations"] == resampled.metadata["operations"]
    assert metadata["metadata"]["operations"] == resampled.metadata["operations"]


def test_loaded_array_quicklook_writes_single_product_artifacts(tmp_path) -> None:
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
    loaded = SopranArray(
        name="quality",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="quality", dims=("time",)),
        xr=quality,
    )

    result = loaded.quicklook("quality_review", root=tmp_path, formats=("png", "html"))

    assert isinstance(result, spn.QuicklookResult)
    assert (tmp_path / "quality_review.png").exists()
    assert (tmp_path / "quality_review.html").exists()
    assert result.metadata["dataset_id"] == "quality"
    assert result.metadata["time_range"] == {
        "start": "2008-01-01T00:00:00Z",
        "stop": "2008-01-02T00:00:00Z",
    }
    assert result.metadata["items"] == ["quality"]


def test_loaded_array_quicklook_can_write_spectrogram_metadata(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
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
    loaded = SopranArray(
        name="counts",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="counts", dims=("time", "energy")),
        xr=counts,
    )

    result = loaded.quicklook(
        "counts_spectrum",
        root=tmp_path,
        y="energy",
        log_color=True,
    )
    metadata = json.loads((tmp_path / "counts_spectrum.json").read_text(encoding="utf-8"))

    assert isinstance(result, spn.QuicklookResult)
    assert result.metadata["panel_kinds"] == ["spectrogram"]
    assert metadata["panels"] == [
        {
            "name": "counts",
            "kind": "spectrogram",
            "x": "time",
            "y": "energy",
            "log_color": True,
        }
    ]


def test_loaded_array_quicklook_accepts_loaded_array_as_context(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    quality = xr.DataArray(
        np.array([0, 1]),
        dims=("time",),
        coords={"time": ["t0", "t1"]},
        name="quality",
    )
    loaded = SopranArray(
        name="quality",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="quality", dims=("time",)),
        xr=quality,
    )

    result = loaded.quicklook("quality_context", root=tmp_path, context=loaded)
    metadata = json.loads((tmp_path / "quality_context.json").read_text(encoding="utf-8"))

    assert result.metadata["context"] == loaded.metadata
    assert metadata["context"] == loaded.metadata


def test_loaded_array_exports_polars_and_pandas_tables() -> None:
    array = xr.DataArray(
        np.array([[1.0, 2.0], [3.0, 4.0]]),
        dims=("time", "energy"),
        coords={"time": ["t0", "t1"], "energy": [10.0, 20.0]},
        name="counts",
    )
    loaded = SopranArray(
        name="counts",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="counts", dims=("time", "energy")),
        xr=array,
    )

    polars_frame = loaded.to_polars()
    pandas_frame = loaded.to_pandas()

    assert polars_frame.to_dicts() == [
        {"time": "t0", "energy": 10.0, "counts": 1.0},
        {"time": "t0", "energy": 20.0, "counts": 2.0},
        {"time": "t1", "energy": 10.0, "counts": 3.0},
        {"time": "t1", "energy": 20.0, "counts": 4.0},
    ]
    assert pandas_frame.to_dict(orient="records") == polars_frame.to_dicts()


def test_loaded_array_writes_parquet_dataset_to_store(tmp_path) -> None:
    array = xr.DataArray(
        np.array([0, 1]),
        dims=("time",),
        coords={"time": ["t0", "t1"]},
        name="quality",
    )
    loaded = SopranArray(
        name="quality",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(
            name="quality",
            dims=("time",),
            description="Quality flag.",
        ),
        files=(tmp_path / "raw" / "kaguya" / "esa1.pbf",),
        xr=array,
    )

    record = loaded.write_parquet(
        spn.Store(tmp_path / "store"),
        dataset_id="kaguya.esa1.quality",
        mission="kaguya",
        instrument="esa1",
        provenance={"source": "unit-test"},
    )

    assert record.manifest()["dataset_id"] == "kaguya.esa1.quality"
    assert record.manifest()["layer"] == "normalized"
    assert record.manifest()["product"] == "quality"
    assert record.manifest()["source_files"] == [
        str(tmp_path / "raw" / "kaguya" / "esa1.pbf")
    ]
    assert record.manifest()["provenance"] == {"source": "unit-test"}
    assert record.schema()["variables"][0]["name"] == "quality"
    assert record.schema()["variables"][0]["description"] == "Quality flag."
    assert record.catalog().select("row_count").to_series().to_list() == [2]
    assert record.scan().collect().to_dicts() == [
        {"time": "t0", "quality": 0},
        {"time": "t1", "quality": 1},
    ]


def test_loaded_array_write_parquet_accepts_loaded_array_as_context(tmp_path) -> None:
    array = xr.DataArray(
        np.array([0, 1]),
        dims=("time",),
        coords={"time": ["t0", "t1"]},
        name="quality",
    )
    loaded = SopranArray(
        name="quality",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="quality", dims=("time",)),
        xr=array,
    )

    record = loaded.write_parquet(
        spn.Store(tmp_path / "store"),
        dataset_id="kaguya.esa1.quality",
        mission="kaguya",
        instrument="esa1",
        context=loaded,
    )

    assert record.manifest()["context"] == loaded.metadata


def test_loaded_array_resample_write_parquet_records_operation_parameters(
    tmp_path,
) -> None:
    times = np.array(
        [
            "2008-01-01T00:00:00",
            "2008-01-01T00:01:00",
            "2008-01-01T00:02:00",
            "2008-01-01T00:03:00",
        ],
        dtype="datetime64[ns]",
    )
    array = xr.DataArray(
        np.array([1.0, 2.0, 3.0, 4.0]),
        dims=("time",),
        coords={"time": times},
        name="quality",
    )
    loaded = SopranArray(
        name="quality",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="quality", dims=("time",)),
        xr=array,
    )
    resampled = loaded.resample(time="2min").sum()

    record = resampled.write_parquet(
        spn.Store(tmp_path / "store"),
        dataset_id="analysis.quality.2min",
        mission="analysis",
        instrument="quality",
    )

    assert (
        record.manifest()["parameters"]["operations"]
        == resampled.metadata["operations"]
    )


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


def test_plot_stack_lines_selects_vector_components() -> None:
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

    stack = spn.stack(spn.lines(magnetic_field, components="xz"))
    result = stack.plot()

    assert result.metadata["items"] == ["magnetic_field"]
    assert len(result.axes[0].lines) == 2


def test_loaded_array_lines_selects_vector_components() -> None:
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
    loaded = SopranArray(
        name="magnetic_field",
        time=spn.period("2008-01-01", "2008-01-02"),
        schema=spn.VariableSchema(name="magnetic_field", dims=("time", "component")),
        xr=magnetic_field,
    )

    result = spn.stack(loaded.lines(components="yz")).plot()

    assert len(result.axes[0].lines) == 2


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
    assert metadata["panel_kinds"] == ["line"]
    assert metadata["panels"] == [
        {
            "name": "quality",
            "kind": "line",
            "x": "time",
            "y": None,
            "log_color": False,
        }
    ]
    assert metadata["artifacts"] == ["wake_overview.png"]
    assert metadata["time_axis"] == {
        "shared": True,
        "coordinates": ["time"],
        "timezone": "UTC",
        "cadence_policy": "native",
    }


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


def test_plot_stack_quicklook_accepts_to_metadata_object_as_context(tmp_path) -> None:
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
    region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

    result = spn.stack(spn.line(quality)).quicklook(
        "region_context",
        root=tmp_path,
        context=region,
    )

    metadata = json.loads((tmp_path / "region_context.json").read_text(encoding="utf-8"))
    assert result.metadata["context"] == region.to_metadata()
    assert metadata["context"] == region.to_metadata()
