# PACE ESA Mode Policy

When building pitch-angle spectra, SOPRAN screens each PACE record by observation mode: may it be reconstructed from the detector viewing directions?
This page states that rule (`esa_look_quality_v2`) and its basis.

## Conclusion: modes 17/18 are accepted

In the PACE header, `mode` is the command number shared by all sensors, `mode2` the per-sensor sub-data mode, `type` the record format,
and `svs_tbl` the voltage sweep table. **A calibration-named command does not mean every sensor measures a calibration signal.**

| `mode` (hex) | Decimal | Common command | ESA treatment |
|---|---:|---|---|
| `0x11` | 17 | TOFCAL | ESA records EC-N (type 0) angular counts. Accepted |
| `0x12` | 18 | POSCAL | ESA records the same EC-N. Accepted |
| `0x14` / `0x24` | 20 / 36 | 3D MASS Solarwind / Wake | Accepted when the viewing-direction format is supported |
| `0x17` / `0x18` | 23 / 24 | Uncompressed Lunar Ion / ER Lunar Ion | Different commands from decimal 17/18; judged by format |
| `0x29` | 41 | ER Lunar Ion Wake Backup | Only `type=1, svs_tbl=0` is a known invalid combination |

In the official specification for MODE 11/12, the ESA-S1/S2 data structure is `TYPE00_EC_N` in both cases, while the ion side performs TOF and Position checks.
EC-N has 32 energies × 16 × 64 directions and a 16 s accumulation. The former rule `exclude_calibration_v1`,
which also excluded ESA in these modes, was too broad.

The command names `Solarwind` and `Wake` do not mean the spacecraft was actually in the solar wind or the wake.
Classify the environment separately from position, plasma, and upstream observations.

## Rules

`esa_look_quality_v2` judges **whether a pitch-angle spectrum may be built from the detector viewing directions**, not the raw data itself.
The same rule applies to count and energy-flux pitch spectra, S1/S2 combinations, and electron reflectometry inputs.

| Condition | Result and reason code |
|---|---|
| Regular command, ESA type 0/1 | Accepted, including 17/18 |
| `mode=0x29, type=1, svs_tbl=0` | Excluded: `spedas_mode29_type1_ram0_invalid` |
| Common mode with the internal-count `0x80` bit | Excluded: `internal_count_mode` |
| Special or unconfirmed command not in the regular command table | Excluded: `unvalidated_command` (not a confirmed physical invalidity) |
| type 2 | Excluded: `onboard_pitch_sorted_not_supported` (already pitch-sorted on board; reconstruction from viewing directions is not supported) |
| Other types | Excluded: `unsupported_esa_look_type` (type 3 has no matching angle calibration path) |

The 0x29 condition matches the condition where SPEDAS ESA-S1/S2 `get3d` sets `valid=0`. It does not exclude all of 0x29 or all of RAM 0.
SPEDAS also reads types 0/1 and does not support `get3d` for type 2.

Some special commands may operate only the ion side, but their equivalence to regular ESA observations has not been verified, so they are held back.
TOF scans and similar commands are not uniformly treated as "ESA calibration data".

## What this rule does not guarantee

Acceptance does not mean the angle and sensitivity calibration, a finite magnetic field, the attitude, S1/S2 time alignment, or the data support for a fit have been checked.
It does not mean a loss cone is detectable either. Raw zero counts and low counts are not discarded by this rule as long as the exposure is valid.

The bit meanings of `data_quality` are not settled in public documents. Real data contains `0xFFFFFFFF`,
but non-zero values alone are not excluded; the value stays in the `pace_data_quality` coordinate.

## Records and caching

`pace_data_mode`, `pace_data_type`, `pace_submode`, `pace_svs_tbl`, `pace_data_quality`, and `record_duration_seconds`
are kept in the pitch-angle spectra and in the Store. Times where every record was excluded are marked `excluded_by_record_policy`,
distinct from missing data or SPICE failures.

`record_duration_seconds=16` is the accumulation time of one record, which differs from the per-direction
`integration_time_seconds = 16 / sampl_time`. Assignment to time windows and the data required for fits are decided separately by the analysis.

The quality rule is part of the cache identity. Pitch-angle spectra built under different rules are never reused as the same product,
and source files are never modified.

## Sources

- [PACE format description (JAXA DARTS)](https://data.darts.isas.jaxa.jp/pub/pds3/sln-l-pace-3-pbf1-v3.0/20071107/document/PACE_Format_en_V01.pdf)
- [PACE header definition](https://data.darts.isas.jaxa.jp/pub/pds3/sln-l-pace-3-pbf1-v3.0/20071107/software/paceql_outputdata_090805.h)
- SPEDAS [`kgy_esa1_get3d.pro`](https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_esa1_get3d.pro),
  [`kgy_esa2_get3d.pro`](https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_esa2_get3d.pro)
