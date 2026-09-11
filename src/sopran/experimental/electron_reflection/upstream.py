"""Hourly near-Earth OMNI context, not a measurement of the local lunar plasma."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OMNI_DOCUMENTATION = "https://omniweb.gsfc.nasa.gov/html/ow_data.html"
# One-based NASA OMNI2 ASCII column, fill value, output column (unit in name).
OMNI_COLUMNS = (
    (9, 999.9, "omni_b_nT"),
    (13, 999.9, "omni_bx_gse_nT"),
    (14, 999.9, "omni_by_gse_nT"),
    (15, 999.9, "omni_bz_gse_nT"),
    (17, 999.9, "omni_bz_gsm_nT"),
    (23, 9999999.0, "omni_temperature_K"),
    (24, 999.9, "omni_density_cm3"),
    (25, 9999.0, "omni_speed_km_s"),
    (29, 99.99, "omni_pressure_nPa"),
    (37, 999.99, "omni_beta"),
    (38, 999.9, "omni_alfven_mach"),
    (41, 99999.0, "omni_dst_nT"),
)


def read_omni_hourly(path: Path) -> pd.DataFrame:
    """Read official annual OMNI2 ASCII; preserve gaps, never interpolate fills."""
    raw = pd.read_csv(path, sep=r"\s+", header=None)
    if raw.shape[1] < 42:
        raise ValueError("Expected at least 42 OMNI2 ASCII columns")
    year, doy, hour = (raw[i] for i in range(3))
    if not (hour.between(0, 23).all() and doy.between(1, 366).all()):
        raise ValueError("Invalid OMNI timestamp")
    index = pd.DatetimeIndex(
        pd.to_datetime(year.astype(int).astype(str), format="%Y", utc=True)
        + pd.to_timedelta(doy - 1, unit="D")
        + pd.to_timedelta(hour, unit="h"),
        name="omni_hour",
    )
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError("OMNI hours must be unique and sorted")
    result = pd.DataFrame(index=index)
    for column, fill, name in OMNI_COLUMNS:
        values = raw[column - 1].to_numpy(dtype=float)
        result[name] = np.where(np.isclose(values, fill, rtol=0, atol=1e-7), np.nan, values)
    result.attrs.update(
        source=str(path),
        documentation=OMNI_DOCUMENTATION,
        context="near_earth_hourly_proxy_not_local_lunar_measurement",
    )
    return result


def match_omni_hourly(times: pd.DatetimeIndex, hourly: pd.DataFrame) -> pd.DataFrame:
    """Join [HH:00, HH+1:00) intervals. Naive timestamps are interpreted as UTC."""
    index = pd.DatetimeIndex(pd.to_datetime(times, utc=True))
    if hourly.index.tz is None or hourly.index.has_duplicates:
        raise ValueError("OMNI index must be timezone-aware and unique")
    matched = hourly.reindex(index.floor("h")).copy()
    matched.insert(0, "omni_hour", index.floor("h"))
    matched.index = index
    matched["upstream_pressure_available"] = matched.omni_pressure_nPa.notna()
    matched["upstream_context"] = "near_earth_hourly_proxy"
    matched["lunar_plasma_regime"] = "undetermined"
    return matched
