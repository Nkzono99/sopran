# Wave Candidates

This experiment extracts **candidate intervals** of wave events from KAGUYA LRS/WFC spectra.
It covers the detection preset `KAGUYA_WFC_V1`, the quality mask, the validation intervals, and how to define the denominator of occurrence rates.
Labels obtained here are automatic detection candidates, not confirmed physical phenomena.

## Minimal example

```python
import sopran as spn
from sopran.experimental.waves import detect_wave_candidates
from sopran.experimental.kaguya.waves import KAGUYA_WFC_V1, build_kaguya_wfc_quality_mask

time = spn.day("2008-01-10")
data = spn.Kaguya().lrs.load(time, kind="WFC")
spectrum = data.wfc_ey_power_spectral_density.to_xarray()
quality = build_kaguya_wfc_quality_mask(
    spectrum.values,
    mode=data.wfc_mode.to_xarray().values,
    gain=data.wfc_gain.to_xarray().values,
    fband=data.wfc_fband.to_xarray().values,
    postgap=data.wfc_postgap.to_xarray().values,
)
result = detect_wave_candidates(
    spectrum.time.values,
    spectrum.frequency.values,
    spectrum.values,
    input_scale="linear_power",
    config=KAGUYA_WFC_V1,
    valid_time=quality.valid_time,
    component="Ey",
    source_dataset="kaguya.lrs.wfc_ey_power_spectral_density",
)

window_features = result.features_to_polars()
events = result.events_to_polars(mission="kaguya", instrument="lrs_wfc_h")
```

`confidence` is currently an uncalibrated heuristic built from thresholds. Use the raw `score` for comparison and ranking, and do not read it as a probability.

## Preset `KAGUYA_WFC_V1`

The input is the WFC-H Ex/Ey power spectral density. Times are UTC and intervals are half-open `[start, stop)`.
Windows are 120 s long with a 60 s step. Features are computed in these bands:

| Use | Band (kHz) | Intent |
|---|---:|---|
| `low_broadband` | 0.1–10 | Low-frequency broadband enhancement |
| `low_fpe` | 2–30 | Low-frequency peak candidates (the 30 kHz line is not masked uniformly) |
| `ridge` | 10–100 | Ridges, drift, frequency shifts |
| `radio` | 100–500 | Broadband radio candidates |
| `high` | 500–1000 | High-frequency diagnostics |

### Fixed lines

Instrumental fixed-frequency lines are not removed from every band unconditionally. Each use treats them as follows.

| Center | Half width | Use | Treatment |
|---:|---:|---|---|
| 30 kHz | 2 kHz | `ridge`, tracking | Masked from ridge scores and tracking paths; not applied uniformly to single-peak decisions in `low_fpe` |
| 200 kHz | 12 kHz | `radio` | Masked from the broadband radio score; kept for separate radio-frequency interference (RFI) diagnostics |
| 957 kHz | 3 kHz | `high` | Masked from high-band derived features and cluster inputs; kept in raw summaries and RFI diagnostics |
| 30/200/957 kHz | 3 kHz each | Clustering | Excluded or turned into separate features so raw peak positions do not dominate clusters |

The earlier tracker masked 30 kHz by ±2 kHz and raw-spectrum clustering uses a common ±3 kHz mask; the same `FixedLine` is not reused.
200 kHz and 957 kHz remain in detection, with physical candidate scores and fixed-line diagnostics kept separate.
In particular, never use the 957 kHz maximum as the representative frequency of an event that occurred at low frequencies.
The preset and feature definitions are stored in shards together with `feature_spec_hash`.

## Quality mask

`build_kaguya_wfc_quality_mask` returns per-value `sample_valid`, per-time `record_valid`, and warnings for state changes.

- Spectral values that are NaN, inf, or CDF pad values (`254`, `65534`) are invalid.
- Times where `Mode`, `Gain`, `Fband`, or `PostGap` is NaN or a pad value are invalid.
- Finite `Mode`, `Gain`, `Fband`, or `PostGap` values, or changes in them, never discard observations on their own; they only produce warnings,
  because stable non-default modes are scientifically usable.
- Times where only some frequency bins are missing keep `record_valid` so the usable bins remain, and report the gap through `sample_valid` and
  `finite_fraction`. Times where every bin is missing are invalid.
- Windows with warnings are not rejected automatically; the detector metadata keeps warning counts so people can review them.

