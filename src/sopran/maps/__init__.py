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

    def to_lon_domain(self, lon_domain: LonDomain) -> Region:
        if lon_domain == self.lon_domain:
            return self
        return replace(
            self,
            lon=tuple(_convert_lon(value, lon_domain) for value in self.lon),
            lon_domain=lon_domain,
        )


def _convert_lon(value: float, lon_domain: LonDomain) -> float:
    if lon_domain == "0_360":
        return float(value % 360)
    if lon_domain == "-180_180":
        converted = (value + 180) % 360 - 180
        return float(180 if converted == -180 and value > 0 else converted)
    raise ValueError("lon_domain must be '0_360' or '-180_180'")


__all__ = ["LonDomain", "Region"]
