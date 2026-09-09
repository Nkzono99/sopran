from __future__ import annotations

import calendar
import os
from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from shutil import copyfileobj
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.error import ContentTooShortError
from urllib.request import urlopen

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    import xarray as xr

from sopran.core.config import current_session_config
from sopran.core.data import SopranArray
from sopran.core.plotting import PlotItem, PlotResult
from sopran.core.schema import VariableSchema
from sopran.core.store import Store
from sopran.core.time import TimeRange, day, period

DownloadMode = Literal["never", "missing", "always"]
BASE_URL = "https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/"
DOCUMENTATION = "https://omniweb.gsfc.nasa.gov/html/ow_data.html"

# One-based OMNI2 ASCII columns. Kp is stored as ten times its physical index.
_COLUMNS = {
    "imf_spacecraft_id": (5, 99.0, "1", None, 1.0),
    "plasma_spacecraft_id": (6, 99.0, "1", None, 1.0),
    "imf_sample_count": (7, 999.0, "1", None, 1.0),
    "plasma_sample_count": (8, 999.0, "1", None, 1.0),
    "b_magnitude": (9, 999.9, "nT", None, 1.0),
    "bx_gse": (13, 999.9, "nT", "GSE", 1.0),
    "by_gse": (14, 999.9, "nT", "GSE", 1.0),
    "bz_gse": (15, 999.9, "nT", "GSE", 1.0),
    "by_gsm": (16, 999.9, "nT", "GSM", 1.0),
    "bz_gsm": (17, 999.9, "nT", "GSM", 1.0),
    "temperature": (23, 9999999.0, "K", None, 1.0),
    "density": (24, 999.9, "cm^-3", None, 1.0),
    "speed": (25, 9999.0, "km/s", None, 1.0),
    "alpha_proton_ratio": (28, 9.999, "1", None, 1.0),
    "pressure": (29, 99.99, "nPa", None, 1.0),
    "electric_field": (36, 999.99, "mV/m", None, 1.0),
    "beta": (37, 999.99, "1", None, 1.0),
    "alfven_mach": (38, 999.9, "1", None, 1.0),
    "kp": (39, 99.0, "1", None, 0.1),
    "dst": (41, 99999.0, "nT", None, 1.0),
    "ae": (42, 9999.0, "nT", None, 1.0),
    "al": (53, 99999.0, "nT", None, 1.0),
    "au": (54, 99999.0, "nT", None, 1.0),
    "magnetosonic_mach": (55, 99.9, "1", None, 1.0),
}


def read_omni_hourly(path: Path | str) -> pd.DataFrame:
    """Read a NASA hourly ASCII file, retaining missing hours and replacing fill values."""
    raw = pd.read_csv(path, sep=r"\s+", header=None)
    if raw.empty or raw.shape[1] < 55 or raw.iloc[:, :55].isna().any().any():
        raise ValueError("Expected OMNI2 hourly ASCII with at least 55 columns")
    stamp = raw.iloc[:, :3].to_numpy(dtype=float)
    if not np.all(np.isfinite(stamp) & (stamp == np.floor(stamp))):
        raise ValueError("OMNI year/day/hour must be finite integers")
    years, days, hours = stamp.astype(int).T
    limits = np.array([366 if calendar.isleap(int(y)) else 365 for y in years])
    if np.any((days < 1) | (days > limits) | (hours < 0) | (hours > 23)):
        raise ValueError("Invalid OMNI day of year or hour")
    index = pd.DatetimeIndex(
        pd.to_datetime(years.astype(str), format="%Y", utc=True)
        + pd.to_timedelta(days - 1, unit="D")
        + pd.to_timedelta(hours, unit="h"),
        name="time",
    )
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError("OMNI hours must be unique and sorted")
    result = pd.DataFrame(index=index)
    for name, (column, fill, _, _, scale) in _COLUMNS.items():
        values = raw[column - 1].to_numpy(dtype=float)
        result[name] = np.where(np.isclose(values, fill, rtol=0, atol=1e-7), np.nan, values) * scale
    result.attrs.update(
        source=str(path),
        documentation=DOCUMENTATION,
        resolution_seconds=3600,
        interval="[time, time + 1 hour)",
        context="near_earth_hourly_proxy_not_local_lunar_measurement",
        units={name: spec[2] for name, spec in _COLUMNS.items()},
    )
    return result


