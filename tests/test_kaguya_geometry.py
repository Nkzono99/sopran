from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr

import sopran as spn
from sopran import Store
from sopran.missions.kaguya.geometry import (
    KaguyaMagneticConnectionData,
    lmag_magnetic_connection,
)


def test_kaguya_orbit_geometry_loads_from_lmag_native_time(tmp_path) -> None:
    store = Store(tmp_path / "store")
    _write_lmag_file(store)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.day("2008-01-01")

    position = kg.orbit.position.load(time, cache="never")
    position_gse = kg.orbit.position_gse.load(time, cache="never")
    position_me = kg.orbit.position.load(time, cache="never", frame="MOON_ME")
    radial_distance = kg.orbit.radial_distance.load(time, cache="never")
    radius_alias = kg.orbit.radius.load(time, cache="never")
    altitude = kg.orbit.altitude.load(time, cache="never")
    subpoint = kg.orbit.subpoint.load(time, cache="never")

    assert position.to_xarray().dims == ("time", "component")
    assert kg.orbit.position.schema().aliases == ("rme", "r_moon_me")
    assert position.to_xarray().coords["component"].values.tolist() == ["x", "y", "z"]
    np.testing.assert_allclose(
        position.to_xarray().values[0],
        np.asarray([1837.4, 0.0, 0.0]),
    )
    assert position_gse.to_xarray().attrs["frame"] == "GSE"
    np.testing.assert_allclose(
        position_gse.to_xarray().values[0],
        np.asarray([10.0, 20.0, 30.0]),
    )
    assert position_me.to_xarray().attrs["frame"] == "MOON_ME"
    assert position_me.schema.frame == "MOON_ME"
    np.testing.assert_allclose(
        radial_distance.to_xarray().values,
        np.asarray([1837.4, 1837.4, 1837.4]),
        atol=1e-9,
    )
    assert radial_distance.schema.units == "km"
    np.testing.assert_allclose(
        radius_alias.to_xarray().values,
        radial_distance.to_xarray().values,
        atol=1e-9,
    )
    np.testing.assert_allclose(
        altitude.to_xarray().values,
        np.asarray([100.0, 100.0, 100.0]),
        atol=1e-9,
    )
    assert subpoint.to_xarray().coords["component"].values.tolist() == ["lon", "lat"]
    np.testing.assert_allclose(
        subpoint.to_xarray().values[:2],
        np.asarray([[0.0, 0.0], [90.0, 0.0]]),
        atol=1e-9,
    )


def test_kaguya_orbit_sza_requires_sun_vector_and_computes_spherical_angle(tmp_path) -> None:
    store = Store(tmp_path / "store")
    _write_lmag_file(store)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.day("2008-01-01")

    with pytest.raises(ValueError, match="sun_vector"):
        kg.orbit.sza.load(time, cache="never")

    sza = kg.orbit.sza.load(time, cache="never", sun_vector=(1.0, 0.0, 0.0))

    assert sza.to_xarray().dims == ("time",)
    assert sza.to_xarray().attrs["sun_frame"] == "MOON_ME"
    np.testing.assert_allclose(
        sza.to_xarray().values,
        np.asarray([0.0, 90.0, 0.0]),
        atol=1e-9,
    )


def test_kaguya_orbit_sza_cache_variant_includes_non_identity_context(tmp_path) -> None:
    store = Store(tmp_path / "store")
    _write_lmag_file(store)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.day("2008-01-01")

    first = kg.orbit.sza.load(
        time,
        sun_vector=(1.0, 0.0, 0.0),
        sun_frame="GSE",
        context=_SunContext("x", (1.0, 0.0, 0.0)),
        cache="use",
    )
    second = kg.orbit.sza.load(
        time,
        sun_vector=(1.0, 0.0, 0.0),
        sun_frame="GSE",
        context=_SunContext("y", (0.0, 1.0, 0.0)),
        cache="use",
    )

    np.testing.assert_allclose(first.to_xarray().values[0], 0.0, atol=1e-9)
    np.testing.assert_allclose(second.to_xarray().values[0], 90.0, atol=1e-9)
    rows = store.datasets(layer="features", refresh=True).to_dicts()
    assert sum(row["dataset_id"] == "kaguya.orbit.sza" for row in rows) == 2


