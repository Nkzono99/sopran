from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import urlretrieve

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
        urlretrieve(self.remote_url(remote_file), target)
        return target


def iter_days(start: object, stop: object | None = None):
    current = _as_date(start)
    final = _as_date(stop) if stop is not None else current
    while current <= final:
        yield current
        current += timedelta(days=1)


def format_kaguya_template(template: str, day: date) -> str:
    replacements = {
        "YYYY": f"{day.year:04d}",
        "yy": f"{day.year % 100:02d}",
        "MM": f"{day.month:02d}",
        "DD": f"{day.day:02d}",
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


def pace_pbf_public_template(sensor: str, version: str = "003") -> str:
    sensor = sensor.upper()
    version2 = f"{version[2]}.0"
    return f"sln-l-pace-3-pbf1-v{version2}/YYYYMMDD/data/IPACE_PBF1_yyMMDD_{sensor}_V{version}.dat.gz"


def lmag_public_templates(version: str = "1.0") -> tuple[str, str]:
    return (
        f"sln-l-lmag-3-mag-ts-v{version}/nominal/YYYYMMDD/data/MAG_TSYYYYMMDD.dat",
        f"sln-l-lmag-3-mag-ts-v{version}/optional/YYYYMMDD/data/MAG_TSOPYYYYMMDD.dat",
    )


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
