# Schema Reference

This page is generated from SOPRAN runtime schema objects.
Update the schema objects first, then regenerate this page.

## kaguya / esa1

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| energy_flux | time, energy, look | eV/(cm^2 s sr eV) |  |  | eflux, differential_energy_flux | Differential electron energy flux from KAGUYA PACE ESA1. |
| counts | time, energy, look | count |  |  |  | Raw ESA1 counts. |
| energy | energy | eV |  |  |  | Energy bin center. |
| quality | time |  |  |  | q, quality_flag | Quality flag. |

## artemis / fgm

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| magnetic_field | time, component | nT |  |  | b, fgm | ARTEMIS fluxgate magnetic field vector. |

## artemis / esa

| name | dims | units | dtype | frame | aliases | description |
| --- | --- | --- | --- | --- | --- | --- |
| ion_energy_flux | time, energy | eV/(cm^2 s sr eV) |  |  | ion_eflux, esa | ARTEMIS ESA ion differential energy flux. |
