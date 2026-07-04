from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
import xarray as xr

import sopran as spn
from sopran.core.data import SopranArray


def test_resample_like_aligns_sopran_array_to_target_time_grid() -> None:
    source = _array(
        "magnetic_field",
        ["2008-01-01T00:00:00", "2008-01-01T00:00:10", "2008-01-01T00:00:20"],
        [0.0, 10.0, 20.0],
    )
    target = _array(
        "counts",
        ["2008-01-01T00:00:01", "2008-01-01T00:00:09", "2008-01-01T00:00:25"],
        [1.0, 1.0, 1.0],
    )

    result = spn.resample_like(source, target, method="nearest", tolerance="2s")

    assert isinstance(result, SopranArray)
    assert result.name == "magnetic_field"
    assert result.time == target.time
    np.testing.assert_allclose(
        result.to_xarray().values,
        np.asarray([0.0, 10.0, np.nan]),
        equal_nan=True,
    )
    assert result.metadata["operations"][-1]["operation"] == "resample_like"
    assert result.metadata["operations"][-1]["method"] == "nearest"
    assert result.metadata["operations"][-1]["tolerance_seconds"] == 2.0


def test_sopran_array_resample_like_supports_linear_interpolation() -> None:
    source = _array(
        "altitude",
        ["2008-01-01T00:00:00", "2008-01-01T00:00:10", "2008-01-01T00:00:20"],
        [100.0, 110.0, 130.0],
    )
    target = _array(
        "counts",
        ["2008-01-01T00:00:05", "2008-01-01T00:00:15"],
        [1.0, 1.0],
    )

    result = source.resample_like(target, method="linear")

    np.testing.assert_allclose(result.to_xarray().values, np.asarray([105.0, 120.0]))


def test_resample_like_linear_respects_bracketing_tolerance_for_xarray() -> None:
    source = _array(
        "altitude",
        ["2008-01-01T00:00:00", "2008-01-01T01:00:00"],
        [100.0, 200.0],
    )
    target = _array(
        "counts",
        ["2008-01-01T00:30:00", "2008-01-01T00:30:01"],
        [1.0, 1.0],
    )

    result = source.resample_like(target, method="linear", tolerance="5s")

    np.testing.assert_allclose(
        result.to_xarray().values,
        np.asarray([np.nan, np.nan]),
        equal_nan=True,
    )


def test_resample_like_linear_respects_bracketing_tolerance_for_pandas() -> None:
    source = pd.DataFrame(
        {
            "time": pd.to_datetime(
                ["2008-01-01T00:00:00Z", "2008-01-01T01:00:00Z"],
                utc=True,
            ),
            "altitude": [100.0, 200.0],
        }
    )
    target = pd.DataFrame(
        {"time": pd.to_datetime(["2008-01-01T00:30:00Z"], utc=True)}
    )

    result = spn.resample_like(source, target, method="linear", tolerance="5s")

    np.testing.assert_allclose(
        result["altitude"].to_numpy(),
        np.asarray([np.nan]),
        equal_nan=True,
    )


def test_resample_like_linear_does_not_extrapolate_for_pandas() -> None:
    source = pd.DataFrame(
        {
            "time": pd.to_datetime(
                ["2008-01-01T00:00:00Z", "2008-01-01T00:00:10Z"],
                utc=True,
            ),
            "altitude": [100.0, 110.0],
        }
    )
    target = pd.DataFrame(
        {"time": pd.to_datetime(["2008-01-01T00:00:20Z"], utc=True)}
    )

    result = spn.resample_like(source, target, method="linear")

    np.testing.assert_allclose(
        result["altitude"].to_numpy(),
        np.asarray([np.nan]),
        equal_nan=True,
    )


def test_resample_like_preserves_non_time_dimensions() -> None:
    time = ["2008-01-01T00:00:00", "2008-01-01T00:00:10"]
    source_xr = xr.DataArray(
        np.asarray([[1.0, 2.0], [3.0, 4.0]]),
        dims=("time", "component"),
        coords={"time": np.asarray(time, dtype="datetime64[ns]"), "component": ["x", "y"]},
        name="position",
    )
    source = SopranArray(
        name="position",
        time=spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:20Z"),
        schema=spn.VariableSchema(
            name="position",
            dims=("time", "component"),
            units="km",
            frame="MOON_ME",
        ),
        xr=source_xr,
    )
    target = _array(
        "counts",
        ["2008-01-01T00:00:09", "2008-01-01T00:00:11"],
        [1.0, 1.0],
    )

    result = spn.resample_like(source, target, method="nearest", tolerance="2s")

    assert result.to_xarray().dims == ("time", "component")
    assert result.to_xarray().coords["component"].values.tolist() == ["x", "y"]
    np.testing.assert_allclose(
        result.to_xarray().values,
        np.asarray([[3.0, 4.0], [3.0, 4.0]]),
    )


