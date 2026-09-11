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
                units="channel",
                description=(
                    f"PACE {sensor} energy channel index by default; calibrated loads "
                    "replace it with PACE INFO energy centers in eV."
                ),
            ),
            VariableSchema(
                name="quality",
                aliases=("q", "quality_flag"),
                dims=("time",),
                units="flag",
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
        "Solar zenith angle at the spherical Moon subpoint, computed from SPICE "
        "Sun geometry unless an explicit Sun direction vector is supplied."
    ),
)

KAGUYA_LMAG_CONNECTION_VARIABLES = (
    VariableSchema(
        name="connected_any",
        dims=("time",),
        units="flag",
        dtype="bool",
        description="Whether either magnetic-field direction intersects the sphere.",
    ),
    VariableSchema(
        name="connected_plus",
        dims=("time",),
        units="flag",
        dtype="bool",
        description="Whether the plus magnetic-field direction intersects the sphere.",
    ),
    VariableSchema(
        name="connected_minus",
        dims=("time",),
        units="flag",
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

KAGUYA_ER_SCHEMA = InstrumentSchema(
    mission="kaguya",
    instrument="er",
    variables=(
        VariableSchema(
            name="effective_field",
            aliases=("b_eff",),
            dims=("time",),
            units="nT",
            description=(
                "Effective magnetic mirror-field magnitude inferred from paired "
                "electron pitch-angle counts. This is not a surface field vector."
            ),
        ),
        VariableSchema(
            name="effective_field_ci95_low",
            dims=("time",),
            units="nT",
            description="Lower endpoint of the profile-likelihood 95% B_eff interval.",
        ),
        VariableSchema(
            name="effective_field_ci95_high",
            dims=("time",),
            units="nT",
            description="Upper endpoint of the profile-likelihood 95% B_eff interval.",
        ),
        VariableSchema(
            name="mirror_ratio",
            aliases=("b_eff_over_b_sc",),
            dims=("time",),
            units="1",
            description="Effective mirror-field ratio B_eff/B_sc used as the primary ER estimate.",
        ),
        VariableSchema(
            name="mirror_ratio_ci95_low",
            dims=("time",),
            units="1",
            description="Lower endpoint of the profile-likelihood 95% mirror-ratio interval.",
        ),
        VariableSchema(
            name="mirror_ratio_ci95_high",
            dims=("time",),
            units="1",
            description="Upper endpoint of the profile-likelihood 95% mirror-ratio interval.",
        ),
        VariableSchema(
            name="b_sc_nT",
            dims=("time",),
            units="nT",
            description="Spacecraft magnetic-field magnitude used to convert the mirror ratio.",
        ),
        VariableSchema(
            name="magnetic_field_x",
            dims=("time",),
            units="nT",
            frame="MOON_ME",
            description="MOON_ME magnetic-field x component at the fitted observation.",
        ),
        VariableSchema(
            name="magnetic_field_y",
            dims=("time",),
            units="nT",
            frame="MOON_ME",
            description="MOON_ME magnetic-field y component at the fitted observation.",
        ),
        VariableSchema(
            name="magnetic_field_z",
            dims=("time",),
            units="nT",
            frame="MOON_ME",
            description="MOON_ME magnetic-field z component at the fitted observation.",
        ),
        VariableSchema(
            name="radial_magnetic_field",
            dims=("time",),
            units="nT",
            frame="MOON_ME",
            description="Outward radial magnetic-field component at the spacecraft.",
        ),
        VariableSchema(
            name="position_x",
            dims=("time",),
            units="km",
            frame="MOON_ME",
            description="MOON_ME spacecraft position x component.",
        ),
        VariableSchema(
            name="position_y",
            dims=("time",),
            units="km",
            frame="MOON_ME",
            description="MOON_ME spacecraft position y component.",
        ),
        VariableSchema(
            name="position_z",
            dims=("time",),
            units="km",
            frame="MOON_ME",
            description="MOON_ME spacecraft position z component.",
        ),
        VariableSchema(
            name="radial_distance",
            dims=("time",),
            units="km",
            frame="MOON_ME",
            description="Spacecraft distance from the Moon center.",
        ),
        VariableSchema(
            name="altitude",
            dims=("time",),
            units="km",
            frame="MOON_ME",
            description="Spacecraft altitude above the 1737.4 km spherical Moon.",
        ),
        VariableSchema(
            name="longitude",
            dims=("time",),
            units="deg",
            frame="MOON_ME",
            description="East longitude of the spacecraft spherical subpoint.",
        ),
        VariableSchema(
            name="latitude",
            dims=("time",),
            units="deg",
            frame="MOON_ME",
            description="Latitude of the spacecraft spherical subpoint.",
        ),
        VariableSchema(
            name="sza",
            dims=("time",),
            units="deg",
            frame="MOON_ME",
            description="Solar zenith angle at the spacecraft spherical subpoint.",
        ),
        VariableSchema(
            name="delta_u_eff",
            dims=("time",),
            units="eV",
            description=(
                "Optional effective low-energy curvature term; not a direct surface-potential "
                "measurement unless independently validated."
            ),
        ),
        VariableSchema(
            name="sigma_ln_b",
            dims=("time",),
            units="1",
            description=(
                "Logarithmic width of a selected smooth mirror transition; absent for a "
                "response-integrated hard transition."
            ),
        ),
        VariableSchema(
            name="transition_model",
            dims=("time",),
            units="category",
            dtype="str",
            description="Selected none, hard, or smooth latent loss-cone transition.",
        ),
        VariableSchema(
            name="smooth_transition_delta_bic",
            dims=("time",),
            units="1",
            description=(
                "BIC improvement from hard to smooth transition; positive values support "
                "the additional smooth-transition width."
            ),
        ),
        VariableSchema(
            name="smooth_transition_screen_delta_bic",
            dims=("time",),
            units="1",
            description=(
                "Low-resolution screening BIC improvement from hard to smooth; used only "
                "to decide whether the full-response smooth fit is run."
            ),
        ),
        VariableSchema(
            name="smooth_transition_refined",
            dims=("time",),
            units="flag",
            dtype="bool",
            description="Whether the smooth candidate reached full-response refinement.",
        ),
        VariableSchema(
            name="contrast_model",
            dims=("time",),
            units="category",
            dtype="str",
            description=(
                "Selected none, free, constant, or log-energy band model for the "
                "pitch-angle edge contrast."
            ),
        ),
        VariableSchema(
            name="contrast_band_center",
            dims=("time",),
            units="eV",
            description=(
                "Center energy of a selected log-energy contrast band; this is a "
                "detectability descriptor, not an energy or potential shift."
            ),
        ),
        VariableSchema(
            name="contrast_band_width_ln",
            dims=("time",),
            units="1",
            description="Gaussian sigma of the selected contrast band in natural-log energy.",
        ),
        VariableSchema(
            name="contrast_band_floor_log_ratio",
            dims=("time",),
            units="1",
            description="Asymptotic pitch-edge log-ratio contrast outside the selected band.",
        ),
        VariableSchema(
            name="contrast_band_peak_log_ratio",
            dims=("time",),
            units="1",
            description="Pitch-edge log-ratio contrast at the selected band center.",
        ),
        VariableSchema(
            name="contrast_band_delta_bic",
            dims=("time",),
            units="1",
            description="BIC(constant contrast) minus BIC(log-energy band contrast).",
        ),
        VariableSchema(
            name="contrast_band_screen_delta_bic",
            dims=("time",),
            units="1",
            description=(
                "Partial-fit screening BIC improvement for the log-energy contrast band."
            ),
        ),
        VariableSchema(
            name="contrast_band_refined",
            dims=("time",),
            units="flag",
            dtype="bool",
            description="Whether the contrast-band candidate reached full refinement.",
        ),
        VariableSchema(
            name="secondary_beam_delta_bic",
            dims=("time",),
            units="1",
            description="Full-response BIC improvement from adding the secondary-beam model.",
        ),
        VariableSchema(
            name="secondary_beam_screen_delta_bic",
            dims=("time",),
            units="1",
            description=(
                "Low-resolution partial-fit BIC improvement used to screen the beam model."
            ),
        ),
        VariableSchema(
            name="secondary_beam_refined",
            dims=("time",),
            units="flag",
            dtype="bool",
            description="Whether the secondary-beam candidate reached full refinement.",
        ),
        VariableSchema(
            name="boundary_bracket_fraction",
            dims=("time",),
            units="1",
            description=(
                "Fraction of retained energies with at least one observed pitch bin on "
                "each side of the fitted boundary."
            ),
        ),
        VariableSchema(
            name="strict_boundary_bracket_fraction",
            dims=("time",),
            units="1",
            description=(
                "Fraction of retained energies with at least two observed pitch bins on "
                "each side of the fitted boundary."
            ),
        ),
        VariableSchema(
            name="quality_grade",
            dims=("time",),
            units="category",
            dtype="str",
            description=(
                "Conservative good, review, poor, or reject grade combining edge "
                "selection with observed-versus-fitted pitch-map agreement."
            ),
        ),
        VariableSchema(
            name="quality_reasons",
            dims=("time",),
            units="category",
            dtype="str",
            description="Comma-separated reasons that prevented a good fit-quality grade.",
        ),
        VariableSchema(
            name="edge_fit_log_ratio_residual_median_abs",
            dims=("time",),
            units="1",
            description=(
                "Median absolute residual of the paired affected/reference natural-log "
                "count ratio for the assessed edge candidate."
            ),
        ),
        VariableSchema(
            name="edge_fit_log_ratio_residual_p90_abs",
            dims=("time",),
            units="1",
            description=(
                "90th percentile absolute residual of the paired affected/reference "
                "natural-log count ratio."
            ),
        ),
        VariableSchema(
            name="edge_fit_pitch_pattern_correlation",
            dims=("time",),
            units="1",
            description=(
                "Correlation of row-centered observed and fitted pitch-angle patterns "
                "across retained energies."
            ),
        ),
        VariableSchema(
            name="edge_fit_pitch_pattern_nrmse",
            dims=("time",),
            units="1",
            description=(
                "RMSE of row-centered fitted pitch patterns normalized by observed "
                "pitch-pattern standard deviation."
            ),
        ),
        VariableSchema(
            name="edge_fit_standardized_residual_median_abs",
            dims=("time",),
            units="1",
            description="Median absolute beta-binomial Pearson residual.",
        ),
        VariableSchema(
            name="edge_fit_standardized_residual_p90_abs",
            dims=("time",),
            units="1",
            description="90th percentile absolute beta-binomial Pearson residual.",
        ),
        VariableSchema(
            name="edge_fit_standardized_residual_inlier_fraction",
            dims=("time",),
            units="1",
            description=(
                "Fraction of retained cells within the configured standardized-residual "
                "sigma threshold."
            ),
        ),
        VariableSchema(
            name="energy_ratio_step_supported",
            dims=("time",),
            units="flag",
            dtype="bool",
            description=(
                "Whether a separate all-pitch affected/reference energy-ratio change "
                "point is supported."
            ),
        ),
        VariableSchema(
            name="energy_ratio_step_center",
            dims=("time",),
            units="eV",
            description=(
                "Energy of a supported affected/reference ratio change point; not a "
                "calibrated energy or potential shift."
            ),
        ),
        VariableSchema(
            name="energy_ratio_step_log_ratio",
            dims=("time",),
            units="1",
            description="Fitted log-ratio jump across the supported energy change point.",
        ),
        VariableSchema(
            name="energy_ratio_step_delta_bic",
            dims=("time",),
            units="1",
            description="BIC(linear log-energy trend) minus BIC(trend plus change point).",
        ),
        VariableSchema(
            name="energy_ratio_step_direction",
            dims=("time",),
            units="category",
            dtype="str",
            description="Up or down direction of the supported energy-ratio change point.",
        ),
        VariableSchema(
            name="edge_supported",
            dims=("time",),
            units="flag",
            dtype="bool",
            description="Whether an edge model is supported over the no-edge model.",
        ),
        VariableSchema(
            name="no_edge_delta_bic",
            dims=("time",),
            units="1",
            description="BIC(no-edge) minus BIC(mirror-only); positive values favor an edge.",
        ),
        VariableSchema(
            name="electrostatic_delta_bic",
            dims=("time",),
            units="1",
            description=(
                "BIC(mirror-only) minus BIC(electrostatic); positive values favor curvature."
            ),
        ),
        VariableSchema(
            name="total_counts",
            dims=("time",),
            units="count",
            dtype="int64",
            description="Total affected plus reference counts retained by the fit.",
        ),
        VariableSchema(
            name="n_energy_bins",
            dims=("time",),
            units="count",
            dtype="int64",
            description="Number of energy bins retained by the fit.",
        ),
        VariableSchema(
            name="n_cells",
            dims=("time",),
            units="count",
            dtype="int64",
            description="Number of paired energy-pitch cells retained by the fit.",
        ),
        VariableSchema(
            name="selected_model",
            dims=("time",),
            units="category",
            dtype="str",
            description="Selected no-edge, mirror-only, or electrostatic nested model.",
        ),
        VariableSchema(
            name="edge_candidate_model",
            dims=("time",),
            units="category",
            dtype="str",
            description="Edge model assessed by the bounds and boundary-support quality gates.",
        ),
        VariableSchema(
            name="edge_candidate_contrast_model",
            dims=("time",),
            units="category",
            dtype="str",
            description="Contrast family used by the edge candidate, including rejected fits.",
        ),
        VariableSchema(
            name="affected_side",
            dims=("time",),
            units="category",
            dtype="str",
            description="Low- or high-pitch outgoing hemisphere used as the affected side.",
        ),
        VariableSchema(
            name="exposure_mode",
            dims=("time",),
            units="category",
            dtype="str",
            description="Origin and calibration level of the paired count exposure correction.",
        ),
        VariableSchema(
            name="success",
            dims=("time",),
            units="flag",
            dtype="bool",
            description="Whether numerical fitting completed with a physical candidate.",
        ),
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
            units="flag",
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
            name="wfc_mode",
            aliases=("kgy_lrs_wfc_mode",),
            dims=("time",),
            units="flag",
            description="Raw KAGUYA LRS WFC Mode support byte.",
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
            units="flag",
            description="KAGUYA LRS WFC XY mode decoded from the Mode flag.",
        ),
        VariableSchema(
            name="wfc_fband",
            aliases=("kgy_lrs_wfc_fband",),
            dims=("time",),
            units="flag",
            description="KAGUYA LRS WFC frequency band decoded from the Mode flag.",
        ),
        VariableSchema(
            name="wfc_omode",
            aliases=("kgy_lrs_wfc_omode",),
            dims=("time",),
            units="flag",
            description="KAGUYA LRS WFC operation mode decoded from the Mode flag.",
        ),
        VariableSchema(
            name="wfc_pdc_ti",
            aliases=("kgy_lrs_wfc_pdc_ti", "kgy_lrs_wfc_pdc-ti"),
            dims=("time",),
            units="count",
            description=(
                "KAGUYA LRS WFC PDC-TI 48-bit spacecraft observation-time counter; "
                "this is not UTC."
            ),
        ),
        VariableSchema(
            name="wfc_pdc_ti_words",
            dims=("time", "pdc_word"),
            units="counter word",
            description=(
                "Raw high, middle, and low uint16 words of the KAGUYA LRS WFC "
                "PDC-TI counter."
            ),
        ),
        VariableSchema(
            name="wfc_postgap",
            aliases=("kgy_lrs_wfc_postgap",),
            dims=("time",),
            units="flag",
            description="KAGUYA LRS WFC PostGap flag.",
        ),
    ),
)
