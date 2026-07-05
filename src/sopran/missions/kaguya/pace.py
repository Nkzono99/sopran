from __future__ import annotations

import gzip
import importlib
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, TextIO, cast

import numpy as np

from sopran.missions.kaguya.sensors import normalize_sensor, normalize_sensors

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

SENSOR_IDS = {
    "ESA1": 0,
    "ESA2": 1,
    "IMA": 2,
    "IEA": 3,
}

SENSOR_RAM_COUNTS = {
    0: 8,
    1: 8,
    2: 4,
    3: 4,
}

PACE_CALIBRATION_BASE_URL = "http://step0ku.kugi.kyoto-u.ac.jp/~haraday/data/kaguya/"

PACE_FOV_LAYOUT = {
    "ESA1": ("ESAS1", "esas1", 8),
    "ESA2": ("ESAS2", "esas2", 8),
    "IMA": ("IMA", "ima", 4),
    "IEA": ("IEA", "iea", 4),
}

PACE_INFO_FILES = {
    "ESA1": (
        "public/Kaguya_MAP_PACE_information/ESA-S1_ENE_POL_AZ_GFACTOR_16X64_20090828.dat",
        "public/Kaguya_MAP_PACE_information/ESA-S1_ENE_POL_AZ_GFACTOR_4X16_20090828.dat",
    ),
    "ESA2": (
        "public/Kaguya_MAP_PACE_information/ESA-S2_ENE_POL_AZ_GFACTOR_16X64_20090828.dat",
        "public/Kaguya_MAP_PACE_information/ESA-S2_ENE_POL_AZ_GFACTOR_4X16_20090828.dat",
    ),
    "IMA": (
        "public/Kaguya_MAP_PACE_information/IMA_ENE_POL_AZ_GFACTOR_16X64_20090212.dat",
        "public/Kaguya_MAP_PACE_information/IMA_ENE_POL_AZ_GFACTOR_4X16_20090212.dat",
    ),
    "IEA": (
        "public/Kaguya_MAP_PACE_information/IEA_ENE_POL_AZ_GFACTOR_16X64_20080225R.dat",
        "public/Kaguya_MAP_PACE_information/IEA_ENE_POL_AZ_GFACTOR_4X16_20080226.dat",
    ),
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
PaceBackend = Literal["auto", "python", "rust"]


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


@dataclass(frozen=True)
class PaceCalibration:
    """PACE FOV and INFO calibration tables keyed by sensor id.

    The arrays are loaded as published table values. Applying them to produce
    physical ESA1 flux is a separate step so incomplete calibration is explicit.
    """

    fov: dict[int, dict[str, np.ndarray]] = field(default_factory=dict)
    info: dict[int, dict[str, np.ndarray]] = field(default_factory=dict)

    def has_fov(self, sensor: object) -> bool:
        return _sensor_id(sensor) in self.fov

    def has_info(self, sensor: object) -> bool:
        return _sensor_id(sensor) in self.info

    def coverage(self, sensor: object) -> dict[str, bool]:
        sensor_id = _sensor_id(sensor)
        return {
            "fov": sensor_id in self.fov,
            "info": sensor_id in self.info,
        }


def read_pace_pbf(
    files: str | Path | Iterable[str | Path],
    *,
    backend: PaceBackend | None = None,
) -> PaceData:
    """Read KAGUYA PACE PBF binary records from one or more local files."""

    resolved_backend = _resolve_pace_backend(backend)
    paths = _as_paths(files)
    if resolved_backend == "rust":
        try:
            return _read_pace_pbf_native(paths)
        except ModuleNotFoundError as exc:
            if _is_missing_native_module(exc):
                raise RuntimeError(_native_backend_missing_message()) from exc
            raise
    if resolved_backend == "auto":
        try:
            return _read_pace_pbf_native(paths)
        except ModuleNotFoundError as exc:
            if not _is_missing_native_module(exc):
                raise

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


def _resolve_pace_backend(backend: PaceBackend | str | None) -> PaceBackend:
    value = backend or os.environ.get("SOPRAN_PACE_BACKEND") or "auto"
    if value not in {"auto", "python", "rust"}:
        raise ValueError("backend must be 'auto', 'python', or 'rust'")
    return cast(PaceBackend, value)


def _read_pace_pbf_native(paths: list[Path]) -> PaceData:
    native = importlib.import_module("sopran_native")
    payload = cast(dict[str, Any], native.read_pace_pbf([str(path) for path in paths]))
    return _pace_data_from_native(payload, paths)


def _is_missing_native_module(exc: ModuleNotFoundError) -> bool:
    return exc.name == "sopran_native" or (
        exc.name is None and "sopran_native" in str(exc)
    )


def _native_backend_missing_message() -> str:
    return (
        "sopran_native is not installed. From crates/sopran-native, build it with "
        "`python -m maturin develop --release --features extension-module`, "
        "or use backend='python'."
    )


def _pace_data_from_native(payload: dict[str, Any], paths: list[Path]) -> PaceData:
    headers = tuple(cast(dict[str, Any], header) for header in payload.get("headers", ()))
    records_by_type: dict[int, list[PaceRecord]] = {}
    record_order: list[PaceRecord] = []

    for item in payload.get("records", ()):
        record_type = int(item["type"])
        arrays = {
            str(name): _native_array_to_numpy(array)
            for name, array in dict(item.get("arrays") or {}).items()
        }
        record = PaceRecord(
            type=record_type,
            index=int(item["index"]),
            arrays=arrays,
        )
        records_by_type.setdefault(record_type, []).append(record)
        record_order.append(record)

    sensor = int(payload.get("sensor", -1))
    if sensor < 0:
        sensor = _detect_sensor(paths[0])
    return PaceData(
        sensor=sensor,
        headers=headers,
        records={key: tuple(value) for key, value in records_by_type.items()},
        source_files=tuple(paths),
        record_order=tuple(record_order),
    )


def _native_array_to_numpy(value: object) -> np.ndarray:
    if isinstance(value, np.ndarray):
        return value
    payload = cast(dict[str, Any], value)
    dtype = np.dtype(str(payload["dtype"]))
    shape = tuple(int(size) for size in payload["shape"])
    return np.frombuffer(payload["data"], dtype=dtype).reshape(shape)


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


def pace_calibration_remote_files(
    sensors: object | None = ("ESA1", "ESA2", "IMA", "IEA"),
) -> list[str]:
    """Return public KAGUYA PACE calibration table paths for selected sensors."""

    remote_files: list[str] = []
    for sensor in normalize_sensors(sensors):
        if sensor not in PACE_FOV_LAYOUT:
            continue
        directory, prefix, ram_count = PACE_FOV_LAYOUT[sensor]
        remote_files.append(f"public/FOV_ANGLE_070726/{directory}/{prefix}-ch_angle")
        remote_files.extend(
            f"public/FOV_ANGLE_070726/{directory}/{prefix}-pol_angle-RAM{ram}"
            for ram in range(ram_count)
        )
        remote_files.extend(PACE_INFO_FILES[sensor])
    return remote_files


def read_pace_info(files: str | Path | Iterable[str | Path]) -> dict[int, dict[str, np.ndarray]]:
    """Read KAGUYA PACE energy/polar/azimuth/gfactor INFO tables."""

    out: dict[int, dict[str, np.ndarray]] = {}
    for path in _as_paths(files):
        sensor = _require_sensor(path)
        info = out.setdefault(sensor, _init_info(sensor))
        is_16x64 = "16X64" in path.name.upper()
        key = "16x64" if is_16x64 else "4x16"
        table = _load_numeric_table(path, min_cols=16 if is_16x64 else 10)

        for row in table:
            ram, energy, polar, azimuth = (int(value) for value in row[:4])
            info[f"ene_{key}"][ram, energy, polar, azimuth] = row[4]
            info[f"pol_{key}"][ram, energy, polar, azimuth] = row[5]
            info[f"az_{key}"][ram, energy, polar, azimuth] = row[6]
            info[f"gfactor_{key}"][ram, energy, polar, azimuth] = row[7]
            info[f"ene_sqno_{key}"][ram, energy, polar, azimuth] = int(row[8])
            info[f"pol_sqno_{key}"][ram, energy, polar, azimuth] = int(row[9])
            if is_16x64:
                info["enemin_16x64"][ram, energy, polar, azimuth] = row[10]
                info["enemax_16x64"][ram, energy, polar, azimuth] = row[11]
                info["polmin_16x64"][ram, energy, polar, azimuth] = row[12]
                info["polmax_16x64"][ram, energy, polar, azimuth] = row[13]
                info["azmin_16x64"][ram, energy, polar, azimuth] = row[14]
                info["azmax_16x64"][ram, energy, polar, azimuth] = row[15]
    return out


def read_pace_fov(files: str | Path | Iterable[str | Path]) -> dict[int, dict[str, np.ndarray]]:
    """Read KAGUYA PACE FOV angle tables."""

    out: dict[int, dict[str, np.ndarray]] = {}
    for path in _as_paths(files):
        sensor = _require_sensor(path)
        fov = out.setdefault(sensor, _init_fov(sensor))
        name = path.name.lower()
        is_channel_angle = "ch_angle" in name
        ram = _ram_from_name(name, sensor)

        for row in _load_numeric_table(path, min_cols=2 if is_channel_angle else 4):
            if is_channel_angle:
                azimuth = int(row[0])
                fov["az64"][azimuth] = row[1]
                if azimuth < 16 and row.size >= 3:
                    fov["az16"][azimuth] = row[2]
            else:
                energy = int(row[0])
                polar = int(row[1])
                fov["ene"][ram, energy] = row[2]
                fov["pol16"][ram, energy, polar] = row[3]
                if polar < 4 and row.size >= 5:
                    fov["pol4"][ram, energy, polar] = row[4]
    return out


def _as_paths(files: str | Path | Iterable[str | Path]) -> list[Path]:
    if isinstance(files, str | Path):
        return [Path(files)]
    paths = [Path(file) for file in files]
    if not paths:
        raise ValueError("At least one PACE PBF file is required")
    return paths


def _open_binary(path: Path) -> Any:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rb")
    return path.open("rb")


def _detect_sensor(path: Path) -> int:
    name = path.name.upper()
    if "ESA1" in name or "ESA-S1" in name or "ESAS1" in name:
        return 0
    if "ESA2" in name or "ESA-S2" in name or "ESAS2" in name:
        return 1
    if "IMA" in name:
        return 2
    if "IEA" in name:
        return 3
    return -1


def _require_sensor(path: Path) -> int:
    sensor = _detect_sensor(path)
    if sensor < 0:
        raise ValueError(f"Cannot determine KAGUYA PACE sensor from {path}")
    return sensor


def _sensor_id(sensor: object) -> int:
    if isinstance(sensor, int):
        if sensor in SENSOR_NAMES:
            return sensor
        raise ValueError(f"Unknown KAGUYA PACE sensor id: {sensor!r}")
    normalized = normalize_sensor(sensor)
    if normalized not in SENSOR_IDS:
        raise ValueError(f"Sensor is not a PACE instrument: {sensor!r}")
    return SENSOR_IDS[normalized]


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
    header: dict[str, Any] = {
        field: int(values[index]) for index, field in enumerate(HEADER_FIELDS)
    }
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
            tzinfo=UTC,
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


def _init_info(sensor: int) -> dict[str, np.ndarray]:
    ram = SENSOR_RAM_COUNTS[sensor]
    shape16 = (ram, 32, 16, 64)
    shape4 = (ram, 32, 4, 16)
    return {
        "ene_16x64": np.full(shape16, np.nan, dtype=np.float32),
        "pol_16x64": np.full(shape16, np.nan, dtype=np.float32),
        "az_16x64": np.full(shape16, np.nan, dtype=np.float32),
        "gfactor_16x64": np.full(shape16, np.nan, dtype=np.float64),
        "ene_sqno_16x64": np.zeros(shape16, dtype=np.int16),
        "pol_sqno_16x64": np.zeros(shape16, dtype=np.int16),
        "enemin_16x64": np.full(shape16, np.nan, dtype=np.float32),
        "enemax_16x64": np.full(shape16, np.nan, dtype=np.float32),
        "polmin_16x64": np.full(shape16, np.nan, dtype=np.float32),
        "polmax_16x64": np.full(shape16, np.nan, dtype=np.float32),
        "azmin_16x64": np.full(shape16, np.nan, dtype=np.float32),
        "azmax_16x64": np.full(shape16, np.nan, dtype=np.float32),
        "ene_4x16": np.full(shape4, np.nan, dtype=np.float32),
        "pol_4x16": np.full(shape4, np.nan, dtype=np.float32),
        "az_4x16": np.full(shape4, np.nan, dtype=np.float32),
        "gfactor_4x16": np.full(shape4, np.nan, dtype=np.float64),
        "ene_sqno_4x16": np.zeros(shape4, dtype=np.int16),
        "pol_sqno_4x16": np.zeros(shape4, dtype=np.int16),
    }


def _init_fov(sensor: int) -> dict[str, np.ndarray]:
    ram = SENSOR_RAM_COUNTS[sensor]
    return {
        "az64": np.full(64, np.nan, dtype=np.float32),
        "az16": np.full(16, np.nan, dtype=np.float32),
        "ene": np.full((ram, 32), np.nan, dtype=np.float32),
        "pol16": np.full((ram, 32, 16), np.nan, dtype=np.float64),
        "pol4": np.full((ram, 32, 4), np.nan, dtype=np.float64),
    }


def _load_numeric_table(path: Path, *, min_cols: int) -> np.ndarray:
    rows: list[list[float]] = []
    with _open_text(path) as file:
        for line in file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) < min_cols:
                continue
            try:
                rows.append([float(value) for value in parts])
            except ValueError:
                continue
    if not rows:
        return np.empty((0, min_cols), dtype=float)
    width = max(len(row) for row in rows)
    table = np.full((len(rows), width), np.nan, dtype=float)
    for index, row in enumerate(rows):
        table[index, : len(row)] = row
    return table


