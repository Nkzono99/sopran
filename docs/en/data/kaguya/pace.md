# PACE (Electrons And Ions)

PACE (Plasma energy Angle and Composition Experiment) is the set of four particle analyzers on KAGUYA.
SOPRAN reads the public PBF1 (v3.0) files and uses the same variable names for all four.

| Entry point | Sensor | Particles |
|---|---|---|
| `kg.esa1` | ESA-S1 | Electrons |
| `kg.esa2` | ESA-S2 | Electrons |
| `kg.ima` | IMA | Ions (mass analysis) |
| `kg.iea` | IEA | Ions |

## Variables

| Variable | Dimensions | Units | Meaning |
|---|---|---|---|
| `counts` | `time, energy, look` | count | Raw counts |
| `energy_flux` | `time, energy, look` | eV/(cm^2 s sr eV) | Differential energy flux computed from counts with the calibration tables |
| `energy` | `energy` | channel / eV | Energy channel index when uncalibrated, energy center in eV when calibrated |
| `quality` | `time` | flag | Record quality flag |

`look` is the index of a detector viewing direction, not the direction itself. Directions (polar and azimuth angles)
require the calibration tables; the pitch-angle spectra below use them.
`energy_flux` has the aliases `eflux` and `differential_energy_flux`.

## Loading

```python
kg = spn.kaguya
time = spn.day("2008-01-01")

flux = kg.esa1.energy_flux.load(time)       # SopranArray
esa1 = kg.esa1.load(time)                   # instrument-level result

esa1.counts, esa1.energy_flux, esa1.quality
esa1.to_xarray()                            # xarray.Dataset with all variables
esa1.to_polars("counts", reduce_look="sum") # table summed over look
esa1.files                                  # source files
esa1.pace                                   # decoded headers and records
```

To decode source files directly, use `sopran.missions.kaguya.read_pace_pbf(files)`.
Decoding runs in the Rust extension and falls back to the Python reference implementation when the extension is missing (`backend="auto"`).

## Energy flux calibration

`energy_flux` is computed from counts as

$$
\mathrm{energy\_flux} = \frac{\mathrm{counts}}{t_\mathrm{integ}\; G\; \varepsilon}
$$

where $t_\mathrm{integ}$ is the integration time, $G$ the g-factor from the PACE INFO table, and $\varepsilon$ the detection efficiency.
The default $\varepsilon = 0.6$ is the uniform value used by SPEDAS `kgy_esa1_get3d.pro` and `kgy_esa2_get3d.pro`.
For another value, call `kg.esa1.load(time).to_energy_flux(efficiency=...)`.

The calibration tables (INFO and FOV) load automatically. They come from the same distribution as SPEDAS `kgy_read_inf.pro` and `kgy_read_fov.pro`,
which is served over HTTP only. Retrieved tables are recorded in the Store's source-file registry with their URL and sha256.
Without the tables, loading `energy_flux` raises; uncalibrated values are never returned under that name.
After calibration the `energy` coordinate holds energy centers in eV, and the original channel index stays in the `energy_channel` coordinate.

```python
cal = kg.esa1.load_calibration(download="never")   # read the tables explicitly
esa1 = kg.esa1.load(time, calibration=cal)
```

All four sensors use the same formula and table handling. Regression tests cover ESA1;
the flux of ESA2, IMA, and IEA has not been compared numerically with SPEDAS yet.

## Missing value 65535

PBF1 counts are 16-bit unsigned integers. Following the SPEDAS PACE readers (`kgy_read_pbf.pro`, `kgy_esa1_get3d.pro`),
SOPRAN converts the maximum value `65535` to NaN as missing.
The PDS3 labels we checked declare no missing value such as `MISSING_CONSTANT`. Zero counts stay zero.

## Pitch-angle spectra

`pitch_angle_spectrum()` turns `look` back into directions with the calibration tables and bins by the angle to the magnetic field,
producing a `time × energy × pitch_angle` array.

```python
from sopran.missions.kaguya import selene_spice_kernels

b = kg.lmag.magnetic_field.load(time)                         # MOON_ME
frames = spn.FrameContext(spice_kernels=selene_spice_kernels(kg.store, time))   # fetch Moon and attitude kernels

pas = kg.esa1.energy_flux.pitch_angle_spectrum(
    time,
    magnetic_field=b,
    frame_context=frames,             # rotate the MOON_ME field into the PACE viewing frame
    pitch_bins="native",
    cache="use",
)
pas.plot()                                          # pitch vs time and energy vs time
pas.energy_spectrogram(pitch=(0.0, 30.0), log_color=True)
```

A fixed vector in the viewing frame, such as `magnetic_field=[1.0, 0.0, 0.0]`, works without kernels for quick tests.

| Argument | Meaning |
|---|---|
| `magnetic_field` | Required. A vector in the viewing frame, or a `SopranArray` that carries its frame |
| `look_frame`, `magnetic_frame` | Frames of the viewing directions (default `SELENE_M_SPACECRAFT`) and the field. When they differ, pass a `FrameContext` as `frame_context` |
| `pitch_bins` | `"native"` (16 bins for 4×16-direction records, 32 for 16×64; the larger on mixed days), a bin count, or bin edges |
| `min_look_bins` | Minimum number of viewing directions per pitch-angle bin |
| `count_correction` | `"none"` (default), `"event"`, `"trash"`, `"event_trash"`; corresponds to SPEDAS `/cntcorr` |
| `cache` | With `"use"`, results with the same arguments are saved in the `features` layer and reused |

`count_correction="trash"` redistributes discarded counts (trash counters) over azimuth, and `"event"` scales adjacent energy pairs
to the event counter. The correction is kept as a separate multiplier, so raw counts remain integers.

Results carry the per-record exposure and the coordinates `pace_data_mode`, `pace_data_type`, `pace_submode`, `pace_svs_tbl`,
`pace_data_quality`, and `record_duration_seconds`. Whether a record may be used for pitch angles is decided from the observation mode;
the rules are in [PACE ESA Mode Policy](esa-mode-policy.md).

## Saving to Parquet

```python
record = (
    kg.esa1.energy_flux.pipeline(spn.period("2008-01-01", "2008-01-03"))
    .calibrate(calibration="auto")
    .write("kaguya.esa1.energy_flux", layer="normalized", partition="day")
    .run()
)
```

To save counts, start from `kg.esa1.counts.pipeline(...)` and drop `calibrate`.
Running pipelines is covered in [Batch Pipelines](../../guide/pipeline.md).

## Limitations

- Saved Parquet does not yet include `look` directions (polar and azimuth angles) or energy coordinate metadata.
- ESA2, IMA, and IEA energy flux has not been compared numerically with SPEDAS.
- The bit meanings of `data_quality` are not settled in public documents, so the value is kept as is in `pace_data_quality`.

## Sources

- [PACE format description (JAXA DARTS)](https://data.darts.isas.jaxa.jp/pub/pds3/sln-l-pace-3-pbf1-v3.0/20071107/document/PACE_Format_en_V01.pdf)
- [SPEDAS `kgy_read_pbf.pro`](https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_read_pbf.pro),
  [`kgy_esa1_get3d.pro`](https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_esa1_get3d.pro)