def test_kaguya_lmag_magnetic_connection_uses_straight_field_line(tmp_path) -> None:
    store = Store(tmp_path / "store")
    _write_lmag_file(store)
    kg = spn.Kaguya(store=store, download="never")

    connection = kg.lmag.magnetic_connection.load(
        spn.day("2008-01-01"),
        radius_km=1737.4,
        cache="never",
    )
    frame = connection.to_polars()

    assert frame.select("connected_any").to_series().to_list() == [True, True, False]
    assert frame.select("connected_plus").to_series().to_list() == [True, False, False]
    assert frame.select("connected_minus").to_series().to_list() == [False, True, False]
    np.testing.assert_allclose(
        frame.select("footpoint_plus_lon").to_series().to_numpy(),
        np.asarray([0.0, np.nan, np.nan]),
        equal_nan=True,
    )
    np.testing.assert_allclose(
        frame.select("distance_plus_km").to_series().to_numpy(),
        np.asarray([100.0, np.nan, np.nan]),
        equal_nan=True,
    )
    np.testing.assert_allclose(
        frame.select("incidence_angle_plus_deg").to_series().to_numpy(),
        np.asarray([0.0, np.nan, np.nan]),
        equal_nan=True,
    )
    assert connection.to_xarray().attrs["field_model"] == "straight_local_field_line"


