from __future__ import annotations

import gzip
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sopran.core.data import SopranArray
from sopran.core.time import TimeRange
from sopran.missions.kaguya.schema import KAGUYA_LMAG_SCHEMA

LMAG_PUBLIC_COLUMNS = [
    "date",
    "clock",
    "rme_x",
    "rme_y",
    "rme_z",
    "bme_x",
    "bme_y",
    "bme_z",
    "rgse_x",
    "rgse_y",
    "rgse_z",
    "bgse_x",
    "bgse_y",
    "bgse_z",
]


@dataclass(frozen=True)
class KaguyaLmagData:
    frame: pd.DataFrame
    files: tuple[Path, ...] = ()
    time: TimeRange | None = None
    instrument: str = "LMAG"
    missing_reason: str | None = None

    @property
    def magnetic_field(self) -> SopranArray:
        return self._magnetic_field("magnetic_field", "magnetic_field_moon_me")

    @property
    def magnetic_field_gse(self) -> SopranArray:
        return self._magnetic_field("magnetic_field_gse", "magnetic_field_gse")

    @property
    def magnetic_field_magnitude(self) -> SopranArray:
        if self.time is None:
            raise ValueError(
                "KaguyaLmagData.magnetic_field_magnitude requires a TimeRange; "
                "use kg.lmag.load(time) or read_lmag_public(..., time=time)."
            )
        try:
            import xarray as xr
        except ImportError as exc:
            raise RuntimeError("xarray is required for magnetic_field_magnitude") from exc
        schema = KAGUYA_LMAG_SCHEMA.variable("magnetic_field_magnitude")
        dataset = self.to_xarray()
        values = np.linalg.norm(
            dataset["magnetic_field_moon_me"].values.astype(float),
            axis=1,
        )
        array = xr.DataArray(
            values,
            dims=("time",),
            coords={"time": dataset.coords["time"].values},
            name=schema.name,
            attrs={
                "units": schema.units,
                "description": schema.description,
            },
        )
        return SopranArray(
            name=schema.name,
            time=self.time,
            schema=schema,
            files=self.files,
            xr=array,
        )

    def _magnetic_field(self, name: str, source: str) -> SopranArray:
        if self.time is None:
            raise ValueError(
                f"KaguyaLmagData.{name} requires a TimeRange; "
                "use kg.lmag.load(time) or read_lmag_public(..., time=time)."
            )
        schema = KAGUYA_LMAG_SCHEMA.variable(name)
        array = self.to_xarray()[source].rename(schema.name)
        array.attrs.update(
            {
                "units": schema.units,
                "frame": schema.frame,
                "description": schema.description,
            }
        )
        return SopranArray(
            name=schema.name,
            time=self.time,
            schema=schema,
            files=self.files,
            xr=array,
        )

    @property
    def b(self) -> SopranArray:
        return self.magnetic_field

    @property
    def bmag(self) -> SopranArray:
        return self.magnetic_field_magnitude

    def to_pandas(self) -> pd.DataFrame:
        return self.frame.copy()

    def to_polars(self):
        try:
            import polars as pl
        except ImportError as exc:
            raise RuntimeError("polars is required for to_polars()") from exc
        return pl.from_pandas(self.to_pandas())

    def to_xarray(self):
        try:
            import xarray as xr
        except ImportError as exc:
            raise RuntimeError("xarray is required for to_xarray()") from exc

        frame = self.frame
        components = np.asarray(["x", "y", "z"], dtype=object)
        time_values = _datetime64_from_unix(frame["time"].to_numpy(dtype=float))
        attrs: dict[str, Any] = {
            "mission": "kaguya",
            "instrument": self.instrument,
            "source_files": [str(path) for path in self.files],
        }
        if self.missing_reason is not None:
            attrs["missing_reason"] = self.missing_reason
        return xr.Dataset(
            data_vars={
                "position_moon_me": (
                    ("time", "component"),
                    _vector(frame, "rme"),
                    {"units": "km", "frame": "MOON_ME"},
                ),
                "magnetic_field_moon_me": (
                    ("time", "component"),
                    _vector(frame, "bme"),
                    {"units": "nT", "frame": "MOON_ME"},
                ),
                "position_gse": (
                    ("time", "component"),
                    _vector(frame, "rgse"),
                    {"units": "km", "frame": "GSE"},
                ),
                "magnetic_field_gse": (
                    ("time", "component"),
                    _vector(frame, "bgse"),
                    {"units": "nT", "frame": "GSE"},
                ),
            },
            coords={"time": time_values, "component": components},
            attrs=attrs,
        )


