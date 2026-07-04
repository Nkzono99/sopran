# Schemas

This page is generated from SOPRAN runtime schema objects.
Update the schema objects first, then regenerate this page.

## kaguya / esa1

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| energy_flux | time, energy, look | eV/(cm^2 s sr eV) |  |  | eflux, differential_energy_flux | Uncalibrated placeholder for KAGUYA PACE ESA1 differential electron energy flux; values are NaN until calibration is implemented. |
| counts | time, energy, look | count |  |  |  | Raw ESA1 counts. |
| energy | energy |  |  |  |  | PACE ESA1 energy channel index. Physical eV calibration is not applied. |
| quality | time |  |  |  | q, quality_flag | Quality flag. |

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
| npw_mode | time |  |  |  | kgy_lrs_npw_mode | KAGUYA LRS NPW mode flag. |
| wfc_ex_db | time, frequency | dB |  |  | kgy_lrs_wfc_ex_db, kgy_lrs_wfc_Ex, kgy_lrs_wfc_Ex_dB | KAGUYA LRS WFC Ex raw electric-field spectrum in dB. |
| wfc_ey_db | time, frequency | dB |  |  | kgy_lrs_wfc_ey_db, kgy_lrs_wfc_Ey, kgy_lrs_wfc_Ey_dB | KAGUYA LRS WFC Ey raw electric-field spectrum in dB. |
| wfc_gain | time | dB |  |  | kgy_lrs_wfc_gain | KAGUYA LRS WFC gain decoded from the Gain flag. |
| wfc_ex_field | time, frequency | dB uV/m |  |  | wfc_ex_physical, kgy_lrs_wfc_ex_phys, kgy_lrs_wfc_Ex_phys | KAGUYA LRS WFC Ex field level after gain and band correction. |
| wfc_ey_field | time, frequency | dB uV/m |  |  | wfc_ey_physical, kgy_lrs_wfc_ey_phys, kgy_lrs_wfc_Ey_phys | KAGUYA LRS WFC Ey field level after gain and band correction. |
| wfc_ex_power_spectral_density | time, frequency | (V/m)^2/Hz |  |  | wfc_ex_power, kgy_lrs_wfc_ex_phys2, kgy_lrs_wfc_Ex_phys2 | KAGUYA LRS WFC Ex electric-field power spectral density. |
| wfc_ey_power_spectral_density | time, frequency | (V/m)^2/Hz |  |  | wfc_ey_power, kgy_lrs_wfc_ey_phys2, kgy_lrs_wfc_Ey_phys2 | KAGUYA LRS WFC Ey electric-field power spectral density. |
| wfc_xymode | time |  |  |  | kgy_lrs_wfc_xymode | KAGUYA LRS WFC XY mode decoded from the Mode flag. |
| wfc_fband | time |  |  |  | kgy_lrs_wfc_fband | KAGUYA LRS WFC frequency band decoded from the Mode flag. |
| wfc_omode | time |  |  |  | kgy_lrs_wfc_omode | KAGUYA LRS WFC operation mode decoded from the Mode flag. |
| wfc_pdc_ti | time |  |  |  | kgy_lrs_wfc_pdc_ti, kgy_lrs_wfc_pdc-ti | KAGUYA LRS WFC PDC-TI flag. |
| wfc_postgap | time |  |  |  | kgy_lrs_wfc_postgap | KAGUYA LRS WFC PostGap flag. |

## kaguya / orbit

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| position | time, component | km |  | MOON_ME | rme, r_moon_me | KAGUYA spacecraft position vector in the Moon Mean Earth frame. |
| position_gse | time, component | km |  | GSE | rgse, r_gse | KAGUYA spacecraft position vector in the GSE frame. |
| radial_distance | time | km |  | MOON_ME | radius, r | Distance from the Moon center to the KAGUYA spacecraft. |
| altitude | time | km |  | MOON_ME |  | KAGUYA altitude above a spherical Moon reference radius. |
| subpoint | time, component | deg |  | MOON_ME |  | Spherical Moon subpoint longitude and latitude. |
| sza | time | deg |  | MOON_ME |  | Solar zenith angle at the spherical Moon subpoint, computed from an explicit Sun direction vector. |

## kaguya / lmag

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| connected_any | time |  | bool |  |  | Whether either magnetic-field direction intersects the sphere. |
| connected_plus | time |  | bool |  |  | Whether the plus magnetic-field direction intersects the sphere. |
| connected_minus | time |  | bool |  |  | Whether the minus magnetic-field direction intersects the sphere. |
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
| shadow | lat, lon | fraction | float64 | Moon body-fixed | shadow_map, shadow_fraction | terrain-aware shadow or shadow-fraction map. |
| illumination | lat, lon | fraction | float64 | Moon body-fixed | illumination_map, visibility | Illumination or visibility fraction derived from solar geometry. |
| sza | lat, lon | deg | float64 | Moon body-fixed | solar_zenith_angle | Solar zenith angle on the lunar surface. |
