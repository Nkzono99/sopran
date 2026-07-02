from __future__ import annotations

import gzip
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np


SENSOR_NAMES = {
    0: "ESA-S1",
    1: "ESA-S2",
    2: "IMA",
    3: "IEA",
}

SENSOR_SHORT_NAMES = {
    0: "esa1",
    1: "esa2",
    2: "ima",
    3: "iea",
}

HEADER_FIELDS = (
    "sensor",
    "mode",
    "mode2",
    "type",
    "size",
    "time_resolution",
    "sampl_time",
    "ver",
    "tbl_ver",
    "obs_ver",
    "timeH",
    "timeM",
    "timeL",
    "bc",
    "ic",
    "sc",
    "sc_step0",
    "t_date",
    "time_ms",
    "yyyymmdd",
    "hhmmss",
    "tof_tbl",
    "pd_pha",
    "svg_tbl",
    "sva_tbl",
    "svs_tbl",
    "obs_tbl",
    "obs_ctr",
    "nv_high",
    "nv_low",
    "data_quality",
    "pol_step",
    "az_step",
    "ene_step",
    "mass_step",
    "pitch_step",
    "tof_step",
    "solwnd_step",
    "exb_step",
    "event_step",
    "trash_step",
    "tof_disc_start",
    "tof_disc_stop",
    "hv_scan_level",
)

PBF_SPECS = {
    0x00: (("event", "u4", (16,)), ("cnt", "u2", (32, 16, 64)), ("trash", "u2", (32, 16, 2))),
    0x01: (("event", "u4", (16,)), ("cnt", "u2", (32, 4, 16)), ("trash", "u2", (32, 4, 2))),
    0x02: (("event", "u4", (16,)), ("cnt", "u2", (32, 32))),
    0x03: (("event", "u4", (16,)), ("cnt", "u2", (32, 8, 64)), ("trash", "u2", (32, 8, 2))),
    0x40: (("event", "u4", (4, 16)), ("cnt", "u2", (4, 32, 1024))),
    0x41: (("event", "u4", (4, 16)), ("cnt", "u2", (32, 16, 64)), ("trash", "u2", (32, 16, 2))),
    0x42: (("event", "u4", (4, 16)), ("cnt", "u2", (32, 4, 16)), ("trash", "u2", (32, 4, 2))),
    0x43: (("event", "u4", (4, 16)), ("cnt", "u2", (8, 32, 4, 16)), ("trash", "u2", (8, 32, 4, 2))),
    0x44: (
        ("event", "u4", (4, 16)),
        ("s_cnt", "u2", (16, 32, 64)),
        ("cnt", "u2", (16, 32, 16, 64)),
    ),
    0x45: (
        ("event", "u4", (4, 16)),
        ("cnt", "u2", (16, 32, 4, 16)),
        ("trash", "u2", (16, 32, 4, 2)),
    ),
    0x80: (("event", "u4", (16,)), ("cnt", "u2", (32, 4, 16)), ("trash", "u2", (32, 4, 2))),
    0x81: (("event", "u4", (16,)), ("cnt", "u2", (32, 16, 64)), ("trash", "u2", (32, 16, 2))),
    0x82: (("event", "u4", (16,)), ("s_cnt", "u2", (32, 128)), ("cnt", "u2", (32, 16, 64))),
}

PbfSpec = tuple[tuple[str, str, tuple[int, ...]], ...]


@dataclass(frozen=True)
class PaceRecord:
    type: int
    index: int
    arrays: dict[str, np.ndarray]


@dataclass(frozen=True)
class PaceData:
    sensor: int
    headers: tuple[dict[str, Any], ...]
    records: dict[int, tuple[PaceRecord, ...]]
    source_files: tuple[Path, ...]
    record_order: tuple[PaceRecord, ...]

    @property
    def sensor_name(self) -> str:
        return SENSOR_NAMES.get(self.sensor, f"UNKNOWN-{self.sensor}")

    @property
    def sensor_short_name(self) -> str:
        return SENSOR_SHORT_NAMES.get(self.sensor, f"sensor{self.sensor}")


