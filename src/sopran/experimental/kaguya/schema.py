from sopran.core.schema import InstrumentSchema, VariableSchema

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