def test_kaguya_magnetic_connection_load_passes_missing_error(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"), download="never")

    with pytest.raises(FileNotFoundError, match="No local KAGUYA LMAG raw files found"):
        kg.lmag.magnetic_connection.load(
            spn.day("2008-01-01"),
            cache="never",
            missing="error",
        )


def test_kaguya_orbit_geometry_does_not_cache_missing_lmag_data(tmp_path) -> None:
    store = Store(tmp_path / "store")
    kg = spn.Kaguya(store=store, download="never")

    altitude = kg.orbit.altitude.load(spn.day("2008-01-01"), cache="use")

    assert altitude.to_xarray().sizes["time"] == 0
    rows = store.datasets(layer="features", refresh=True).to_dicts()
    assert all(row["dataset_id"] != "kaguya.orbit.altitude" for row in rows)


def test_kaguya_magnetic_connection_does_not_cache_missing_lmag_data(tmp_path) -> None:
    store = Store(tmp_path / "store")
    kg = spn.Kaguya(store=store, download="never")

    connection = kg.lmag.magnetic_connection.load(spn.day("2008-01-01"), cache="use")

    assert connection.to_xarray().sizes["time"] == 0
    rows = store.datasets(layer="features", refresh=True).to_dicts()
    assert all(row["dataset_id"] != "kaguya.lmag.magnetic_connection" for row in rows)


def test_kaguya_geometry_does_not_cache_partial_lmag_coverage(tmp_path) -> None:
    store = Store(tmp_path / "store")
    _write_lmag_file(store)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.period("2008-01-01", "2008-01-03")

    with pytest.warns(UserWarning, match="Missing local KAGUYA LMAG raw files"):
        altitude = kg.orbit.altitude.load(time, cache="use", missing="warn")
    with pytest.warns(UserWarning, match="Missing local KAGUYA LMAG raw files"):
        connection = kg.lmag.magnetic_connection.load(time, cache="use", missing="warn")

    assert altitude.to_xarray().sizes["time"] == 3
    assert connection.to_xarray().sizes["time"] == 3
    rows = store.datasets(layer="features", refresh=True).to_dicts()
    assert all(row["dataset_id"] != "kaguya.orbit.altitude" for row in rows)
    assert all(row["dataset_id"] != "kaguya.lmag.magnetic_connection" for row in rows)


def test_kaguya_orbit_geometry_load_passes_missing_error(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"), download="never")

    with pytest.raises(FileNotFoundError, match="No local KAGUYA LMAG raw files found"):
        kg.orbit.altitude.load(
            spn.day("2008-01-01"),
            cache="never",
            missing="error",
        )


def test_kaguya_magnetic_connection_preserves_subsecond_row_times() -> None:
    time = spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:00.000001Z")
    sample_time = np.asarray(["2008-01-01T00:00:00.000001"], dtype="datetime64[ns]")
    dataset = xr.Dataset(
        {
            "position_moon_me": (("time", "component"), np.asarray([[1837.4, 0.0, 0.0]])),
            "magnetic_field_moon_me": (
                ("time", "component"),
                np.asarray([[-1.0, 0.0, 0.0]]),
            ),
        },
        coords={"time": sample_time, "component": ["x", "y", "z"]},
    )
    data = SimpleNamespace(
        time=time,
        files=(),
        to_xarray=lambda: dataset,
    )

    connection = lmag_magnetic_connection(data, radius_km=1737.4, direction="plus")

    assert connection.to_polars().select("time").to_series().to_list() == [
        "2008-01-01T00:00:00.000001Z"
    ]


def test_kaguya_magnetic_connection_resample_like_infers_pandas_target_time_range() -> None:
    source_time = spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:20Z")
    connection = KaguyaMagneticConnectionData(
        rows=(
            {"time": "2008-01-01T00:00:00Z", "connected_plus": True},
            {"time": "2008-01-01T00:00:10Z", "connected_plus": False},
        ),
        time=source_time,
    )
    target = pd.DataFrame(
        {"time": pd.to_datetime(["2008-01-01T00:00:05Z"], utc=True)}
    )

    result = connection.resample_like(target, method="nearest", tolerance="10s")

    assert result.time.start_iso == "2008-01-01T00:00:05Z"
    assert result.time.stop_iso == "2008-01-01T00:00:05.000001Z"


def test_kaguya_magnetic_connection_resample_like_infers_polars_lazy_target_time_range() -> None:
    pl = pytest.importorskip("polars")
    source_time = spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:20Z")
    connection = KaguyaMagneticConnectionData(
        rows=(
            {"time": "2008-01-01T00:00:00Z", "connected_any": True},
            {"time": "2008-01-01T00:00:10Z", "connected_any": False},
        ),
        time=source_time,
    )
    target = pl.DataFrame(
        {"time": [datetime(2008, 1, 1, 0, 0, 5, tzinfo=UTC)]}
    ).lazy()

    result = connection.resample_like(target, method="nearest", tolerance="10s")

    assert result.time.start_iso == "2008-01-01T00:00:05Z"
    assert result.time.stop_iso == "2008-01-01T00:00:05.000001Z"


def test_kaguya_magnetic_connection_from_pandas_fills_connected_any() -> None:
    frame = pd.DataFrame(
        {
            "time": ["2008-01-01T00:00:00Z", "2008-01-01T00:00:10Z"],
            "connected_plus": [False, False],
            "connected_minus": [True, False],
            "altitude_km": [100.0, 101.0],
        }
    )

    connection = KaguyaMagneticConnectionData.from_pandas(
        frame,
        time_range=spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:20Z"),
    )

    assert connection.to_polars().select("connected_any").to_series().to_list() == [
        True,
        False,
    ]


def test_kaguya_lmag_gse_magnetic_field_endpoint_reads_public_bgse_columns(tmp_path) -> None:
    store = Store(tmp_path / "store")
    _write_lmag_file(store)
    kg = spn.Kaguya(store=store, download="never")

    bgse = kg.lmag.magnetic_field_gse.load(spn.day("2008-01-01"))

    assert bgse.to_xarray().attrs["frame"] == "GSE"
    np.testing.assert_allclose(
        bgse.to_xarray().values[0],
        np.asarray([1.0, 2.0, 3.0]),
    )
    assert kg.lmag.bgse.load(spn.day("2008-01-01")).to_xarray().identical(bgse.to_xarray())


def test_kaguya_lmag_magnetic_connection_direction_filters_direction_columns(tmp_path) -> None:
    store = Store(tmp_path / "store")
    _write_lmag_file(store)
    kg = spn.Kaguya(store=store, download="never")

    plus = kg.lmag.magnetic_connection.load(
        spn.day("2008-01-01"),
        radius_km=1737.4,
        direction="plus",
        cache="never",
    )
    minus = kg.lmag.magnetic_connection.load(
        spn.day("2008-01-01"),
        radius_km=1737.4,
        direction="minus",
        cache="never",
    )

    assert "connected_plus" in plus.to_polars().columns
    assert "connected_minus" not in plus.to_polars().columns
    assert "connected_minus" in minus.to_polars().columns
    assert "connected_plus" not in minus.to_polars().columns
    assert plus.plot(kind="footpoint") is not None
    assert plus.plot(kind="incidence") is not None
    assert plus.plot(kind="distance") is not None


def test_kaguya_lmag_magnetic_connection_empty_data_preserves_columns(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"), download="never")

    connection = kg.lmag.magnetic_connection.load(
        spn.day("2008-01-01"),
        cache="never",
    )

    assert connection.to_polars().columns == [
        "time",
        "connected_any",
        "connected_plus",
        "footpoint_plus_lon",
        "footpoint_plus_lat",
        "distance_plus_km",
        "incidence_angle_plus_deg",
        "connected_minus",
        "footpoint_minus_lon",
        "footpoint_minus_lat",
        "distance_minus_km",
        "incidence_angle_minus_deg",
        "altitude_km",
    ]
    assert connection.to_xarray().sizes["time"] == 0


def test_kaguya_lmag_magnetic_connection_uses_store_cache(tmp_path) -> None:
    store = Store(tmp_path / "store")
    lmag_file = _write_lmag_file(store)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.day("2008-01-01")

    first = kg.lmag.magnetic_connection.load(time, radius_km=1737.4, cache="use")
    lmag_file.unlink()
    cached = kg.lmag.magnetic_connection.load(time, radius_km=1737.4, cache="use")

    assert first.to_polars().to_dicts() == cached.to_polars().to_dicts()
    record = store.dataset(
        "kaguya.lmag.magnetic_connection",
        layer="features",
        variant_id="sphere_r1737_4_moon_me_both_v1",
    )
    assert record.manifest()["variant"]["field_model"] == "straight_local_field_line"


def test_kaguya_orbit_vector_products_use_store_cache(tmp_path) -> None:
    store = Store(tmp_path / "store")
    lmag_file = _write_lmag_file(store)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.day("2008-01-01")

    first_position = kg.orbit.position.load(time, cache="use")
    first_position_gse = kg.orbit.position_gse.load(time, cache="use")
    first_radial_distance = kg.orbit.radial_distance.load(time, cache="use")
    first_subpoint = kg.orbit.subpoint.load(time, cache="use")
    lmag_file.unlink()
    cached_position = kg.orbit.position.load(time, cache="use")
    cached_position_gse = kg.orbit.position_gse.load(time, cache="use")
    cached_radial_distance = kg.orbit.radial_distance.load(time, cache="use")
    cached_subpoint = kg.orbit.subpoint.load(time, cache="use")

    np.testing.assert_allclose(
        cached_position.to_xarray().values,
        first_position.to_xarray().values,
    )
    assert cached_position.to_xarray().coords["component"].values.tolist() == [
        "x",
        "y",
        "z",
    ]
    np.testing.assert_allclose(
        cached_position_gse.to_xarray().values,
        first_position_gse.to_xarray().values,
    )
    assert cached_position_gse.to_xarray().attrs["frame"] == "GSE"
    np.testing.assert_allclose(
        cached_radial_distance.to_xarray().values,
        first_radial_distance.to_xarray().values,
    )
    np.testing.assert_allclose(
        cached_subpoint.to_xarray().values,
        first_subpoint.to_xarray().values,
    )
    assert cached_subpoint.to_xarray().coords["component"].values.tolist() == [
        "lon",
        "lat",
    ]


def test_kaguya_geometry_rejects_unknown_cache_policy(tmp_path) -> None:
    store = Store(tmp_path / "store")
    _write_lmag_file(store)
    kg = spn.Kaguya(store=store, download="never")

    with pytest.raises(ValueError, match="cache"):
        kg.orbit.altitude.load(spn.day("2008-01-01"), cache="sometimes")


def test_kaguya_scalar_geometry_rejects_non_native_frame_transform(tmp_path) -> None:
    store = Store(tmp_path / "store")
    _write_lmag_file(store)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.day("2008-01-01")

    altitude = kg.orbit.altitude.load(time, cache="never", frame="MOON_ME")

    assert altitude.schema.frame == "MOON_ME"
    with pytest.raises(ValueError, match="frame transform is only supported"):
        kg.orbit.altitude.load(time, cache="never", frame="GSE")


def _write_lmag_file(store: Store):
    path = (
        store.raw_path("kaguya", "pds3")
        / "sln-l-lmag-3-mag-ts-v1.0"
        / "nominal"
        / "20080101"
        / "data"
        / "MAG_TS20080101.dat"
    )
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                # plus direction along B hits the sphere at lon=0, lat=0.
                "2008-01-01 00:00:00 1837.4 0 0 -1 0 0 10 20 30 1 2 3",
                # minus direction along -B hits the sphere at lon=90, lat=0.
                "2008-01-01 00:00:10 0 1837.4 0 0 1 0 40 50 60 4 5 6",
                # tangent field line does not intersect the spherical surface.
                "2008-01-01 00:00:20 1837.4 0 0 0 1 0 70 80 90 7 8 9",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


class _SunContext:
    def __init__(self, name: str, output_vector: tuple[float, float, float]) -> None:
        self.name = name
        self.output_vector = output_vector

    def metadata(self) -> dict[str, str]:
        return {"test_context": self.name}

    def transform_vectors(self, vectors, **_kwargs):
        return np.broadcast_to(np.asarray(self.output_vector), np.asarray(vectors).shape)
