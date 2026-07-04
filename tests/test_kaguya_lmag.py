from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError

import numpy as np
import pytest

import sopran as spn
from sopran import Store
from sopran.missions.kaguya import read_lmag_public


def test_read_lmag_public_file_to_pandas_and_xarray(tmp_path: Path) -> None:
    path = tmp_path / "MAG_TS20080101.dat"
    path.write_text(
        "2008-01-01 00:00:00 1 2 3 4 5 6 7 8 9 10 11 12\n"
        "2008-01-01 00:00:04 1 2 3 999.99 5 6 7 8 9 10 11 12\n",
        encoding="utf-8",
    )

    data = read_lmag_public(path)
    frame = data.to_pandas()

    assert list(frame.columns[:4]) == ["time", "rme_x", "rme_y", "rme_z"]
    assert len(frame) == 2
    assert np.isnan(frame.loc[1, "bme_x"])

    dataset = data.to_xarray()
    assert dataset["position_moon_me"].shape == (2, 3)
    assert dataset["magnetic_field_gse"].attrs["frame"] == "GSE"


def test_kaguya_lmag_load_reads_cached_public_file(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-lmag-3-mag-ts-v1.0/nominal/20080101/data/MAG_TS20080101.dat"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    cached.write_text(
        "2008-01-01T00:00:00,  -155.0,  -305.2, -1791.2,  -2.61,   2.98,  -1.09,  "
        "157120.9, -356486.3,  -14589.0,  -1.26,  -3.78,  -1.00\n"
        "2008-01-01T00:00:04,  -151.8,  -299.5, -1792.3,  -2.90,   2.79,  -1.02,  "
        "157117.7, -356484.7,  -14589.6,  -0.95,  -3.93,  -0.93\n",
        encoding="utf-8",
    )

    data = spn.Kaguya(store=store, download="never").lmag.load(spn.day("2008-01-01"))
    dataset = data.to_xarray()

    assert data.files == (cached,)
    assert dataset.attrs["instrument"] == "LMAG"
    assert str(dataset["time"].values[0]) == "2008-01-01T00:00:00.000000000"
    assert dataset["magnetic_field_moon_me"].values.tolist()[0] == [-2.61, 2.98, -1.09]


def test_kaguya_lmag_magnetic_field_endpoint_loads_sopran_array(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-lmag-3-mag-ts-v1.0/nominal/20080101/data/MAG_TS20080101.dat"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    cached.write_text(
        "2008-01-01T00:00:00,  -155.0,  -305.2, -1791.2,  -2.61,   2.98,  -1.09,  "
        "157120.9, -356486.3,  -14589.0,  -1.26,  -3.78,  -1.00\n"
        "2008-01-01T00:00:04,  -151.8,  -299.5, -1792.3,  -2.90,   2.79,  -1.02,  "
        "157117.7, -356484.7,  -14589.6,  -0.95,  -3.93,  -0.93\n",
        encoding="utf-8",
    )

    kg = spn.Kaguya(store=store, download="never")
    time = spn.day("2008-01-01")
    plan = kg.lmag.magnetic_field.plan(time)
    field = kg.lmag.magnetic_field.load(time)
    item = kg.lmag.magnetic_field.lines(time, components="xz")

    assert kg.lmag.b is kg.lmag.magnetic_field
    assert plan.dataset_id == "kaguya.lmag.magnetic_field"
    assert remote_file in plan.remote_files
    assert field.name == "magnetic_field"
    assert field.schema.aliases == ("b", "lmag", "bme", "b_moon_me")
    assert field.schema.units == "nT"
    assert field.schema.frame == "MOON_ME"
    assert field.files == (cached,)
    assert tuple(field.to_xarray().dims) == ("time", "component")
    assert field.to_xarray().values.tolist()[0] == [-2.61, 2.98, -1.09]
    assert item.kind == "line"
    assert item.name == "magnetic_field"


