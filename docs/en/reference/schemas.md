# Schemas

This page is generated from SOPRAN runtime schema objects.
Update the schema objects first, then regenerate this page.

## kaguya / esa1

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| energy_flux | time, energy, look | eV/(cm^2 s sr eV) |  |  | eflux, differential_energy_flux | KAGUYA PACE ESA1 differential electron energy flux derived from counts with PACE INFO calibration tables. |
| counts | time, energy, look | count |  |  |  | Raw ESA1 counts. |
| energy | energy | channel |  |  |  | PACE ESA1 energy channel index by default; calibrated loads replace it with PACE INFO energy centers in eV. |
| quality | time | flag |  |  | q, quality_flag | Quality flag. |

## kaguya / esa2

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| energy_flux | time, energy, look | eV/(cm^2 s sr eV) |  |  | eflux, differential_energy_flux | KAGUYA PACE ESA2 differential electron energy flux derived from counts with PACE INFO calibration tables. |
| counts | time, energy, look | count |  |  |  | Raw ESA2 counts. |
| energy | energy | channel |  |  |  | PACE ESA2 energy channel index by default; calibrated loads replace it with PACE INFO energy centers in eV. |
| quality | time | flag |  |  | q, quality_flag | Quality flag. |

## kaguya / er

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| effective_field | time | nT |  |  | b_eff | Effective magnetic mirror-field magnitude inferred from paired electron pitch-angle counts. This is not a surface field vector. |
| effective_field_ci95_low | time | nT |  |  |  | Lower endpoint of the profile-likelihood 95% B_eff interval. |
| effective_field_ci95_high | time | nT |  |  |  | Upper endpoint of the profile-likelihood 95% B_eff interval. |
| mirror_ratio | time | 1 |  |  | b_eff_over_b_sc | Effective mirror-field ratio B_eff/B_sc used as the primary ER estimate. |
| mirror_ratio_ci95_low | time | 1 |  |  |  | Lower endpoint of the profile-likelihood 95% mirror-ratio interval. |
| mirror_ratio_ci95_high | time | 1 |  |  |  | Upper endpoint of the profile-likelihood 95% mirror-ratio interval. |
| b_sc_nT | time | nT |  |  |  | Spacecraft magnetic-field magnitude used to convert the mirror ratio. |
| magnetic_field_x | time | nT |  | MOON_ME |  | MOON_ME magnetic-field x component at the fitted observation. |
| magnetic_field_y | time | nT |  | MOON_ME |  | MOON_ME magnetic-field y component at the fitted observation. |
| magnetic_field_z | time | nT |  | MOON_ME |  | MOON_ME magnetic-field z component at the fitted observation. |
| radial_magnetic_field | time | nT |  | MOON_ME |  | Outward radial magnetic-field component at the spacecraft. |
| position_x | time | km |  | MOON_ME |  | MOON_ME spacecraft position x component. |
| position_y | time | km |  | MOON_ME |  | MOON_ME spacecraft position y component. |
| position_z | time | km |  | MOON_ME |  | MOON_ME spacecraft position z component. |
| radial_distance | time | km |  | MOON_ME |  | Spacecraft distance from the Moon center. |
| altitude | time | km |  | MOON_ME |  | Spacecraft altitude above the 1737.4 km spherical Moon. |
| longitude | time | deg |  | MOON_ME |  | East longitude of the spacecraft spherical subpoint. |
| latitude | time | deg |  | MOON_ME |  | Latitude of the spacecraft spherical subpoint. |
| sza | time | deg |  | MOON_ME |  | Solar zenith angle at the spacecraft spherical subpoint. |
| delta_u_eff | time | eV |  |  |  | Optional effective low-energy curvature term; not a direct surface-potential measurement unless independently validated. |
| sigma_ln_b | time | 1 |  |  |  | Logarithmic width of a selected smooth mirror transition; absent for a response-integrated hard transition. |
| transition_model | time | category | str |  |  | Selected none, hard, or smooth latent loss-cone transition. |
| smooth_transition_delta_bic | time | 1 |  |  |  | BIC improvement from hard to smooth transition; positive values support the additional smooth-transition width. |
| smooth_transition_screen_delta_bic | time | 1 |  |  |  | Low-resolution screening BIC improvement from hard to smooth; used only to decide whether the full-response smooth fit is run. |
| smooth_transition_refined | time | flag | bool |  |  | Whether the smooth candidate reached full-response refinement. |
| contrast_model | time | category | str |  |  | Selected none, free, constant, or log-energy band model for the pitch-angle edge contrast. |
| contrast_band_center | time | eV |  |  |  | Center energy of a selected log-energy contrast band; this is a detectability descriptor, not an energy or potential shift. |
| contrast_band_width_ln | time | 1 |  |  |  | Gaussian sigma of the selected contrast band in natural-log energy. |
| contrast_band_floor_log_ratio | time | 1 |  |  |  | Asymptotic pitch-edge log-ratio contrast outside the selected band. |
| contrast_band_peak_log_ratio | time | 1 |  |  |  | Pitch-edge log-ratio contrast at the selected band center. |
| contrast_band_delta_bic | time | 1 |  |  |  | BIC(constant contrast) minus BIC(log-energy band contrast). |
| contrast_band_screen_delta_bic | time | 1 |  |  |  | Partial-fit screening BIC improvement for the log-energy contrast band. |
| contrast_band_refined | time | flag | bool |  |  | Whether the contrast-band candidate reached full refinement. |
| secondary_beam_delta_bic | time | 1 |  |  |  | Full-response BIC improvement from adding the secondary-beam model. |
| secondary_beam_screen_delta_bic | time | 1 |  |  |  | Low-resolution partial-fit BIC improvement used to screen the beam model. |
| secondary_beam_refined | time | flag | bool |  |  | Whether the secondary-beam candidate reached full refinement. |
| boundary_bracket_fraction | time | 1 |  |  |  | Fraction of retained energies with at least one observed pitch bin on each side of the fitted boundary. |
| strict_boundary_bracket_fraction | time | 1 |  |  |  | Fraction of retained energies with at least two observed pitch bins on each side of the fitted boundary. |
| quality_grade | time | category | str |  |  | Conservative good, review, poor, or reject grade combining edge selection with observed-versus-fitted pitch-map agreement. |
| quality_reasons | time | category | str |  |  | Comma-separated reasons that prevented a good fit-quality grade. |
| edge_fit_log_ratio_residual_median_abs | time | 1 |  |  |  | Median absolute residual of the paired affected/reference natural-log count ratio for the assessed edge candidate. |
| edge_fit_log_ratio_residual_p90_abs | time | 1 |  |  |  | 90th percentile absolute residual of the paired affected/reference natural-log count ratio. |
| edge_fit_pitch_pattern_correlation | time | 1 |  |  |  | Correlation of row-centered observed and fitted pitch-angle patterns across retained energies. |
| edge_fit_pitch_pattern_nrmse | time | 1 |  |  |  | RMSE of row-centered fitted pitch patterns normalized by observed pitch-pattern standard deviation. |
| edge_fit_standardized_residual_median_abs | time | 1 |  |  |  | Median absolute beta-binomial Pearson residual. |
| edge_fit_standardized_residual_p90_abs | time | 1 |  |  |  | 90th percentile absolute beta-binomial Pearson residual. |
| edge_fit_standardized_residual_inlier_fraction | time | 1 |  |  |  | Fraction of retained cells within the configured standardized-residual sigma threshold. |
| energy_ratio_step_supported | time | flag | bool |  |  | Whether a separate all-pitch affected/reference energy-ratio change point is supported. |
| energy_ratio_step_center | time | eV |  |  |  | Energy of a supported affected/reference ratio change point; not a calibrated energy or potential shift. |
| energy_ratio_step_log_ratio | time | 1 |  |  |  | Fitted log-ratio jump across the supported energy change point. |
| energy_ratio_step_delta_bic | time | 1 |  |  |  | BIC(linear log-energy trend) minus BIC(trend plus change point). |
| energy_ratio_step_direction | time | category | str |  |  | Up or down direction of the supported energy-ratio change point. |
| edge_supported | time | flag | bool |  |  | Whether an edge model is supported over the no-edge model. |
| no_edge_delta_bic | time | 1 |  |  |  | BIC(no-edge) minus BIC(mirror-only); positive values favor an edge. |
| electrostatic_delta_bic | time | 1 |  |  |  | BIC(mirror-only) minus BIC(electrostatic); positive values favor curvature. |
| total_counts | time | count | int64 |  |  | Total affected plus reference counts retained by the fit. |
| n_energy_bins | time | count | int64 |  |  | Number of energy bins retained by the fit. |
| n_cells | time | count | int64 |  |  | Number of paired energy-pitch cells retained by the fit. |
| selected_model | time | category | str |  |  | Selected no-edge, mirror-only, or electrostatic nested model. |
| edge_candidate_model | time | category | str |  |  | Edge model assessed by the bounds and boundary-support quality gates. |
| edge_candidate_contrast_model | time | category | str |  |  | Contrast family used by the edge candidate, including rejected fits. |
| affected_side | time | category | str |  |  | Low- or high-pitch outgoing hemisphere used as the affected side. |
| exposure_mode | time | category | str |  |  | Origin and calibration level of the paired count exposure correction. |
| success | time | flag | bool |  |  | Whether numerical fitting completed with a physical candidate. |

