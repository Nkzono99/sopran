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


def test_time_bins_export_bin_table_and_metadata() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:24Z"),
        cadence="10s",
        partial="keep",
    )

    assert bins.to_polars().to_dicts() == [
        {
            "index": 0,
            "start": "2008-01-01T00:00:00Z",
            "stop": "2008-01-01T00:00:10Z",
            "center": "2008-01-01T00:00:05Z",
            "duration_seconds": 10.0,
            "is_partial": False,
        },
        {
            "index": 1,
            "start": "2008-01-01T00:00:10Z",
            "stop": "2008-01-01T00:00:20Z",
            "center": "2008-01-01T00:00:15Z",
            "duration_seconds": 10.0,
            "is_partial": False,
        },
        {
            "index": 2,
            "start": "2008-01-01T00:00:20Z",
            "stop": "2008-01-01T00:00:24Z",
            "center": "2008-01-01T00:00:22Z",
            "duration_seconds": 4.0,
            "is_partial": True,
        },
    ]
    assert bins.metadata()["durations_seconds"] == [10.0, 10.0, 4.0]
    assert bins.metadata()["is_partial"] == [False, False, True]


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


def test_align_quality_mask_drops_masked_bins() -> None:
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
    quality = xr.DataArray(
        np.array([1.0, 0.0]),
        dims=("time",),
        coords={
            "time": np.array(
                ["2008-01-01T00:00:04", "2008-01-01T00:00:16"],
                dtype="datetime64[ns]",
            )
        },
        name="quality",
    )

    aligned = spn.align(
        sza,
        grid=bins,
        method="nearest",
        tolerance="3s",
        quality_mask=quality,
    )

    assert aligned.quality_mask is True
    assert aligned.metadata()["quality_mask"] is True
    assert aligned.to_polars().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "sza": 70.0}
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


def test_align_center_samples_nearest_value_inside_each_bin() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:20Z"),
        cadence="10s",
    )
    sza = xr.DataArray(
        np.array([70.0, 75.0, 80.0]),
        dims=("time",),
        coords={
            "time": np.array(
                [
                    "2008-01-01T00:00:02",
                    "2008-01-01T00:00:07",
                    "2008-01-01T00:00:16",
                ],
                dtype="datetime64[ns]",
            )
        },
        name="sza",
    )

    aligned = spn.align(sza, grid=bins, method="center")

    assert aligned.to_polars().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "sza": 75.0},
        {"time": "2008-01-01T00:00:15Z", "sza": 80.0},
    ]


def test_sample_table_supports_first_and_last_bin_reducers() -> None:
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
        np.array([1.0, 3.0, 10.0, 20.0]),
        dims=("time",),
        coords={
            "time": np.array(
                [
                    "2008-01-01T00:00:01",
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
        .add(wave_power, method="first")
        .add(density, method="last")
        .collect()
    )

    assert result.to_polars().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "wave_power": 1.0, "density": 3.0},
        {"time": "2008-01-01T00:00:15Z", "wave_power": 10.0, "density": 20.0},
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


def test_alignment_result_exports_long_feature_table() -> None:
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
    )

    assert aligned.to_polars(layout="long").to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "feature": "sza", "value": 70.0},
        {"time": "2008-01-01T00:00:05Z", "feature": "wave_power", "value": 5.0},
    ]


def test_alignment_result_writes_long_parquet_feature_table(tmp_path) -> None:
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

    path = aligned.write_parquet(tmp_path / "features-long.parquet", layout="long")

    assert path == tmp_path / "features-long.parquet"
    assert pl.read_parquet(path).to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "feature": "sza", "value": 70.0}
    ]


