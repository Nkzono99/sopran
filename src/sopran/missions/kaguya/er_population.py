"""LMAG geometry diagnostics for population studies of saved ER fits.

Connection here means intersection of a straight local B line with the mean
lunar sphere. It is not magnetic field-line tracing or proof of lunar origin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from .geometry import MOON_MEAN_RADIUS_KM, lmag_magnetic_connection

if TYPE_CHECKING:
    from .lmag import KaguyaLmagData


def magnetic_geometry_samples(
    data: KaguyaLmagData, *, radius_km: float = MOON_MEAN_RADIUS_KM
) -> pd.DataFrame:
    """Return native LMAG samples, angles in degrees and distances in km.

    surface_crossing_deg is 0 at tangency and 90 at normal incidence. Its
    complement incidence_normal_deg is the angle to the footpoint normal.
    Nonintersections and invalid geometry have missing footpoint angles.
    """
    if not np.isfinite(radius_km) or radius_km <= 0:
        raise ValueError("radius_km must be positive and finite")
    ds = data.to_xarray()
    r = np.asarray(ds.position_moon_me.values, dtype=float)
    b = np.asarray(ds.magnetic_field_moon_me.values, dtype=float)
    nr, nb = np.linalg.norm(r, axis=1), np.linalg.norm(b, axis=1)
    valid = np.isfinite(r).all(axis=1) & np.isfinite(b).all(axis=1)
    valid &= (nr >= radius_km) & (nb > 0)
    cosine = np.full(len(r), np.nan)
    np.divide(np.sum(r * b, axis=1), nr * nb, out=cosine, where=valid)
    cosine = np.clip(cosine, -1, 1)
    frame = lmag_magnetic_connection(data, radius_km=radius_km).to_pandas()
    frame["time"] = pd.to_datetime(ds.time.values, utc=True)
    frame["geometry_valid"] = valid
    frame["local_radial_angle_deg"] = np.degrees(np.arccos(np.abs(cosine)))
    frame["local_signed_elevation_deg"] = np.degrees(np.arcsin(cosine))
    frame["line_clearance_km"] = nr * np.sqrt(1 - cosine**2) - radius_km
    frame["connection"] = "unavailable"
    frame.loc[valid, "connection"] = "nonintersecting"
    for side in ("plus", "minus"):
        connected = valid & frame[f"connected_{side}"].to_numpy(dtype=bool)
        frame.loc[connected, "connection"] = side
        frame[f"connected_{side}"] = connected
    frame["connected_any"] = frame.connected_plus | frame.connected_minus
    for destination, source in (
        ("incidence_normal_deg", "incidence_angle_{side}_deg"),
        ("footpoint_lon_deg", "footpoint_{side}_lon"),
        ("footpoint_lat_deg", "footpoint_{side}_lat"),
        ("distance_km", "distance_{side}_km"),
    ):
        frame[destination] = np.nan
        for side in ("plus", "minus"):
            mask = frame[f"connected_{side}"]
            values = pd.to_numeric(frame[source.format(side=side)], errors="coerce")
            frame.loc[mask, destination] = values[mask]
    frame["surface_crossing_deg"] = 90 - frame.incidence_normal_deg
    return frame[
        ["time", "geometry_valid", "connection", "connected_any",
         "local_radial_angle_deg", "local_signed_elevation_deg", "line_clearance_km",
         "surface_crossing_deg", "incidence_normal_deg", "footpoint_lon_deg",
         "footpoint_lat_deg", "distance_km"]
    ].sort_values("time").drop_duplicates("time").reset_index(drop=True)


def summarize_window_geometry(
    samples: pd.DataFrame, start: str, stop: str, *, nominal_cadence_seconds: float = 4.0
) -> dict[str, str | int | float | None]:
    """Summarize [start, stop); completeness is diagnostic, not a fit filter."""
    begin, end = pd.Timestamp(start), pd.Timestamp(stop)
    begin = begin.tz_localize("UTC") if begin.tz is None else begin.tz_convert("UTC")
    end = end.tz_localize("UTC") if end.tz is None else end.tz_convert("UTC")
    if end <= begin or not np.isfinite(nominal_cadence_seconds) or nominal_cadence_seconds <= 0:
        raise ValueError("A positive window and cadence are required")
    times = pd.DatetimeIndex(samples.time)
    lo, hi = times.searchsorted([begin, end])
    window = samples.iloc[lo:hi]
    valid = window[window.geometry_valid.astype(bool)]
    connected = valid[valid.connected_any.astype(bool)]
    labels = set(valid.connection)
    connection = next(iter(labels)) if len(labels) == 1 else "mixed" if labels else "unavailable"
    expected = int(np.ceil((end - begin).total_seconds() / nominal_cadence_seconds))
    support = "missing" if window.empty else "partial"
    if len(valid) >= expected:
        points = pd.DatetimeIndex(valid.time)
        gap = max((points[1:] - points[:-1]).total_seconds(), default=0)
        if (gap <= nominal_cadence_seconds * 1.01
                and (points[0] - begin).total_seconds() <= nominal_cadence_seconds
                and (end - points[-1]).total_seconds() <= nominal_cadence_seconds):
            support = "complete"
    result: dict[str, str | int | float | None] = dict(
        connection=connection, geometry_support=support, geometry_samples=len(window),
        geometry_valid_samples=len(valid), geometry_expected_samples=expected,
        connected_samples=len(connected),
        connected_fraction=len(connected) / len(valid) if len(valid) else None,
    )
    for name in ("surface_crossing_deg", "incidence_normal_deg", "local_radial_angle_deg",
                 "local_signed_elevation_deg", "line_clearance_km"):
        values = valid[name].dropna()
        for stat in ("min", "median", "max"):
            result[f"{name}_{stat}"] = float(getattr(values, stat)()) if len(values) else None
    return result