## kaguya / ima

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| energy_flux | time, energy, look | eV/(cm^2 s sr eV) |  |  | eflux, differential_energy_flux | KAGUYA PACE IMA differential ion energy flux derived from counts with PACE INFO calibration tables. |
| counts | time, energy, look | count |  |  |  | Raw IMA counts. |
| energy | energy | channel |  |  |  | PACE IMA energy channel index by default; calibrated loads replace it with PACE INFO energy centers in eV. |
| quality | time | flag |  |  | q, quality_flag | Quality flag. |

## kaguya / iea

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| energy_flux | time, energy, look | eV/(cm^2 s sr eV) |  |  | eflux, differential_energy_flux | KAGUYA PACE IEA differential ion energy flux derived from counts with PACE INFO calibration tables. |
| counts | time, energy, look | count |  |  |  | Raw IEA counts. |
| energy | energy | channel |  |  |  | PACE IEA energy channel index by default; calibrated loads replace it with PACE INFO energy centers in eV. |
| quality | time | flag |  |  | q, quality_flag | Quality flag. |

## kaguya / lmag

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| magnetic_field | time, component | nT |  | MOON_ME | b, lmag, bme, b_moon_me | KAGUYA LMAG magnetic field vector in the Moon Mean Earth frame. |
| magnetic_field_gse | time, component | nT |  | GSE | bgse, b_gse | KAGUYA LMAG magnetic field vector in the GSE frame. |
| magnetic_field_magnitude | time | nT |  |  | bmag, magnetic_field_strength | Magnitude of the KAGUYA LMAG magnetic field vector. |

