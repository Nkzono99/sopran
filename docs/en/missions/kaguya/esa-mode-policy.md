# ESA Modes and Input Quality

PACE `mode` is a shared command number; `mode2` is the sensor submode, `type`
the record format, and `svs_tbl` the sweep RAM table. A calibration command
for the ion sensor does not necessarily make ESA electron measurements invalid.

## Do Not Reject Decimal 17 and 18 Together

| Mode | Decimal | Command | ESA treatment |
|---|---:|---|---|
| `0x11` | 17 | TOFCAL | ESA EC-N, type-0 directional counts; eligible |
| `0x12` | 18 | POSCAL | ESA EC-N; eligible |
| `0x14` / `0x24` | 20 / 36 | 3D MASS Solarwind / Wake | Eligible with supported look format |
| `0x17` / `0x18` | 23 / 24 | Lunar Ion / ER Lunar Ion | Different from decimal 17/18; inspect format |
| `0x29` | 41 | ER Lunar Ion Wake Backup | Reject the known `type=1, svs_tbl=0` combination |

The PACE format specifies `TYPE00_EC_N` for both ESAs in commands 11/12 while
the ion sensor performs the check. EC-N has 32 energies, 16 by 64 directions,
and a 16-second record duration. Command names do not classify the actual
solar-wind/wake environment.
Sources: [PACE format](https://data.darts.isas.jaxa.jp/pub/pds3/sln-l-pace-3-pbf1-v3.0/20071107/document/PACE_Format_en_V01.pdf),
[header definitions](https://data.darts.isas.jaxa.jp/pub/pds3/sln-l-pace-3-pbf1-v3.0/20071107/software/paceql_outputdata_090805.h).

## Pitch-Construction Policy

`esa_look_quality_v2` selects records usable for detector-look-based pitch
construction; it does not delete raw observations.

| Condition | Treatment |
|---|---|
| Standard command, ESA type 0/1 | Eligible, including commands 17/18 |
| `mode=0x29, type=1, svs_tbl=0` | `spedas_mode29_type1_ram0_invalid` |
| Shared mode has internal-count bit `0x80` | `internal_count_mode` |
| Special/unvalidated command | `unvalidated_command`, not proof of physical invalidity |
| Type 2 | `onboard_pitch_sorted_not_supported` |
| Other ESA type | `unsupported_esa_look_type` |

The mode-29 condition follows the SPEDAS ESA
[S1](https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_esa1_get3d.pro)
and [S2](https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_esa2_get3d.pro)
loaders. It does not reject all mode-29 or all RAM-0 records.
Unresolved `data_quality` bits are retained rather than rejecting every nonzero
value. Calibration, finite field/attitude, timing and downstream support still
need checking. Zero/low counts are not rejected by mode alone.

## Metadata and Cache

Pitch products retain `pace_data_mode`, `pace_data_type`, `pace_submode`,
`pace_svs_tbl`, `pace_data_quality` and `record_duration_seconds`.
`excluded_by_record_policy` is distinct from missing input or SPICE failure.

A 16-second record duration differs from each look's integration time,
`integration_time_seconds=16/sampl_time`. Window assignment and fit support
belong to the analysis settings. Automatic and explicit variant checks include
the quality policy, so incompatible pitch caches are not reused. Raw files stay
unchanged.
