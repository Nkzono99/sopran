from __future__ import annotations

import numpy as np
import polars as pl
import xarray as xr

import sopran as spn


def test_time_bins_build_regular_half_open_bins() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:30Z"),
        cadence="10s",
    )

    assert bins.count == 3
    assert bins.start_iso == "2008-01-01T00:00:00Z"
    assert bins.stop_iso == "2008-01-01T00:00:30Z"
    assert bins.centers_iso == (
        "2008-01-01T00:00:05Z",
        "2008-01-01T00:00:15Z",
        "2008-01-01T00:00:25Z",
    )


def test_time_bins_can_keep_partial_tail_bin() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:24Z"),
        cadence="10s",
        partial="keep",
    )

    assert bins.partial == "keep"
    assert bins.count == 3
    assert bins.stop_iso == "2008-01-01T00:00:24Z"
    assert bins.centers_iso == (
        "2008-01-01T00:00:05Z",
        "2008-01-01T00:00:15Z",
        "2008-01-01T00:00:22Z",
    )


def test_time_bins_can_drop_partial_tail_bin() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:24Z"),
        cadence="10s",
        partial="drop",
    )

    assert bins.partial == "drop"
    assert bins.count == 2
    assert bins.stop_iso == "2008-01-01T00:00:20Z"
    assert bins.centers_iso == (
        "2008-01-01T00:00:05Z",
        "2008-01-01T00:00:15Z",
    )


def test_align_nearest_samples_arrays_to_time_bin_centers() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:30Z"),
        cadence="10s",
    )
    sza = xr.DataArray(
        np.array([70.0, 80.0, 90.0]),
        dims=("time",),
        coords={
            "time": np.array(
                [
                    "2008-01-01T00:00:04",
                    "2008-01-01T00:00:16",
                    "2008-01-01T00:00:27",
                ],
                dtype="datetime64[ns]",
            )
        },
        name="sza",
    )

    aligned = spn.align(sza, grid=bins, method="nearest", tolerance="3s")

    assert aligned.to_polars().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "sza": 70.0},
        {"time": "2008-01-01T00:00:15Z", "sza": 80.0},
        {"time": "2008-01-01T00:00:25Z", "sza": 90.0},
    ]


def test_align_mean_aggregates_arrays_inside_time_bins() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:20Z"),
        cadence="10s",
    )
    wave_power = xr.DataArray(
        np.array([1.0, 3.0, 10.0]),
        dims=("time",),
        coords={
            "time": np.array(
                [
                    "2008-01-01T00:00:01",
                    "2008-01-01T00:00:03",
                    "2008-01-01T00:00:12",
                ],
                dtype="datetime64[ns]",
            )
        },
        name="wave_power",
    )

    aligned = spn.align(wave_power, grid=bins, method="mean")

    assert aligned.to_polars().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "wave_power": 2.0},
        {"time": "2008-01-01T00:00:15Z", "wave_power": 10.0},
    ]


def test_align_max_aggregates_arrays_inside_time_bins() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:20Z"),
        cadence="10s",
    )
    wave_power = xr.DataArray(
        np.array([1.0, 5.0, 2.0, 10.0]),
        dims=("time",),
        coords={
            "time": np.array(
                [
                    "2008-01-01T00:00:01",
                    "2008-01-01T00:00:03",
                    "2008-01-01T00:00:08",
                    "2008-01-01T00:00:12",
                ],
                dtype="datetime64[ns]",
            )
        },
        name="wave_power",
    )

    aligned = spn.align(wave_power, grid=bins, method="max")

    assert aligned.to_polars().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "wave_power": 5.0},
        {"time": "2008-01-01T00:00:15Z", "wave_power": 10.0},
    ]


def test_align_inner_join_drops_bins_with_missing_features() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:20Z"),
        cadence="10s",
    )
    sza = xr.DataArray(
        np.array([70.0, 80.0]),
        dims=("time",),
        coords={
            "time": np.array(
                ["2008-01-01T00:00:04", "2008-01-01T00:00:16"],
                dtype="datetime64[ns]",
            )
        },
        name="sza",
    )
    wave_power = xr.DataArray(
        np.array([5.0]),
        dims=("time",),
        coords={"time": np.array(["2008-01-01T00:00:04"], dtype="datetime64[ns]")},
        name="wave_power",
    )

    aligned = spn.align(
        sza,
        wave_power,
        grid=bins,
        method="nearest",
        tolerance="2s",
        join="inner",
    )

    assert aligned.join == "inner"
    assert aligned.to_polars().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "sza": 70.0, "wave_power": 5.0}
    ]


