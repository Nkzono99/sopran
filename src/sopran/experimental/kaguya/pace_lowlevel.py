"""Low-level summaries of decoded PACE PBF1 records.

The tables stay close to the public files: one row per record with the
header fields, count/event/trash totals per record, and the IMA time-of-flight
histogram summed over a day. They are the first database layer that higher
products (ion peaks, reflected-ion candidates) can read without decoding the
binaries again. Fill values (``65535``) are excluded from the sums and
reported as ``*_fill_cells``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import polars as pl

from sopran.missions.kaguya.pace import PaceData

FILL_U16 = 65535
TOF_RECORD_TYPES = (0x40,)


def record_header_table(pace: PaceData) -> pl.DataFrame:
    """All integer header fields plus ``time_unix``, ``record_type`` and ``record_index``."""

    keys: list[str] = []
    for header in pace.headers:
        for key in header:
            if key not in keys:
                keys.append(key)
    columns: dict[str, Any] = {
        "record_index": np.arange(len(pace.headers), dtype=np.int64),
        "sensor": np.full(len(pace.headers), int(pace.sensor), dtype=np.int64),
    }
    for key in keys:
        values = [header.get(key) for header in pace.headers]
        if key == "time":
            columns["time_unix"] = np.asarray(
                [np.nan if v is None else float(v) for v in values], dtype=float
            )
        else:
            columns[key] = np.asarray([-1 if v is None else int(v) for v in values], dtype=np.int64)
    columns["record_type"] = np.asarray([int(r.type) for r in pace.record_order], dtype=np.int64)
    return pl.DataFrame(columns)


def record_count_table(pace: PaceData) -> pl.DataFrame:
    """Per-record totals of ``cnt``, ``s_cnt``, ``event`` and ``trash`` arrays."""

    rows: list[dict[str, Any]] = []
    for index, (record, header) in enumerate(zip(pace.record_order, pace.headers, strict=True)):
        row: dict[str, Any] = {
            "record_index": index,
            "time_unix": float(header.get("time", np.nan)),
            "record_type": int(record.type),
            "mode": int(header.get("mode", -1)),
        }
        for name in ("cnt", "s_cnt", "event", "trash"):
            array = record.arrays.get(name)
            if array is None:
                row[f"{name}_sum"] = None
                row[f"{name}_max"] = None
                row[f"{name}_fill_cells"] = None
                row[f"{name}_cells"] = None
                continue
            values = np.asarray(array)
            fill = (
                values == FILL_U16
                if values.dtype.kind in "ui" and values.dtype.itemsize == 2
                else np.zeros(values.shape, bool)
            )
            valid = values[~fill].astype(np.int64)
            row[f"{name}_sum"] = int(valid.sum()) if valid.size else 0
            row[f"{name}_max"] = int(valid.max()) if valid.size else 0
            row[f"{name}_fill_cells"] = int(np.count_nonzero(fill))
            row[f"{name}_cells"] = int(values.size)
        rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame()


def tof_energy_aggregate(
    pace: PaceData, *, record_types: tuple[int, ...] = TOF_RECORD_TYPES
) -> pl.DataFrame:
    """IMA TOF histogram summed over records: rows of ``(energy_index, tof_index, counts)``.

    Type ``0x40`` records carry ``cnt`` with shape ``(4, 32, 1024)``; the
    leading axis is summed. ``records`` is the number of contributing records.
    """

    total: np.ndarray | None = None
    used = 0
    for record in pace.record_order:
        if int(record.type) not in record_types:
            continue
        array = record.arrays.get("cnt")
        if array is None or np.asarray(array).ndim != 3:
            continue
        values = np.asarray(array).astype(np.int64)
        values[values == FILL_U16] = 0
        summed = values.sum(axis=0)
        total = summed if total is None else total + summed
        used += 1
    if total is None:
        return pl.DataFrame(
            schema={
                "energy_index": pl.Int64,
                "tof_index": pl.Int64,
                "counts": pl.Int64,
                "records": pl.Int64,
            }
        )
    energy_index, tof_index = np.meshgrid(
        np.arange(total.shape[0]), np.arange(total.shape[1]), indexing="ij"
    )
    return pl.DataFrame(
        {
            "energy_index": energy_index.reshape(-1).astype(np.int64),
            "tof_index": tof_index.reshape(-1).astype(np.int64),
            "counts": total.reshape(-1).astype(np.int64),
            "records": np.full(total.size, used, dtype=np.int64),
        }
    )


def lowlevel_summary(pace: PaceData) -> Mapping[str, pl.DataFrame]:
    """``headers``, ``counts`` and (for IMA) ``tof`` tables of one decoded day."""

    tables: dict[str, pl.DataFrame] = {
        "headers": record_header_table(pace),
        "counts": record_count_table(pace),
    }
    if int(pace.sensor) == 2:
        tables["tof"] = tof_energy_aggregate(pace)
    return tables


__all__ = [
    "FILL_U16",
    "lowlevel_summary",
    "record_count_table",
    "record_header_table",
    "tof_energy_aggregate",
]
