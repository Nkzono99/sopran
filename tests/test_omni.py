import subprocess
import sys
from io import BytesIO
from urllib.error import HTTPError

import numpy as np
import pandas as pd
import pytest

import sopran as spn
from sopran.missions.omni import hourly


def test_import_without_optional_xarray():
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['xarray'] = None; import sopran; assert sopran.Omni",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def record(year=2008, doy=1, hour=0, *, fill_pressure=False):
    values = [0.0] * 55
    for _, (column, fill, _, _, _) in hourly._COLUMNS.items():
        values[column - 1] = fill
    values[:3] = [year, doy, hour]
    for column, value in {
        9: 8.0,
        13: 3.0,
        14: 4.0,
        15: 0.0,
        16: 2.0,
        17: -3.0,
        23: 123456.0,
        24: 5.0,
        25: 400.0,
        29: 1.37,
        39: 17,
        41: -25,
    }.items():
        values[column - 1] = value
    if fill_pressure:
        values[28] = 99.99
    return " ".join(map(str, values)) + "\n"


def cached(store, year, text):
    path = store.raw_path("omni", f"omni2_{year}.dat")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class Response(BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def test_reader_units_fill_values_and_scalar_vector_difference(tmp_path):
    store = spn.Store(tmp_path)
    cached(store, 2008, record() + record(hour=1, fill_pressure=True))
    data = spn.Omni(store=store, download="never").load("2008-01-01")
    assert data.pressure.schema.units == "nPa"
    assert data.magnetic_field.schema.frame == "GSE"
    assert data["bz_gsm"].schema.frame == "GSM"
    frame = data.to_dataframe()
    assert frame.shape == (2, len(hourly._COLUMNS))
    assert frame.kp.iloc[0] == pytest.approx(1.7)
    assert frame.dst.iloc[0] == -25
    assert frame.pressure.iloc[0] == 1.37 and np.isnan(frame.pressure.iloc[1])
    assert frame.ae.isna().all()
    assert frame.b_magnitude.iloc[0] == 8
    assert np.linalg.norm(data.magnetic_field.to_xarray().values[0]) == 5
    assert frame.attrs["units"]["density"] == "cm^-3"


@pytest.mark.parametrize(
    "text",
    [
        record(year=2007, doy=366),
        record(doy=0),
        record(hour=24),
        record(hour=0.5),
        record() + record(),
        record(hour=2) + record(hour=1),
    ],
)
def test_bad_timestamps_rejected(tmp_path, text):
    path = tmp_path / "bad.dat"
    path.write_text(text)
    with pytest.raises(ValueError):
        hourly.read_omni_hourly(path)


def test_leap_year_cross_year_half_open_and_timezone(tmp_path):
    store = spn.Store(tmp_path)
    cached(store, 2008, record(doy=366, hour=23))
    cached(store, 2009, record(year=2009) + record(year=2009, hour=1))
    client = spn.Omni(store=store, download="never")
    data = client.load("2009-01-01T08:00:00+09:00", "2009-01-01T10:00:00+09:00")
    assert len(data.files) == 2
    assert list(data.to_dataframe().index.hour) == [23, 0]
    assert len(client.load(spn.day("2008-12-31")).files) == 1


def test_match_containing_hours_preserves_missing_order_duplicates(tmp_path):
    store = spn.Store(tmp_path)
    cached(store, 2008, record() + record(hour=2, fill_pressure=True))
    result = spn.Omni(store=store, download="never").at(
        ["2008-01-01T02:20Z", "2008-01-01T00:59Z", "2008-01-01T01:00Z", "2008-01-01T00:59Z"]
    )
    assert list(result.index.hour) == [2, 0, 1, 0]
    assert np.isnan(result.pressure.iloc[0]) and np.isnan(result.pressure.iloc[2])
    assert result.pressure.iloc[1] == result.pressure.iloc[3] == 1.37
    assert pd.isna(result.source_time.iloc[2])
    assert result.source_time.iloc[0] == pd.Timestamp("2008-01-01T02:00Z")
    assert result.attrs["resolution_seconds"] == 3600


def test_download_cache_and_manifest(tmp_path, monkeypatch):
    calls = []

    def fetch(url, *, timeout):
        calls.append(url)
        assert timeout == 90
        return Response(record().encode())

    monkeypatch.setattr(hourly, "urlopen", fetch)
    store = spn.Store(tmp_path)
    client = spn.Omni(store=store, download="missing")
    first = client.load("2008-01-01")
    second = client.load("2008-01-01")
    assert first.files == second.files and len(calls) == 1
    assert store.raw_file(first.files[0]).verify_checksum()
    client.load("2008-01-01", download="always")
    assert len(calls) == 2


@pytest.mark.parametrize("failure", ["http", "timeout", "short", "html", "wrong_year", "short_row"])
def test_failed_refresh_preserves_existing_file(tmp_path, monkeypatch, failure):
    store = spn.Store(tmp_path)
    path = cached(store, 2008, record())
    original = path.read_bytes()

    def fetch(url, **kwargs):
        if failure == "http":
            raise HTTPError(url, 404, "missing", {}, None)
        if failure == "timeout":
            raise TimeoutError("connection timed out")
        result = Response(
            (
                "<html>error</html>"
                if failure == "html"
                else record(year=2009)
                if failure == "wrong_year"
                else record()
            ).encode()
        )
        if failure == "short":
            result.headers["Content-Length"] = "100000"
        if failure == "short_row":
            result = Response((record() + "2008 1 1 0\n").encode())
        return result

    monkeypatch.setattr(hourly, "urlopen", fetch)
    with pytest.raises((OSError, ValueError)):
        spn.Omni(store=store, download="always").load("2008-01-01")
    assert path.read_bytes() == original
    assert not list(path.parent.glob("*.tmp"))


def test_no_network_empty_targets_offline_and_wrong_cached_year(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Must not access the network")

    monkeypatch.setattr(hourly, "urlopen", fail)
    client = spn.Omni(store=spn.Store(tmp_path), download="never")
    assert client.at([]).empty
    with pytest.raises(ValueError, match="NaT"):
        client.at([pd.NaT])
    with pytest.raises(FileNotFoundError):
        client.load("2008-01-01")
    cached(client.store, 2008, record(year=2009))
    with pytest.raises(ValueError, match="expected year"):
        client.load("2008-01-01")


def test_typed_shortcuts_view_binding_and_plot(tmp_path, monkeypatch):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SOPRAN_CONFIG", str(tmp_path / "none.toml"))
    store = spn.Store(tmp_path / "store")
    cached(store, 2008, record() + record(hour=1))
    with spn.config.using(store=store, download="never"):
        assert isinstance(spn.omni, spn.Omni)
        assert spn.omni.load("2008-01-01").pressure.schema.units == "nPa"
        bound = spn.view(time=spn.day("2008-01-01")).omni
        assert bound.pressure.load().to_xarray().sizes["time"] == 2
        result = bound.pressure.plot()
        assert "nPa" in result.fig.axes[0].get_ylabel()
        plt.close(result.fig)
        result = bound.magnetic_field.plot()
        assert len(result.fig.axes[0].lines) == 3
        plt.close(result.fig)
        assert spn.Project(tmp_path, store=store).omni.download == "never"
        with pytest.raises(ValueError, match="time range"):
            spn.omni.load()


def test_invalid_variable_and_policy(tmp_path):
    client = spn.Omni(store=spn.Store(tmp_path), download="never")
    with pytest.raises(KeyError):
        client.variable("unknown")
    with pytest.raises(ValueError):
        spn.Omni(download="bogus")
    with pytest.raises(ValueError):
        spn.Omni(timeout_seconds=float("inf"))


def test_relative_store_download(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hourly, "urlopen", lambda *a, **kw: Response(record().encode()))
    store = spn.Store("relative-data")
    data = spn.Omni(store=store, download="missing").load("2008-01-01")
    assert store.raw_file(data.files[0].relative_to(store.raw_path())).verify_checksum()


def test_match_mixed_timestamp_precision(tmp_path):
    store = spn.Store(tmp_path)
    cached(store, 2008, record())
    result = spn.Omni(store=store, download="never").at(
        [
            "2008-01-01T00:59Z",
            "2008-01-01T00:59:59Z",
            "2008-01-01T09:59:59+09:00",
            "2008-01-01T00:30:00",
        ]
    )
    assert result.pressure.eq(1.37).all()
    assert result.source_time.eq(pd.Timestamp("2008-01-01T00:00Z")).all()
