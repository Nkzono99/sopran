from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sopran.core.pages import GuidePage, InfoPage
from sopran.core.schema import InstrumentSchema, VariableSchema

_GUIDE_LANGUAGES = ("ja", "en")
_PUBLIC_DOC_URL = "https://nkzono99.github.io/sopran/maps/moon/"


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
    """Body-first entry point for Moon map products."""

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
                "schema: "
                + _format_list(variable.name for variable in self.schema().variables),
            ),
        )

    def guide(self, *, language: str = "ja") -> GuidePage:
        return _guide_page(
            title="Moon Maps",
            source="sopran.bodies.moon",
            markdowns=_MOON_GUIDES,
            language=language,
            url=_PUBLIC_DOC_URL,
        ).with_schema(MOON_SURFACE_SCHEMA)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def schema(self) -> InstrumentSchema:
        return MOON_SURFACE_SCHEMA

    def example(self) -> GuidePage:
        return _example_page(
            "Moon Maps Example",
            """# Moon Maps Example

```python
import sopran as spn

moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

dem_plan = moon.dem.plan(
    source="kaguya.tc.dem",
    region=region,
    resolution="512ppd",
    projection="native",
)
shadow_plan = moon.shadow.plan(time="2008-02-01T12:00:00Z", dem=dem_plan)
sza_plan = moon.sza.plan(
    time="2008-02-01T12:00:00Z",
    region=region,
    geometry_source="spice",
)
metadata = shadow_plan.to_metadata()
```
""",
        )

    def map(self, product: str) -> SurfaceEndpoint:
        endpoints = {
            "dem": self.dem,
            "svm": self.svm,
            "shadow": self.shadow,
            "illumination": self.illumination,
            "sza": self.sza,
        }
        try:
            canonical = MOON_SURFACE_SCHEMA.variable(product).name
            return endpoints[canonical]
        except KeyError as exc:
            raise ValueError(
                "Unknown Moon surface product. Available products: "
                + _format_list(variable.name for variable in MOON_SURFACE_SCHEMA.variables)
                + ". Aliases: "
                + _format_list(
                    alias
                    for variable in MOON_SURFACE_SCHEMA.variables
                    for alias in variable.aliases
                )
            ) from exc