`Mode` may be passed as raw values. When using decoded flags, evaluate `xymode` and `omode` as separate quality series
and pass `fband` to its dedicated argument. No interpolation that changes the meaning of a state is applied.

## Validation intervals

`tests/fixtures/kaguya_wfc_wave_gold.json` is a small anchor set for catching detector regressions. It cannot serve as a complete event catalog.

- `strict_intervals` have relatively clear quality and spectral shape, and candidates are expected to survive preset changes.
- `review_intervals` are for people to recheck context such as state changes, data gaps, saturation, fixed lines, and solar radio bursts.
  Tests do not fail on detection alone there.
- The "candidate type" given to intervals is not a scientific identification. When thresholds or background estimates change, review figures and features before updating.
- Short spikes may be suppressed by the 120 s median. Misclassification into physical candidates by the main detector and the performance of short-duration detectors are evaluated separately.

## Rate denominators

The denominator of occurrence rates is the **eligible exposure**: the time the detector could actually decide, not calendar time or file counts.
For each detector, component, band, and preset hash, accumulate only the time that has data, is `record_valid`, and has the required frequency bins.

With 120 s windows stepped by 60 s, summing window lengths double-counts overlaps. The basic implementation assigns one step of time to each valid window center,
and stores as `exposure_seconds` either that non-overlapping time clipped at data boundaries or the union of valid time intervals.
`finite_sample_count` depends on the sampling period and the number of frequency bins, so it is not used as exposure.

```text
event_rate_per_hour = event_count / (exposure_seconds / 3600)
```

`exposure_seconds == 0` means "not observed", not zero events or a zero rate. Daily shards store, besides event counts, the eligible, invalid,
and warning seconds, the source product, component, detector name, and preset and feature hashes. To avoid double-counting events that span day boundaries,
the final catalog deduplicates by event ID and half-open interval. The Store event catalog's `rates()` follows the same approach
([Storing Data](../guide/store.md#event-catalogs)).

## WFC-H and WFC-L

WFC-H spectra support statements up to `BBN/ESW candidate`, broadband enhancement, ridges, and radio candidates.
Confirming electrostatic solitary waves (ESW) requires checking bipolar pulses and the time waveform in WFC-L.
Never mark `ESW confirmed` based only on WFC-H broadband spectra.

WFC-H and WFC-L have separate readers, source products, data availability, and quality conditions. WFC-H candidates can be saved without WFC-L,
but their confirmation status stays `unverified`. Later matching uses a common event ID or overlapping UTC intervals, and times without WFC-L are not treated as negatives.

The public CDF `sln-l-lrs-4-wfc-spectrum-v1.0` and SPEDAS `kgy_lrs_load.pro` cover WFC-H spectra.
WFC-L is a 10 Hz–100 kHz waveform receiver, a different product from these public spectra and from the subsurface sounder `sln-l-lrs-2-sndr-waveform-*`.
The current reader does not support WFC-L waveforms, and no guessed paths are registered as datasets.

## Shards and clustering

The first shard stores not only candidate intervals but also background differences, per-band statistics, ridge slopes and continuity, fixed-line diagnostics,
quality warnings, and data availability and exposure. Clustering takes these reproducible feature shards as input and never calls mission-specific readers or raw CDF directly.
Raw peaks at 30/200/957 kHz are excluded or separated into dedicated RFI features, and shards with different preset or feature hashes are never mixed silently.

Exploratory clusters come from `fit_background_residual_clustering(result.windows.normalized_z)`.
The returned integer IDs are local to each fit, so always store them with `cluster_run_id`.
Clusters are never promoted automatically to phenomenon names or noise decisions; only interpreted labels are written to the event catalog as a separate detector version.

## References

- Y. Kasahara et al., "Plasma wave observation using waveform capture in the Lunar Radar Sounder on board the SELENE spacecraft,"
  *Earth, Planets and Space* 60, 341–351 (2008). [doi:10.1186/BF03352799](https://doi.org/10.1186/BF03352799).
  Used for the WFC-H/WFC-L instrument boundary and the 12-digit hexadecimal TI counter description on p. 350.
- NASA/SPDF, [CDF User's Guide](https://spdf.gsfc.nasa.gov/pub/software/cdf/doc/cdf_User_Guide.pdf). Used for the default pad values of CDF_UINT1 and CDF_UINT2.
- [DARTS KAGUYA archive](https://darts.isas.jaxa.jp/en/missions/kaguya). Used to confirm public product boundaries.
