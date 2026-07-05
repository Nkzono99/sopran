from __future__ import annotations

from sopran.core.schema import InstrumentSchema, VariableSchema

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


def surface_product_schema(product: str) -> InstrumentSchema:
    return InstrumentSchema(
        mission="moon",
        instrument=f"surface.{product}",
        variables=(MOON_SURFACE_SCHEMA.variable(product),),
    )