def read_lmag_public(
    files: str | Path | Iterable[str | Path],
    *,
    time: TimeRange | None = None,
    missing_reason: str | None = None,
) -> KaguyaLmagData:
    paths = _as_paths(files)
    frames = [_read_public_file(path) for path in paths]
    frame = pd.concat(frames, ignore_index=True) if frames else _empty_frame()
    frame = _filter_time(frame, time).sort_values("time", ignore_index=True)
    return KaguyaLmagData(
        frame=frame,
        files=tuple(paths),
        time=time,
        missing_reason=missing_reason,
    )


def _as_paths(files: str | Path | Iterable[str | Path]) -> list[Path]:
    if isinstance(files, str | Path):
        return [Path(files)]
    return [Path(file) for file in files]


def _read_public_file(path: Path) -> pd.DataFrame:
    frame = _read_table(path, LMAG_PUBLIC_COLUMNS)
    return _replace_invalid(_append_time(frame))


def _read_table(path: Path, names: list[str]) -> pd.DataFrame:
    with _open_text(path) as file:
        frame = pd.read_csv(file, sep=r"\s*,\s*|\s+", header=None, engine="python")
    frame = frame.dropna(axis=1, how="all")
    if frame.shape[1] == len(names):
        frame.columns = names
        return frame
    if frame.shape[1] == len(names) - 1 and names[:2] == ["date", "clock"]:
        frame.columns = ["datetime", *names[2:]]
        return frame
    raise ValueError(f"Unexpected KAGUYA LMAG column count in {path}: {frame.shape[1]}")


def _open_text(path: Path):
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt")
    return path.open("r", encoding="utf-8")


def _append_time(frame: pd.DataFrame) -> pd.DataFrame:
    if "datetime" in frame.columns:
        text = frame["datetime"].astype(str).str.rstrip(",")
        dt = pd.to_datetime(text, utc=True, format="mixed")
        frame = frame.drop(columns=["datetime"])
    else:
        text = frame["date"].astype(str) + " " + frame["clock"].astype(str)
        dt = pd.to_datetime(text, utc=True, format="mixed")
        frame = frame.drop(columns=["date", "clock"])
    frame.insert(0, "time", np.asarray([value.timestamp() for value in dt], dtype=float))
    return frame


def _replace_invalid(frame: pd.DataFrame) -> pd.DataFrame:
    for column in frame.columns:
        if column != "time":
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.replace(999.99, np.nan)


def _filter_time(frame: pd.DataFrame, time: TimeRange | None) -> pd.DataFrame:
    if time is None or frame.empty:
        return frame
    start = time.start.timestamp()
    stop = time.stop.timestamp()
    return frame[(frame["time"] >= start) & (frame["time"] < stop)]


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["time", *LMAG_PUBLIC_COLUMNS[2:]])


def _vector(frame: pd.DataFrame, prefix: str) -> np.ndarray:
    columns = [f"{prefix}_x", f"{prefix}_y", f"{prefix}_z"]
    return frame[columns].to_numpy(dtype=float)


def _datetime64_from_unix(values: Any) -> np.ndarray:
    return np.asarray(
        [
            np.datetime64(
                pd.Timestamp(value, unit="s", tz="UTC").tz_convert(None).to_datetime64(),
                "ns",
            )
            for value in values
        ],
        dtype="datetime64[ns]",
    )