## kaguya / lrs

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| npw_rx1 | time, frequency | dB |  |  | kgy_lrs_npw_rx1 | KAGUYA LRS NPW receiver 1 spectrum. |
| npw_rx2 | time, frequency | dB |  |  | kgy_lrs_npw_rx2 | KAGUYA LRS NPW receiver 2 spectrum. |
| npw_mode | time | flag |  |  | kgy_lrs_npw_mode | KAGUYA LRS NPW mode flag. |
| wfc_ex_db | time, frequency | dB |  |  | kgy_lrs_wfc_ex_db, kgy_lrs_wfc_Ex, kgy_lrs_wfc_Ex_dB | KAGUYA LRS WFC Ex raw electric-field spectrum in dB. |
| wfc_ey_db | time, frequency | dB |  |  | kgy_lrs_wfc_ey_db, kgy_lrs_wfc_Ey, kgy_lrs_wfc_Ey_dB | KAGUYA LRS WFC Ey raw electric-field spectrum in dB. |
| wfc_gain | time | dB |  |  | kgy_lrs_wfc_gain | KAGUYA LRS WFC gain decoded from the Gain flag. |
| wfc_mode | time | flag |  |  | kgy_lrs_wfc_mode | Raw KAGUYA LRS WFC Mode support byte. |
| wfc_ex_field | time, frequency | dB uV/m |  |  | wfc_ex_physical, kgy_lrs_wfc_ex_phys, kgy_lrs_wfc_Ex_phys | KAGUYA LRS WFC Ex field level after gain and band correction. |
| wfc_ey_field | time, frequency | dB uV/m |  |  | wfc_ey_physical, kgy_lrs_wfc_ey_phys, kgy_lrs_wfc_Ey_phys | KAGUYA LRS WFC Ey field level after gain and band correction. |
| wfc_ex_power_spectral_density | time, frequency | (V/m)^2/Hz |  |  | wfc_ex_power, kgy_lrs_wfc_ex_phys2, kgy_lrs_wfc_Ex_phys2 | KAGUYA LRS WFC Ex electric-field power spectral density. |
| wfc_ey_power_spectral_density | time, frequency | (V/m)^2/Hz |  |  | wfc_ey_power, kgy_lrs_wfc_ey_phys2, kgy_lrs_wfc_Ey_phys2 | KAGUYA LRS WFC Ey electric-field power spectral density. |
| wfc_xymode | time | flag |  |  | kgy_lrs_wfc_xymode | KAGUYA LRS WFC XY mode decoded from the Mode flag. |
| wfc_fband | time | flag |  |  | kgy_lrs_wfc_fband | KAGUYA LRS WFC frequency band decoded from the Mode flag. |
| wfc_omode | time | flag |  |  | kgy_lrs_wfc_omode | KAGUYA LRS WFC operation mode decoded from the Mode flag. |
| wfc_pdc_ti | time | count |  |  | kgy_lrs_wfc_pdc_ti, kgy_lrs_wfc_pdc-ti | KAGUYA LRS WFC PDC-TI 48-bit spacecraft observation-time counter; this is not UTC. |
| wfc_pdc_ti_words | time, pdc_word | counter word |  |  |  | Raw high, middle, and low uint16 words of the KAGUYA LRS WFC PDC-TI counter. |
| wfc_postgap | time | flag |  |  | kgy_lrs_wfc_postgap | KAGUYA LRS WFC PostGap flag. |

