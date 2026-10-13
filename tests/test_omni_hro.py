from __future__ import annotations

from email.message import Message
from io import BytesIO

import numpy as np
import pandas as pd
import pytest

import sopran as spn
from sopran.missions.omni import hro


def _arrays(count: int = 6, start: float = 1_207_008_000.0) -> tuple[np.ndarray, dict, dict]:
    times = start + 300.0 * np.arange(count)
    arrays = {name: np.zeros(count) for name in hro._VARIABLES}
    arrays["Vx"] = np.full(count, -400.0)
    arrays["Vy"] = np.full(count, 10.0)
    arrays["Vz"] = np.full(count, -5.0)
    arrays["flow_speed"] = np.full(count, 400.5)
    arrays["BSN_x"] = np.full(count, 13.0)
    arrays["Pressure"] = np.full(count, 1.5)
    arrays["Pressure"][2] = 99.99
    arrays["Vx"][3] = 99999.9
    fills = {name: None for name in hro._VARIABLES}
    fills["Pressure"] = 99.99
    fills["Vx"] = 99999.9
    return times, arrays, fills


def test_arrays_become_a_table_with_fill_values_as_nan() -> None:
    times, arrays, fills = _arrays()
    frame = hro.read_omni_hro_arrays(times, arrays, fills)
    assert list(frame.index[:2]) == [
        pd.Timestamp("2008-04-01T00:00:00Z"),
        pd.Timestamp("2008-04-01T00:05:00Z"),
    ]
    assert np.isnan(frame["pressure"].iloc[2]) and frame["pressure"].iloc[0] == 1.5
    assert np.isnan(frame["vx_gse"].iloc[3]) and frame["vx_gse"].iloc[0] == -400.0
    assert frame.attrs["resolution_seconds"] == 300
    with pytest.raises(ValueError, match="strictly increasing"):
        hro.read_omni_hro_arrays(times[::-1], arrays, fills)


def test_data_at_matches_nearest_sample_within_tolerance() -> None:
    times, arrays, fills = _arrays()
    frame = hro.read_omni_hro_arrays(times, arrays, fills)
    data = hro.OmniHroData(spn.day("2008-04-01"), (), frame)
    matched = data.at(["2008-04-01T00:04:00Z", "2008-04-01T00:12:31Z", "2008-04-01T03:00:00Z"])
    assert matched["source_time"].iloc[0] == pd.Timestamp("2008-04-01T00:05:00Z")
    assert matched["dt_seconds"].iloc[0] == -60.0
    assert matched["source_time"].iloc[1] == pd.Timestamp("2008-04-01T00:15:00Z")
    assert np.isnan(matched["vx_gse"].iloc[2]) and pd.isna(matched["source_time"].iloc[2])
    dataset = data.to_xarray()
    assert dataset["velocity"].attrs["frame"] == "GSE"
    assert data.velocity.schema.units == "km/s"


class _Response(BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = Message()
        self.headers["Content-Length"] = str(len(payload))

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def test_monthly_files_are_downloaded_once_and_registered(tmp_path, monkeypatch) -> None:
    times, arrays, fills = _arrays(count=12 * 24 * 30)
    table = hro.read_omni_hro_arrays(times, arrays, fills)
    urls: list[str] = []

    def fake_urlopen(url: str, timeout: float) -> _Response:
        urls.append(url)
        return _Response(b"cdf-bytes")

    monkeypatch.setattr(hro, "urlopen", fake_urlopen)
    monkeypatch.setattr(hro, "read_omni_hro", lambda path, **_kwargs: table.copy())
    store = spn.Store(tmp_path / "store")
    source = hro.OmniHighResolution(store=store, download="missing")
    data = source.load(spn.period("2008-04-01T00:00", "2008-04-01T01:00"))
    assert urls == [f"{hro.BASE_URL}2008/omni_hro_5min_20080401_v01.cdf"]
    assert data.files[0].name == "omni_hro_5min_20080401_v01.cdf"
    assert len(data.frame) == 12
    again = source.load(spn.period("2008-04-01T00:00", "2008-04-01T01:00"))
    assert len(urls) == 1 and again.files == data.files
    with pytest.raises(FileNotFoundError):
        hro.OmniHighResolution(store=store, download="never").load(spn.day("2008-05-02"))
    assert hro._months(spn.period("2008-11-20", "2009-02-01")) == [
        (2008, 11),
        (2008, 12),
        (2009, 1),
    ]


def test_omni_entry_point_exposes_high_resolution_access(tmp_path) -> None:
    omni = spn.Omni(store=spn.Store(tmp_path), download="never")
    assert isinstance(omni.hro, hro.OmniHighResolution)
    assert omni.hro.download == "never"
    assert "## omni / hro_5min" in spn.schema_reference_markdown()


def test_one_minute_and_hro2_use_their_own_directories(tmp_path, monkeypatch) -> None:
    times = 1_207_008_000.0 + 60.0 * np.arange(120)
    _times5, arrays5, fills = _arrays(count=120)
    table = hro.read_omni_hro_arrays(times, arrays5, fills, resolution_seconds=60)
    urls: list[str] = []
    reads: list[int] = []

    def fake_urlopen(url: str, timeout: float) -> _Response:
        urls.append(url)
        return _Response(b"cdf-bytes")

    def fake_read(path, *, resolution_seconds):
        reads.append(resolution_seconds)
        return table.copy()

    monkeypatch.setattr(hro, "urlopen", fake_urlopen)
    monkeypatch.setattr(hro, "read_omni_hro", fake_read)
    omni = spn.Omni(store=spn.Store(tmp_path / "store"), download="missing")
    window = spn.period("2008-04-01T00:00", "2008-04-01T01:00")

    one_minute = omni.hro_1min.load(window)
    definitive = omni.hro2_1min.load(window)

    assert urls == [
        f"{hro.CDAWEB_OMNI_URL}hro_1min/2008/omni_hro_1min_20080401_v01.cdf",
        f"{hro.CDAWEB_OMNI_URL}hro2_1min/2008/omni_hro2_1min_20080401_v01.cdf",
    ]
    assert reads == [60, 60]
    assert one_minute.files[0].parent.parent.name == "hro_1min"
    assert len(one_minute.frame) == 60
    assert one_minute.velocity.name == "omni.hro_1min.velocity"
    assert definitive.to_xarray().attrs["product"] == "omni.hro2_1min"
    assert omni.hro2.directory == "hro2_5min" and omni.hro.dataset == "omni.hro"


def test_nearest_match_tolerance_follows_the_resolution() -> None:
    times = 1_207_008_000.0 + 60.0 * np.arange(5)
    _times5, arrays, fills = _arrays(count=5)
    data = hro.OmniHroData(
        spn.day("2008-04-01"),
        (),
        hro.read_omni_hro_arrays(times, arrays, fills, resolution_seconds=60),
        "omni.hro_1min",
    )

    matched = data.at(["2008-04-01T00:05:30Z", "2008-04-01T00:07:30Z"])

    assert matched["dt_seconds"].iloc[0] == 90.0
    assert np.isnan(matched["dt_seconds"].iloc[1])


def test_high_resolution_rejects_unknown_products(tmp_path) -> None:
    with pytest.raises(ValueError, match="resolution"):
        hro.OmniHighResolution(store=spn.Store(tmp_path), resolution="2min")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="product"):
        hro.OmniHighResolution(store=spn.Store(tmp_path), product="hro3")  # type: ignore[arg-type]
