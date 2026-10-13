"""ARTEMIS (THEMIS-B/C) Level 2 CDF files from NASA SPDF/CDAWeb.

ARTEMIS P1 is THEMIS-B (``thb``) and P2 is THEMIS-C (``thc``). Daily Level 2
files live under ``themis/<probe>/l2/<instrument>/<year>/`` with a version
suffix, so the newest version for a day is chosen from the directory listing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from pathlib import Path
from shutil import copyfileobj
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, Literal
from urllib.error import ContentTooShortError, HTTPError
from urllib.request import urlopen

import numpy as np

from sopran.core.config import DownloadMode
from sopran.core.errors import DecodeError
from sopran.core.store import Store

if TYPE_CHECKING:
    import xarray as xr

SPDF_THEMIS_URL = "https://spdf.gsfc.nasa.gov/pub/data/themis/"
PROBE_IDS = {"p1": "thb", "p2": "thc"}
EsaMode = Literal["reduced", "full", "burst"]
ESA_MODES: dict[str, str] = {"reduced": "r", "full": "f", "burst": "b"}
_FILL_ATOL = 1e-6


def artemis_remote_dir(probe_id: str, instrument: str, year: int) -> str:
    return f"{SPDF_THEMIS_URL}{probe_id}/l2/{instrument}/{year:04d}/"


def artemis_filename(probe_id: str, instrument: str, day: date, version: int) -> str:
    return f"{probe_id}_l2_{instrument}_{day:%Y%m%d}_v{version:02d}.cdf"


def _file_pattern(probe_id: str, instrument: str, day: date) -> re.Pattern[str]:
    return re.compile(rf"{probe_id}_l2_{instrument}_{day:%Y%m%d}_v(\d+)\.cdf")


@dataclass
class ArtemisFileSource:
    """Find, download, and register daily ARTEMIS Level 2 CDF files in a Store."""

    store: Store
    timeout_seconds: float = 120.0
    _listings: dict[str, tuple[str, ...]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")

    def local_dir(self, probe_id: str, instrument: str, year: int) -> Path:
        return self.store.raw_path("artemis", "themis", probe_id, "l2", instrument, f"{year:04d}")

    def file_for_day(
        self, probe_id: str, instrument: str, day: date, *, download: DownloadMode
    ) -> Path | None:
        """Return the newest local or remote file for ``day``; ``None`` when there is none."""

        pattern = _file_pattern(probe_id, instrument, day)
        local = _newest(self.local_dir(probe_id, instrument, day.year), pattern)
        if local is not None and download != "always":
            return local
        if download == "never":
            return None
        names = [
            name
            for name in self._listing(probe_id, instrument, day.year)
            if pattern.fullmatch(name)
        ]
        if not names:
            return None
        name = max(names, key=lambda item: int(pattern.fullmatch(item).group(1)))  # type: ignore[union-attr]
        return self._download(probe_id, instrument, day.year, name)

    def _listing(self, probe_id: str, instrument: str, year: int) -> tuple[str, ...]:
        url = artemis_remote_dir(probe_id, instrument, year)
        if url not in self._listings:
            try:
                with urlopen(url, timeout=self.timeout_seconds) as response:
                    text = response.read().decode("utf-8", errors="replace")
            except HTTPError as exc:
                if exc.code != 404:
                    raise
                text = ""
            names = re.findall(rf'href="({probe_id}_l2_{instrument}_\d{{8}}_v\d+\.cdf)"', text)
            self._listings[url] = tuple(sorted(set(names)))
        return self._listings[url]

    def _download(self, probe_id: str, instrument: str, year: int, name: str) -> Path:
        target = self.local_dir(probe_id, instrument, year) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        url = artemis_remote_dir(probe_id, instrument, year) + name
        with NamedTemporaryFile(
            dir=target.parent, prefix=name + ".", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
        try:
            with (
                urlopen(url, timeout=self.timeout_seconds) as response,
                temporary.open("wb") as out,
            ):
                expected = response.headers.get("Content-Length")
                copyfileobj(response, out)
            if expected is not None and temporary.stat().st_size < int(expected):
                raise ContentTooShortError(
                    "Incomplete ARTEMIS download", (str(target), response.headers)
                )
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        self.store.register_raw_file(
            target.relative_to(self.store.raw_path()),
            mission="artemis",
            provider="nasa-spdf",
            provider_path=f"themis/{probe_id}/l2/{instrument}/{year:04d}/{name}",
            download_url=url,
        )
        return target


def _newest(directory: Path, pattern: re.Pattern[str]) -> Path | None:
    if not directory.is_dir():
        return None
    matches = [
        (int(match.group(1)), path)
        for path in directory.iterdir()
        if (match := pattern.fullmatch(path.name))
    ]
    return max(matches)[1] if matches else None


def read_fgm_field(path: Path | str, probe_id: str) -> xr.DataArray:
    """Spin-resolution (~3 s) FGS magnetic field in GSE from one FGM Level 2 file."""

    cdf = _open(path)
    times = _times(cdf, f"{probe_id}_fgs_time")
    values = _values(cdf, f"{probe_id}_fgs_gse", rows=times.size)
    return _vector_array(values, times, units="nT", frame="GSE", path=path)


def read_esa_variable(
    path: Path | str,
    probe_id: str,
    *,
    species: Literal["i", "e"],
    mode: EsaMode,
    quantity: Literal["en_eflux", "density", "velocity_gse"],
) -> xr.DataArray:
    """One ESA Level 2 quantity for ions (``i``) or electrons (``e``) in one mode."""

    import xarray as xr

    if mode not in ESA_MODES:
        raise ValueError("mode must be 'reduced', 'full', or 'burst'")
    prefix = f"{probe_id}_pe{species}{ESA_MODES[mode]}"
    cdf = _open(path)
    times = _times(cdf, f"{prefix}_time")
    values = _values(cdf, f"{prefix}_{quantity}", rows=times.size)
    attrs: dict[str, Any] = {"source_file": str(path), "esa_mode": mode}
    if quantity == "velocity_gse":
        return _vector_array(values, times, units="km/s", frame="GSE", path=path, attrs=attrs)
    if quantity == "density":
        return xr.DataArray(
            values.reshape(-1),
            dims=("time",),
            coords={"time": times},
            attrs={"units": "cm^-3", **attrs},
        )
    energy = _values(cdf, f"{prefix}_en_eflux_yaxis", rows=times.size)
    bins = np.arange(values.shape[1])
    return xr.DataArray(
        values,
        dims=("time", "energy_bin"),
        coords={
            "time": times,
            "energy_bin": bins,
            "energy": (("time", "energy_bin"), energy, {"units": "eV"}),
        },
        attrs={"units": "eV/(cm^2 s sr eV)", **attrs},
    )


def _open(path: Path | str) -> Any:
    try:
        import cdflib
    except ImportError as exc:
        raise RuntimeError(
            'cdflib is required to read ARTEMIS CDF files: pip install "sopran[artemis]"'
        ) from exc
    try:
        return cdflib.CDF(str(path))
    except Exception as exc:  # cdflib raises several error types for broken files
        raise DecodeError(f"Could not open ARTEMIS CDF file: {path}") from exc


def _times(cdf: Any, name: str) -> np.ndarray:
    seconds = _raw(cdf, name).astype(float).reshape(-1)
    if seconds.size and not np.all(np.isfinite(seconds)):
        raise DecodeError(f"ARTEMIS time variable {name} has non-finite values")
    return (seconds * 1e9).astype("int64").astype("datetime64[ns]")


def _values(cdf: Any, name: str, *, rows: int) -> np.ndarray:
    values = _raw(cdf, name).astype(float)
    if values.size == 0:
        values = values.reshape((0, *values.shape[1:])) if values.ndim > 1 else values
    if values.shape[0] != rows:
        raise DecodeError(f"ARTEMIS variable {name} has {values.shape[0]} records, expected {rows}")
    fill = cdf.varattsget(name).get("FILLVAL")
    if fill is not None:
        fill_value = float(np.asarray(fill).reshape(-1)[0])
        if isfinite(fill_value):
            values = np.where(
                np.isclose(values, fill_value, rtol=_FILL_ATOL, atol=0.0), np.nan, values
            )
    return values


def _raw(cdf: Any, name: str) -> np.ndarray:
    try:
        data = cdf.varget(name)
    except ValueError as exc:
        raise DecodeError(f"ARTEMIS CDF file has no variable {name}") from exc
    if data is None:
        return np.empty(0)
    return np.asarray(data)


def _vector_array(
    values: np.ndarray,
    times: np.ndarray,
    *,
    units: str,
    frame: str,
    path: Path | str,
    attrs: dict[str, Any] | None = None,
) -> xr.DataArray:
    import xarray as xr

    vectors = values.reshape(-1, 3) if values.size else np.empty((0, 3))
    return xr.DataArray(
        vectors,
        dims=("time", "component"),
        coords={"time": times, "component": ["x", "y", "z"]},
        attrs={"units": units, "frame": frame, "source_file": str(path), **(attrs or {})},
    )