def _open_text(path: Path) -> TextIO:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt")
    return path.open("r", encoding="utf-8")


def _ram_from_name(name: str, sensor: int) -> int:
    for ram in range(SENSOR_RAM_COUNTS[sensor]):
        if f"ram{ram}" in name:
            return ram
    return 0


def _collapse_energy_counts(counts: np.ndarray) -> np.ndarray:
    energy_look = pace_count_energy_look(counts)
    return cast(np.ndarray, energy_look.astype(np.uint64, copy=False).sum(axis=1))


def pace_count_energy_look(counts: np.ndarray) -> np.ndarray:
    """Return a PACE count array as ``energy x flattened-look``.

    PACE electron records usually store the 32-bin energy axis first, while ion
    records can store sensor/RAM-like axes before energy. This helper normalizes
    both layouts without applying fill-value masking or calibration.
    """

    if counts.ndim < 2:
        raise NotImplementedError(
            f"PACE count records with shape {counts.shape} cannot be mapped to energy spectra"
        )
    if counts.shape[0] != 32:
        energy_axes = [index for index, size in enumerate(counts.shape) if size == 32]
        if not energy_axes:
            raise NotImplementedError(
                f"PACE count records with shape {counts.shape} cannot be mapped to energy spectra"
            )
        counts = np.swapaxes(counts, 0, energy_axes[0])
    return counts.reshape(32, -1)
