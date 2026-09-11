# KAGUYA LRS/WFC Wave-Event Extraction

> Experimental API. No backward-compatibility or physical-identification guarantee.

This document defines the `KAGUYA_WFC_V1` preset used to extract **candidate
intervals** from KAGUYA LRS/WFC spectra, together with its validation and
aggregation boundaries. Its labels are automated candidates, not confirmed
physical phenomena.

## Scope And Preset

The expected input is WFC-H Ex/Ey power spectral density. Times are UTC and
intervals are half-open `[start, stop)`. The standard window is 120 seconds
with a 60-second step.

| Purpose | Frequency band (kHz) | Intent |
| --- | ---: | --- |
| `low_broadband` | 0.1--10 | Low-frequency broadband enhancement |
| `low_fpe` | 2--30 | Low-frequency peak candidate; do not always mask 30 kHz |
| `ridge` | 10--100 | Ridges, drift, and shifts |
| `radio` | 100--500 | Broadband radio candidates |
| `high` | 500--1000 | High-frequency diagnostics |

Fixed lines are not removed unconditionally from every band.

| Center | Half width | Use | Treatment |
| ---: | ---: | --- | --- |
| 30 kHz | 2 kHz | `ridge` / `tracker` | Mask from ridge scores and tracking paths, but not every standalone `low_fpe` peak |
| 200 kHz | 12 kHz | `radio` | Mask from broad radio scores and retain as a separate RFI diagnostic |
| 957 kHz | 3 kHz | `high` | Mask from high-band derived features and clustering, but retain in raw summaries and RFI diagnostics |
| 30/200/957 kHz | 3 kHz each | `clustering` | Exclude or separate them so raw peak locations do not dominate clusters |

The legacy 30 kHz tracker mask is +/-2 kHz, while common raw-spectrum
clustering uses +/-3 kHz. They must not silently share one `FixedLine` object.
The 200 and 957 kHz lines are separated from physical-candidate scores rather
than making their data disappear. In particular, a 957 kHz maximum must not be
reported as the representative frequency of an event that occurs in the low
kHz range. Every shard stores the preset and feature definitions together with
`feature_spec_hash`.

## Quality Mask

`build_kaguya_wfc_quality_mask` returns per-sample `sample_valid`, per-record
`record_valid`, and state-transition warnings.

- NaN, infinity, and CDF pad values (`254`, `65534`) are hard-invalid spectral samples.
- NaN or pad values in `Mode`, `Gain`, `Fband`, and `PostGap` make a record hard invalid.
- Finite state values and their transitions produce warnings; they do not alone discard observations.
- A record with only some missing frequency bins remains usable through `sample_valid` and `finite_fraction`. A record with every bin missing is hard invalid.
- Windows containing warnings remain available to the review queue, with warning counts retained in detector metadata.

Raw `Mode` values may be passed directly. With decoded flags, evaluate `xymode`
and `omode` as separate quality series and pass `fband` through its dedicated
argument. Do not interpolate in ways that change the meaning of instrument
states.

## Strict And Review Gold Intervals

`tests/fixtures/kaguya_wfc_wave_gold.json` is a small regression anchor set, not a
complete event catalog.

- `strict_intervals` are relatively clear in quality and spectral shape and should remain candidates after preset changes.
- `review_intervals` require human review of transitions, gaps, saturation, fixed lines, or solar-radio context. Detection alone does not determine test success.
- Candidate classes in the gold data are not scientific identifications. Review plots and features before updating the manifest after threshold or background changes.
- Short spikes may be suppressed by a 120-second median. Evaluate leakage into
  physical labels separately from short-timescale detection performance.

## Coverage-Normalized Rates

The rate denominator is **eligible exposure**, not calendar time or file count.
For each detector, component, frequency band, and preset hash, accumulate only
times where coverage, `record_valid`, and required frequency bins permit a
decision.

With 120-second windows stepped every 60 seconds, summing window durations
double-counts overlap. Assign one step of time to valid window centers and clip
at coverage boundaries, or compute the union of valid intervals, and store the
result as `exposure_seconds`. `finite_sample_count` depends on sample cadence
and frequency-bin count and is not an exposure substitute.

```text
event_rate_per_hour = event_count / (exposure_seconds / 3600)
```

When `exposure_seconds == 0`, the result is unobserved, not zero events at zero
rate. Daily shards store event count, eligible/invalid/warning seconds, source
product, component, detector name, and preset/feature hashes. Final catalogs
deduplicate connected events crossing day boundaries by event ID and half-open
interval.

## WFC-H And WFC-L Boundary

WFC-H spectra support labels such as `BBN/ESW candidate`, broadband
enhancement, ridge, and radio candidate. Confirming an ESW requires a WFC-L
waveform showing a bipolar pulse and its temporal shape. Do not label a WFC-H
broadband spectrum alone as `ESW confirmed`.

WFC-H and WFC-L retain separate readers, source products, coverage, and quality
conditions. A WFC-H candidate may be stored when WFC-L is unavailable, but its
verification state remains `unverified`. Later matching uses a shared event ID
or overlapping UTC intervals; absence of WFC-L coverage is not a negative
example.

The public `sln-l-lrs-4-wfc-spectrum-v1.0` CDF product and the SPEDAS
`idl/projects/kaguya/lrs/kgy_lrs_load.pro` loader cover WFC-H spectra. WFC-L is
a 10 Hz--100 kHz waveform receiver and is distinct from both that public
spectrum product and the subsurface-sounding `sln-l-lrs-2-sndr-waveform-*`
products. The current reader does not acquire natural-wave WFC-L waveforms.
Do not register guessed paths in the dataset registry.

`PDC-TI` is not UTC. It is a 48-bit spacecraft time counter stored as high,
middle, and low `uint16` words. The public API preserves both the exactly
representable scalar count and the three raw words, while CDF `Epoch` supplies
UTC. Do not convert the counter to time without a TI--UT correlation table.
CDF `FILLVAL=0` is distinct from sparse default pads: WFC support variables
treat UINT1 value 254 as missing, and PDC-TI treats `[65534, 0, 65534]` as
missing.

## Shards And Clustering

Initial shards retain candidate intervals, background residuals, band
statistics, ridge slope and continuity, fixed-line diagnostics, quality
warnings, coverage, and exposure. Clustering consumes this reproducible feature
shard and does not call mission-specific readers or raw CDF files directly.
Raw 30/200/957 kHz peaks are removed or separated into dedicated RFI features,
and shards with different preset or feature hashes are never mixed implicitly.
`fit_background_residual_clustering(result.windows.normalized_z)` returns
exploratory integer IDs scoped by `cluster_run_id`; these IDs are not physical
phenomena or noise labels.

## References

- Y. Kasahara et al., "Plasma wave observation using waveform capture in the
  Lunar Radar Sounder on board the SELENE spacecraft," *Earth, Planets and
  Space* 60, 341--351 (2008), DOI
  [10.1186/BF03352799](https://doi.org/10.1186/BF03352799). See the WFC-H/WFC-L
  instrument boundary and the 12-digit hexadecimal TI-counter description on
  p. 350.
- NASA/SPDF, [CDF User's Guide](https://spdf.gsfc.nasa.gov/pub/software/cdf/doc/cdf_User_Guide.pdf),
  for the CDF_UINT1/CDF_UINT2 default pad values.
- [DARTS KAGUYA archive](https://darts.isas.jaxa.jp/en/missions/kaguya), used
  to verify the public product boundary.