## kaguya / orbit

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| position | time, component | km |  | MOON_ME | rme, r_moon_me | KAGUYA spacecraft position vector in the Moon Mean Earth frame. |
| position_gse | time, component | km |  | GSE | rgse, r_gse | KAGUYA spacecraft position vector in the GSE frame. |
| radial_distance | time | km |  | MOON_ME | radius, r | Distance from the Moon center to the KAGUYA spacecraft. |
| altitude | time | km |  | MOON_ME |  | KAGUYA altitude above a spherical Moon reference radius. |
| subpoint | time, component | deg |  | MOON_ME |  | Spherical Moon subpoint longitude and latitude. |
| sza | time | deg |  | MOON_ME |  | Solar zenith angle at the spherical Moon subpoint, computed from SPICE Sun geometry unless an explicit Sun direction vector is supplied. |

## kaguya / lmag

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| connected_any | time | flag | bool |  |  | Whether either magnetic-field direction intersects the sphere. |
| connected_plus | time | flag | bool |  |  | Whether the plus magnetic-field direction intersects the sphere. |
| connected_minus | time | flag | bool |  |  | Whether the minus magnetic-field direction intersects the sphere. |
| footpoint_plus_lon | time | deg |  | MOON_ME |  | Plus-direction spherical footpoint longitude. |
| footpoint_plus_lat | time | deg |  | MOON_ME |  | Plus-direction spherical footpoint latitude. |
| footpoint_minus_lon | time | deg |  | MOON_ME |  | Minus-direction spherical footpoint longitude. |
| footpoint_minus_lat | time | deg |  | MOON_ME |  | Minus-direction spherical footpoint latitude. |
| distance_plus_km | time | km |  |  |  | Distance along the plus magnetic-field direction to the sphere. |
| distance_minus_km | time | km |  |  |  | Distance along the minus magnetic-field direction to the sphere. |
| incidence_angle_plus_deg | time | deg |  |  |  | Acute angle between plus field line and local surface normal. |
| incidence_angle_minus_deg | time | deg |  |  |  | Acute angle between minus field line and local surface normal. |
| altitude_km | time | km |  |  |  | Spacecraft altitude above the spherical reference radius. |

## artemis / fgm

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| magnetic_field | time, component | nT |  |  | b, fgm | ARTEMIS fluxgate magnetic field vector. |

## artemis / esa

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| ion_energy_flux | time, energy | eV/(cm^2 s sr eV) |  |  | ion_eflux, esa | ARTEMIS ESA ion differential energy flux. |

## moon / surface

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| dem | lat, lon | m | float64 | Moon body-fixed | elevation, height | Digital elevation model on a body-fixed lunar grid. |
| svm | lat, lon | nT | float64 | Moon body-fixed | surface_vector_map, svm_tsunakawa2015, tsunakawa_svm2015, lunar_magnetic_anomaly | Tsunakawa lunar magnetic anomaly surface vector map. |
| shadow | lat, lon | fraction | float64 | Moon body-fixed | shadow_map, shadow_fraction | Shadow or shadow-fraction map computed with SZA-threshold or terrain-ray DEM horizon classification. |
| illumination | lat, lon | fraction | float64 | Moon body-fixed | illumination_map, visibility | Illumination or visibility fraction derived from solar geometry. |
| sza | lat, lon | deg | float64 | Moon body-fixed | solar_zenith_angle | Solar zenith angle on the lunar surface. |
