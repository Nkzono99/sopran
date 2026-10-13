from __future__ import annotations

import numpy as np
import pytest

from sopran.experimental.kaguya import pace_lowlevel
from sopran.missions.kaguya.pace import PaceData, PaceRecord

pytest.importorskip("polars")


def _pace(sensor: int, tof: bool = False) -> PaceData:
    counts = np.ones((32, 4, 16), dtype=np.uint16)
    counts[0, 0, 0] = 65535
    counts[1, 0, 0] = 9
    record = PaceRecord(
        type=0x01,
        index=0,
        arrays={
            "cnt": counts,
            "trash": np.full((32, 4, 2), 2, np.uint16),
            "event": np.arange(16, dtype=np.uint32),
        },
    )
    records = [record]
    headers = [
        {"time": 1_207_008_000.0, "mode": 0x14, "type": 0x01, "sensor": sensor, "sampl_time": 16000}
    ]
    if tof:
        tof_counts = np.ones((4, 32, 1024), dtype=np.uint16)
        tof_counts[:, 3, 7] = 5
        records.append(
            PaceRecord(
                type=0x40,
                index=1,
                arrays={"cnt": tof_counts, "event": np.zeros((4, 16), np.uint32)},
            )
        )
        headers.append({"time": 1_207_008_002.0, "mode": 0x14, "type": 0x40, "sensor": sensor})
    return PaceData(
        sensor=sensor,
        headers=tuple(headers),
        records={r.type: (r,) for r in records},
        source_files=(),
        record_order=tuple(records),
    )


def test_header_and_count_tables_follow_the_records() -> None:
    tables = pace_lowlevel.lowlevel_summary(_pace(0))
    headers = tables["headers"]
    assert headers["record_type"].to_list() == [1]
    assert headers["time_unix"][0] == pytest.approx(1_207_008_000.0)
    assert headers["sampl_time"][0] == 16000
    counts = tables["counts"]
    assert counts["cnt_fill_cells"][0] == 1
    assert counts["cnt_sum"][0] == 32 * 4 * 16 - 1 - 1 + 9
    assert counts["cnt_max"][0] == 9
    assert counts["trash_sum"][0] == 32 * 4 * 2 * 2
    assert counts["event_sum"][0] == sum(range(16))
    assert counts["s_cnt_sum"][0] is None
    assert "tof" not in tables


def test_ima_tof_histogram_is_summed_over_records_and_sectors() -> None:
    tables = pace_lowlevel.lowlevel_summary(_pace(2, tof=True))
    tof = tables["tof"]
    assert tof.height == 32 * 1024
    peak = tof.filter((tof["energy_index"] == 3) & (tof["tof_index"] == 7))
    assert peak["counts"][0] == 20 and peak["records"][0] == 1
    assert tof["counts"].sum() == 4 * 32 * 1024 + 4 * 4
    empty = pace_lowlevel.tof_energy_aggregate(_pace(2))
    assert empty.height == 0