def test_align_fill_replaces_missing_feature_values() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:20Z"),
        cadence="10s",
    )
    sza = xr.DataArray(
        np.array([70.0, 80.0]),
        dims=("time",),
        coords={
            "time": np.array(
                ["2008-01-01T00:00:04", "2008-01-01T00:00:16"],
                dtype="datetime64[ns]",
            )
        },
        name="sza",
    )
    wave_power = xr.DataArray(
        np.array([5.0]),
        dims=("time",),
        coords={"time": np.array(["2008-01-01T00:00:04"], dtype="datetime64[ns]")},
        name="wave_power",
    )

    aligned = spn.align(
        sza,
        wave_power,
        grid=bins,
        method="nearest",
        tolerance="2s",
        fill=-1.0,
    )

    assert aligned.fill == -1.0
    assert aligned.to_polars().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "sza": 70.0, "wave_power": 5.0},
        {"time": "2008-01-01T00:00:15Z", "sza": 80.0, "wave_power": -1.0},
    ]


def test_align_nearest_expands_vector_components_to_wide_columns() -> None:
    bins = spn.time_bins(
        spn.period("2011-07-01T00:00:00Z", "2011-07-01T00:00:20Z"),
        cadence="10s",
    )
    magnetic_field = xr.DataArray(
        np.array([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]]),
        dims=("time", "component"),
        coords={
            "time": np.array(
                ["2011-07-01T00:00:04", "2011-07-01T00:00:16"],
                dtype="datetime64[ns]",
            ),
            "component": ["x", "y", "z"],
        },
        name="magnetic_field",
    )

    aligned = spn.align(magnetic_field, grid=bins, method="nearest", tolerance="3s")

    assert aligned.columns == (
        "magnetic_field_x",
        "magnetic_field_y",
        "magnetic_field_z",
    )
    assert aligned.to_polars().to_dicts() == [
        {
            "time": "2011-07-01T00:00:05Z",
            "magnetic_field_x": 1.0,
            "magnetic_field_y": 2.0,
            "magnetic_field_z": 3.0,
        },
        {
            "time": "2011-07-01T00:00:15Z",
            "magnetic_field_x": 10.0,
            "magnetic_field_y": 20.0,
            "magnetic_field_z": 30.0,
        },
    ]


def test_align_mean_aggregates_vector_components_inside_bins() -> None:
    bins = spn.time_bins(
        spn.period("2011-07-01T00:00:00Z", "2011-07-01T00:00:10Z"),
        cadence="10s",
    )
    magnetic_field = xr.DataArray(
        np.array([[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]]),
        dims=("time", "component"),
        coords={
            "time": np.array(
                ["2011-07-01T00:00:01", "2011-07-01T00:00:03"],
                dtype="datetime64[ns]",
            ),
            "component": ["x", "y", "z"],
        },
        name="magnetic_field",
    )

    aligned = spn.align(magnetic_field, grid=bins, method="mean")

    assert aligned.to_polars().to_dicts() == [
        {
            "time": "2011-07-01T00:00:05Z",
            "magnetic_field_x": 2.0,
            "magnetic_field_y": 3.0,
            "magnetic_field_z": 4.0,
        }
    ]


def test_alignment_result_writes_parquet_feature_table(tmp_path) -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:10Z"),
        cadence="10s",
    )
    sza = xr.DataArray(
        np.array([70.0]),
        dims=("time",),
        coords={"time": np.array(["2008-01-01T00:00:04"], dtype="datetime64[ns]")},
        name="sza",
    )
    aligned = spn.align(sza, grid=bins, method="nearest", tolerance="3s")

    path = aligned.write_parquet(tmp_path / "features.parquet")

    assert path == tmp_path / "features.parquet"
    assert pl.read_parquet(path).to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "sza": 70.0}
    ]