def test_resample_like_accepts_xarray_datasets() -> None:
    source = xr.Dataset(
        {
            "altitude": (
                ("time",),
                np.asarray([100.0, 110.0, 120.0]),
            )
        },
        coords={
            "time": np.asarray(
                [
                    "2008-01-01T00:00:00",
                    "2008-01-01T00:00:10",
                    "2008-01-01T00:00:20",
                ],
                dtype="datetime64[ns]",
            )
        },
    )
    target = xr.Dataset(
        coords={
            "time": np.asarray(
                ["2008-01-01T00:00:09", "2008-01-01T00:00:25"],
                dtype="datetime64[ns]",
            )
        }
    )

    result = spn.resample_like(source, target, method="nearest", tolerance="2s")

    assert isinstance(result, xr.Dataset)
    np.testing.assert_allclose(
        result["altitude"].values,
        np.asarray([110.0, np.nan]),
        equal_nan=True,
    )


def test_resample_like_accepts_pandas_frames_with_time_column() -> None:
    source = pd.DataFrame(
        {
            "time": pd.to_datetime(
                [
                    "2008-01-01T00:00:00Z",
                    "2008-01-01T00:00:10Z",
                    "2008-01-01T00:00:20Z",
                ],
                utc=True,
            ),
            "altitude": [100.0, 110.0, 130.0],
        }
    )
    target = pd.DataFrame(
        {
            "time": pd.to_datetime(
                ["2008-01-01T00:00:09Z", "2008-01-01T00:00:25Z"],
                utc=True,
            )
        }
    )

    result = spn.resample_like(source, target, method="nearest", tolerance="2s")

    assert isinstance(result, pd.DataFrame)
    np.testing.assert_array_equal(
        result["time"].to_numpy(dtype="datetime64[ns]"),
        target["time"].dt.tz_convert(None).to_numpy(dtype="datetime64[ns]"),
    )
    np.testing.assert_allclose(
        result["altitude"].to_numpy(),
        np.asarray([110.0, np.nan]),
        equal_nan=True,
    )


def test_resample_like_accepts_polars_lazyframes() -> None:
    pl = pytest.importorskip("polars")
    source = pl.DataFrame(
        {
            "time": [
                datetime(2008, 1, 1, 0, 0, 0, tzinfo=UTC),
                datetime(2008, 1, 1, 0, 0, 10, tzinfo=UTC),
            ],
            "altitude": [100.0, 110.0],
        }
    ).lazy()
    target = pl.DataFrame(
        {
            "time": [
                datetime(2008, 1, 1, 0, 0, 9, tzinfo=UTC),
                datetime(2008, 1, 1, 0, 0, 20, tzinfo=UTC),
            ]
        }
    ).lazy()

    result = spn.resample_like(source, target, method="nearest", tolerance="2s")

    assert isinstance(result, pl.DataFrame)
    np.testing.assert_allclose(
        result["altitude"].to_numpy(),
        np.asarray([110.0, np.nan]),
        equal_nan=True,
    )


def test_resample_like_sopran_array_infers_timerange_from_pandas_target() -> None:
    source = _array(
        "altitude",
        ["2008-01-01T00:00:00", "2008-01-01T00:00:10"],
        [100.0, 110.0],
    )
    target = pd.DataFrame(
        {
            "time": pd.to_datetime(
                ["2008-01-01T00:00:05Z"],
                utc=True,
            )
        }
    )

    result = spn.resample_like(source, target, method="nearest", tolerance="10s")

    assert result.time.start_iso == "2008-01-01T00:00:05Z"
    assert result.time.stop > result.time.start
    assert result.time.stop == datetime(
        2008,
        1,
        1,
        0,
        0,
        5,
        tzinfo=UTC,
    ) + timedelta(microseconds=1)
    assert result.metadata["time_range"] == {
        "start": result.time.start_iso,
        "stop": "2008-01-01T00:00:05.000001Z",
    }