def read_pace_pbf(files: str | Path | Iterable[str | Path]) -> PaceData:
    """Read KAGUYA PACE PBF binary records from one or more local files."""

    paths = _as_paths(files)
    headers: list[dict[str, Any]] = []
    records_by_type: dict[int, list[PaceRecord]] = {}
    record_order: list[PaceRecord] = []
    detected_sensor: int | None = None

    for path in paths:
        with _open_binary(path) as file:
            file_header = file.read(1024)
            if len(file_header) != 1024:
                raise ValueError(f"PACE PBF file is missing the 1024-byte file header: {path}")

            while True:
                header_bytes = file.read(256)
                if not header_bytes:
                    break
                if len(header_bytes) != 256:
                    raise ValueError(f"Truncated PACE PBF record header in {path}")

                endian = _choose_endian(header_bytes)
                header = _parse_header(header_bytes, endian)
                pbf_type = int(header["type"])
                spec = PBF_SPECS.get(pbf_type)
                if spec is None:
                    raise ValueError(f"Unsupported PACE PBF record type 0x{pbf_type:02X} in {path}")

                payload_size = _payload_size(spec, endian)
                payload = file.read(payload_size)
                if len(payload) != payload_size:
                    raise ValueError(
                        f"Truncated PACE PBF payload for type 0x{pbf_type:02X} in {path}"
                    )

                arrays = _read_payload(payload, spec, endian)
                index = len(headers)
                record = PaceRecord(type=pbf_type, index=index, arrays=arrays)
                headers.append(header)
                records_by_type.setdefault(pbf_type, []).append(record)
                record_order.append(record)
                detected_sensor = int(header["sensor"])

    if detected_sensor is None:
        detected_sensor = _detect_sensor(paths[0])

    return PaceData(
        sensor=detected_sensor,
        headers=tuple(headers),
        records={key: tuple(value) for key, value in records_by_type.items()},
        source_files=tuple(paths),
        record_order=tuple(record_order),
    )


def pace_energy_counts(pace: PaceData, *, record_type: int | None = None) -> np.ndarray:
    """Collapse supported PACE count records into one row per record and 32 energy bins."""

    rows: list[np.ndarray] = []
    records = pace.record_order
    if record_type is not None:
        records = tuple(record for record in records if record.type == record_type)

    for record in records:
        counts = record.arrays.get("cnt")
        if counts is None:
            continue
        rows.append(_collapse_energy_counts(counts))

    if not rows:
        return np.empty((0, 32), dtype=np.uint64)
    return np.vstack(rows)


def _as_paths(files: str | Path | Iterable[str | Path]) -> list[Path]:
    if isinstance(files, str | Path):
        return [Path(files)]
    paths = [Path(file) for file in files]
    if not paths:
        raise ValueError("At least one PACE PBF file is required")
    return paths


def _open_binary(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rb")
    return path.open("rb")


def _detect_sensor(path: Path) -> int:
    name = path.name.upper()
    if "ESA1" in name:
        return 0
    if "ESA2" in name:
        return 1
    if "IMA" in name:
        return 2
    if "IEA" in name:
        return 3
    return -1


def _choose_endian(header_bytes: bytes) -> str:
    for endian in ("<", ">"):
        values = np.frombuffer(header_bytes, dtype=f"{endian}u4", count=64)
        pbf_type = int(values[3])
        yyyymmdd = int(values[19])
        hhmmss = int(values[20])
        if pbf_type in PBF_SPECS and 20000101 <= yyyymmdd <= 20300101 and hhmmss <= 235959:
            return endian
    return "<"


def _parse_header(header_bytes: bytes, endian: str) -> dict[str, Any]:
    values = np.frombuffer(header_bytes, dtype=f"{endian}u4", count=64)
    header = {field: int(values[index]) for index, field in enumerate(HEADER_FIELDS)}
    header["time"] = _decode_unix_time(
        int(header["yyyymmdd"]),
        int(header["hhmmss"]),
        int(header["time_resolution"]),
    )
    return header


def _decode_unix_time(yyyymmdd: int, hhmmss: int, time_resolution: int) -> float | None:
    try:
        date_text = f"{yyyymmdd:08d}"
        time_text = f"{hhmmss:06d}"
        value = datetime(
            int(date_text[0:4]),
            int(date_text[4:6]),
            int(date_text[6:8]),
            int(time_text[0:2]),
            int(time_text[2:4]),
            int(time_text[4:6]),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    value += timedelta(seconds=time_resolution * 0.5e-3)
    return value.timestamp()


def _payload_size(spec: PbfSpec, endian: str) -> int:
    total = 0
    for _, dtype, shape in spec:
        total += np.dtype(f"{endian}{dtype}").itemsize * int(np.prod(shape))
    return total


def _read_payload(payload: bytes, spec: PbfSpec, endian: str) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    offset = 0
    for name, dtype, shape in spec:
        array_dtype = np.dtype(f"{endian}{dtype}")
        count = int(np.prod(shape))
        size = array_dtype.itemsize * count
        arrays[name] = np.frombuffer(
            payload,
            dtype=array_dtype,
            count=count,
            offset=offset,
        ).reshape(shape)
        offset += size
    return arrays


def _collapse_energy_counts(counts: np.ndarray) -> np.ndarray:
    if counts.ndim < 2 or counts.shape[0] != 32:
        raise NotImplementedError(
            f"Energy count collapse expects a leading 32-bin energy axis, got {counts.shape}"
        )
    return counts.astype(np.uint64, copy=False).sum(axis=tuple(range(1, counts.ndim)))
