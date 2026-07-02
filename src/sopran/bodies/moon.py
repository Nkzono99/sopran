from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sopran.core.pages import GuidePage, InfoPage


@dataclass(frozen=True)
class SurfacePlan:
    body: str
    product: str
    parameters: dict[str, Any]


class Moon:
    """Body-first entry point for Moon surface products."""

    name = "moon"

    def __init__(self) -> None:
        self.dem = SurfaceEndpoint(self, "dem", "DEM")
        self.svm = SurfaceEndpoint(self, "svm", "SVM")
        self.shadow = SurfaceEndpoint(self, "shadow", "Shadow map")
        self.illumination = SurfaceEndpoint(self, "illumination", "Illumination map")

    def info(self) -> InfoPage:
        return InfoPage(
            title="Moon",
            lines=(
                "dem: digital elevation model endpoint",
                "svm: surface vector map endpoint",
                "shadow: terrain-aware shadow map endpoint skeleton",
                "illumination: terrain-aware illumination endpoint skeleton",
            ),
        )

    def guide(self) -> GuidePage:
        return GuidePage(
            title="Moon Surface Products",
            markdown=_MOON_GUIDE,
            source="sopran.bodies.moon",
        )

    def help(self) -> GuidePage:
        return self.guide()


class SurfaceEndpoint:
    def __init__(self, body: Moon, product: str, label: str) -> None:
        self.body = body
        self.product = product
        self.label = label

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"Moon.{self.product}",
            lines=(
                f"{self.label} surface product.",
                "v0.1 implements planning only; load/compute backends are later milestones.",
            ),
        )

    def guide(self) -> GuidePage:
        return GuidePage(
            title=f"Moon {self.label}",
            markdown=_SURFACE_GUIDES.get(self.product, _MOON_GUIDE),
            source=f"sopran.bodies.moon.{self.product}",
        )

    def help(self) -> GuidePage:
        return self.guide()

    def sources(self) -> tuple[str, ...]:
        return _SURFACE_SOURCES.get(self.product, ())

    def plan(self, **parameters: Any) -> SurfacePlan:
        return SurfacePlan(
            body=self.body.name,
            product=self.product,
            parameters=dict(parameters),
        )

    def load(self, **parameters: Any) -> None:
        plan = self.plan(**parameters)
        raise NotImplementedError(f"Moon.{plan.product}.load() is not implemented yet")

    def compute(self, **parameters: Any) -> None:
        plan = self.plan(**parameters)
        raise NotImplementedError(f"Moon.{plan.product}.compute() is not implemented yet")


_MOON_GUIDE = """# Moon Surface Products

SOPRAN uses a body-first API for Moon surface products. Mission modules provide
provider-specific discovery, while `spn.Moon()` owns body-fixed DEM, SVM,
shadow, illumination, projection, and region semantics.

The v0.1 implementation is a planning skeleton. Terrain-aware shadow and
illumination backends will require DEM data, solar geometry, body shape, and
explicit longitude/projection metadata.
"""

_SURFACE_GUIDES = {
    "dem": """# Moon DEM

DEM products represent body-fixed lunar elevation rasters. Planned metadata
includes source, resolution, datum or shape model, longitude domain, projection,
and area-or-point interpretation.
""",
    "svm": """# Moon SVM

SVM products represent lunar surface vector maps or classified map layers.
They share the same body-fixed region and projection metadata as DEM products.
""",
    "shadow": """# Moon Shadow Map

Shadow products must be computed from DEM terrain, solar position, body shape,
and projection metadata. The current endpoint only records plans.
""",
    "illumination": """# Moon Illumination Map

Illumination products will represent solar incidence and visibility derived
from DEM terrain and SPICE-backed solar geometry.
""",
}

_SURFACE_SOURCES = {
    "dem": ("kaguya.tc.dem", "lro.lola.dem"),
    "svm": ("kaguya.lism.svm",),
    "shadow": ("legacy.shadowmap_sza",),
    "illumination": (),
}