def test_resample_like_sopran_array_accepts_timezone_aware_pandas_target() -> None:
    source = _array(
        "altitude",
        ["2008-01-01T00:00:00", "2008-01-01T00:00:10"],
        [100.0, 110.0],
    )
    target = pd.DataFrame(
        {
            "time": pd.to_datetime(
                ["2008-01-01T00:00:05Z", "2008-01-01T00:00:10Z"],
                utc=True,
            )
        }
    )

    result = source.resample_like(target, method="linear")

    np.testing.assert_array_equal(
        result.to_xarray().coords["time"].values,
        np.asarray(
            ["2008-01-01T00:00:05", "2008-01-01T00:00:10"],
            dtype="datetime64[ns]",
        ),
    )
    np.testing.assert_allclose(result.to_xarray().values, np.asarray([105.0, 110.0]))
    assert result.time.start_iso == "2008-01-01T00:00:05Z"
    assert result.time.stop == datetime(
        2008,
        1,
        1,
        0,
        0,
        10,
        tzinfo=UTC,
    ) + timedelta(microseconds=1)


def test_resample_like_rejects_target_without_time_coordinate() -> None:
    source = _array(
        "altitude",
        ["2008-01-01T00:00:00", "2008-01-01T00:00:10"],
        [100.0, 110.0],
    )
    target = SopranArray(
        name="target",
        time=source.time,
        schema=spn.VariableSchema(name="target", dims=("sample",)),
        xr=xr.DataArray(np.asarray([1.0]), dims=("sample",), name="target"),
    )

    with pytest.raises(ValueError, match="target has no 'time' coordinate"):
        source.resample_like(target)


def test_resample_like_rejects_duplicate_xarray_source_times() -> None:
    source = SopranArray(
        name="altitude",
        time=spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:01Z"),
        schema=spn.VariableSchema(name="altitude", dims=("time",)),
        xr=xr.DataArray(
            np.asarray([100.0, 110.0]),
            dims=("time",),
            coords={
                "time": np.asarray(
                    ["2008-01-01T00:00:00", "2008-01-01T00:00:00"],
                    dtype="datetime64[ns]",
                )
            },
            name="altitude",
        ),
    )
    target = pd.DataFrame(
        {"time": pd.to_datetime(["2008-01-01T00:00:00Z"], utc=True)}
    )

    with pytest.raises(ValueError, match="source time values must be unique"):
        source.resample_like(target)


def test_resample_like_rejects_duplicate_pandas_source_time_columns() -> None:
    source = pd.DataFrame(
        [
            [
                pd.Timestamp("2008-01-01T00:00:00Z"),
                pd.Timestamp("2008-01-01T00:00:01Z"),
                100.0,
            ],
        ],
        columns=["time", "time", "altitude"],
    )
    target = pd.DataFrame(
        {"time": pd.to_datetime(["2008-01-01T00:00:00Z"], utc=True)}
    )

    with pytest.raises(ValueError, match="source columns must be unique: time"):
        spn.resample_like(source, target, method="nearest")


def test_resample_like_rejects_duplicate_pandas_source_value_columns() -> None:
    source = pd.DataFrame(
        [
            [pd.Timestamp("2008-01-01T00:00:00Z"), 100.0, 101.0],
            [pd.Timestamp("2008-01-01T00:00:10Z"), 110.0, 111.0],
        ],
        columns=["time", "altitude", "altitude"],
    )
    target = pd.DataFrame(
        {"time": pd.to_datetime(["2008-01-01T00:00:00Z"], utc=True)}
    )

    with pytest.raises(ValueError, match="source columns must be unique: altitude"):
        spn.resample_like(source, target, method="linear")


def test_resample_like_rejects_duplicate_pandas_target_time_columns() -> None:
    source = pd.DataFrame(
        {
            "time": pd.to_datetime(["2008-01-01T00:00:00Z"], utc=True),
            "altitude": [100.0],
        }
    )
    target = pd.DataFrame(
        [
            [
                pd.Timestamp("2008-01-01T00:00:00Z"),
                pd.Timestamp("2008-01-01T00:00:01Z"),
            ],
        ],
        columns=["time", "time"],
    )

    with pytest.raises(ValueError, match="target columns must be unique: time"):
        spn.resample_like(source, target, method="nearest")


def _array(name: str, time_values: list[str], values: list[float]) -> SopranArray:
    array = xr.DataArray(
        np.asarray(values, dtype=float),
        dims=("time",),
        coords={"time": np.asarray(time_values, dtype="datetime64[ns]")},
        name=name,
    )
    return SopranArray(
        name=name,
        time=spn.period(
            f"{time_values[0]}Z",
            f"{time_values[-1]}Z",
        ),
        schema=spn.VariableSchema(name=name, dims=("time",)),
        xr=array,
    )