def test_alignment_result_writes_feature_dataset_to_store(tmp_path) -> None:
    store = spn.Store(tmp_path / "store")
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
        tolerance="3s",
    )

    dataset = aligned.write_dataset(
        store,
        "analysis.wake_context",
        source_datasets=("kaguya.orbit.sza", "artemis.p1.efi.wave_power"),
    )

    assert dataset.manifest()["layer"] == "features"
    assert dataset.manifest()["mission"] == "analysis"
    assert dataset.manifest()["instrument"] == "alignment"
    assert dataset.manifest()["product"] == "wake_context"
    assert dataset.manifest()["source_datasets"] == [
        "kaguya.orbit.sza",
        "artemis.p1.efi.wave_power",
    ]
    assert dataset.manifest()["parameters"]["layout"] == "wide"
    assert dataset.manifest()["parameters"]["alignment"]["features"] == [
        {"column": "sza", "method": "nearest", "tolerance_seconds": 3.0},
        {"column": "wave_power", "method": "nearest", "tolerance_seconds": 3.0},
    ]
    assert dataset.schema()["variables"] == [
        {
            "name": "time",
            "dims": ["time"],
            "units": None,
            "dtype": None,
            "frame": None,
            "description": "Feature table bin center time.",
            "aliases": [],
        },
        {
            "name": "sza",
            "dims": ["time"],
            "units": None,
            "dtype": None,
            "frame": None,
            "description": "Aligned feature column.",
            "aliases": [],
        },
        {
            "name": "wave_power",
            "dims": ["time"],
            "units": None,
            "dtype": None,
            "frame": None,
            "description": "Aligned feature column.",
            "aliases": [],
        },
    ]
    assert dataset.scan().collect().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "sza": 70.0, "wave_power": 5.0}
    ]


def test_alignment_result_writes_to_database_product_reference(tmp_path) -> None:
    store = spn.Store(tmp_path / "store")
    target = store.database("lunar_wake").product("wake_context")
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

    dataset = aligned.write_dataset(target)

    assert dataset.root == store.database_path("lunar_wake", "wake_context")
    assert dataset.manifest()["dataset_id"] == "lunar_wake.wake_context"
    assert dataset.manifest()["layer"] == "databases"
    assert dataset.manifest()["mission"] == "analysis"
    assert dataset.manifest()["instrument"] == "alignment"
    assert dataset.manifest()["product"] == "wake_context"
    assert target.scan().collect().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "sza": 70.0}
    ]


def test_alignment_result_exposes_feature_table_metadata() -> None:
    bins = spn.time_bins(
        spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:24Z"),
        cadence="10s",
        partial="keep",
    )
    sza = xr.DataArray(
        np.array([70.0]),
        dims=("time",),
        coords={"time": np.array(["2008-01-01T00:00:04"], dtype="datetime64[ns]")},
        name="sza",
    )
    aligned = spn.align(
        sza,
        grid=bins,
        method="nearest",
        tolerance="3s",
        fill=-1.0,
    )

    assert aligned.metadata() == {
        "columns": ["sza"],
        "features": [
            {"column": "sza", "method": "nearest", "tolerance_seconds": 3.0}
        ],
        "fill": -1.0,
        "grid": {
            "closed": "left",
            "centers": [
                "2008-01-01T00:00:05Z",
                "2008-01-01T00:00:15Z",
                "2008-01-01T00:00:22Z",
            ],
            "count": 3,
            "durations_seconds": [10.0, 10.0, 4.0],
            "edges": [
                "2008-01-01T00:00:00Z",
                "2008-01-01T00:00:10Z",
                "2008-01-01T00:00:20Z",
                "2008-01-01T00:00:24Z",
            ],
            "is_partial": [False, False, True],
            "label": "center",
            "partial": "keep",
            "start": "2008-01-01T00:00:00Z",
            "stop": "2008-01-01T00:00:24Z",
        },
        "join": "outer",
        "method": "nearest",
        "quality_mask": False,
    }


