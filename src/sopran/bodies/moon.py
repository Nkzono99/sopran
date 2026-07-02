from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sopran.core.pages import GuidePage, InfoPage

_GUIDE_LANGUAGES = ("ja", "en")
_PUBLIC_DOC_URL = "https://nkzono99.github.io/sopran/surface/moon/"


@dataclass(frozen=True)
class SurfacePlan:
    body: str
    product: str
    parameters: dict[str, Any]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "body": self.body,
            "product": self.product,
            "parameters": _metadata_value(self.parameters),
        }


class Moon:
    """Body-first entry point for Moon surface products."""

    name = "moon"

    def __init__(self) -> None:
        self.dem = SurfaceEndpoint(self, "dem", "DEM")
        self.svm = SurfaceEndpoint(self, "svm", "SVM")
        self.shadow = SurfaceEndpoint(self, "shadow", "Shadow map")
        self.illumination = SurfaceEndpoint(self, "illumination", "Illumination map")
        self.sza = SurfaceEndpoint(self, "sza", "Solar zenith angle")

    def info(self) -> InfoPage:
        return InfoPage(
            title="Moon",
            lines=(
                "dem: digital elevation model endpoint",
                "svm: surface vector map endpoint",
                "shadow: terrain-aware shadow map endpoint skeleton",
                "illumination: terrain-aware illumination endpoint skeleton",
                "sza: solar zenith angle planning endpoint skeleton",
            ),
        )

    def guide(self, *, language: str = "ja") -> GuidePage:
        return _guide_page(
            title="Moon Surface Products",
            source="sopran.bodies.moon",
            markdowns=_MOON_GUIDES,
            language=language,
            url=_PUBLIC_DOC_URL,
        )

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def map(self, product: str) -> SurfaceEndpoint:
        try:
            return {
                "dem": self.dem,
                "svm": self.svm,
                "shadow": self.shadow,
                "illumination": self.illumination,
                "sza": self.sza,
            }[product]
        except KeyError as exc:
            raise ValueError(
                "Unknown Moon surface product. Available products: "
                "dem, svm, shadow, illumination, sza"
            ) from exc


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

    def guide(self, *, language: str = "ja") -> GuidePage:
        return _guide_page(
            title=f"Moon {self.label}",
            source=f"sopran.bodies.moon.{self.product}",
            markdowns=_SURFACE_GUIDES.get(self.product, _MOON_GUIDES),
            language=language,
            url=_PUBLIC_DOC_URL,
        )

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def sources(self) -> tuple[str, ...]:
        return _SURFACE_SOURCES.get(self.product, ())

    def plan(self, **parameters: Any) -> SurfacePlan:
        return SurfacePlan(
            body=self.body.name,
            product=self.product,
            parameters=_surface_parameters(self.product, parameters),
        )

    def load(self, **parameters: Any) -> None:
        plan = self.plan(**parameters)
        raise NotImplementedError(f"Moon.{plan.product}.load() is not implemented yet")

    def compute(self, **parameters: Any) -> None:
        plan = self.plan(**parameters)
        raise NotImplementedError(f"Moon.{plan.product}.compute() is not implemented yet")


_MOON_GUIDES = {
    "en": """# Moon Surface Products

SOPRAN uses a body-first API for Moon surface products. Mission modules provide
provider-specific discovery, while `spn.Moon()` owns body-fixed DEM, SVM, SZA,
shadow, illumination, projection, and region semantics.

The v0.1 implementation is a planning skeleton. Terrain-aware shadow and
illumination backends will require DEM data, solar geometry, body shape, and
explicit longitude/projection metadata.
""",
    "ja": """# Moon Surface Products

SOPRAN は月面プロダクトを body-first API として扱います。mission module は
provider-specific discovery を担当し、`spn.Moon()` は月固定 DEM、SVM、SZA、shadow、
illumination、projection、region semantics を受け持ちます。

v0.1 実装は planning skeleton です。terrain-aware shadow と illumination backend では
DEM data、solar geometry、body shape、longitude/projection metadata を明示的に扱います。
""",
}

