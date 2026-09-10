"""Literature reference locations, not an exhaustive lunar anomaly inventory.

Numerical reference facts are transcribed from the corrected Table 1 of
Blewett (2011), doi:10.1029/2011JE003852, and Table 1 of Oliveira & Wieczorek
(2017), doi:10.1002/2016JE005199. No source prose, figures, or satellite
payloads are bundled. See docs/maps/moon.md for coordinate semantics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

AnomalyCatalog = Literal["blewett2011", "oliveira2017", "all"]

# id, reported name, east longitude, latitude, peak |B| at 30 km (nT),
# terrain setting, swirl morphology (as classified in 2011).
# IMPORTANT: coordinates are from the correction, not the original article.
_BLEWETT = (
    ("abel", "Abel", 88.0, -32.0, 10.0, "mare/highland", "not_recognized"),
    ("airy", "Airy", 3.25, -18.0, 13.0, "highland", "loop_dark_lane"),
    ("crozier", "Crozier", 51.0, -15.0, 6.0, "mare/highland", "not_recognized"),
    ("descartes", "Descartes", 16.5, -10.5, 24.0, "highland", "diffuse_bright_spot"),
    ("firsov", "Firsov", 115.0, 4.7, 11.0, "highland", "complex"),
    ("gerasimovich", "Gerasimovich", 236.5, -21.0, 28.0, "highland", "loop_dark_lane"),
    ("hartwig", "Hartwig", 280.0, -9.0, 12.0, "highland/mare", "not_recognized"),
    ("hopmann", "Hopmann", 160.0, -48.5, 5.0, "mare/highland", "complex_loop"),
    ("ingenii", "Ingenii", 160.0, -33.5, 20.0, "mare/highland", "complex"),
    ("marginis", "Marginis", 88.0, 16.0, 6.0, "mare/highland", "complex"),
    ("moscoviense", "Moscoviense", 145.0, 27.0, 4.0, "mare", "complex"),
    ("nw_of_apollo", "NW of Apollo", 197.5, -25.0, 12.0, "highland", "loop_dark_lane"),
    ("reiner_gamma", "Reiner Gamma", 302.5, 7.5, 22.0, "mare", "complex"),
    ("sirsalis", "Rima Sirsalis", 304.5, -8.5, 8.0, "mare/highland", "loop_dark_lane"),
    ("stofler", "Stöfler", 5.0, -37.0, 10.0, "highland", "not_recognized"),
)

# id, reported name, east longitude, latitude, observation radius r_o (deg),
# dipole-domain radius r_d (deg). These radii are inversion domains, not borders.
_OLIVEIRA = (
    ("abel", "Abel", 87.5, -31.0, 8.0, 7.0),
    ("airy", "Airy", 3.1, -18.2, 5.0, 4.0),
    ("crisium", "Crisium", 58.5, 17.3, 9.0, 8.0),
    ("crozier", "Crozier", 51.4, -15.4, 5.0, 4.0),
    ("descartes", "Descartes", 16.0, -10.7, 6.5, 5.5),
    ("hartwig", "Hartwig", 280.0, -9.0, 9.0, 8.0),
    ("kolhorster", "Kolhorster", 247.0, 13.0, 8.0, 7.0),
    ("mendel_rydberg", "Mendel-Rydberg", 264.0, -51.0, 8.0, 7.0),
    ("necho", "Necho", 124.0, -7.0, 4.5, 3.5),
    ("reiner_gamma", "Reiner-γ", 302.7, 7.6, 8.0, 7.0),
    ("scheiner", "Scheiner", 335.0, -62.0, 5.0, 4.0),
    ("serenitatis", "Serenitatis", 18.5, 33.0, 4.5, 3.0),
    ("sirsalis", "Sirsalis", 303.0, -10.0, 6.0, 5.0),
    ("smythii", "Smythii", 87.5, 0.0, 4.5, 3.5),
    ("sylvester", "Sylvester", 288.0, 80.0, 5.0, 4.0),
)


def magnetic_anomalies(
    catalog: AnomalyCatalog = "blewett2011",
    *,
    name: str | None = None,
    near: tuple[float, float] | None = None,
    radius_deg: float | None = None,
) -> pd.DataFrame:
    """Return cited lunar anomaly reference locations as a fresh DataFrame.

    Args:
        catalog: Corrected Blewett 2011 locations (15), Oliveira 2017 analysis
            centers (15), or both (30 source rows, 23 distinct feature IDs).
        name: Case-insensitive literal substring of name or feature_id.
            Greek gamma and hyphens/underscores are normalized for searching.
        near: (east longitude, latitude) in degrees. Negative longitude is
            accepted. Sort by great-circle distance to the reference point.
        radius_deg: Keep reference points within this angular distance of
            near, inclusive. This is not an anomaly-boundary intersection.

    Returns:
        Frame with lon_deg in [0, 360), north-positive lat_deg, per-row DOI,
        position_kind, peak_field_30km_nt, and literature-specific fields.
        Missing values mean not supplied by that catalog. With near, adds
        distance_deg and distance_km (sphere of radius 1737.4 km).
        attrs describes units, selection limits, and coordinate conventions.

    The peak fields are approximate *regional maxima at 30 km*, not surface
    fields or point samples at the listed coordinates. Swirl classifications
    are historical. Oliveira radii describe inversion domains, not physical
    anomaly sizes. No network access, Store, or optional dependencies are used.
    """
    import pandas as pd

    if catalog not in ("blewett2011", "oliveira2017", "all"):
        raise ValueError("catalog must be 'blewett2011', 'oliveira2017', or 'all'")
    if radius_deg is not None and (
        near is None or not np.isfinite(radius_deg) or not 0 <= radius_deg <= 180
    ):
        raise ValueError("radius_deg requires near and must be finite and in [0, 180]")

    frames = []
    common = ["feature_id", "name", "lon_deg", "lat_deg"]
    if catalog in ("blewett2011", "all"):
        frame = pd.DataFrame(_BLEWETT, columns=[*common, "peak_field_30km_nt", "setting", "swirl"])
        frame["catalog"] = "blewett2011"
        frame["reference_doi"] = "10.1029/2011JE003852"
        frame["position_kind"] = "approximate_anomaly_location"
        frame["observation_radius_deg"] = np.nan
        frame["dipole_radius_deg"] = np.nan
        frame["note"] = ""
        frame.loc[frame.feature_id == "marginis", "note"] = "Limited LP MAG coverage"
        frames.append(frame)
    if catalog in ("oliveira2017", "all"):
        frame = pd.DataFrame(
            _OLIVEIRA, columns=[*common, "observation_radius_deg", "dipole_radius_deg"]
        )
        frame["catalog"] = "oliveira2017"
        frame["reference_doi"] = "10.1002/2016JE005199"
        frame["position_kind"] = "analysis_center"
        frame["peak_field_30km_nt"] = np.nan
        frame["setting"] = None
        frame["swirl"] = None
        frame["note"] = ""
        frames.append(frame)
    table = pd.concat(frames, ignore_index=True)[
        [
            "catalog",
            *common,
            "position_kind",
            "peak_field_30km_nt",
            "setting",
            "swirl",
            "observation_radius_deg",
            "dipole_radius_deg",
            "reference_doi",
            "note",
        ]
    ]
    if name is not None:
        query = _search_name(name)
        table = table.loc[
            table.name.map(_search_name).str.contains(query, regex=False)
            | table.feature_id.map(_search_name).str.contains(query, regex=False)
        ].copy()
    if near is not None:
        lon, lat = near
        if not np.isfinite(lon) or not np.isfinite(lat) or not -90 <= lat <= 90:
            raise ValueError(
                "near must contain finite (longitude, latitude), latitude in [-90, 90]"
            )
        # Reduce longitudes before differencing, including the 0/360 seam.
        delta_lon = np.deg2rad((table.lon_deg.to_numpy() - lon % 360 + 180) % 360 - 180)
        latitudes = np.deg2rad(table.lat_deg.to_numpy())
        latitude = np.deg2rad(lat)
        haversine = (
            np.sin((latitudes - latitude) / 2) ** 2
            + np.cos(latitudes) * np.cos(latitude) * np.sin(delta_lon / 2) ** 2
        )
        angle = 2 * np.arcsin(np.sqrt(np.clip(haversine, 0, 1)))
        table["distance_deg"] = np.rad2deg(angle)
        table["distance_km"] = angle * 1737.4
        if radius_deg is not None:
            # Inclusive boundary, with 1e-10 deg tolerance for floating-point roundoff.
            table = table.loc[table.distance_deg <= radius_deg + 1e-10]
        table = table.sort_values("distance_deg", kind="stable")
    table = table.reset_index(drop=True)
    table.attrs = {
        "body": "moon",
        "coordinates": (
            "Lunar body-fixed literature locations; east lon [0, 360), north-positive lat"
        ),
        "coordinate_precision": "Literature locations; no precision MOON_ME/MOON_PA transformation",
        "units": {"angles": "deg", "peak_field_30km_nt": "nT", "distance_km": "km"},
        "distance_radius_km": 1737.4,
        "complete_global_inventory": False,
        "selection": "Published study selections; all retains multiple source rows per feature_id",
        "field_semantics": "Approximate regional peak |B| at 30 km, not surface or point field",
        "radius_semantics": "Oliveira inversion domains, not measured anomaly boundaries",
        "swirl_semantics": "Blewett 2011 classification; not_recognized is not proof of absence",
        "verified_on": "2026-09-10",
    }
    return table


def _search_name(value: str) -> str:
    return value.casefold().replace("γ", "gamma").replace("-", " ").replace("_", " ")
