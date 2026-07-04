from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from sopran.maps.raster import RasterLayer, RasterSpec

LonDomain = Literal["0_360", "-180_180", "minus180_180"]
LonDirection = Literal["east_positive", "west_positive"]
LatType = Literal["planetocentric", "planetographic"]


@dataclass(frozen=True)
class Region:
    lon: tuple[float, float]
    lat: tuple[float, float]
    body: str = "moon"
    lon_domain: LonDomain = "0_360"
    lon_direction: LonDirection = "east_positive"
    lat_type: LatType = "planetocentric"

    def __post_init__(self) -> None:
        lon_domain = _canonical_lon_domain(self.lon_domain)
        object.__setattr__(self, "lon_domain", lon_domain)
        object.__setattr__(
            self,
            "lon_direction",
            _canonical_lon_direction(self.lon_direction),
        )
        object.__setattr__(self, "lat_type", _canonical_lat_type(self.lat_type))
        object.__setattr__(
            self,
            "lon",
            _convert_lon_pair(self.lon, lon_domain),
        )
        object.__setattr__(self, "lat", tuple(float(value) for value in self.lat))

    @property
    def crosses_lon_boundary(self) -> bool:
        return self.lon[0] > self.lon[1]

    @property
    def lon_span(self) -> float:
        start, stop = self.lon
        if stop >= start:
            return float(stop - start)
        domain_width = 360.0
        return float((stop + domain_width) - start)

    def to_lon_domain(self, lon_domain: LonDomain) -> Region:
        lon_domain = _canonical_lon_domain(lon_domain)
        if lon_domain == self.lon_domain:
            return self
        return replace(
            self,
            lon=_convert_lon_pair(self.lon, lon_domain),
            lon_domain=lon_domain,
        )

    def contains_lon(self, lon: float) -> bool:
        value = _convert_lon(lon, self.lon_domain)
        start, stop = self.lon
        if start <= stop:
            return start <= value <= stop
        return value >= start or value <= stop

    def contains(self, lon: float, lat: float) -> bool:
        return self.contains_lon(lon) and self.lat[0] <= lat <= self.lat[1]

    def to_metadata(self) -> dict[str, object]:
        return {
            "body": self.body,
            "lon": [float(self.lon[0]), float(self.lon[1])],
            "lat": [float(self.lat[0]), float(self.lat[1])],
            "lon_domain": self.lon_domain,
            "lon_direction": self.lon_direction,
            "lat_type": self.lat_type,
        }


def _convert_lon(value: float, lon_domain: LonDomain) -> float:
    lon_domain = _canonical_lon_domain(lon_domain)
    if lon_domain == "0_360":
        return float(value % 360)
    if lon_domain == "-180_180":
        converted = (value + 180) % 360 - 180
        return float(180 if converted == -180 and value > 0 else converted)
    raise ValueError("lon_domain must be '0_360', '-180_180', or 'minus180_180'")


def _convert_lon_pair(
    values: tuple[float, float],
    lon_domain: LonDomain,
) -> tuple[float, float]:
    return (
        _convert_lon(values[0], lon_domain),
        _convert_lon(values[1], lon_domain),
    )


def _canonical_lon_domain(lon_domain: LonDomain) -> Literal["0_360", "-180_180"]:
    if lon_domain == "minus180_180":
        return "-180_180"
    if lon_domain in ("0_360", "-180_180"):
        return lon_domain
    raise ValueError("lon_domain must be '0_360', '-180_180', or 'minus180_180'")


def _canonical_lon_direction(lon_direction: str) -> LonDirection:
    if lon_direction in ("east_positive", "west_positive"):
        return lon_direction  # type: ignore[return-value]
    raise ValueError("lon_direction must be 'east_positive' or 'west_positive'")


def _canonical_lat_type(lat_type: str) -> LatType:
    if lat_type in ("planetocentric", "planetographic"):
        return lat_type  # type: ignore[return-value]
    raise ValueError("lat_type must be 'planetocentric' or 'planetographic'")


__all__ = [
    "LatType",
    "LonDirection",
    "LonDomain",
    "RasterLayer",
    "RasterSpec",
    "Region",
]