_SURFACE_GUIDES = {
    "dem": {
        "en": """# Moon DEM

DEM products represent body-fixed lunar elevation rasters. Planned metadata
includes source, resolution, datum or shape model, longitude domain, projection,
and area-or-point interpretation.
""",
        "ja": """# Moon DEM

DEM product は月固定の elevation raster を表します。予定している metadata には source、
resolution、datum または shape model、longitude domain、projection、area-or-point
interpretation を含めます。
""",
    },
    "svm": {
        "en": """# Moon SVM

SVM products represent lunar surface vector maps or classified map layers.
They share the same body-fixed region and projection metadata as DEM products.
""",
        "ja": """# Moon SVM

SVM product は lunar surface vector map または classified map layer を表します。
DEM product と同じ body-fixed region と projection metadata を共有します。
""",
    },
    "shadow": {
        "en": """# Moon Shadow Map

Shadow products must be computed from DEM terrain, solar position, body shape,
and projection metadata. The current endpoint only records plans.
""",
        "ja": """# Moon Shadow Map

Shadow product は DEM terrain、solar position、body shape、projection metadata から
計算する必要があります。現在の endpoint は plan の記録だけを行います。
""",
    },
    "illumination": {
        "en": """# Moon Illumination Map

Illumination products will represent solar incidence and visibility derived
from DEM terrain and SPICE-backed solar geometry.
""",
        "ja": """# Moon Illumination Map

Illumination product は DEM terrain と SPICE-backed solar geometry から導く
solar incidence と visibility を表す予定です。
""",
    },
    "sza": {
        "en": """# Moon Solar Zenith Angle

SZA products represent solar zenith angle on the lunar surface. The planning
endpoint records time, region, geometry_source backend, and projection metadata
before SPICE-backed computation is implemented.
""",
        "ja": """# Moon Solar Zenith Angle

SZA product は月面上の solar zenith angle を表します。planning endpoint は
SPICE-backed computation の実装前に、time、region、geometry_source backend、
projection metadata を記録します。
""",
    },
}

_SURFACE_SOURCES = {
    "dem": ("kaguya.tc.dem", "lro.lola.dem"),
    "svm": ("kaguya.lism.svm",),
    "shadow": ("legacy.shadowmap_sza",),
    "illumination": (),
    "sza": ("computed.spice.sza",),
}


def _metadata_value(value: Any) -> Any:
    if hasattr(value, "to_metadata"):
        return value.to_metadata()
    if isinstance(value, dict):
        return {str(key): _metadata_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_metadata_value(item) for item in value]
    return value


def _surface_parameters(product: str, parameters: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(parameters)
    if (
        product == "sza"
        or "geometry_source" in normalized
        or "geometry" in normalized
    ):
        default_geometry = "spice" if product == "sza" else None
        geometry = _geometry_source(normalized, default=default_geometry)
        normalized["geometry"] = geometry
        normalized["geometry_source"] = geometry
    normalized["projection"] = _canonical_projection(
        str(normalized.get("projection", "native"))
    )
    normalized["area_or_point"] = _canonical_area_or_point(
        str(normalized.get("area_or_point", "area"))
    )
    return normalized


def _geometry_source(parameters: dict[str, Any], *, default: str | None) -> str:
    value = parameters.get("geometry_source", parameters.get("geometry", default))
    if value is None:
        raise ValueError("geometry_source cannot be empty")
    return str(value)


def _canonical_projection(projection: str) -> str:
    aliases = {
        "polar_stereo": "polar_stereographic",
    }
    canonical = aliases.get(projection, projection)
    allowed = {
        "equirectangular",
        "polar_stereographic",
        "orthographic",
        "azimuthal_equidistant",
        "lambert",
        "native",
    }
    if canonical in allowed:
        return canonical
    raise ValueError(
        "projection must be one of equirectangular, polar_stereographic, "
        "orthographic, azimuthal_equidistant, lambert, native, or polar_stereo"
    )


def _canonical_area_or_point(area_or_point: str) -> str:
    if area_or_point in {"area", "point"}:
        return area_or_point
    raise ValueError("area_or_point must be 'area' or 'point'")


def _guide_page(
    *,
    title: str,
    source: str,
    markdowns: dict[str, str],
    language: str,
    url: str | None = None,
) -> GuidePage:
    if language not in _GUIDE_LANGUAGES:
        raise ValueError(f"Moon guide language is not available: {language}")
    return GuidePage(
        title=title,
        markdown=markdowns[language],
        source=source,
        url=url,
        language=language,
        available_languages=_GUIDE_LANGUAGES,
        translations={
            available_language: markdowns[available_language]
            for available_language in _GUIDE_LANGUAGES
            if available_language != language
        },
    )
