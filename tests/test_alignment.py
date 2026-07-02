from __future__ import annotations

import numpy as np
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
