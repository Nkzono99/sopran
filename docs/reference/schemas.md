# スキーマ

このページは SOPRAN の runtime schema object から生成しています。
スキーマを変更する場合は、先に code 側の schema object を更新してから再生成します。

## kaguya / esa1

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| energy_flux | time, energy, look | eV/(cm^2 s sr eV) |  |  | eflux, differential_energy_flux | Differential electron energy flux from KAGUYA PACE ESA1. |
| counts | time, energy, look | count |  |  |  | Raw ESA1 counts. |
| energy | energy | eV |  |  |  | Energy bin center. |
| quality | time |  |  |  | q, quality_flag | Quality flag. |

## kaguya / lmag

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| magnetic_field | time, component | nT |  | MOON_ME | b, lmag | KAGUYA LMAG magnetic field vector in the Moon Mean Earth frame. |

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
