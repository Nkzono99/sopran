"""Lunar Prospector MAG/ER Level 1B files from the PDS PPI node.

The LP_1201..LP_1204 volumes hold one ASCII table per day for each dataset,
under ``DATA/<dataset>/<YY_MMMON>/<prefix><YYMMDD>.TAB``. Missing values use
per-column constants from the PDS labels and become NaN here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite
from pathlib import Path
from shutil import copyfileobj
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING
from urllib.error import ContentTooShortError, HTTPError
from urllib.request import urlopen

import numpy as np

from sopran.core.config import DownloadMode
from sopran.core.errors import DecodeError
from sopran.core.store import Store

if TYPE_CHECKING:
    import pandas as pd
    import xarray as xr

PPI_VOLUME_URL = "https://pds-ppi.igpp.ucla.edu/volume/"
#: (volume, first day, last day) of the Level 1B DVD series.
VOLUMES: tuple[tuple[str, date, date], ...] = (
    ("LP_1201", date(1998, 1, 16), date(1998, 5, 31)),
    ("LP_1202", date(1998, 6, 1), date(1998, 10, 31)),
    ("LP_1203", date(1998, 11, 1), date(1999, 3, 31)),
    ("LP_1204", date(1999, 4, 1), date(1999, 7, 29)),
)
#: dataset directory -> file prefix
DATASETS = {"MAG": "MA", "ER_LO_TS": "EL", "ER_3DIST": "3D"}
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
ER_ENERGY_BINS = 15
ER_LOOK_DIRECTIONS = 88


def volume_for(day: date) -> str | None:
    for volume, first, last in VOLUMES:
        if first <= day <= last:
            return volume
    return None


def lp_provider_path(dataset: str, day: date) -> str | None:
    """Path below the PPI volume root, or ``None`` outside the mission."""

    volume = volume_for(day)
    if volume is None:
        return None
    month = f"{day:%y}_{day.month:02d}{_MONTHS[day.month - 1]}"
    return f"{volume}/DATA/{dataset}/{month}/{DATASETS[dataset]}{day:%y%m%d}.TAB"


def lp_support_path(dataset: str, name: str) -> str:
    """Path of a dataset-level table (``E_BINS.TAB``, ``THETA.TAB``); identical in every volume."""

    return f"{VOLUMES[0][0]}/DATA/{dataset}/{name}"


@dataclass
class LpFileSource:
    """Find, download, and register Lunar Prospector tables in a Store."""

    store: Store
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")

    def local_path(self, provider_path: str) -> Path:
        return self.store.raw_path("lunar_prospector", "pds3", *provider_path.split("/"))

    def fetch(self, provider_path: str, *, download: DownloadMode) -> Path | None:
        """Return the local table, retrieving it per ``download``; ``None`` when there is none."""

        target = self.local_path(provider_path)
        if target.exists() and download != "always":
            return target
        if download == "never":
            return None
        try:
            return self._download(provider_path, target)
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def _download(self, provider_path: str, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        url = PPI_VOLUME_URL + provider_path
        with NamedTemporaryFile(
            dir=target.parent, prefix=target.name + ".", suffix=".tmp", delete=False
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
                    "Incomplete Lunar Prospector download", (str(target), response.headers)
                )
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        self.store.register_raw_file(
            target.relative_to(self.store.raw_path()),
            mission="lunar_prospector",
            provider="pds-ppi",
            provider_path=provider_path,
            download_url=url,
        )
        return target


def read_mag(path: Path | str) -> xr.Dataset:
    """5-s MAG table: field in SSE and SEL, RMS, and position in SSE and SEL (km)."""

    import xarray as xr

    table = _read_table(path, columns=16)
    times = _pds_times(table[0], path)
    values = table.iloc[:, 1:].to_numpy(dtype=float)
    values[:, 1:7] = _missing(values[:, 1:7], 999.999)
    values[:, 7] = _missing(values[:, 7], 999.999)
    values[:, 8:14] = _missing(values[:, 8:14], 999999.99)
    component = ["x", "y", "z"]

    def vector(columns: slice, units: str, frame: str) -> xr.DataArray:
        return xr.DataArray(
            values[:, columns],
            dims=("time", "component"),
            coords={"time": times, "component": component},
            attrs={"units": units, "frame": frame},
        )

    return xr.Dataset(
        {
            "magnetic_field_sel": vector(slice(1, 4), "nT", "SEL"),
            "magnetic_field": vector(slice(4, 7), "nT", "SSE"),
            "magnetic_field_rms": xr.DataArray(
                values[:, 7], dims=("time",), coords={"time": times}, attrs={"units": "nT"}
            ),
            "position_sel": vector(slice(8, 11), "km", "SEL"),
            "position": vector(slice(11, 14), "km", "SSE"),
        },
        attrs={"source_file": str(path)},
    )


def read_energy_bins(path: Path | str) -> tuple[np.ndarray, np.ndarray]:
    """ER energy tables: start times (datetime64) and centre energies (eV), one row per change."""

    table = _read_table(path, columns=2 + ER_ENERGY_BINS)
    starts = (table[0].to_numpy(dtype=float) * 1e9).astype("int64").astype("datetime64[ns]")
    energies = table.iloc[:, 2:].to_numpy(dtype=float)
    order = np.argsort(starts)
    return starts[order], energies[order]


def read_er_flux(path: Path | str, energy_bins: tuple[np.ndarray, np.ndarray]) -> xr.DataArray:
    """~80-s omnidirectional electron flux in 15 energy bins with the energy table in effect."""

    import xarray as xr

    table = _read_table(path, columns=1 + ER_ENERGY_BINS)
    times = _pds_times(table[0], path)
    flux = _missing(table.iloc[:, 1:].to_numpy(dtype=float), 9.999e-99, relative=True)
    starts, tables = energy_bins
    index = np.searchsorted(starts, times, side="right") - 1
    energy = np.full(flux.shape, np.nan)
    known = index >= 0
    energy[known] = tables[index[known]]
    return xr.DataArray(
        flux,
        dims=("time", "energy_bin"),
        coords={
            "time": times,
            "energy_bin": np.arange(ER_ENERGY_BINS),
            "energy": (("time", "energy_bin"), energy, {"units": "eV"}),
        },
        attrs={"units": "1/(cm^2 s sr eV)", "source_file": str(path)},
    )


def read_theta(path: Path | str) -> np.ndarray:
    """Fixed detector inclination (theta, deg) for each of the 88 look directions."""

    values = np.loadtxt(path, dtype=float).reshape(-1)
    if values.size != ER_LOOK_DIRECTIONS:
        raise DecodeError(f"THETA.TAB must list {ER_LOOK_DIRECTIONS} angles: {path}")
    return values


def read_er_3d(path: Path | str, theta: np.ndarray) -> xr.DataArray:
    """3-D electron spectra: 15 energy records x 88 look directions per ~80-s spectrum.

    The time coordinate is the spectrum time; each record keeps its own time
    (``record_time``), energy, azimuths (``phi``) and despun-spacecraft field
    components (``bx_despun``, ``by_despun``, ``bz_despun``).
    """

    import pandas as pd
    import xarray as xr

    columns = 7 + 2 * ER_LOOK_DIRECTIONS
    table = _read_table(path, columns=columns)
    if table.empty:
        raise DecodeError(f"Lunar Prospector 3-D table has no records: {path}")
    record_times = _pds_times(table[0], path)
    spectrum_seconds = _missing(table[1].to_numpy(dtype=float), 99999999999999.0)
    energy = _missing(table[2].to_numpy(dtype=float), 99999.999)
    spectrum = table[3].to_numpy(dtype=int)
    field = _missing(table.iloc[:, 4:7].to_numpy(dtype=float), 999999.999999)
    flux = _missing(
        table.iloc[:, 7 : 7 + ER_LOOK_DIRECTIONS].to_numpy(dtype=float), 9.999e-99, relative=True
    )
    phi = _missing(table.iloc[:, 7 + ER_LOOK_DIRECTIONS :].to_numpy(dtype=float), 999.99)

    spectra, first = np.unique(spectrum, return_index=True)
    spectra = spectra[np.argsort(first)]
    position = {value: index for index, value in enumerate(spectra)}
    row = np.array([position[value] for value in spectrum])
    step = pd.Series(row).groupby(row).cumcount().to_numpy()
    keep = step < ER_ENERGY_BINS
    shape = (spectra.size, ER_ENERGY_BINS)

    def grid(values: np.ndarray, *extra: int) -> np.ndarray:
        out = np.full((*shape, *extra), np.nan)
        out[row[keep], step[keep]] = values[keep]
        return out

    times = np.full(spectra.size, np.datetime64("NaT"), dtype="datetime64[ns]")
    finite = np.isfinite(spectrum_seconds)
    times[row[finite]] = (spectrum_seconds[finite] * 1e9).astype("int64").astype("datetime64[ns]")
    valid = ~np.isnat(times)
    record_time = np.full(shape, np.datetime64("NaT"), dtype="datetime64[ns]")
    record_time[row[keep], step[keep]] = record_times[keep]
    field_grid = grid(field, 3)
    array = xr.DataArray(
        grid(flux, ER_LOOK_DIRECTIONS),
        dims=("time", "energy_bin", "look"),
        coords={
            "time": times,
            "energy_bin": np.arange(ER_ENERGY_BINS),
            "look": np.arange(ER_LOOK_DIRECTIONS),
            "energy": (("time", "energy_bin"), grid(energy), {"units": "eV"}),
            "record_time": (("time", "energy_bin"), record_time),
            "theta": (("look",), theta, {"units": "deg"}),
            "phi": (
                ("time", "energy_bin", "look"),
                grid(phi, ER_LOOK_DIRECTIONS),
                {"units": "deg"},
            ),
            "bx_despun": (("time", "energy_bin"), field_grid[..., 0], {"units": "nT"}),
            "by_despun": (("time", "energy_bin"), field_grid[..., 1], {"units": "nT"}),
            "bz_despun": (("time", "energy_bin"), field_grid[..., 2], {"units": "nT"}),
        },
        attrs={"units": "1/(cm^2 s sr eV)", "source_file": str(path)},
    )
    return array.isel(time=np.flatnonzero(valid))


def _read_table(path: Path | str, *, columns: int) -> pd.DataFrame:
    import pandas as pd

    try:
        table = pd.read_csv(path, sep=r"\s+", header=None, dtype={0: str})
    except (ValueError, pd.errors.ParserError) as exc:
        raise DecodeError(f"Could not read Lunar Prospector table: {path}") from exc
    if table.shape[1] != columns:
        raise DecodeError(
            f"Lunar Prospector table {path} has {table.shape[1]} columns, expected {columns}"
        )
    return table


def _pds_times(values: pd.Series, path: Path | str) -> np.ndarray:
    import pandas as pd

    parsed = pd.to_datetime(values, format="ISO8601", errors="coerce")
    if parsed.isna().any():
        raise DecodeError(f"Lunar Prospector table {path} has unreadable times")
    return parsed.to_numpy(dtype="datetime64[ns]")


def _missing(values: np.ndarray, constant: float, *, relative: bool = False) -> np.ndarray:
    tolerance = abs(constant) * 1e-3 if relative else 1e-6 * max(1.0, abs(constant))
    return np.where(np.abs(values - constant) <= tolerance, np.nan, values)
