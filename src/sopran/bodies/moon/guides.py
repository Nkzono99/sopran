from __future__ import annotations

from sopran.core.pages import GuidePage

from .models import SurfaceSource
from .schema import MOON_SURFACE_SCHEMA, surface_product_schema

GUIDE_LANGUAGES = ("ja", "en")
PUBLIC_DOC_URL = "https://nkzono99.github.io/sopran/maps/moon/"

MOON_GUIDES = {
    "en": """# Moon Maps

SOPRAN uses a body-first API for Moon map products. Mission modules provide
provider-specific discovery, while `spn.Moon()` owns body-fixed DEM, Tsunakawa
SVM, SZA, shadow, illumination, projection, and region semantics.

DEM and Tsunakawa SVM can be loaded as rasters when source files are available.
Terrain-aware shadow and illumination backends will require DEM data, solar
geometry, body shape, and explicit longitude/projection metadata.
""",
    "ja": """# Moon Maps

SOPRAN は月面マップを body-first API として扱います。mission module は
provider-specific discovery を担当し、`spn.Moon()` は月固定 DEM、Tsunakawa SVM、
SZA、shadow、illumination、projection、region semantics を受け持ちます。

source file が利用できる場合、DEM と Tsunakawa SVM は raster として読み込めます。
terrain-aware shadow と illumination backend では DEM data、solar geometry、body shape、
longitude/projection metadata を明示的に扱います。
""",
}

SURFACE_GUIDES = {
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

SVM products represent the Tsunakawa lunar magnetic anomaly surface vector map.
`moon.svm` returns the current default SVM endpoint, which is
`moon.svm_tsunakawa2015`.
""",
        "ja": """# Moon SVM

SVM product は Tsunakawa lunar magnetic anomaly surface vector map を表します。
`moon.svm` は現在の default SVM endpoint として `moon.svm_tsunakawa2015` を返します。
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


def moon_guide(*, language: str = "ja") -> GuidePage:
    return guide_page(
        title="Moon Maps",
        source="sopran.bodies.moon",
        markdowns=MOON_GUIDES,
        language=language,
        url=PUBLIC_DOC_URL,
    ).with_schema(MOON_SURFACE_SCHEMA)


def surface_guide(product: str, label: str, *, language: str = "ja") -> GuidePage:
    return guide_page(
        title=f"Moon {label}",
        source=f"sopran.bodies.moon.{product}",
        markdowns=SURFACE_GUIDES.get(product, MOON_GUIDES),
        language=language,
        url=PUBLIC_DOC_URL,
    ).with_schema(surface_product_schema(product))


def acquisition_guide_page(
    source: SurfaceSource,
    *,
    label: str,
    language: str = "ja",
) -> GuidePage:
    markdowns = acquisition_markdowns(source)
    return guide_page(
        title=f"Moon {label} Data Acquisition",
        source=f"sopran.bodies.moon.{source.product}.acquisition",
        markdowns=markdowns,
        language=language,
        url=source.landing_page,
    )


def guide_page(
    *,
    title: str,
    source: str,
    markdowns: dict[str, str],
    language: str,
    url: str | None = None,
) -> GuidePage:
    if language not in GUIDE_LANGUAGES:
        raise ValueError(f"Moon guide language is not available: {language}")
    return GuidePage(
        title=title,
        markdown=markdowns[language],
        source=source,
        url=url,
        language=language,
        available_languages=GUIDE_LANGUAGES,
        translations={
            available_language: markdowns[available_language]
            for available_language in GUIDE_LANGUAGES
            if available_language != language
        },
    )


def moon_example() -> GuidePage:
    return example_page(
        "Moon Maps Example",
        """# Moon Maps Example

```python
import sopran as spn

moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

dem_plan = moon.dem.plan(
    source="lro.lola.dem_118m",
    region=region,
    resolution="256ppd",
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


def surface_example(product: str) -> GuidePage:
    examples = {
        "dem": (
            "Moon DEM Example",
            """# Moon DEM Example

```python
import sopran as spn

moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

dem_plan = moon.dem.plan(
    source="lro.lola.dem_118m",
    region=region,
    resolution="256ppd",
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
dem_plan = moon.dem.plan(source="lro.lola.dem_118m", region=region)

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
dem_plan = moon.dem.plan(source="lro.lola.dem_118m")

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
            "Moon Tsunakawa SVM Example",
            """# Moon SVM Example

```python
import sopran as spn

moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

svm_plan = moon.svm_tsunakawa2015.plan(region=region)
metadata = svm_plan.to_metadata()
```
""",
        ),
    }
    title, markdown = examples.get(product, examples["dem"])
    return example_page(title, markdown)


def example_page(title: str, markdown: str) -> GuidePage:
    return GuidePage(
        title=title,
        markdown=markdown,
        source="sopran.bodies.moon.examples",
    )


def acquisition_markdowns(source: SurfaceSource) -> dict[str, str]:
    if source.url is not None:
        return {
            "ja": f"""# {source.source_id} の取得

この source は SOPRAN から直接 download できます。

```python
moon = spn.Moon()
path = moon.{source.product}.download(source="{source.source_id}")
layer = moon.{source.product}.load(path=path, source="{source.source_id}")
```

- file: `{source.filename}`
- provider: `{source.provider}`
- description: {source.description}
- size: {source.size or "unknown"}
- landing page: {source.landing_page or "none"}
- original URL: {source.original_url or "none"}
- direct URL: {source.url}
""",
            "en": f"""# Acquire {source.source_id}

SOPRAN can download this source directly.

```python
moon = spn.Moon()
path = moon.{source.product}.download(source="{source.source_id}")
layer = moon.{source.product}.load(path=path, source="{source.source_id}")
```

- file: `{source.filename}`
- provider: `{source.provider}`
- description: {source.description}
- size: {source.size or "unknown"}
- landing page: {source.landing_page or "none"}
- original URL: {source.original_url or "none"}
- direct URL: {source.url}
""",
        }
    return {
        "ja": f"""# {source.source_id} の手動取得

この source は安定した直接 download URL を SOPRAN 側で確認できていません。
`{source.filename}` を手動で取得し、次のどちらかで読み込んでください。

```python
moon = spn.Moon()
layer = moon.svm_tsunakawa2015.load(path=r"C:/path/to/{source.filename}")
```

または Store に配置します。

```text
<store>/raw/moon/svm/{source.filename}
```

その後:

```python
layer = moon.svm.load(download="never")
```

- provider: `{source.provider}`
- description: {source.description}
- landing page: {source.landing_page or "none"}
- original URL: {source.original_url or "none"}
- note: {source.manual_note or "manual acquisition required"}
""",
        "en": f"""# Manually acquire {source.source_id}

SOPRAN does not currently have a verified stable direct download URL for this source.
Acquire `{source.filename}` manually and load it in one of these ways.

```python
moon = spn.Moon()
layer = moon.svm_tsunakawa2015.load(path=r"C:/path/to/{source.filename}")
```

Or place it in the Store:

```text
<store>/raw/moon/svm/{source.filename}
```

Then:

```python
layer = moon.svm.load(download="never")
```

- provider: `{source.provider}`
- description: {source.description}
- landing page: {source.landing_page or "none"}
- original URL: {source.original_url or "none"}
- note: {source.manual_note or "manual acquisition required"}
""",
    }