class SurfaceEndpoint:
    def __init__(self, body: Moon, product: str, label: str) -> None:
        self.body = body
        self.product = product
        self.label = label

    def info(self) -> InfoPage:
        schema = self.schema()
        return InfoPage(
            title=f"Moon.{self.product}",
            lines=(
                f"{self.label} surface product.",
                "v0.1 implements planning only; load/compute backends are later milestones.",
                "sources: " + _format_list(self.sources()),
                "dims: " + _format_list(schema.dims),
                f"units: {schema.units or 'none'}",
                f"frame: {schema.frame or 'none'}",
                "aliases: " + _format_list(schema.aliases),
            ),
        )

    def guide(self, *, language: str = "ja") -> GuidePage:
        return _guide_page(
            title=f"Moon {self.label}",
            source=f"sopran.bodies.moon.{self.product}",
            markdowns=_SURFACE_GUIDES.get(self.product, _MOON_GUIDES),
            language=language,
            url=_PUBLIC_DOC_URL,
        ).with_schema(_surface_product_schema(self.product))

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def schema(self) -> VariableSchema:
        return MOON_SURFACE_SCHEMA.variable(self.product)

    def example(self) -> GuidePage:
        examples = {
            "dem": (
                "Moon DEM Example",
                """# Moon DEM Example

```python
import sopran as spn

moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

dem_plan = moon.dem.plan(
    source="kaguya.tc.dem",
    region=region,
    resolution="512ppd",
    projection="native",
)
metadata = dem_plan.to_metadata()
```
""",
            ),
            "shadow": (
                "Moon Shadow Example",
                """# Moon Shadow Example

```python
import sopran as spn

moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")
dem_plan = moon.dem.plan(source="kaguya.tc.dem", region=region)

shadow_plan = moon.shadow.plan(
    time="2008-02-01T12:00:00Z",
    dem=dem_plan,
    model="terrain_ray",
)
metadata = shadow_plan.to_metadata()
```
""",
            ),
            "illumination": (
                "Moon Illumination Example",
                """# Moon Illumination Example

```python
import sopran as spn

moon = spn.Moon()
dem_plan = moon.dem.plan(source="kaguya.tc.dem")

illumination_plan = moon.illumination.plan(
    time="2008-02-01T12:00:00Z",
    dem=dem_plan,
    geometry_source="spice",
)
metadata = illumination_plan.to_metadata()
```
""",
            ),
            "sza": (
                "Moon Solar Zenith Angle Example",
                """# Moon Solar Zenith Angle Example

```python
import sopran as spn

moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

sza_plan = moon.sza.plan(
    time="2008-02-01T12:00:00Z",
    region=region,
    geometry_source="spice",
)
metadata = sza_plan.to_metadata()
```
""",
            ),
            "svm": (
                "Moon SVM Example",
                """# Moon SVM Example

```python
import sopran as spn

moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

svm_plan = moon.svm.plan(source="kaguya.lism.svm", region=region)
metadata = svm_plan.to_metadata()
```
""",
            ),
        }
        title, markdown = examples.get(self.product, examples["dem"])
        return _example_page(title, markdown)

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
    "en": """# Moon Maps

SOPRAN uses a body-first API for Moon map products. Mission modules provide
provider-specific discovery, while `spn.Moon()` owns body-fixed DEM, SVM, SZA,
shadow, illumination, projection, and region semantics.

The v0.1 implementation is a planning skeleton. Terrain-aware shadow and
illumination backends will require DEM data, solar geometry, body shape, and
explicit longitude/projection metadata.
""",
    "ja": """# Moon Maps

SOPRAN は月面マップを body-first API として扱います。mission module は
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

MOON_SURFACE_SCHEMA = InstrumentSchema(
    mission="moon",
    instrument="surface",
    variables=(
        VariableSchema(
            name="dem",
            dims=("lat", "lon"),
            units="m",
            dtype="float64",
            frame="Moon body-fixed",
            description="Digital elevation model on a body-fixed lunar grid.",
            aliases=("elevation", "height"),
        ),
        VariableSchema(
            name="svm",
            dims=("lat", "lon"),
            dtype="string",
            frame="Moon body-fixed",
            description="Surface vector map or classified lunar map layer.",
            aliases=("surface_vector_map",),
        ),
        VariableSchema(
            name="shadow",
            dims=("lat", "lon"),
            units="fraction",
            dtype="float64",
            frame="Moon body-fixed",
            description="terrain-aware shadow or shadow-fraction map.",
            aliases=("shadow_map", "shadow_fraction"),
        ),
        VariableSchema(
            name="illumination",
            dims=("lat", "lon"),
            units="fraction",
            dtype="float64",
            frame="Moon body-fixed",
            description="Illumination or visibility fraction derived from solar geometry.",
            aliases=("illumination_map", "visibility"),
        ),
        VariableSchema(
            name="sza",
            dims=("lat", "lon"),
            units="deg",
            dtype="float64",
            frame="Moon body-fixed",
            description="Solar zenith angle on the lunar surface.",
            aliases=("solar_zenith_angle",),
        ),
    ),
)


def _metadata_value(value: Any) -> Any:
    if hasattr(value, "to_metadata"):
        return value.to_metadata()
    if isinstance(value, dict):
        return {str(key): _metadata_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_metadata_value(item) for item in value]
    return value


def _format_list(values) -> str:
    items = tuple(str(value) for value in values)
    return ", ".join(items) if items else "none"


def _surface_parameters(product: str, parameters: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(parameters)
    if product in {"shadow", "illumination"} and (
        "method" in normalized or "model" in normalized
    ):
        model = _surface_model(normalized)
        normalized["method"] = model
        normalized["model"] = model
    if (
        product == "sza"
        or "geometry_source" in normalized
        or "geometry" in normalized
        or "ephemeris" in normalized
    ):
        default_geometry = "spice" if product == "sza" else None
        geometry = _geometry_source(normalized, default=default_geometry)
        normalized["geometry"] = geometry
        normalized["geometry_source"] = geometry
    reference = _coordinate_reference(normalized)
    normalized["lon_domain"] = _canonical_lon_domain(
        str(normalized.get("lon_domain", reference.get("lon_domain", "0_360")))
    )
    normalized["lon_direction"] = _canonical_lon_direction(
        str(
            normalized.get(
                "lon_direction",
                reference.get("lon_direction", "east_positive"),
            )
        )
    )
    normalized["lat_type"] = _canonical_lat_type(
        str(normalized.get("lat_type", reference.get("lat_type", "planetocentric")))
    )
    normalized["shape"] = _canonical_shape(
        str(normalized.get("shape", reference.get("shape", "spherical")))
    )
    datum = normalized.get("datum", reference.get("datum"))
    if datum is not None:
        normalized["datum"] = str(datum)
    normalized["projection"] = _canonical_projection(
        str(normalized.get("projection", reference.get("projection", "native")))
    )
    normalized["area_or_point"] = _canonical_area_or_point(
        str(normalized.get("area_or_point", reference.get("area_or_point", "area")))
    )
    return normalized


def _surface_model(parameters: dict[str, Any]) -> str:
    method = parameters.get("method")
    model = parameters.get("model")
    if method is not None and model is not None and str(method) != str(model):
        raise ValueError("method and model must match when both are provided")
    value = method if method is not None else model
    if value is None:
        raise ValueError("method/model cannot be empty")
    return str(value)


def _geometry_source(parameters: dict[str, Any], *, default: str | None) -> str:
    value = parameters.get(
        "geometry_source",
        parameters.get("geometry", parameters.get("ephemeris", default)),
    )
    if value is None:
        raise ValueError("geometry_source cannot be empty")
    return str(value)


def _coordinate_reference(parameters: dict[str, Any]) -> dict[str, Any]:
    region = _metadata_value(parameters.get("region"))
    if isinstance(region, dict):
        return region
    dem = _metadata_value(parameters.get("dem"))
    if isinstance(dem, dict) and isinstance(dem.get("parameters"), dict):
        return dem["parameters"]
    return {}


def _canonical_lon_domain(lon_domain: str) -> str:
    if lon_domain == "minus180_180":
        return "-180_180"
    if lon_domain in {"0_360", "-180_180"}:
        return lon_domain
    raise ValueError("lon_domain must be '0_360', '-180_180', or 'minus180_180'")


def _canonical_lon_direction(lon_direction: str) -> str:
    if lon_direction in {"east_positive", "west_positive"}:
        return lon_direction
    raise ValueError("lon_direction must be 'east_positive' or 'west_positive'")


def _canonical_lat_type(lat_type: str) -> str:
    if lat_type in {"planetocentric", "planetographic"}:
        return lat_type
    raise ValueError("lat_type must be 'planetocentric' or 'planetographic'")


def _canonical_shape(shape: str) -> str:
    aliases = {
        "sphere": "spherical",
        "spice": "spice_body_radii",
        "body_radii": "spice_body_radii",
    }
    canonical = aliases.get(shape, shape)
    allowed = {"spherical", "ellipsoid", "triaxial", "spice_body_radii"}
    if canonical in allowed:
        return canonical
    raise ValueError(
        "shape must be one of spherical, ellipsoid, triaxial, "
        "spice_body_radii, sphere, spice, or body_radii"
    )


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


def _surface_product_schema(product: str) -> InstrumentSchema:
    return InstrumentSchema(
        mission="moon",
        instrument=f"surface.{product}",
        variables=(MOON_SURFACE_SCHEMA.variable(product),),
    )


def _example_page(title: str, markdown: str) -> GuidePage:
    return GuidePage(
        title=title,
        markdown=markdown,
        source="sopran.bodies.moon.examples",
    )
