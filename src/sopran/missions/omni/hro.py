"""NASA OMNI high-resolution (HRO) 5-minute data from monthly CDAWeb CDF files.

The 5-minute product carries the solar-wind velocity vector in GSE, which the
hourly OMNI2 text files do not. SOPRAN keeps the CDF values as published:
velocities are time-shifted to the bow-shock nose and the GSE ``Vy`` component
already has the mean Earth orbital aberration removed by NASA (see
:data:`OMNI_ABERRATION_CORRECTION_KM_S`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from shutil import copyfileobj
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, cast
from urllib.error import ContentTooShortError
from urllib.request import urlopen

import numpy as np
import pandas as pd

from sopran.core.config import DownloadMode, resolve_download_mode
from sopran.core.data import SopranArray
from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.core.store import Store
from sopran.core.time import TimeRange, day, period

if TYPE_CHECKING:
    import xarray as xr

BASE_URL = "https://spdf.gsfc.nasa.gov/pub/data/omni/omni_cdaweb/hro_5min/"
DOCUMENTATION = "https://omniweb.gsfc.nasa.gov/html/omni_min_data.html"
RESOLUTION_SECONDS = 300
EARTH_RADIUS_KM = 6371.2
#: NASA removes the mean Earth orbital aberration from the published GSE ``Vy``.
#: Add this vector once to recover the geocentric flow direction (HRO documentation, Appendix 4).
OMNI_ABERRATION_CORRECTION_KM_S = (0.0, 29.8, 0.0)

# CDF variable -> (SOPRAN name, units, frame)
_VARIABLES: dict[str, tuple[str, str, str | None]] = {
    "Vx": ("vx_gse", "km/s", "GSE"),
    "Vy": ("vy_gse", "km/s", "GSE"),
    "Vz": ("vz_gse", "km/s", "GSE"),
    "flow_speed": ("speed", "km/s", None),
    "proton_density": ("density", "cm^-3", None),
    "T": ("temperature", "K", None),
    "Pressure": ("pressure", "nPa", None),
    "F": ("b_magnitude", "nT", None),
    "BX_GSE": ("bx_gse", "nT", "GSE"),
    "BY_GSE": ("by_gse", "nT", "GSE"),
    "BZ_GSE": ("bz_gse", "nT", "GSE"),
    "BY_GSM": ("by_gsm", "nT", "GSM"),
    "BZ_GSM": ("bz_gsm", "nT", "GSM"),
    "E": ("electric_field", "mV/m", None),
    "Beta": ("beta", "1", None),
    "Mach_num": ("alfven_mach", "1", None),
    "Mgs_mach_num": ("magnetosonic_mach", "1", None),
    "Timeshift": ("timeshift", "s", None),
    "BSN_x": ("bsn_x", "Re", "GSE"),
    "x": ("spacecraft_x", "Re", "GSE"),
    "SYM_H": ("sym_h", "nT", None),
    "AE_INDEX": ("ae", "nT", None),
}

OMNI_HRO_SCHEMA = InstrumentSchema(
    mission="omni",
    instrument="hro_5min",
    variables=(
        VariableSchema(
            name="velocity",
            dims=("time", "component"),
            units="km/s",
            dtype="float64",
            frame="GSE",
            description=(
                "Solar-wind bulk velocity vector at the bow-shock nose; NASA removes the mean "
                "Earth aberration from Vy"
            ),
        ),
        VariableSchema(
            name="magnetic_field",
            dims=("time", "component"),
            units="nT",
            dtype="float64",
            frame="GSE",
            description="5-minute mean interplanetary magnetic field vector",
        ),
        VariableSchema(
            name="speed", dims=("time",), units="km/s", dtype="float64", description="Flow speed"
        ),
        VariableSchema(
            name="density",
            dims=("time",),
            units="cm^-3",
            dtype="float64",
            description="Proton density",
        ),
        VariableSchema(
            name="pressure",
            dims=("time",),
            units="nPa",
            dtype="float64",
            description="Flow pressure",
        ),
        VariableSchema(
            name="timeshift",
            dims=("time",),
            units="s",
            dtype="float64",
            description="Shift applied by NASA from the observing spacecraft to the bow-shock nose",
        ),
        VariableSchema(
            name="bsn_x",
            dims=("time",),
            units="Re",
            dtype="float64",
            frame="GSE",
            description="Bow-shock nose x position used for the NASA time shift",
        ),
    ),
)


def read_omni_hro(path: Path | str) -> pd.DataFrame:
    """Read one monthly HRO 5-minute CDF with ``cdflib``; fill values become NaN."""

    try:
        import cdflib
    except ImportError as exc:
        raise RuntimeError("cdflib is required to read OMNI HRO CDF files") from exc
    cdf = cdflib.CDF(str(path))
    arrays: dict[str, np.ndarray] = {}
    fills: dict[str, float | None] = {}
    for name in ("Epoch", *_VARIABLES):
        arrays[name] = np.asarray(cdf.varget(name))
        attributes = cdf.varattsget(name)
        fill = attributes.get("FILLVAL") if isinstance(attributes, Mapping) else None
        fills[name] = None if fill is None else float(np.asarray(fill).reshape(-1)[0])
    epoch = cdflib.cdfepoch.unixtime(arrays["Epoch"])
    frame = read_omni_hro_arrays(np.asarray(epoch, dtype=float), arrays, fills)
    frame.attrs["source"] = str(path)
    return frame


def read_omni_hro_arrays(
    unix_time: np.ndarray,
    arrays: Mapping[str, np.ndarray],
    fills: Mapping[str, float | None] | None = None,
) -> pd.DataFrame:
    """Build the HRO table from decoded CDF arrays (one row per 5-minute sample)."""

    times = np.asarray(unix_time, dtype=float)
    if times.ndim != 1 or not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0.0):
        raise ValueError("OMNI HRO epochs must be finite and strictly increasing")
    index = pd.DatetimeIndex(pd.to_datetime(times, unit="s", utc=True), name="time")
    result = pd.DataFrame(index=index)
    for cdf_name, (name, _, _) in _VARIABLES.items():
        if cdf_name not in arrays:
            raise ValueError(f"OMNI HRO arrays are missing {cdf_name}")
        values = np.asarray(arrays[cdf_name], dtype=float).reshape(-1)
        if values.size != times.size:
            raise ValueError(f"OMNI HRO variable {cdf_name} does not match the epoch length")
        fill = None if fills is None else fills.get(cdf_name)
        if fill is not None and isfinite(fill):
            values = np.where(
                np.isclose(values, fill, rtol=0.0, atol=abs(fill) * 1e-6 + 1e-9), np.nan, values
            )
        result[name] = values
    result.attrs.update(
        documentation=DOCUMENTATION,
        resolution_seconds=RESOLUTION_SECONDS,
        context="bow_shock_nose_5min_proxy_not_local_lunar_measurement",
        aberration="NASA removed the mean Earth aberration from vy_gse",
        units={name: units for name, units, _ in _VARIABLES.values()},
    )
    return result


@dataclass(frozen=True)
class OmniHroData:
    """Loaded 5-minute HRO data for one time range."""

    time: TimeRange
    files: tuple[Path, ...]
    frame: pd.DataFrame

    def to_dataframe(self) -> pd.DataFrame:
        return self.frame

    def to_xarray(self) -> xr.Dataset:
        import xarray as xr

        times = (
            pd.DatetimeIndex(self.frame.index).tz_localize(None).to_numpy(dtype="datetime64[ns]")
        )
        arrays: dict[str, Any] = {}
        for name, units, frame in _VARIABLES.values():
            attrs: dict[str, Any] = dict(
                units=units, long_name=f"OMNI HRO {name.replace('_', ' ')}"
            )
            if frame is not None:
                attrs["frame"] = frame
            arrays[name] = xr.DataArray(
                self.frame[name].to_numpy(), dims="time", coords=dict(time=times), attrs=attrs
            )
        component = ["x", "y", "z"]
        arrays["velocity"] = xr.DataArray(
            self.frame[["vx_gse", "vy_gse", "vz_gse"]].to_numpy(dtype=float),
            dims=("time", "component"),
            coords=dict(time=times, component=component),
            attrs=dict(units="km/s", frame="GSE", long_name="OMNI HRO solar-wind velocity (GSE)"),
        )
        arrays["magnetic_field"] = xr.DataArray(
            self.frame[["bx_gse", "by_gse", "bz_gse"]].to_numpy(dtype=float),
            dims=("time", "component"),
            coords=dict(time=times, component=component),
            attrs=dict(units="nT", frame="GSE", long_name="OMNI HRO magnetic field (GSE)"),
        )
        return xr.Dataset(
            arrays,
            attrs=dict(
                documentation=DOCUMENTATION,
                resolution_seconds=RESOLUTION_SECONDS,
                time_scale="UTC",
                source_files=[str(p) for p in self.files],
                context=self.frame.attrs.get("context"),
                aberration=self.frame.attrs.get("aberration"),
            ),
        )

    @property
    def velocity(self) -> SopranArray:
        return self._array("velocity")

    @property
    def magnetic_field(self) -> SopranArray:
        return self._array("magnetic_field")

    def __getitem__(self, name: str) -> SopranArray:
        return self._array(name)

    def _array(self, name: str) -> SopranArray:
        array = self.to_xarray()[name]
        schema = VariableSchema(
            name=name,
            dims=tuple(str(dim) for dim in array.dims),
            units=array.attrs.get("units"),
            frame=array.attrs.get("frame"),
            description=str(array.attrs.get("long_name", "")),
        )
        return SopranArray(
            name=f"omni.hro.{name}", time=self.time, schema=schema, files=self.files, xr=array
        )

    def at(
        self,
        times: Iterable[object],
        *,
        tolerance_seconds: float = 600.0,
        columns: tuple[str, ...] = ("vx_gse", "vy_gse", "vz_gse", "speed", "density", "pressure"),
    ) -> pd.DataFrame:
        """Nearest 5-minute sample for each time, without interpolation.

        Rows farther than ``tolerance_seconds`` from any sample are NaN. The
        matched sample time is ``source_time`` and the signed offset is
        ``dt_seconds`` (target minus source).
        """

        targets = pd.DatetimeIndex(pd.to_datetime(list(cast(Any, times)), utc=True, format="mixed"))
        if targets.hasnans:
            raise ValueError("target times cannot contain NaT")
        source = pd.DatetimeIndex(self.frame.index)
        target_unix = _unix_seconds(targets)
        source_unix = _unix_seconds(source)
        out = pd.DataFrame(index=pd.DatetimeIndex(targets, name="time"))
        if source_unix.size == 0:
            for column in columns:
                out[column] = np.nan
            out["source_time"] = pd.NaT
            out["dt_seconds"] = np.nan
            return out
        position = np.searchsorted(source_unix, target_unix)
        left = np.clip(position - 1, 0, source_unix.size - 1)
        right = np.clip(position, 0, source_unix.size - 1)
        choose_right = np.abs(source_unix[right] - target_unix) < np.abs(
            source_unix[left] - target_unix
        )
        nearest = np.where(choose_right, right, left)
        offset = target_unix - source_unix[nearest]
        matched = np.abs(offset) <= tolerance_seconds
        for column in columns:
            values = self.frame[column].to_numpy(dtype=float)[nearest]
            out[column] = np.where(matched, values, np.nan)
        out["source_time"] = pd.Series(source[nearest], index=out.index).where(matched)
        out["dt_seconds"] = np.where(matched, offset, np.nan)
        return out


class OmniHighResolution:
    """OMNI HRO 5-minute access with Store caching of the monthly CDF files."""

    def __init__(
        self,
        *,
        store: Store | None = None,
        download: DownloadMode | None = None,
        time: TimeRange | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        self.store = store or Store()
        self.download = resolve_download_mode(download)
        self.time = time
        self.timeout_seconds = timeout_seconds

    def load(
        self,
        time: object | None = None,
        stop: object | None = None,
        *,
        download: DownloadMode | None = None,
    ) -> OmniHroData:
        interval = _time_range(time if time is not None else self.time, stop)
        policy = self.download if download is None else resolve_download_mode(download)
        months = _months(interval)
        records = [self._month(year, month, policy) for year, month in months]
        frame = pd.concat([row[1] for row in records]) if records else pd.DataFrame()
        attrs = dict(records[0][1].attrs) if records else {}
        frame = frame.loc[(frame.index >= interval.start) & (frame.index < interval.stop)]
        frame.attrs.update(attrs)
        return OmniHroData(interval, tuple(row[0] for row in records), frame)

    def _month(self, year: int, month: int, policy: DownloadMode) -> tuple[Path, pd.DataFrame]:
        name = f"omni_hro_5min_{year:04d}{month:02d}01_v01.cdf"
        path = self.store.raw_path("omni", "hro_5min", f"{year:04d}", name)
        if path.is_file() and policy != "always":
            return path, read_omni_hro(path)
        if policy == "never":
            raise FileNotFoundError(f"OMNI HRO file is not cached: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{BASE_URL}{year:04d}/{name}"
        with NamedTemporaryFile(
            dir=path.parent, prefix=name + ".", suffix=".tmp", delete=False
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
                    "Incomplete OMNI HRO download", (str(path), response.headers)
                )
            frame = read_omni_hro(temporary)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        self.store.register_raw_file(
            path.relative_to(self.store.raw_path()),
            mission="omni",
            provider="nasa-spdf",
            provider_path=f"omni_cdaweb/hro_5min/{year:04d}/{name}",
            download_url=url,
        )
        frame.attrs["source"] = str(path)
        return path, frame


def _unix_seconds(index: pd.DatetimeIndex) -> np.ndarray:
    naive = index.tz_convert(None) if index.tz is not None else index
    return naive.to_numpy(dtype="datetime64[ns]").astype("int64").astype(float) / 1e9


def _months(interval: TimeRange) -> list[tuple[int, int]]:
    start = pd.Timestamp(interval.start)
    final = pd.Timestamp(interval.stop) - pd.Timedelta(microseconds=1)
    months: list[tuple[int, int]] = []
    year, month = start.year, start.month
    while (year, month) <= (final.year, final.month):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def _time_range(time: object | None, stop: object | None) -> TimeRange:
    if time is None:
        raise ValueError("Specify a time range")
    if isinstance(time, TimeRange):
        if stop is not None:
            raise ValueError("stop cannot be combined with a TimeRange")
        return time
    return day(time) if stop is None else period(time, stop)


__all__ = [
    "EARTH_RADIUS_KM",
    "OMNI_ABERRATION_CORRECTION_KM_S",
    "OMNI_HRO_SCHEMA",
    "OmniHighResolution",
    "OmniHroData",
    "read_omni_hro",
    "read_omni_hro_arrays",
]
