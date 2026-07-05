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
SZA can be computed from an explicit Sun vector, subsolar point, or `time=` with
SPICE kernels. Illumination supports SZA-threshold binary maps, and shadow
supports both SZA-threshold and terrain-ray DEM horizon maps.
""",
    "ja": """# Moon Maps

SOPRAN は月面マップを body-first API として扱います。mission module は
provider-specific discovery を担当し、`spn.Moon()` は月固定 DEM、Tsunakawa SVM、
SZA、shadow、illumination、projection、region semantics を受け持ちます。

source file が利用できる場合、DEM と Tsunakawa SVM は raster として読み込めます。
SZA は明示的な Sun vector、subsolar point、または `time=` と SPICE kernel から計算できます。
illumination は SZA 閾値による二値 map、shadow は SZA 閾値と terrain-ray DEM horizon map を
返します。
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
and projection metadata. The compute backend supports SZA-threshold binary
shadow maps and `method="terrain_ray"` DEM horizon shadowing.
""",
        "ja": """# Moon Shadow Map

Shadow product は DEM terrain、solar position、body shape、projection metadata から
計算する必要があります。compute backend は SZA 閾値による二値 shadow map と
`method="terrain_ray"` の DEM horizon shadowing を返します。
""",
    },
    "illumination": {
        "en": """# Moon Illumination Map

Illumination products currently support SZA-threshold binary maps. Solar
incidence and visibility derived from DEM terrain are planned.
""",
        "ja": """# Moon Illumination Map

Illumination product は現時点では SZA 閾値による二値 map を返します。DEM terrain と
solar geometry から導く local incidence と visibility は今後追加します。
""",
    },
    "sza": {
        "en": """# Moon Solar Zenith Angle

SZA products represent solar zenith angle on the lunar surface. The compute
endpoint accepts `sun_vector=`, `subsolar_lon_lat=`, or `time=` with
`spice_kernels=`.
""",
        "ja": """# Moon Solar Zenith Angle

SZA product は月面上の solar zenith angle を表します。compute endpoint は `sun_vector=`、
`subsolar_lon_lat=`、または `spice_kernels=` 付きの `time=` を受け取ります。
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
dem = moon.dem.load(path="Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif", region=region)
sza = moon.sza.compute(
    region=region,
    time="2008-02-01T12:00:00Z",
    spice_kernels=(
        "kernels/naif0012.tls",
        "kernels/de421.bsp",
        "kernels/moon_pa.bpc",
    ),
)
shadow = moon.shadow.compute(method="terrain_ray", dem=dem, sza=sza)
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
dem = moon.dem.load(path="Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif", region=region)
sza = moon.sza.compute(region=region, subsolar_lon_lat=(0.0, 0.0))
shadow = moon.shadow.compute(method="terrain_ray", dem=dem, sza=sza)
```
""",
        ),
        "illumination": (
            "Moon Illumination Example",
            """# Moon Illumination Example

```python
import sopran as spn

moon = spn.Moon()

illumination = moon.illumination.compute(
    region=spn.Region(lon=(120, 160), lat=(-45, -10), body="moon"),
    subsolar_lon_lat=(0.0, 0.0),
    threshold_deg=90.0,
)
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
    region=region,
    time="2008-02-01T12:00:00Z",
    spice_kernels=(
        "kernels/naif0012.tls",
        "kernels/de421.bsp",
        "kernels/moon_pa.bpc",
    ),
)
sza = moon.sza.compute(
    region=region,
    time="2008-02-01T12:00:00Z",
    spice_kernels=(
        "kernels/naif0012.tls",
        "kernels/de421.bsp",
        "kernels/moon_pa.bpc",
    ),
)
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
