from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


LonDomain = Literal["0_360", "-180_180"]


@dataclass(frozen=True)
class Region:
    lon: tuple[float, float]
    lat: tuple[float, float]
    body: str = "moon"
    lon_domain: LonDomain = "0_360"

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
        if lon_domain == self.lon_domain:
            return self
        return replace(
            self,
            lon=tuple(_convert_lon(value, lon_domain) for value in self.lon),
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
        }


def _convert_lon(value: float, lon_domain: LonDomain) -> float:
    if lon_domain == "0_360":
        return float(value % 360)
    if lon_domain == "-180_180":
        converted = (value + 180) % 360 - 180
        return float(180 if converted == -180 and value > 0 else converted)
    raise ValueError("lon_domain must be '0_360' or '-180_180'")


__all__ = ["LonDomain", "Region"]
