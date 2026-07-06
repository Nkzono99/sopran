from __future__ import annotations

from sopran.core.schema import InstrumentSchema, VariableSchema

_PACE_PARTICLE = {
    "ESA1": "electron",
    "ESA2": "electron",
    "IMA": "ion",
    "IEA": "ion",
}


def _pace_spectrum_schema(sensor: str) -> InstrumentSchema:
    particle = _PACE_PARTICLE[sensor]
    return InstrumentSchema(
        mission="kaguya",
        instrument=sensor.lower(),
        variables=(
            VariableSchema(
                name="energy_flux",
                aliases=("eflux", "differential_energy_flux"),
                dims=("time", "energy", "look"),
                units="eV/(cm^2 s sr eV)",
                description=(
                    f"KAGUYA PACE {sensor} differential {particle} energy flux "
                    "derived from counts with PACE INFO calibration tables."
                ),
            ),
            VariableSchema(
                name="counts",
                dims=("time", "energy", "look"),
                units="count",
                description=f"Raw {sensor} counts.",
            ),
            VariableSchema(
                name="energy",
                dims=("energy",),
                units=None,
                description=(
                    f"PACE {sensor} energy channel index by default; calibrated loads "
                    "replace it with PACE INFO energy centers in eV."
                ),
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


KAGUYA_ESA1_SCHEMA = _pace_spectrum_schema("ESA1")
KAGUYA_ESA2_SCHEMA = _pace_spectrum_schema("ESA2")
KAGUYA_IMA_SCHEMA = _pace_spectrum_schema("IMA")
KAGUYA_IEA_SCHEMA = _pace_spectrum_schema("IEA")

KAGUYA_PACE_SCHEMAS = {
    "ESA1": KAGUYA_ESA1_SCHEMA,
    "ESA2": KAGUYA_ESA2_SCHEMA,
    "IMA": KAGUYA_IMA_SCHEMA,
    "IEA": KAGUYA_IEA_SCHEMA,
}


def kaguya_pace_schema(sensor: str) -> InstrumentSchema:
    normalized = sensor.upper()
    if normalized == "ESA-S1":
        normalized = "ESA1"
    elif normalized == "ESA-S2":
        normalized = "ESA2"
    return KAGUYA_PACE_SCHEMAS[normalized]


KAGUYA_LMAG_MAGNETIC_FIELD = VariableSchema(
    name="magnetic_field",
    aliases=("b", "lmag", "bme", "b_moon_me"),
    dims=("time", "component"),
    units="nT",
    frame="MOON_ME",
    description="KAGUYA LMAG magnetic field vector in the Moon Mean Earth frame.",
)

KAGUYA_LMAG_MAGNETIC_FIELD_GSE = VariableSchema(
    name="magnetic_field_gse",
    aliases=("bgse", "b_gse"),
    dims=("time", "component"),
    units="nT",
    frame="GSE",
    description="KAGUYA LMAG magnetic field vector in the GSE frame.",
)

KAGUYA_LMAG_MAGNETIC_FIELD_MAGNITUDE = VariableSchema(
    name="magnetic_field_magnitude",
    aliases=("bmag", "magnetic_field_strength"),
    dims=("time",),
    units="nT",
    description="Magnitude of the KAGUYA LMAG magnetic field vector.",
)

KAGUYA_ORBIT_POSITION = VariableSchema(
    name="position",
    aliases=("rme", "r_moon_me"),
    dims=("time", "component"),
    units="km",
    frame="MOON_ME",
    description="KAGUYA spacecraft position vector in the Moon Mean Earth frame.",
)

KAGUYA_ORBIT_POSITION_GSE = VariableSchema(
    name="position_gse",
    aliases=("rgse", "r_gse"),
    dims=("time", "component"),
    units="km",
    frame="GSE",
    description="KAGUYA spacecraft position vector in the GSE frame.",
)

KAGUYA_ORBIT_RADIAL_DISTANCE = VariableSchema(
    name="radial_distance",
    aliases=("radius", "r"),
    dims=("time",),
    units="km",
    frame="MOON_ME",
    description="Distance from the Moon center to the KAGUYA spacecraft.",
)

KAGUYA_ORBIT_ALTITUDE = VariableSchema(
    name="altitude",
    dims=("time",),
    units="km",
    frame="MOON_ME",
    description="KAGUYA altitude above a spherical Moon reference radius.",
)

KAGUYA_ORBIT_SUBPOINT = VariableSchema(
    name="subpoint",
    dims=("time", "component"),
    units="deg",
    frame="MOON_ME",
    description="Spherical Moon subpoint longitude and latitude.",
)

KAGUYA_ORBIT_SZA = VariableSchema(
    name="sza",
    dims=("time",),
    units="deg",
    frame="MOON_ME",
    description=(
        "Solar zenith angle at the spherical Moon subpoint, computed from an explicit "
        "Sun direction vector."
    ),
)

KAGUYA_LMAG_CONNECTION_VARIABLES = (
    VariableSchema(
        name="connected_any",
        dims=("time",),
        dtype="bool",
        description="Whether either magnetic-field direction intersects the sphere.",
    ),
    VariableSchema(
        name="connected_plus",
        dims=("time",),
        dtype="bool",
        description="Whether the plus magnetic-field direction intersects the sphere.",
    ),
    VariableSchema(
        name="connected_minus",
        dims=("time",),
        dtype="bool",
        description="Whether the minus magnetic-field direction intersects the sphere.",
    ),
    VariableSchema(
        name="footpoint_plus_lon",
        dims=("time",),
        units="deg",
        frame="MOON_ME",
        description="Plus-direction spherical footpoint longitude.",
    ),
    VariableSchema(
        name="footpoint_plus_lat",
        dims=("time",),
        units="deg",
        frame="MOON_ME",
        description="Plus-direction spherical footpoint latitude.",
    ),
    VariableSchema(
        name="footpoint_minus_lon",
        dims=("time",),
        units="deg",
        frame="MOON_ME",
        description="Minus-direction spherical footpoint longitude.",
    ),
    VariableSchema(
        name="footpoint_minus_lat",
        dims=("time",),
        units="deg",
        frame="MOON_ME",
        description="Minus-direction spherical footpoint latitude.",
    ),
    VariableSchema(
        name="distance_plus_km",
        dims=("time",),
        units="km",
        description="Distance along the plus magnetic-field direction to the sphere.",
    ),
    VariableSchema(
        name="distance_minus_km",
        dims=("time",),
        units="km",
        description="Distance along the minus magnetic-field direction to the sphere.",
    ),
    VariableSchema(
        name="incidence_angle_plus_deg",
        dims=("time",),
        units="deg",
        description="Acute angle between plus field line and local surface normal.",
    ),
    VariableSchema(
        name="incidence_angle_minus_deg",
        dims=("time",),
        units="deg",
        description="Acute angle between minus field line and local surface normal.",
    ),
    VariableSchema(
        name="altitude_km",
        dims=("time",),
        units="km",
        description="Spacecraft altitude above the spherical reference radius.",
    ),
)

KAGUYA_LMAG_SCHEMA = InstrumentSchema(
    mission="kaguya",
    instrument="lmag",
    variables=(
        KAGUYA_LMAG_MAGNETIC_FIELD,
        KAGUYA_LMAG_MAGNETIC_FIELD_GSE,
        KAGUYA_LMAG_MAGNETIC_FIELD_MAGNITUDE,
    ),
)

KAGUYA_ORBIT_SCHEMA = InstrumentSchema(
    mission="kaguya",
    instrument="orbit",
    variables=(
        KAGUYA_ORBIT_POSITION,
        KAGUYA_ORBIT_POSITION_GSE,
        KAGUYA_ORBIT_RADIAL_DISTANCE,
        KAGUYA_ORBIT_ALTITUDE,
        KAGUYA_ORBIT_SUBPOINT,
        KAGUYA_ORBIT_SZA,
    ),
)

KAGUYA_LMAG_CONNECTION_SCHEMA = InstrumentSchema(
    mission="kaguya",
    instrument="lmag",
    variables=KAGUYA_LMAG_CONNECTION_VARIABLES,
)

KAGUYA_LRS_SCHEMA = InstrumentSchema(
    mission="kaguya",
    instrument="lrs",
    variables=(
        VariableSchema(
            name="npw_rx1",
            aliases=("kgy_lrs_npw_rx1",),
            dims=("time", "frequency"),
            units="dB",
            description="KAGUYA LRS NPW receiver 1 spectrum.",
        ),
        VariableSchema(
            name="npw_rx2",
            aliases=("kgy_lrs_npw_rx2",),
            dims=("time", "frequency"),
            units="dB",
            description="KAGUYA LRS NPW receiver 2 spectrum.",
        ),
        VariableSchema(
            name="npw_mode",
            aliases=("kgy_lrs_npw_mode",),
            dims=("time",),
            description="KAGUYA LRS NPW mode flag.",
        ),
        VariableSchema(
            name="wfc_ex_db",
            aliases=("kgy_lrs_wfc_ex_db", "kgy_lrs_wfc_Ex", "kgy_lrs_wfc_Ex_dB"),
            dims=("time", "frequency"),
            units="dB",
            description="KAGUYA LRS WFC Ex raw electric-field spectrum in dB.",
        ),
        VariableSchema(
            name="wfc_ey_db",
            aliases=("kgy_lrs_wfc_ey_db", "kgy_lrs_wfc_Ey", "kgy_lrs_wfc_Ey_dB"),
            dims=("time", "frequency"),
            units="dB",
            description="KAGUYA LRS WFC Ey raw electric-field spectrum in dB.",
        ),
        VariableSchema(
            name="wfc_gain",
            aliases=("kgy_lrs_wfc_gain",),
            dims=("time",),
            units="dB",
            description="KAGUYA LRS WFC gain decoded from the Gain flag.",
        ),
        VariableSchema(
            name="wfc_ex_field",
            aliases=(
                "wfc_ex_physical",
                "kgy_lrs_wfc_ex_phys",
                "kgy_lrs_wfc_Ex_phys",
            ),
            dims=("time", "frequency"),
            units="dB uV/m",
            description="KAGUYA LRS WFC Ex field level after gain and band correction.",
        ),
        VariableSchema(
            name="wfc_ey_field",
            aliases=(
                "wfc_ey_physical",
                "kgy_lrs_wfc_ey_phys",
                "kgy_lrs_wfc_Ey_phys",
            ),
            dims=("time", "frequency"),
            units="dB uV/m",
            description="KAGUYA LRS WFC Ey field level after gain and band correction.",
        ),
        VariableSchema(
            name="wfc_ex_power_spectral_density",
            aliases=(
                "wfc_ex_power",
                "kgy_lrs_wfc_ex_phys2",
                "kgy_lrs_wfc_Ex_phys2",
            ),
            dims=("time", "frequency"),
            units="(V/m)^2/Hz",
            description="KAGUYA LRS WFC Ex electric-field power spectral density.",
        ),
        VariableSchema(
            name="wfc_ey_power_spectral_density",
            aliases=(
                "wfc_ey_power",
                "kgy_lrs_wfc_ey_phys2",
                "kgy_lrs_wfc_Ey_phys2",
            ),
            dims=("time", "frequency"),
            units="(V/m)^2/Hz",
            description="KAGUYA LRS WFC Ey electric-field power spectral density.",
        ),
        VariableSchema(
            name="wfc_xymode",
            aliases=("kgy_lrs_wfc_xymode",),
            dims=("time",),
            description="KAGUYA LRS WFC XY mode decoded from the Mode flag.",
        ),
        VariableSchema(
            name="wfc_fband",
            aliases=("kgy_lrs_wfc_fband",),
            dims=("time",),
            description="KAGUYA LRS WFC frequency band decoded from the Mode flag.",
        ),
        VariableSchema(
            name="wfc_omode",
            aliases=("kgy_lrs_wfc_omode",),
            dims=("time",),
            description="KAGUYA LRS WFC operation mode decoded from the Mode flag.",
        ),
        VariableSchema(
            name="wfc_pdc_ti",
            aliases=("kgy_lrs_wfc_pdc_ti", "kgy_lrs_wfc_pdc-ti"),
            dims=("time",),
            description="KAGUYA LRS WFC PDC-TI flag.",
        ),
        VariableSchema(
            name="wfc_postgap",
            aliases=("kgy_lrs_wfc_postgap",),
            dims=("time",),
            description="KAGUYA LRS WFC PostGap flag.",
        ),
    ),
)
