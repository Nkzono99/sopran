from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError

import numpy as np
import pytest
from cdflib import cdfepoch, cdfwrite

import sopran as spn
from sopran import Store
from sopran.core.errors import DatasetNotFoundError
from sopran.missions.kaguya import read_lrs_public
from sopran.missions.kaguya.schema import KAGUYA_LRS_SCHEMA


def test_kaguya_lrs_query_builds_npw_and_wfc_public_paths(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))
    time = spn.period("2008-04-01T00:30:00Z", "2008-04-01T04:10:00Z")

    assert kg.lrs.remote_files("2008-03-10", kind="NPW") == [
        "sln-l-lrs-5-npw-spectrum-v1.0/20080310/data/LRS_NPW_V010_20080310.cdf"
    ]
    assert kg.lrs.remote_files(time.start, time.stop, kind="WFC") == [
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/LRS_WFC_V010_20080401000000.cdf",
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/LRS_WFC_V010_20080401020000.cdf",
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/LRS_WFC_V010_20080401040000.cdf",
    ]
    assert kg.lrs.remote_files(
        datetime(2008, 4, 1, 0, 0, tzinfo=UTC),
        datetime(2008, 4, 1, 2, 0, tzinfo=UTC),
        kind="WFC",
    ) == [
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/LRS_WFC_V010_20080401000000.cdf"
    ]
    assert kg.lrs.remote_files(
        datetime(2008, 4, 1, 1, 0, tzinfo=UTC),
        datetime(2008, 4, 1, 1, 30, tzinfo=UTC),
        kind="WFC",
    ) == [
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/LRS_WFC_V010_20080401000000.cdf"
    ]
    assert kg.lrs.remote_files(
        datetime(2008, 4, 1, 1, 30, tzinfo=UTC),
        datetime(2008, 4, 1, 2, 10, tzinfo=UTC),
        kind="WFC",
    ) == [
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/LRS_WFC_V010_20080401000000.cdf",
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/LRS_WFC_V010_20080401020000.cdf",
    ]


