from __future__ import annotations

from sopran.core.schema import InstrumentSchema, VariableSchema


KAGUYA_ESA1_SCHEMA = InstrumentSchema(
    mission="kaguya",
    instrument="esa1",
    variables=(
        VariableSchema(
            name="energy_flux",
            aliases=("eflux", "differential_energy_flux"),
            dims=("time", "energy", "look"),
            units="eV/(cm^2 s sr eV)",
            description="Differential electron energy flux from KAGUYA PACE ESA1.",
        ),
        VariableSchema(
            name="counts",
            dims=("time", "energy", "look"),
            units="count",
            description="Raw ESA1 counts.",
        ),
        VariableSchema(
            name="energy",
            dims=("energy",),
            units="eV",
            description="Energy bin center.",
        ),
        VariableSchema(
            name="quality",
            aliases=("q", "quality_flag"),
            dims=("time",),
            units=None,
            description="Quality flag.",
        ),
    ),
)
