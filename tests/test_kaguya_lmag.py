from __future__ import annotations

from pathlib import Path

import numpy as np

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

    data = spn.Kaguya(store=store).lmag.load(spn.day("2008-01-01"))
    dataset = data.to_xarray()

    assert data.files == (cached,)
    assert dataset.attrs["instrument"] == "LMAG"
    assert str(dataset["time"].values[0]) == "2008-01-01T00:00:00.000000000"
    assert dataset["magnetic_field_moon_me"].values.tolist()[0] == [-2.61, 2.98, -1.09]