@dataclass(frozen=True)
class OmniData:
    """Loaded hourly data; the scalar field average is not the norm of the mean vector."""

    time: TimeRange
    files: tuple[Path, ...]
    dataset: xr.Dataset

    def to_xarray(self) -> xr.Dataset:
        return self.dataset

    def to_dataframe(self) -> pd.DataFrame:
        frame = self.dataset[list(_COLUMNS)].to_dataframe()
        frame.index = pd.DatetimeIndex(frame.index).tz_localize("UTC")
        frame.attrs.update(self.dataset.attrs)
        frame.attrs["units"] = {name: spec[2] for name, spec in _COLUMNS.items()}
        return frame

    def __getitem__(self, name: str) -> SopranArray:
        array = self.dataset[name]
        schema = VariableSchema(
            name=name,
            dims=tuple(str(dim) for dim in array.dims),
            units=array.attrs["units"],
            frame=array.attrs.get("frame"),
            description=array.attrs["long_name"],
        )
        return SopranArray(
            name=f"omni.{name}", time=self.time, schema=schema, files=self.files, xr=array
        )

    @property
    def pressure(self) -> SopranArray:
        return self["pressure"]

    @property
    def magnetic_field(self) -> SopranArray:
        return self["magnetic_field"]

    @property
    def speed(self) -> SopranArray:
        return self["speed"]

    @property
    def density(self) -> SopranArray:
        return self["density"]

    @property
    def temperature(self) -> SopranArray:
        return self["temperature"]


@dataclass(frozen=True)
class OmniVariable:
    mission: Omni
    name: str

    def load(
        self,
        time: object | None = None,
        stop: object | None = None,
        *,
        download: DownloadMode | None = None,
    ) -> SopranArray:
        return self.mission.load(time, stop, download=download)[self.name]

    def plot(
        self,
        time: object | None = None,
        stop: object | None = None,
        *,
        download: DownloadMode | None = None,
        **kwargs: Any,
    ) -> PlotResult:
        kwargs.setdefault("mode", "line")
        return cast(PlotResult, self.load(time, stop, download=download).plot(**kwargs))

    def line(
        self,
        time: object | None = None,
        stop: object | None = None,
        *,
        download: DownloadMode | None = None,
    ) -> PlotItem:
        return self.load(time, stop, download=download).line()


