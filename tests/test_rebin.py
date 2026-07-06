from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

import sopran as spn
from sopran.core.data import SopranArray


def test_sopran_array_rebin_sums_numeric_axis_into_requested_bins() -> None:
    array = xr.DataArray(
        np.asarray([[1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0]]),
        dims=("time", "energy"),
        coords={
            "time": np.asarray(
                ["2008-01-01T00:00:00", "2008-01-01T00:01:00"],
                dtype="datetime64[ns]",
            ),
            "energy": ("energy", [10.0, 20.0, 30.0, 40.0], {"units": "eV"}),
        },
        name="counts",
        attrs={"units": "count"},
    )
    loaded = SopranArray(
        name="counts",
        time=spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:02:00Z"),
        schema=spn.VariableSchema(name="counts", dims=("time", "energy"), units="count"),
        xr=array,
    )

    rebinned = loaded.rebin(axis="energy", bins=[0.0, 25.0, 45.0])

    assert isinstance(rebinned, SopranArray)
    assert rebinned.schema.dims == ("time", "energy")
    assert rebinned.to_xarray().dims == ("time", "energy")
    np.testing.assert_allclose(rebinned.to_xarray().coords["energy"], [12.5, 35.0])
    np.testing.assert_allclose(rebinned.to_xarray().coords["energy_bin_left"], [0.0, 25.0])
    np.testing.assert_allclose(rebinned.to_xarray().coords["energy_bin_right"], [25.0, 45.0])
    assert rebinned.to_xarray().coords["energy"].attrs["units"] == "eV"
    np.testing.assert_allclose(
        rebinned.to_xarray().values,
        np.asarray([[3.0, 7.0], [30.0, 70.0]]),
    )
    assert rebinned.metadata["operations"][-1] == {
        "operation": "rebin",
        "parameters": {
            "axis": "energy",
            "bins": [0.0, 25.0, 45.0],
            "reduction": "sum",
        },
    }


def test_sopran_array_rebin_mean_preserves_other_dimensions() -> None:
    values = np.asarray(
        [
            [
                [1.0, 10.0],
                [2.0, 20.0],
                [3.0, 30.0],
                [4.0, 40.0],
            ]
        ]
    )
    loaded = SopranArray(
        name="energy_flux",
        time=spn.day("2008-01-01"),
        schema=spn.VariableSchema(
            name="energy_flux",
            dims=("time", "energy", "look"),
            units="eV/(cm^2 s sr eV)",
        ),
        xr=xr.DataArray(
            values,
            dims=("time", "energy", "look"),
            coords={
                "time": np.asarray(["2008-01-01T00:00:00"], dtype="datetime64[ns]"),
                "energy": [10.0, 20.0, 30.0, 40.0],
                "look": [0, 1],
            },
            name="energy_flux",
        ),
    )

    rebinned = loaded.rebin("energy", [0.0, 25.0, 45.0], reduction="mean")

    assert rebinned.to_xarray().dims == ("time", "energy", "look")
    np.testing.assert_allclose(
        rebinned.to_xarray().values,
        np.asarray([[[1.5, 15.0], [3.5, 35.0]]]),
    )


def test_sopran_array_rebin_accepts_axis_to_bins_mapping() -> None:
    loaded = SopranArray(
        name="pitch_angle_spectrum",
        time=spn.day("2008-01-01"),
        schema=spn.VariableSchema(
            name="pitch_angle_spectrum",
            dims=("time", "energy", "pitch_angle"),
            units="count",
        ),
        xr=xr.DataArray(
            np.ones((1, 4, 4)),
            dims=("time", "energy", "pitch_angle"),
            coords={
                "time": np.asarray(["2008-01-01T00:00:00"], dtype="datetime64[ns]"),
                "energy": [10.0, 20.0, 30.0, 40.0],
                "pitch_angle": [22.5, 67.5, 112.5, 157.5],
            },
            name="pitch_angle_spectrum",
        ),
    )

    rebinned = loaded.rebin(
        bins={
            "energy": [0.0, 25.0, 45.0],
            "pitch_angle": [0.0, 90.0, 180.0],
        }
    )

    assert rebinned.to_xarray().shape == (1, 2, 2)
    np.testing.assert_allclose(rebinned.to_xarray().values, np.full((1, 2, 2), 4.0))
    assert [operation["parameters"]["axis"] for operation in rebinned.metadata["operations"]] == [
        "energy",
        "pitch_angle",
    ]


def test_top_level_rebin_handles_xarray_data_arrays() -> None:
    array = xr.DataArray(
        np.asarray([1.0, 2.0, 3.0, 4.0]),
        dims=("energy",),
        coords={"energy": [10.0, 20.0, 30.0, 40.0]},
        name="counts",
    )

    rebinned = spn.rebin(array, axis="energy", bins=[0.0, 25.0, 45.0])

    assert isinstance(rebinned, xr.DataArray)
    np.testing.assert_allclose(rebinned.values, np.asarray([3.0, 7.0]))


def test_rebin_rejects_invalid_axis_and_bins() -> None:
    loaded = SopranArray(
        name="counts",
        time=spn.day("2008-01-01"),
        schema=spn.VariableSchema(name="counts", dims=("time", "energy")),
        xr=xr.DataArray(
            np.ones((1, 2)),
            dims=("time", "energy"),
            coords={
                "time": np.asarray(["2008-01-01T00:00:00"], dtype="datetime64[ns]"),
                "energy": ["low", "high"],
            },
            name="counts",
        ),
    )

    with pytest.raises(ValueError, match="numeric coordinate"):
        loaded.rebin(axis="energy", bins=[0.0, 1.0])
    with pytest.raises(ValueError, match="strictly increasing"):
        loaded.rebin(axis="time", bins=[0.0, 0.0, 1.0])
    with pytest.raises(ValueError, match="has no 'missing' dimension"):
        loaded.rebin(axis="missing", bins=[0.0, 1.0])
