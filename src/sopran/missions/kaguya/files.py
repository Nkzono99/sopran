from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.request import urlretrieve
from uuid import uuid4

PUBLIC_BASE_URL = "https://data.darts.isas.jaxa.jp/pub/pds3/"


@dataclass(frozen=True)
class KaguyaFileSource:
    local_root: Path
    remote_base_url: str = PUBLIC_BASE_URL
    fallback_roots: tuple[Path, ...] = ()

    def local_path(self, remote_file: str) -> Path:
        primary = self.local_root / remote_file
        if primary.exists():
            return primary
        for root in self.fallback_roots:
            fallback = root / remote_file
            if fallback.exists():
                return fallback
        return primary

    def remote_url(self, remote_file: str) -> str:
        return self.remote_base_url.rstrip("/") + "/" + remote_file.replace("\\", "/")

    def download(self, remote_file: str, *, overwrite: bool = False) -> Path:
        existing = self.local_path(remote_file)
        if existing.exists() and not overwrite:
            return existing
        target = self.local_root / remote_file
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = _temporary_download_path(target)
        try:
            urlretrieve(self.remote_url(remote_file), temp)
            temp.replace(target)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        return target


def _temporary_download_path(target: Path) -> Path:
    for _ in range(100):
        temp = target.with_name(f"{target.name}.{uuid4().hex}.tmp")
        if not temp.exists():
            return temp
    raise FileExistsError(f"Could not allocate temporary download path for {target}")


def iter_days(start: object, stop: object | None = None) -> Any:
    current = _as_date(start)
    final = _as_date(stop) if stop is not None else current
    while current <= final:
        yield current
        current += timedelta(days=1)


def iter_hours(start: object, stop: object | None = None, *, step_hours: int = 1) -> Any:
    if step_hours <= 0:
        raise ValueError("step_hours must be positive")
    current = _floor_hour(_as_datetime(start))
    final = (
        _floor_hour(_as_datetime(stop) - timedelta(microseconds=1))
        if stop is not None
        else current
    )
    while current <= final:
        yield current
        current += timedelta(hours=step_hours)


def _floor_even_hour(value: object) -> datetime:
    instant = _floor_hour(_as_datetime(value))
    if instant.hour % 2:
        return instant - timedelta(hours=1)
    return instant


def format_kaguya_template(template: str, time: date | datetime) -> str:
    instant = _as_datetime(time)
    replacements = {
        "YYYY": f"{instant.year:04d}",
        "yy": f"{instant.year % 100:02d}",
        "MM": f"{instant.month:02d}",
        "DD": f"{instant.day:02d}",
        "hh": f"{instant.hour:02d}",
        "mm": f"{instant.minute:02d}",
        "ss": f"{instant.second:02d}",
    }
    output = template
    for key, value in replacements.items():
        output = output.replace(key, value)
    return output


def iter_public_paths(template: str, start: object, stop: object | None = None) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for day in iter_days(start, stop):
        path = format_kaguya_template(template, day)
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def iter_hourly_public_paths(
    template: str,
    start: object,
    stop: object | None = None,
    *,
    step_hours: int = 1,
    skip_odd_hours: bool = False,
) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    if skip_odd_hours:
        start = _floor_even_hour(start)
    for instant in iter_hours(start, stop, step_hours=step_hours):
        if skip_odd_hours and instant.hour % 2:
            continue
        path = format_kaguya_template(template, instant)
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def pace_pbf_public_template(sensor: str, version: str = "003") -> str:
    sensor = sensor.upper()
    version2 = f"{version[2]}.0"
    return (
        f"sln-l-pace-3-pbf1-v{version2}/YYYYMMDD/data/"
        f"IPACE_PBF1_yyMMDD_{sensor}_V{version}.dat.gz"
    )


def lmag_public_templates(version: str = "1.0") -> tuple[str, str]:
    return (
        f"sln-l-lmag-3-mag-ts-v{version}/nominal/YYYYMMDD/data/MAG_TSYYYYMMDD.dat",
        f"sln-l-lmag-3-mag-ts-v{version}/optional/YYYYMMDD/data/MAG_TSOPYYYYMMDD.dat",
    )


def lrs_public_template(kind: str, version: str = "010") -> tuple[str, str, bool]:
    version2 = f"{version[1]}.{version[2]}"
    kind = kind.upper()
    if kind == "NPW":
        return (
            f"sln-l-lrs-5-npw-spectrum-v{version2}/YYYYMMDD/data/"
            f"LRS_NPW_V{version}_YYYYMMDD.cdf",
            "daily",
            False,
        )
    if kind == "WFC":
        return (
            f"sln-l-lrs-4-wfc-spectrum-v{version2}/YYYYMMDD/data/"
            f"LRS_WFC_V{version}_YYYYMMDDhhmmss.cdf",
            "hourly",
            True,
        )
    raise ValueError("kind must be 'NPW' or 'WFC'")


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.removesuffix("Z")
        if len(text) == 10:
            return date.fromisoformat(text)
        return datetime.fromisoformat(text).date()
    raise TypeError(f"Unsupported date value: {value!r}")


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        text = value.removesuffix("Z")
        if len(text) == 10:
            return datetime.fromisoformat(text).replace(tzinfo=UTC)
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    raise TypeError(f"Unsupported datetime value: {value!r}")


def _floor_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)