def test_alignment_result_exports_ml_feature_frame_and_metadata() -> None:
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

    aligned = spn.align(sza, wave_power, grid=bins, method="mean", join="inner")

    assert aligned.to_feature_frame().to_dicts() == [
        {"sza": 70.0, "wave_power": 2.0},
        {"sza": 80.0, "wave_power": 10.0},
    ]
    assert aligned.to_feature_frame(include_time=True).to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "sza": 70.0, "wave_power": 2.0},
        {"time": "2008-01-01T00:00:15Z", "sza": 80.0, "wave_power": 10.0},
    ]
    assert aligned.feature_metadata() == {
        "columns": ["sza", "wave_power"],
        "features": [
            {"column": "sza", "method": "mean", "tolerance_seconds": None},
            {"column": "wave_power", "method": "mean", "tolerance_seconds": None},
        ],
        "grid": aligned.grid.metadata(),
        "rows": 2,
        "time_column": "time",
    }


def test_alignment_result_exports_feature_matrix_for_ml() -> None:
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

    aligned = spn.align(sza, wave_power, grid=bins, method="mean", join="inner")
    matrix = aligned.to_feature_matrix()

    assert isinstance(matrix, spn.FeatureMatrix)
    assert matrix.columns == ("sza", "wave_power")
    assert matrix.time == ("2008-01-01T00:00:05Z", "2008-01-01T00:00:15Z")
    assert matrix.shape == (2, 2)
    assert matrix.values.tolist() == [[70.0, 2.0], [80.0, 10.0]]
    assert matrix.metadata == aligned.feature_metadata()


def test_feature_matrix_exports_pandas_and_npz(tmp_path) -> None:
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
    matrix = spn.align(sza, wave_power, grid=bins, method="mean", join="inner").to_feature_matrix()

    assert matrix.to_pandas().to_dict(orient="records") == [
        {"sza": 70.0, "wave_power": 2.0},
        {"sza": 80.0, "wave_power": 10.0},
    ]
    assert matrix.to_pandas(include_time=True).to_dict(orient="records") == [
        {"time": "2008-01-01T00:00:05Z", "sza": 70.0, "wave_power": 2.0},
        {"time": "2008-01-01T00:00:15Z", "sza": 80.0, "wave_power": 10.0},
    ]

    path = matrix.write_npz(tmp_path / "features.npz")

    assert path == tmp_path / "features.npz"
    with np.load(path, allow_pickle=False) as data:
        assert data["values"].tolist() == [[70.0, 2.0], [80.0, 10.0]]
        assert data["columns"].tolist() == ["sza", "wave_power"]
        assert data["time"].tolist() == [
            "2008-01-01T00:00:05Z",
            "2008-01-01T00:00:15Z",
        ]
        assert "metadata_json" in data.files


def test_feature_matrix_reads_npz_round_trip(tmp_path) -> None:
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
    matrix = spn.align(sza, wave_power, grid=bins, method="mean", join="inner").to_feature_matrix()

    loaded = spn.FeatureMatrix.read_npz(matrix.write_npz(tmp_path / "features.npz"))

    assert loaded.columns == matrix.columns
    assert loaded.time == matrix.time
    assert loaded.shape == matrix.shape
    assert loaded.values.tolist() == matrix.values.tolist()
    assert loaded.metadata == matrix.metadata


def test_sample_table_metadata_records_feature_specific_rules() -> None:
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
        .add(wave_power, method="max")
        .collect()
    )

    assert result.metadata()["features"] == [
        {"column": "sza", "method": "nearest", "tolerance_seconds": 3.0},
        {"column": "wave_power", "method": "max", "tolerance_seconds": None},
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


def test_sample_table_quality_mask_drops_masked_bins() -> None:
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
    quality = xr.DataArray(
        np.array([1.0, 0.0]),
        dims=("time",),
        coords={
            "time": np.array(
                ["2008-01-01T00:00:04", "2008-01-01T00:00:16"],
                dtype="datetime64[ns]",
            )
        },
        name="quality",
    )

    result = (
        spn.SampleTable(bins)
        .add(sza, method="nearest", tolerance="3s")
        .collect(quality_mask=quality)
    )

    assert result.quality_mask is True
    assert result.to_polars().to_dicts() == [
        {"time": "2008-01-01T00:00:05Z", "sza": 70.0}
    ]