def test_kaguya_lrs_npw_endpoint_loads_cdf_and_filters_half_open_time(tmp_path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-lrs-5-npw-spectrum-v1.0/20080401/data/LRS_NPW_V010_20080401.cdf"
    path = store.raw_path("kaguya", "pds3") / remote_file
    _write_npw_cdf(path)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.period("2008-04-01T00:00:00Z", "2008-04-01T00:02:00Z")

    data = read_lrs_public(path, time=time)
    rx1 = kg.lrs.npw_rx1.load(time)
    rx1_group_alias = kg.lrs.npw.rx1.load(time)
    mode = kg.lrs.npw_mode.load(time)

    assert data.instrument == "LRS"
    assert rx1.name == "npw_rx1"
    assert rx1_group_alias.to_xarray().identical(rx1.to_xarray())
    assert rx1.to_xarray().dims == ("time", "frequency")
    assert rx1.to_xarray().coords["frequency"].attrs["units"] == "kHz"
    assert rx1.to_xarray().shape == (2, 3)
    np.testing.assert_allclose(
        rx1.to_xarray().values,
        np.asarray([[1.0, 2.0, np.nan], [4.0, 5.0, 6.0]]),
        equal_nan=True,
    )
    assert mode.to_xarray().values.tolist() == [7, 8]
    np.testing.assert_array_equal(
        rx1.to_xarray().coords["time"].values,
        np.asarray(
            [
                np.datetime64("2008-04-01T00:00:00.000000000"),
                np.datetime64("2008-04-01T00:01:00.000000000"),
            ],
            dtype="datetime64[ns]",
        ),
    )


def test_kaguya_lrs_wfc_derived_products_match_spedas_formulas(tmp_path) -> None:
    store = Store(tmp_path / "store")
    remote_file = (
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/"
        "LRS_WFC_V010_20080401000000.cdf"
    )
    path = store.raw_path("kaguya", "pds3") / remote_file
    _write_wfc_cdf(path)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.period("2008-04-01T00:00:00Z", "2008-04-01T00:03:00Z")

    gain = kg.lrs.wfc_gain.load(time)
    ey_field = kg.lrs.wfc_ey_field.load(time)
    ey_power = kg.lrs.wfc_ey_power_spectral_density.load(time)
    xymode = kg.lrs.wfc_xymode.load(time)

    np.testing.assert_allclose(gain.to_xarray().values, np.asarray([40.0, 20.0, 0.0]))
    raw_ey = np.asarray(
        [
            [50.0, 55.0, 60.0],
            [70.0, 75.0, 80.0],
            [90.0, 95.0, 100.0],
        ]
    )
    expected_field = raw_ey - np.asarray([40.0, 20.0, 0.0]).reshape(-1, 1) + 4.5
    expected_power = 10.0 ** (expected_field / 10.0 - 12.0) / 10_000.0

    assert ey_field.to_xarray().attrs["units"] == "dB uV/m"
    assert ey_power.to_xarray().attrs["units"] == "(V/m)^2/Hz"
    assert ey_power.to_xarray().attrs["dfreq_hz"] == [10_000.0, 10_000.0, 10_000.0]
    np.testing.assert_allclose(ey_field.to_xarray().values, expected_field)
    np.testing.assert_allclose(ey_power.to_xarray().values, expected_power)
    np.testing.assert_allclose(xymode.to_xarray().values, np.asarray([0.0, 1.0, 2.0]))


def test_kaguya_lrs_schema_accepts_spedas_wfc_aliases() -> None:
    assert KAGUYA_LRS_SCHEMA.variable("kgy_lrs_wfc_Ex").name == "wfc_ex_db"
    assert KAGUYA_LRS_SCHEMA.variable("kgy_lrs_wfc_Ey").name == "wfc_ey_db"
    assert KAGUYA_LRS_SCHEMA.variable("kgy_lrs_wfc_Ex_dB").name == "wfc_ex_db"
    assert KAGUYA_LRS_SCHEMA.variable("kgy_lrs_wfc_Ey_dB").name == "wfc_ey_db"
    assert KAGUYA_LRS_SCHEMA.variable("kgy_lrs_wfc_Ex_phys").name == "wfc_ex_field"
    assert KAGUYA_LRS_SCHEMA.variable("kgy_lrs_wfc_Ey_phys").name == "wfc_ey_field"
    assert (
        KAGUYA_LRS_SCHEMA.variable("kgy_lrs_wfc_Ex_phys2").name
        == "wfc_ex_power_spectral_density"
    )
    assert (
        KAGUYA_LRS_SCHEMA.variable("kgy_lrs_wfc_Ey_phys2").name
        == "wfc_ey_power_spectral_density"
    )


def test_kaguya_lrs_load_all_preserves_independent_frequency_grids(tmp_path) -> None:
    store = Store(tmp_path / "store")
    npw_remote = "sln-l-lrs-5-npw-spectrum-v1.0/20080401/data/LRS_NPW_V010_20080401.cdf"
    wfc_remote = (
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/"
        "LRS_WFC_V010_20080401000000.cdf"
    )
    _write_npw_cdf(store.raw_path("kaguya", "pds3") / npw_remote)
    _write_wfc_cdf(
        store.raw_path("kaguya", "pds3") / wfc_remote,
        frequency=np.asarray([100.0, 200.0], dtype=float),
        values=np.asarray([[50.0, 55.0], [60.0, 65.0], [70.0, 75.0]], dtype=float),
    )
    kg = spn.Kaguya(store=store, download="never")
    time = spn.period("2008-04-01T00:00:00Z", "2008-04-01T00:03:00Z")

    data = kg.lrs.load(time, kind="all")

    np.testing.assert_allclose(
        data.npw_rx1.to_xarray().coords["frequency"].values,
        np.asarray([10.0, 20.0, 30.0]),
    )
    np.testing.assert_allclose(
        data.wfc_ey_db.to_xarray().coords["frequency"].values,
        np.asarray([100.0, 200.0]),
    )
    with pytest.raises(ValueError, match="different coordinates"):
        data.to_xarray()


def test_kaguya_lrs_partial_missing_files_respect_missing_error(tmp_path) -> None:
    store = Store(tmp_path / "store")
    remote_file = (
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/"
        "LRS_WFC_V010_20080401000000.cdf"
    )
    _write_wfc_cdf(store.raw_path("kaguya", "pds3") / remote_file)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.period("2008-04-01T00:00:00Z", "2008-04-01T04:00:00Z")

    with pytest.raises(FileNotFoundError, match="LRS WFC"):
        kg.lrs.load(time, kind="WFC", missing="error")

    with pytest.warns(UserWarning, match="Missing KAGUYA LRS WFC raw files"):
        data = kg.lrs.load(time, kind="WFC", missing="warn")

    assert data.missing_reason is not None
    assert "LRS_WFC_V010_20080401020000.cdf" in data.missing_reason


def test_kaguya_lrs_missing_empty_data_respects_requested_kind(tmp_path) -> None:
    store = Store(tmp_path / "store")
    kg = spn.Kaguya(store=store, download="never")
    time = spn.day("2008-04-01")

    npw = kg.lrs.load(time, kind="NPW")
    wfc = kg.lrs.load(time, kind="WFC")

    assert tuple(npw.arrays) == ("npw_rx1", "npw_rx2", "npw_mode")
    assert all(name.startswith("wfc_") for name in wfc.arrays)
    assert "npw_rx1" not in wfc.arrays


def test_kaguya_lrs_endpoint_does_not_cache_partial_missing_data(tmp_path) -> None:
    store = Store(tmp_path / "store")
    remote_file = (
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/"
        "LRS_WFC_V010_20080401000000.cdf"
    )
    _write_wfc_cdf(store.raw_path("kaguya", "pds3") / remote_file)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.period("2008-04-01T00:00:00Z", "2008-04-01T04:00:00Z")

    with pytest.warns(UserWarning, match="Missing KAGUYA LRS WFC raw files"):
        power = kg.lrs.wfc_ey_power_spectral_density.load(
            time,
            cache="use",
            missing="warn",
        )

    assert power.to_xarray().shape == (3, 3)
    with pytest.raises(DatasetNotFoundError, match="Dataset not found"):
        store.dataset("kaguya.lrs.wfc_ey_power_spectral_density", layer="features")


def test_kaguya_lrs_download_404_uses_missing_policy(tmp_path) -> None:
    class MissingSource:
        def __init__(self, root: Path) -> None:
            self.root = root

        def local_path(self, remote_file: str) -> Path:
            return self.root / remote_file

        def remote_url(self, remote_file: str) -> str:
            return f"https://example.invalid/{remote_file}"

        def download(self, remote_file: str, *, overwrite: bool = False) -> Path:
            raise HTTPError(self.remote_url(remote_file), 404, "not found", hdrs=None, fp=None)

    source = MissingSource(tmp_path / "raw")
    kg = spn.Kaguya(store=Store(tmp_path / "store"), source=source, download="missing")

    with pytest.warns(UserWarning, match="No local KAGUYA LRS NPW raw files"):
        data = kg.lrs.load(spn.day("2008-04-01"), kind="NPW", missing="warn")

    assert data.files == ()
    assert data.missing_reason is not None


def test_kaguya_lrs_wfc_field_uses_high_frequency_band_correction(tmp_path) -> None:
    store = Store(tmp_path / "store")
    remote_file = (
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/"
        "LRS_WFC_V010_20080401000000.cdf"
    )
    frequency = np.arange(1.0, 130.0)
    values = np.full((3, 129), 60.0, dtype=float)
    _write_wfc_cdf(
        store.raw_path("kaguya", "pds3") / remote_file,
        frequency=frequency,
        values=values,
    )
    kg = spn.Kaguya(store=store, download="never")
    time = spn.period("2008-04-01T00:00:00Z", "2008-04-01T00:03:00Z")

    field = kg.lrs.wfc_ex_field.load(time).to_xarray()

    assert field.values[0, 127] == pytest.approx(24.5)
    assert field.values[0, 128] == pytest.approx(14.5)


def test_kaguya_lrs_wfc_power_uses_nonzero_bandwidth_for_two_bin_band(tmp_path) -> None:
    store = Store(tmp_path / "store")
    remote_file = (
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/"
        "LRS_WFC_V010_20080401000000.cdf"
    )
    _write_wfc_cdf(
        store.raw_path("kaguya", "pds3") / remote_file,
        frequency=np.asarray([10.0, 20.0], dtype=float),
        values=np.full((3, 2), 60.0, dtype=float),
    )
    kg = spn.Kaguya(store=store, download="never")
    time = spn.period("2008-04-01T00:00:00Z", "2008-04-01T00:03:00Z")

    power = kg.lrs.wfc_ex_power_spectral_density.load(time).to_xarray()

    assert power.attrs["dfreq_hz"] == [10_000.0, 10_000.0]
    assert np.isfinite(power.values).all()


def test_kaguya_lrs_endpoint_uses_store_cache(tmp_path) -> None:
    store = Store(tmp_path / "store")
    remote_file = (
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/"
        "LRS_WFC_V010_20080401000000.cdf"
    )
    path = store.raw_path("kaguya", "pds3") / remote_file
    _write_wfc_cdf(path)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.period("2008-04-01T00:00:00Z", "2008-04-01T00:03:00Z")

    first = kg.lrs.wfc_ey_power_spectral_density.load(time, cache="use")
    path.unlink()
    cached = kg.lrs.wfc_ey_power_spectral_density.load(time, cache="use")

    np.testing.assert_allclose(cached.to_xarray().values, first.to_xarray().values)
    np.testing.assert_allclose(
        cached.to_xarray().coords["frequency"].values,
        np.asarray([10.0, 20.0, 30.0]),
    )
    assert cached.to_xarray().coords["frequency"].attrs["units"] == "kHz"
    assert cached.to_xarray().attrs["dfreq_hz"] == [10_000.0, 10_000.0, 10_000.0]
    record = store.dataset(
        "kaguya.lrs.wfc_ey_power_spectral_density",
        layer="features",
    )
    manifest = record.manifest()
    assert manifest["storage_layout"]["layout"] == "array"
    assert manifest["parameters"]["coordinates"]["frequency"] == [10.0, 20.0, 30.0]

    empty_window = spn.period("2008-04-01T00:00:30Z", "2008-04-01T00:00:45Z")
    empty_cached = kg.lrs.wfc_ey_power_spectral_density.load(empty_window, cache="use")
    assert empty_cached.to_xarray().shape == (0, 3)
    np.testing.assert_allclose(
        empty_cached.to_xarray().coords["frequency"].values,
        np.asarray([10.0, 20.0, 30.0]),
    )


def test_kaguya_lrs_cold_empty_cache_preserves_frequency_grid(tmp_path) -> None:
    store = Store(tmp_path / "store")
    remote_file = (
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/"
        "LRS_WFC_V010_20080401000000.cdf"
    )
    path = store.raw_path("kaguya", "pds3") / remote_file
    _write_wfc_cdf(path)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.period("2008-04-01T00:00:30Z", "2008-04-01T00:00:45Z")

    first = kg.lrs.wfc_ey_power_spectral_density.load(time, cache="refresh")
    path.unlink()
    cached = kg.lrs.wfc_ey_power_spectral_density.load(time, cache="use")

    assert first.to_xarray().shape == (0, 3)
    assert cached.to_xarray().shape == (0, 3)
    np.testing.assert_allclose(
        cached.to_xarray().coords["frequency"].values,
        np.asarray([10.0, 20.0, 30.0]),
    )
    record = store.dataset(
        "kaguya.lrs.wfc_ey_power_spectral_density",
        layer="features",
    )
    assert record.manifest()["parameters"]["coordinates"]["frequency"] == [
        10.0,
        20.0,
        30.0,
    ]


def test_kaguya_lrs_cache_reuses_subsecond_coverage_for_second_boundary_query(
    tmp_path,
) -> None:
    store = Store(tmp_path / "store")
    remote_file = (
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/"
        "LRS_WFC_V010_20080401000000.cdf"
    )
    path = store.raw_path("kaguya", "pds3") / remote_file
    _write_wfc_cdf(path)
    kg = spn.Kaguya(store=store, download="never")
    cached_window = spn.period(
        "2008-04-01T00:00:00Z",
        "2008-04-01T00:01:00.000001Z",
    )

    kg.lrs.wfc_ey_power_spectral_density.load(cached_window, cache="refresh")
    path.unlink()
    exact_window = spn.period("2008-04-01T00:00:00Z", "2008-04-01T00:01:00Z")
    cached = kg.lrs.wfc_ey_power_spectral_density.load(exact_window, cache="use")

    assert cached.to_xarray().shape == (1, 3)
    assert cached.time == exact_window


def test_kaguya_lrs_spectrogram_can_refresh_store_cache(tmp_path) -> None:
    store = Store(tmp_path / "store")
    remote_file = (
        "sln-l-lrs-4-wfc-spectrum-v1.0/20080401/data/"
        "LRS_WFC_V010_20080401000000.cdf"
    )
    path = store.raw_path("kaguya", "pds3") / remote_file
    _write_wfc_cdf(path)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.period("2008-04-01T00:00:00Z", "2008-04-01T00:03:00Z")
    first = kg.lrs.wfc_ey_power_spectral_density.load(time, cache="use")

    _write_wfc_cdf(path, values=np.full((3, 3), 120.0, dtype=float))
    item = kg.lrs.wfc.ey_power_spectral_density.spectrogram(
        time,
        y="frequency",
        cache="refresh",
    )
    result = spn.stack(item).plot()
    result.fig.clf()
    refreshed = kg.lrs.wfc_ey_power_spectral_density.load(time, cache="use")

    assert np.nanmin(refreshed.to_xarray().values - first.to_xarray().values) > 0.0


def test_kaguya_lrs_endpoint_cache_policy_can_be_disabled(tmp_path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-lrs-5-npw-spectrum-v1.0/20080401/data/LRS_NPW_V010_20080401.cdf"
    _write_npw_cdf(store.raw_path("kaguya", "pds3") / remote_file)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.period("2008-04-01T00:00:00Z", "2008-04-01T00:02:00Z")

    kg.lrs.npw_rx1.load(time, cache="never")

    with pytest.raises(DatasetNotFoundError, match="Dataset not found"):
        store.dataset("kaguya.lrs.npw_rx1", layer="normalized")


def _write_npw_cdf(path: Path) -> None:
    _write_cdf(
        path,
        {
            "Epoch": _epochs(
                [
                    datetime(2008, 4, 1, 0, 0, tzinfo=UTC),
                    datetime(2008, 4, 1, 0, 1, tzinfo=UTC),
                    datetime(2008, 4, 1, 0, 2, tzinfo=UTC),
                ]
            ),
            "Frequency": np.asarray([10.0, 20.0, 30.0], dtype=float),
            "RX1": np.asarray(
                [[1.0, 2.0, -1.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]],
                dtype=float,
            ),
            "RX2": np.asarray(
                [[11.0, 12.0, 13.0], [14.0, 15.0, 16.0], [17.0, 18.0, 19.0]],
                dtype=float,
            ),
            "Mode": np.asarray([7, 8, 9], dtype=np.int32),
        },
    )


def _write_wfc_cdf(
    path: Path,
    *,
    frequency: np.ndarray | None = None,
    values: np.ndarray | None = None,
) -> None:
    frequency = np.asarray([10.0, 20.0, 30.0], dtype=float) if frequency is None else frequency
    values = (
        np.asarray(
            [[50.0, 55.0, 60.0], [70.0, 75.0, 80.0], [90.0, 95.0, 100.0]],
            dtype=float,
        )
        if values is None
        else values
    )
    _write_cdf(
        path,
        {
            "Epoch": _epochs(
                [
                    datetime(2008, 4, 1, 0, 0, tzinfo=UTC),
                    datetime(2008, 4, 1, 0, 1, tzinfo=UTC),
                    datetime(2008, 4, 1, 0, 2, tzinfo=UTC),
                ]
            ),
            "Frequency": frequency,
            "Gain": np.asarray([0, 4, 12], dtype=np.int32),
            "Ex": values,
            "Ey": values,
            "Mode": np.asarray([0, 1, 2], dtype=np.int32),
            "PDC-TI": np.asarray([10, 11, 12], dtype=np.int32),
            "PostGap": np.asarray([20, 21, 22], dtype=np.int32),
        },
    )


def _write_cdf(path: Path, variables: dict[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cdf = cdfwrite.CDF(path, delete=True)
    try:
        cdf.write_var(
            {
                "Variable": "Epoch",
                "Data_Type": cdfwrite.CDF.CDF_EPOCH,
                "Num_Elements": 1,
                "Rec_Vary": True,
                "Dim_Sizes": [],
            },
            var_data=variables["Epoch"],
        )
        cdf.write_var(
            {
                "Variable": "Frequency",
                "Data_Type": cdfwrite.CDF.CDF_DOUBLE,
                "Num_Elements": 1,
                "Rec_Vary": False,
                "Dim_Sizes": [variables["Frequency"].shape[0]],
            },
            var_attrs={"UNITS": "kHz"},
            var_data=variables["Frequency"],
        )
        for name, values in variables.items():
            if name in {"Epoch", "Frequency"}:
                continue
            values = np.asarray(values)
            cdf.write_var(
                {
                    "Variable": name,
                    "Data_Type": _cdf_data_type(values),
                    "Num_Elements": 1,
                    "Rec_Vary": True,
                    "Dim_Sizes": list(values.shape[1:]),
                },
                var_attrs=_variable_attrs(name, values),
                var_data=values,
            )
    finally:
        cdf.close()


def _cdf_data_type(values: np.ndarray) -> int:
    if np.issubdtype(values.dtype, np.integer):
        return cdfwrite.CDF.CDF_INT4
    return cdfwrite.CDF.CDF_DOUBLE


def _variable_attrs(name: str, values: np.ndarray) -> dict[str, object]:
    if name in {"RX1", "RX2", "Ex", "Ey"}:
        return {"FILLVAL": [-1.0, "CDF_DOUBLE"], "UNITS": "dB"}
    if np.issubdtype(values.dtype, np.integer):
        return {"FILLVAL": [-2147483648, "CDF_INT4"]}
    return {}


def _epochs(values: list[datetime]) -> np.ndarray:
    return cdfepoch.compute_epoch(
        [
            [
                item.year,
                item.month,
                item.day,
                item.hour,
                item.minute,
                item.second,
                item.microsecond // 1000,
            ]
            for item in values
        ]
    )