def test_sample_table_uses_product_specific_alignment_methods() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:20Z"),
        cadence="10s",
    )
    sza = xr.DataArray(
        np.array([70.0, 80.0]),
        dims=("time",),
        coords={
            "time": np.array(
                ["2008-01-01T00:00:04", "2008-01-01T00:00:16"],
                dtype="datetime64[ns]",
            )
        },
        name="sza",
    )
    wave_power = xr.DataArray(
        np.array([1.0, 3.0, 10.0]),
        dims=("time",),
        coords={
            "time": np.array(
                [
                    "2008-01-01T00:00:01",
                    "2008-01-01T00:00:03",
                    "2008-01-01T00:00:12",
                ],
                dtype="datetime64[ns]",
            )
        },
        name="wave_power",
    )

    result = (
        spn.SampleTable(bins)
        .add(sza, method="nearest", tolerance="3s")
        .add(wave_power, method="mean")
        .collect()
    )

    assert result.method == "mixed"
    assert result.to_polars().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "sza": 70.0, "wave_power": 2.0},
        {"time": "2008-01-01T00:00:15Z", "sza": 80.0, "wave_power": 10.0},
    ]


def test_sample_table_supports_product_specific_bin_reducers() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:20Z"),
        cadence="10s",
    )
    wave_power = xr.DataArray(
        np.array([1.0, 5.0, 2.0, 10.0]),
        dims=("time",),
        coords={
            "time": np.array(
                [
                    "2008-01-01T00:00:01",
                    "2008-01-01T00:00:03",
                    "2008-01-01T00:00:08",
                    "2008-01-01T00:00:12",
                ],
                dtype="datetime64[ns]",
            )
        },
        name="wave_power",
    )
    density = xr.DataArray(
        np.array([1.0, 100.0, 3.0, 10.0, 20.0]),
        dims=("time",),
        coords={
            "time": np.array(
                [
                    "2008-01-01T00:00:01",
                    "2008-01-01T00:00:03",
                    "2008-01-01T00:00:08",
                    "2008-01-01T00:00:12",
                    "2008-01-01T00:00:14",
                ],
                dtype="datetime64[ns]",
            )
        },
        name="density",
    )

    result = (
        spn.SampleTable(bins)
        .add(wave_power, method="max")
        .add(density, method="median")
        .collect()
    )

    assert result.to_polars().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "wave_power": 5.0, "density": 3.0},
        {"time": "2008-01-01T00:00:15Z", "wave_power": 10.0, "density": 15.0},
    ]


def test_sample_table_inner_join_drops_bins_with_missing_features() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:20Z"),
        cadence="10s",
    )
    sza = xr.DataArray(
        np.array([70.0, 80.0]),
        dims=("time",),
        coords={
            "time": np.array(
                ["2008-01-01T00:00:04", "2008-01-01T00:00:16"],
                dtype="datetime64[ns]",
            )
        },
        name="sza",
    )
    wave_power = xr.DataArray(
        np.array([5.0]),
        dims=("time",),
        coords={"time": np.array(["2008-01-01T00:00:04"], dtype="datetime64[ns]")},
        name="wave_power",
    )

    result = (
        spn.SampleTable(bins)
        .add(sza, method="nearest", tolerance="2s")
        .add(wave_power, method="max")
        .collect(join="inner")
    )

    assert result.join == "inner"
    assert result.to_polars().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "sza": 70.0, "wave_power": 5.0}
    ]


def test_sample_table_fill_replaces_missing_feature_values() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:20Z"),
        cadence="10s",
    )
    sza = xr.DataArray(
        np.array([70.0, 80.0]),
        dims=("time",),
        coords={
            "time": np.array(
                ["2008-01-01T00:00:04", "2008-01-01T00:00:16"],
                dtype="datetime64[ns]",
            )
        },
        name="sza",
    )
    wave_power = xr.DataArray(
        np.array([5.0]),
        dims=("time",),
        coords={"time": np.array(["2008-01-01T00:00:04"], dtype="datetime64[ns]")},
        name="wave_power",
    )

    result = (
        spn.SampleTable(bins)
        .add(sza, method="nearest", tolerance="2s")
        .add(wave_power, method="max")
        .collect(fill=-1.0)
    )

    assert result.fill == -1.0
    assert result.to_polars().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "sza": 70.0, "wave_power": 5.0},
        {"time": "2008-01-01T00:00:15Z", "sza": 80.0, "wave_power": -1.0},
    ]