class Omni:
    """OMNI2 hourly access with Store caching and optional view-bound time."""

    def __init__(
        self,
        *,
        store: Store | None = None,
        download: DownloadMode | None = None,
        time: TimeRange | None = None,
        timeout_seconds: float = 90.0,
    ) -> None:
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        self.store = store or Store()
        self.download = _download_mode(download)
        self.time = time
        self.timeout_seconds = timeout_seconds
        self.pressure: OmniVariable = OmniVariable(self, "pressure")
        self.magnetic_field: OmniVariable = OmniVariable(self, "magnetic_field")
        self.b_magnitude: OmniVariable = OmniVariable(self, "b_magnitude")
        self.speed: OmniVariable = OmniVariable(self, "speed")
        self.density: OmniVariable = OmniVariable(self, "density")
        self.temperature: OmniVariable = OmniVariable(self, "temperature")
        self.bz_gsm: OmniVariable = OmniVariable(self, "bz_gsm")
        self.kp: OmniVariable = OmniVariable(self, "kp")
        self.dst: OmniVariable = OmniVariable(self, "dst")
        self.ae: OmniVariable = OmniVariable(self, "ae")
        self.beta: OmniVariable = OmniVariable(self, "beta")
        self.alfven_mach: OmniVariable = OmniVariable(self, "alfven_mach")

    def variable(self, name: str) -> OmniVariable:
        if name not in _COLUMNS and name != "magnetic_field":
            raise KeyError(name)
        return OmniVariable(self, name)

    def load(
        self,
        time: object | None = None,
        stop: object | None = None,
        *,
        download: DownloadMode | None = None,
    ) -> OmniData:
        import xarray as xr

        interval = _time_range(time if time is not None else self.time, stop)
        policy = self.download if download is None else _download_mode(download)
        final_year = (pd.Timestamp(interval.stop) - pd.Timedelta(microseconds=1)).year
        records = [self._year(y, policy) for y in range(interval.start.year, final_year + 1)]
        frame = pd.concat([row[1] for row in records])
        frame = frame.loc[(frame.index >= interval.start) & (frame.index < interval.stop)]
        times = pd.DatetimeIndex(frame.index).tz_localize(None).to_numpy(dtype="datetime64[ns]")
        arrays = {}
        for name, (_, _, units, coord_frame, _) in _COLUMNS.items():
            attrs = dict(units=units, long_name=f"OMNI {name.replace('_', ' ')}")
            if coord_frame is not None:
                attrs["frame"] = coord_frame
            arrays[name] = xr.DataArray(
                frame[name].to_numpy(), dims="time", coords=dict(time=times), attrs=attrs
            )
        arrays["magnetic_field"] = xr.DataArray(
            frame[["bx_gse", "by_gse", "bz_gse"]].to_numpy(),
            dims=("time", "component"),
            coords=dict(time=times, component=["x", "y", "z"]),
            attrs=dict(units="nT", frame="GSE", long_name="OMNI mean magnetic field (GSE)"),
        )
        files = tuple(row[0] for row in records)
        dataset = xr.Dataset(
            arrays,
            attrs=dict(
                documentation=DOCUMENTATION,
                resolution_seconds=3600,
                time_scale="UTC",
                interval="[time, time + 1 hour)",
                source_files=[str(p) for p in files],
                context="near_earth_hourly_proxy_not_local_lunar_measurement",
            ),
        )
        return OmniData(interval, files, dataset)

    def at(self, times: Iterable[object], *, download: DownloadMode | None = None) -> pd.DataFrame:
        """Match containing UTC hours, without interpolation or filling missing hours."""
        targets = cast(list[Any], list(times))
        index = pd.DatetimeIndex(pd.to_datetime(targets, utc=True, format="mixed"), name="time")
        if index.hasnans:
            raise ValueError("OMNI target times cannot contain NaT")
        if index.empty:
            result = pd.DataFrame(index=index, columns=list(_COLUMNS), dtype=float)
            result["source_time"] = pd.Series(index=index, dtype="datetime64[ns, UTC]")
            result.attrs.update(
                documentation=DOCUMENTATION,
                resolution_seconds=3600,
                context="near_earth_hourly_proxy_not_local_lunar_measurement",
                units={name: spec[2] for name, spec in _COLUMNS.items()},
            )
            return result
        hours = index.floor("h")
        data = self.load(
            period(
                hours.min().to_pydatetime(), (hours.max() + pd.Timedelta(hours=1)).to_pydatetime()
            ),
            download=download,
        )
        source = data.to_dataframe()
        frame = source.reindex(hours)
        frame.index = index
        frame["source_time"] = hours.where(hours.isin(source.index))
        return frame

    def _year(self, year: int, policy: DownloadMode) -> tuple[Path, pd.DataFrame]:
        path = self.store.raw_path("omni", f"omni2_{year}.dat")
        if path.is_file() and policy != "always":
            frame = read_omni_hourly(path)
            _check_year(frame, year)
            return path, frame
        if policy == "never":
            raise FileNotFoundError(f"OMNI hourly file is not cached: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        url = BASE_URL + path.name
        with NamedTemporaryFile(
            dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
        ) as f:
            temporary = Path(f.name)
        try:
            with urlopen(url, timeout=self.timeout_seconds) as response, temporary.open("wb") as f:
                expected = response.headers.get("Content-Length")
                copyfileobj(response, f)
            if expected is not None and temporary.stat().st_size < int(expected):
                raise ContentTooShortError(
                    "Incomplete OMNI download", (str(path), response.headers)
                )
            frame = read_omni_hourly(temporary)
            _check_year(frame, year)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        self.store.register_raw_file(
            path.relative_to(self.store.raw_path()),
            mission="omni",
            provider="nasa-spdf",
            provider_path="low_res_omni/" + path.name,
            download_url=url,
        )
        return path, frame


def _check_year(frame: pd.DataFrame, year: int) -> None:
    if not (pd.DatetimeIndex(frame.index).year == year).all():
        raise ValueError(f"OMNI file contains records outside expected year {year}")


def _time_range(time: object | None, stop: object | None) -> TimeRange:
    if time is None:
        raise ValueError("Specify a time range or use spn.view(time=...).omni")
    if isinstance(time, TimeRange):
        if stop is not None:
            raise ValueError("stop cannot be combined with a TimeRange")
        return time
    return day(time) if stop is None else period(time, stop)


def _download_mode(value: str | None) -> DownloadMode:
    if value is None:
        value = current_session_config().download
    if value is None:
        value = (
            "never"
            if os.environ.get("SOPRAN_OFFLINE", "").lower() in {"1", "true", "yes", "on"}
            else os.environ.get("SOPRAN_DOWNLOAD_MODE", "missing")
        )
    if value not in {"never", "missing", "always"}:
        raise ValueError("download must be never, missing, or always")
    return cast(DownloadMode, value)
