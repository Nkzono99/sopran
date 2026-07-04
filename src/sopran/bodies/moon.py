from __future__ import annotations

import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from sopran.core.errors import DatasetNotFoundError, DownloadError
from sopran.core.pages import GuidePage, InfoPage
from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.core.store import Store
from sopran.maps.raster import (
    RasterLayer,
    read_geotiff,
    read_tsunakawa_svm_npy,
    read_tsunakawa_svm_text,
)

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


@dataclass(frozen=True)
class SurfaceSource:
    source_id: str
    product: str
    provider: str
    filename: str
    description: str
    url: str | None = None
    landing_page: str | None = None
    original_url: str | None = None
    size: str | None = None
    version: str | None = None
    scale: float | None = None
    offset: float | None = None
    manual_note: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "product": self.product,
            "provider": self.provider,
            "filename": self.filename,
            "description": self.description,
            "url": self.url,
            "landing_page": self.landing_page,
            "original_url": self.original_url,
            "size": self.size,
            "version": self.version,
            "scale": self.scale,
            "offset": self.offset,
            "manual_note": self.manual_note,
        }


class Moon:
    """Body-first entry point for Moon map products."""

    name = "moon"

    def __init__(self) -> None:
        self.dem = SurfaceEndpoint(
            self,
            "dem",
            "DEM",
            default_source="lro.lola.dem_118m",
            variable="dem",
            units="m",
        )
        self.svm_tsunakawa2015 = SurfaceEndpoint(
            self,
            "svm",
            "Tsunakawa 2015 SVM",
            default_source="kaguya.lmag.svm_tsunakawa2015",
            default_model="tsunakawa2015",
            variable="svm_tsunakawa2015",
            units="nT",
        )
        self.svm = self.svm_tsunakawa2015
        self.shadow = SurfaceEndpoint(self, "shadow", "Shadow map")
        self.illumination = SurfaceEndpoint(self, "illumination", "Illumination map")
        self.sza = SurfaceEndpoint(self, "sza", "Solar zenith angle")

    def info(self) -> InfoPage:
        return InfoPage(
            title="Moon",
            lines=(
                "dem: digital elevation model endpoint",
                "svm: default Tsunakawa lunar magnetic anomaly SVM endpoint",
                "svm_tsunakawa2015: explicit Tsunakawa SVM endpoint",
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

    def map(self, product: str) -> SurfaceEndpoint:
        endpoints = {
            "dem": self.dem,
            "svm": self.svm,
            "svm_tsunakawa2015": self.svm_tsunakawa2015,
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
    def __init__(
        self,
        body: Moon,
        product: str,
        label: str,
        *,
        default_source: str | None = None,
        default_model: str | None = None,
        variable: str | None = None,
        units: str | None = None,
    ) -> None:
        self.body = body
        self.product = product
        self.label = label
        self.default_source = default_source
        self.default_model = default_model
        self.variable = variable or product
        self.units = units

    def info(self) -> InfoPage:
        schema = self.schema()
        return InfoPage(
            title=f"Moon.{self.product}",
            lines=(
                f"{self.label} surface product.",
                "load supports implemented raster backends when source data is available.",
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
        title, markdown = examples.get(self.product, examples["dem"])
        return _example_page(title, markdown)

    def sources(self) -> tuple[str, ...]:
        return _SURFACE_SOURCES.get(self.product, ())

    def plan(self, **parameters: Any) -> SurfacePlan:
        normalized_parameters = dict(parameters)
        if self.default_source is not None and "source" not in normalized_parameters:
            normalized_parameters["source"] = self.default_source
        if self.default_model is not None and "model" not in normalized_parameters:
            normalized_parameters["model"] = self.default_model
        return SurfacePlan(
            body=self.body.name,
            product=self.product,
            parameters=_surface_parameters(self.product, normalized_parameters),
        )

    def source_info(self, source: str | None = None) -> SurfaceSource:
        source_id = _canonical_source_id(source or self.default_source)
        info = _SURFACE_SOURCE_INFO.get(source_id)
        if info is None or info.product != self.product:
            raise ValueError(
                f"Unknown Moon.{self.product} source: {source or self.default_source!r}. "
                "Available sources: "
                + _format_list(self.sources())
            )
        return info

    def acquisition_guide(
        self,
        *,
        source: str | None = None,
        language: str = "ja",
    ) -> GuidePage:
        source_info = self.source_info(source)
        markdowns = _acquisition_markdowns(source_info)
        return _guide_page(
            title=f"Moon {self.label} Data Acquisition",
            source=f"sopran.bodies.moon.{self.product}.acquisition",
            markdowns=markdowns,
            language=language,
            url=source_info.landing_page,
        )

    def download(
        self,
        *,
        source: str | None = None,
        store: Store | None = None,
        target: Path | str | None = None,
        overwrite: bool = False,
    ) -> Path:
        source_info = self.source_info(source)
        if source_info.url is None:
            raise DownloadError(
                f"Moon.{self.product} source requires manual acquisition: "
                f"{source_info.filename}. {source_info.manual_note or ''}".strip()
            )
        resolved_store = store or Store()
        target_path = (
            Path(target)
            if target is not None
            else resolved_store.raw_path("moon", self.product, source_info.filename)
        )
        if not target_path.exists() or overwrite:
            _download_file(source_info.url, target_path, overwrite=overwrite)
        _register_surface_download(resolved_store, target_path, source_info)
        return target_path

    def load(self, **parameters: Any) -> RasterLayer:
        store = parameters.pop("store", None)
        download = str(parameters.pop("download", "never"))
        path = parameters.pop("path", parameters.pop("filepath", None))
        plan = self.plan(**parameters)
        source = str(plan.parameters.get("source", self.default_source or ""))
        if self.product == "dem":
            data_path = _surface_data_path(
                endpoint=self,
                source=source,
                path=path,
                store=store,
                download=download,
            )
            return read_geotiff(
                data_path,
                product="dem",
                variable=self.variable,
                source=_canonical_source_id(source),
                units=self.units or "m",
                body=self.body.name,
                source_scale=_optional_source_scale(source),
                source_offset=_optional_source_offset(source),
                region=plan.parameters.get("region"),
                metadata=plan.to_metadata()["parameters"],
            )
        if self.product == "svm":
            data_path = _surface_data_path(
                endpoint=self,
                source=source,
                path=path,
                store=store,
                download=download,
            )
            if data_path.suffix.lower() == ".npy":
                return read_tsunakawa_svm_npy(
                    data_path,
                    source=_canonical_source_id(source),
                    body=self.body.name,
                    metadata=plan.to_metadata()["parameters"],
                )
            return read_tsunakawa_svm_text(
                data_path,
                source=_canonical_source_id(source),
                body=self.body.name,
                metadata=plan.to_metadata()["parameters"],
            )
        raise NotImplementedError(f"Moon.{plan.product}.load() is not implemented yet")

    def compute(self, **parameters: Any) -> None:
        plan = self.plan(**parameters)
        raise NotImplementedError(f"Moon.{plan.product}.compute() is not implemented yet")


_MOON_GUIDES = {
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

_SURFACE_SOURCES = {
    "dem": (
        "lro.lola.dem_118m",
        "lro.lola.sldem2015_59m",
        "lro.lola.dem",
        "kaguya.tc.dem",
    ),
    "svm": (
        "kaguya.lmag.svm_tsunakawa2015",
        "svm_tsunakawa2015",
        "kaguya.lism.svm",
    ),
    "shadow": ("legacy.shadowmap_sza",),
    "illumination": (),
    "sza": ("computed.spice.sza",),
}

_SURFACE_SOURCE_INFO = {
    "lro.lola.dem_118m": SurfaceSource(
        source_id="lro.lola.dem_118m",
        product="dem",
        provider="usgs_astrogeology",
        filename="Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif",
        description="LRO LOLA global lunar DEM, 256 pixels per degree, 118 m at equator.",
        url=(
            "https://planetarymaps.usgs.gov/mosaic/"
            "Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif"
        ),
        landing_page="https://astrogeology.usgs.gov/search/map/moon_lro_lola_dem_118m",
        size="8 GB",
        version="2014-03-11",
        scale=0.5,
        offset=0.0,
    ),
    "lro.lola.sldem2015_59m": SurfaceSource(
        source_id="lro.lola.sldem2015_59m",
        product="dem",
        provider="usgs_astrogeology",
        filename="Lunar_LRO_LOLAKaguya_DEMmerge_60N60S_512ppd.tif",
        description="SLDEM2015 LOLA + SELENE/Kaguya TC merged DEM, 512 ppd, 60S-60N.",
        url=(
            "https://planetarymaps.usgs.gov/mosaic/LolaKaguya_Topo/"
            "Lunar_LRO_LOLAKaguya_DEMmerge_60N60S_512ppd.tif"
        ),
        landing_page=(
            "https://astrogeology.usgs.gov/search/map/"
            "moon_lro_lola_selene_kaguya_tc_dem_merge_60n60s_59m"
        ),
        size="22 GB",
        version="2015",
    ),
    "kaguya.lmag.svm_tsunakawa2015": SurfaceSource(
        source_id="kaguya.lmag.svm_tsunakawa2015",
        product="svm",
        provider="kaguya_lmag_tsunakawa",
        filename="LunarSVM_000_02_v02.dat",
        description="Tsunakawa et al. lunar magnetic anomaly surface vector map.",
        landing_page=(
            "https://stereo-ssc.nascom.nasa.gov/instruments/software/impact/"
            "TDAS/socware/spedas_5_0/idl/projects/kaguya/map/lmag_spd_doc_list.html"
        ),
        original_url="http://www.geo.titech.ac.jp/lab/tsunakawa/Kaguya_LMAG",
        version="2015",
        manual_note=(
            "A stable public direct download URL is not registered in SOPRAN. "
            "Place the file under the store raw/moon/svm directory or pass path= explicitly."
        ),
    ),
}

_SOURCE_ALIASES = {
    "lro.lola.dem": "lro.lola.dem_118m",
    "kaguya.tc.dem": "lro.lola.sldem2015_59m",
    "svm_tsunakawa2015": "kaguya.lmag.svm_tsunakawa2015",
    "tsunakawa2015": "kaguya.lmag.svm_tsunakawa2015",
    "kaguya.lism.svm": "kaguya.lmag.svm_tsunakawa2015",
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
            units="nT",
            dtype="float64",
            frame="Moon body-fixed",
            description="Tsunakawa lunar magnetic anomaly surface vector map.",
            aliases=(
                "surface_vector_map",
                "svm_tsunakawa2015",
                "tsunakawa_svm2015",
                "lunar_magnetic_anomaly",
            ),
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


def _format_list(values: Any) -> str:
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


def _surface_data_path(
    *,
    endpoint: SurfaceEndpoint,
    source: str,
    path: Any,
    store: Store | str | Path | None,
    download: str,
) -> Path:
    if path is not None:
        return Path(path)
    if download not in {"never", "missing", "always"}:
        raise ValueError("download must be 'never', 'missing', or 'always'")
    source_info = endpoint.source_info(source)
    resolved_store = _coerce_store(store)
    candidate = resolved_store.raw_path("moon", endpoint.product, source_info.filename)
    if candidate.exists() and download != "always":
        return candidate
    if download in {"missing", "always"}:
        return endpoint.download(
            source=source_info.source_id,
            store=resolved_store,
            overwrite=download == "always",
        )
    raise DatasetNotFoundError(
        f"Moon.{endpoint.product} data is not available locally: {candidate}. "
        "Pass path= explicitly, set download='missing' for sources with a direct URL, "
        "or call acquisition_guide() for manual acquisition."
    )


def _coerce_store(store: Store | str | Path | None) -> Store:
    if isinstance(store, Store):
        return store
    return Store(store)


def _canonical_source_id(source: str | None) -> str:
    if source is None:
        raise ValueError("source is required")
    source_id = str(source)
    return _SOURCE_ALIASES.get(source_id, source_id)


def _optional_source_scale(source: str | None) -> float | None:
    info = _SURFACE_SOURCE_INFO.get(_canonical_source_id(source))
    return info.scale if info is not None else None


def _optional_source_offset(source: str | None) -> float | None:
    info = _SURFACE_SOURCE_INFO.get(_canonical_source_id(source))
    return info.offset if info is not None else None


def _register_surface_download(store: Store, path: Path, source: SurfaceSource) -> None:
    try:
        store.register_raw_file(
            path,
            mission="moon",
            provider=source.provider,
            provider_path=source.source_id,
            data_version=source.version,
            download_url=source.url,
        )
    except ValueError:
        return


def _download_file(url: str, target: Path, *, overwrite: bool = False) -> None:
    if target.exists() and not overwrite:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = _temporary_download_path(target)
    try:
        with urllib.request.urlopen(url) as response, temp.open("wb") as output:
            shutil.copyfileobj(response, output)
        temp.replace(target)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _temporary_download_path(target: Path) -> Path:
    for _ in range(100):
        temp = target.with_name(f"{target.name}.{uuid4().hex}.tmp")
        if not temp.exists():
            return temp
    raise FileExistsError(f"Could not allocate temporary download path for {target}")


def _acquisition_markdowns(source: SurfaceSource) -> dict[str, str]:
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
        return cast(dict[str, Any], dem["parameters"])
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