def test_kaguya_lmag_magnetic_field_magnitude_endpoint_loads_norm(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-lmag-3-mag-ts-v1.0/nominal/20080101/data/MAG_TS20080101.dat"
    cached = store.raw_path("kaguya", "pds3") / remote_file
    cached.parent.mkdir(parents=True)
    cached.write_text(
        "2008-01-01T00:00:00,  1,  2,  3,  3,  4,  0,  7,  8,  9,  1,  2,  3\n"
        "2008-01-01T00:00:04,  1,  2,  3,  0,  0, 12,  7,  8,  9,  4,  5,  6\n",
        encoding="utf-8",
    )

    bmag = spn.Kaguya(store=store, download="never").lmag.magnetic_field_magnitude.load(
        spn.day("2008-01-01")
    )
    alias = spn.Kaguya(store=store, download="never").lmag.bmag.load(spn.day("2008-01-01"))

    assert bmag.name == "magnetic_field_magnitude"
    assert bmag.schema.units == "nT"
    assert bmag.to_xarray().dims == ("time",)
    np.testing.assert_allclose(bmag.to_xarray().values, np.asarray([5.0, 12.0]))
    np.testing.assert_allclose(alias.to_xarray().values, bmag.to_xarray().values)


def test_kaguya_lmag_load_missing_error_rejects_silent_empty_dataset(tmp_path: Path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"), download="never")
    time = spn.day("2008-01-01")

    with pytest.raises(FileNotFoundError, match="No local KAGUYA LMAG raw files found"):
        kg.lmag.load(time, missing="error")


def test_kaguya_lmag_variable_load_passes_missing_error(tmp_path: Path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"), download="never")
    time = spn.day("2008-01-01")

    with pytest.raises(FileNotFoundError, match="No local KAGUYA LMAG raw files found"):
        kg.lmag.magnetic_field.load(time, missing="error")


def test_kaguya_lmag_load_missing_warn_records_missing_reason(tmp_path: Path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"), download="never")
    time = spn.day("2008-01-01")

    with pytest.warns(UserWarning, match="No local KAGUYA LMAG raw files found"):
        data = kg.lmag.load(time, missing="warn")

    assert data.missing_reason is not None
    assert data.missing_reason.startswith("No local KAGUYA LMAG raw files found")
    assert data.to_xarray().attrs["missing_reason"] == data.missing_reason


def test_kaguya_lmag_load_partial_missing_warn_records_missing_reason(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-lmag-3-mag-ts-v1.0/nominal/20080101/data/MAG_TS20080101.dat"
    path = store.raw_path("kaguya", "pds3") / remote_file
    _write_lmag_file(path)
    kg = spn.Kaguya(store=store, download="never")
    time = spn.period("2008-01-01", "2008-01-03")

    with pytest.warns(UserWarning, match="Missing local KAGUYA LMAG raw files"):
        data = kg.lmag.load(time, missing="warn")

    assert data.missing_reason is not None
    assert "20080102" in data.missing_reason
    assert data.to_xarray().sizes["time"] == 1


def test_kaguya_lmag_download_skips_missing_optional_file(tmp_path: Path) -> None:
    class FakeSource:
        def __init__(self, root: Path) -> None:
            self.root = root
            self.downloaded: list[str] = []

        def local_path(self, remote_file: str) -> Path:
            return self.root / remote_file

        def remote_url(self, remote_file: str) -> str:
            return f"https://example.test/{remote_file}"

        def download(self, remote_file: str, *, overwrite: bool = False) -> Path:
            self.downloaded.append(remote_file)
            if "/optional/" in remote_file:
                raise HTTPError(self.remote_url(remote_file), 404, "Not Found", None, None)
            path = self.local_path(remote_file)
            path.parent.mkdir(parents=True)
            path.write_text(
                "2008-01-01T00:00:00,  -155.0,  -305.2, -1791.2,  -2.61,   2.98,  -1.09,  "
                "157120.9, -356486.3,  -14589.0,  -1.26,  -3.78,  -1.00\n",
                encoding="utf-8",
            )
            return path

    source = FakeSource(tmp_path / "raw")
    kg = spn.Kaguya(store=Store(tmp_path / "store"), source=source, download="missing")

    data = kg.lmag.load(spn.day("2008-01-01"))

    assert len(data.files) == 1
    assert any("/optional/" in path for path in source.downloaded)


def _write_lmag_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "2008-01-01 00:00:00 1 2 3 4 5 6 7 8 9 10 11 12\n",
        encoding="utf-8",
    )
