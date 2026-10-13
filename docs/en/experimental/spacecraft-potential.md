# Spacecraft Potential Proxies And PACE Low-Level Tables

`sopran.experimental.kaguya.spacecraft_potential` builds spacecraft-potential proxies $V_\mathrm{sc}$ from steps in PACE energy
spectra and matches them to event times. It does not solve a charging model. The values are correction candidates with a
width, not measured potentials. In the May 2026 lunarsat trials the ESA steps were adopted, while the ion proxies kept a
systematic offset of about $-57\,\mathrm{V}$ against the ESA proxies and remained diagnostics. Precision is set by the ESA
energy resolution and the thresholds; there is no independent full-period validation.

## Adoption rules

| Proxy | Condition | Value | Enabled by |
|---|---|---|---|
| ESA `falling` step | Day side (SZA < 80°) | Spacecraft photoelectron boundary, $V_\mathrm{sc}=+E_\mathrm{edge}$ | `use_dayside_photoelectron` (default True) |
| ESA `rising` step | Night side (SZA ≥ 120°) | Cold-electron cutoff by a negative spacecraft, $V_\mathrm{sc}=-E_\mathrm{edge}$ | always |
| IMA/IEA low-energy ion peak | Night side | $V_\mathrm{sc}=-E_\mathrm{peak}$ | `use_ion_proxies` (default False, diagnostic) |

The step is the adjacent pair with the largest difference of the 3-point-median-smoothed $\log_{10}$ signal inside
`edge_min_eV`–`edge_max_eV` (default 5–350 eV); `cutoff_energy_eV` is where the profile crosses the midpoint between its
20th and 80th percentiles. `quality` requires `quality_score` ≥ 1, built from the step height (≥ 0.25 dex), the profile
range (≥ 0.35 dex), the number of bins and the low-energy count fraction.

## Usage

```python
import sopran as spn
from sopran.experimental.kaguya import spacecraft_potential as sp
from sopran.missions.kaguya.geometry import lmag_sza

kg = spn.Kaguya()
time = spn.day("2008-04-02")
esa1 = kg.esa1.load(time, calibration=kg.esa1.load_calibration())
times, energy, counts, eflux = sp.energy_spectra(esa1.to_xarray())   # look-summed spectra
features = sp.cutoff_features(energy, counts, eflux, settings=sp.CutoffSettings())
sza = lmag_sza(kg.lmag.load(time)).to_xarray().interp(time=times.astype("datetime64[s]")).values
cutoff = sp.cutoff_table(times, features, sensor="esa1", sza_deg=sza)
proxies = sp.proxy_table(cutoff)

events = ...  # polars.DataFrame with time_unix and sza_deg (for example ER windows)
estimate = sp.estimate_potential(events, proxies, settings=sp.PotentialEstimateSettings())
estimate.select("time_unix", "vsc_est_V", "vsc_sigma_V", "vsc_method")
```

`estimate_potential` picks the first available value in this order and records it in `vsc_method`:

1. `direct_proxy`: a proxy of the same side (day/night) within `direct_tolerance_seconds` (default 60 s)
2. `time_smoothed_proxy`: the rolling median of adopted proxies over `smooth_window_seconds` (default 1800 s), within `gapfill_max_gap_seconds`
3. `condition_prior`: the median of the same side and SZA bin (`sza_bin_deg`, at least 3 rows)
4. `global_prior`: `global_prior_V` (default 0 V) with `global_sigma_V` (default 60 V)

When the value enters an ER boundary model, the electron energy correction is $E-U_\mathrm{sc}$. The sign passed as
`spacecraft_potential_eV` (for example to `FiniteBinObservation`) is the physical spacecraft potential $V_\mathrm{sc}$ of this table.

## PACE low-level tables

`sopran.experimental.kaguya.pace_lowlevel` turns decoded PBF1 records into tables close to the public files: the integer
header fields (`headers`), per-record sums and maxima of `cnt`, `event` and `trash` with the number of fill cells (65535)
(`counts`), and for IMA the `0x40` time-of-flight histogram summed over records and the four leading sectors as
`(energy_index, tof_index, counts)` (`tof`).

```python
from sopran.experimental.kaguya.pace_lowlevel import lowlevel_summary

tables = lowlevel_summary(kg.ima.load(time).pace)
tables["headers"], tables["counts"], tables["tof"]
```

## Limits

- Steps are searched record by record; continuity between neighbouring records is not used. The `quality` thresholds are
  empirical values tuned for night-side cutoffs.
- The day-side photoelectron boundary is not the lunar surface potential, which moves with solar activity and the ambient plasma (Kato et al.).
- Do not adopt the ion proxies until they are validated against the expected solar-wind ion energy and coincident cold ions and electron beams.
- Sources: Saito et al. (2010, 2013), Halekas et al. (2008), lunarsat `working/kgy-er/notes/kgy-er-spacecraft-potential-strategy-2026-05-02.md`.
