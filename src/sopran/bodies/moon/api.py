from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from sopran.core.pages import GuidePage, InfoPage
from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.core.store import Store
from sopran.maps.raster import RasterLayer

from . import guides, loaders
from .models import SurfacePlan, format_list
from .parameters import surface_parameters
from .schema import MOON_SURFACE_SCHEMA
from .sources import SURFACE_SOURCE_INFO, SURFACE_SOURCES, canonical_source_id


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
                + format_list(variable.name for variable in self.schema().variables),
            ),
        )

    def guide(self, *, language: str = "ja") -> GuidePage:
        return guides.moon_guide(language=language)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def schema(self) -> InstrumentSchema:
        return MOON_SURFACE_SCHEMA

    def example(self) -> GuidePage:
        return guides.moon_example()

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
                + format_list(variable.name for variable in MOON_SURFACE_SCHEMA.variables)
                + ". Aliases: "
                + format_list(
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
                "sources: " + format_list(self.sources()),
                "dims: " + format_list(schema.dims),
                f"units: {schema.units or 'none'}",
                f"frame: {schema.frame or 'none'}",
                "aliases: " + format_list(schema.aliases),
            ),
        )

    def guide(self, *, language: str = "ja") -> GuidePage:
        return guides.surface_guide(self.product, self.label, language=language)

    def help(self, *, language: str = "ja") -> GuidePage:
        return self.guide(language=language)

    def schema(self) -> VariableSchema:
        return MOON_SURFACE_SCHEMA.variable(self.product)

    def example(self) -> GuidePage:
        return guides.surface_example(self.product)

    def sources(self) -> tuple[str, ...]:
        return SURFACE_SOURCES.get(self.product, ())

    def plan(self, **parameters: Any) -> SurfacePlan:
        normalized_parameters = dict(parameters)
        if self.default_source is not None and "source" not in normalized_parameters:
            normalized_parameters["source"] = self.default_source
        if self.default_model is not None and "model" not in normalized_parameters:
            normalized_parameters["model"] = self.default_model
        return SurfacePlan(
            body=self.body.name,
            product=self.product,
            parameters=surface_parameters(self.product, normalized_parameters),
        )

    def source_info(self, source: str | None = None) -> Any:
        source_id = canonical_source_id(source or self.default_source)
        info = SURFACE_SOURCE_INFO.get(source_id)
        if info is None or info.product != self.product:
            raise ValueError(
                f"Unknown Moon.{self.product} source: {source or self.default_source!r}. "
                "Available sources: "
                + format_list(self.sources())
            )
        return info

    def acquisition_guide(
        self,
        *,
        source: str | None = None,
        language: str = "ja",
    ) -> GuidePage:
        return guides.acquisition_guide_page(
            self.source_info(source),
            label=self.label,
            language=language,
        )

    def download(
        self,
        *,
        source: str | None = None,
        store: Store | None = None,
        target: Path | str | None = None,
        overwrite: bool = False,
    ) -> Path:
        return loaders.download_surface_source(
            self.source_info(source),
            product=self.product,
            store=store,
            target=target,
            overwrite=overwrite,
        )

    def load(self, **parameters: Any) -> RasterLayer:
        return cast(RasterLayer, loaders.load_surface_raster(self, **parameters))

    def compute(self, **parameters: Any) -> None:
        plan = self.plan(**parameters)
        raise NotImplementedError(f"Moon.{plan.product}.compute() is not implemented yet")
