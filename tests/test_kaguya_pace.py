from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np

from sopran.missions.kaguya import pace_energy_counts, read_pace_pbf


def test_read_pace_pbf_type01_summarizes_energy_counts(tmp_path: Path) -> None:
    path = tmp_path / "IPACE_PBF1_080101_ESA1_V003.dat"
    _write_type01_pbf(path)

    pace = read_pace_pbf(path)

    assert pace.sensor == 0
    assert pace.sensor_name == "ESA-S1"
    assert pace.headers[0]["type"] == 0x01
    assert 0x01 in pace.records

    counts = pace_energy_counts(pace)

    assert counts.shape == (1, 32)
    assert np.all(counts == 64)


def test_read_pace_pbf_accepts_gzip_files(tmp_path: Path) -> None:
    path = tmp_path / "IPACE_PBF1_080101_ESA1_V003.dat"
    gz_path = tmp_path / "IPACE_PBF1_080101_ESA1_V003.dat.gz"
    _write_type01_pbf(path)
    with path.open("rb") as source, gzip.open(gz_path, "wb") as target:
        target.write(source.read())

    pace = read_pace_pbf(gz_path)

    assert pace.source_files == (gz_path,)
    assert pace_energy_counts(pace).shape == (1, 32)


def _write_type01_pbf(path: Path) -> None:
    file_header = bytearray(1024)
    file_header[-1] = 0xEE

    header = np.zeros(64, dtype="<u4")
    header[0] = 0
    header[3] = 0x01
    header[5] = 16000
    header[6] = 16
    header[19] = 20080101
    header[20] = 0
    header[25] = 0

    event = np.arange(16, dtype="<u4")
    counts = np.ones((32, 4, 16), dtype="<u2")
    trash = np.zeros((32, 4, 2), dtype="<u2")

    with path.open("wb") as file:
        file.write(file_header)
        file.write(header.tobytes())
        file.write(event.tobytes())
        file.write(counts.tobytes())
        file.write(trash.tobytes())
