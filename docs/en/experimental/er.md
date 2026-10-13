# Electron Reflectometry

Electron reflectometry (ER) uses the electron energy–pitch-angle distribution measured on the spacecraft to infer where electrons heading
toward the Moon were turned back (the reflection barrier). SOPRAN's experimental implementation fits the magnetic mirror ratio $R_m$
and the potential difference $\Delta U$ to the boundary of the loss cone in the pitch-angle distribution.

!!! warning "Limits of interpretation"
    A numerically converged fit does not mean the lunar surface field was measured.
    $B_\mathrm{eff} = R_m B_\mathrm{sc}$ (nT) is an effective field describing the reflection boundary, not the crustal field vector.
    $\Delta U$ is "surface potential − spacecraft potential" (eV), not the absolute surface potential.
    Decide whether to adopt a field value from the quality flags and profile intervals described below.

## Choosing a method

There are two estimators: **finite-bin** and **Halekas**.

| Purpose | Method and settings |
|---|---|
| Main analysis | finite-bin with the beta-binomial count likelihood (default); enable angular transport $D_\mathrm{out}$ as needed |
| Deciding whether to adopt a field | `profile_mirror_ratio` intervals and `field_flags` |
| Flux-only inputs, comparison with earlier analyses | finite-bin with `loss="huber"` (0.1 dex) |
| Comparison with a fixed 0.1 reflectance and outer level 1 | Halekas |

Model equations, objectives, and flag definitions are in [ER Model Definitions](er-models.md).

## Estimating from KAGUYA data

```python
import sopran as spn
from sopran.experimental.kaguya.er import KaguyaErInstrument
from sopran.experimental.electron_reflection import (
    FiniteBinFitSettings, FiniteBinObservation, HalekasFitSettings,
)

er = KaguyaErInstrument(spn.Kaguya())
pitch_counts = er.pitch_angle_spectrum(spn.day("2008-04-26"))

# magnetic_field and position are arrays or SopranArrays in the same frame
counts = er.paired_counts(
    pitch_counts, index=0, magnetic_field=magnetic_field, position=position,
)

observation = FiniteBinObservation.from_counts(
    counts, energy_edges_eV=energy_edges, pitch_edges_deg=folded_pitch_edges,
)
result = er.effective_field.fit_finite_bin(
    observation, settings=FiniteBinFitSettings(angular_transport="out"),
)
profile = er.effective_field.profile_finite_bin(observation, result)

comparison = er.effective_field.fit_halekas(counts, settings=HalekasFitSettings())
```

### Preparing inputs

`KaguyaErInstrument` shares ESA loading and calibration, LMAG loading with margins, and SPICE setup between its two loading entry points.
`pitch_angle_spectra(..., align=False)` returns pitch-angle spectra that keep each sensor's own times.

`paired_counts` builds an `ElectronReflectionCounts` (energy × folded pitch angle) that pairs 0–90° with 90–180° for one sample.

- The hemisphere of electrons coming back from the surface (after reflection) is "affected", and the hemisphere of electrons heading toward the surface (incident) is "reference".
  When +B points away from the Moon, low pitch angles are affected; otherwise high pitch angles are.
  `affected_side="low"` or `"high"` sets it explicitly.
- Pass the calibrated, actual bin edges to finite-bin as `energy_edges_eV` and `pitch_edges_deg`; edges are never inferred from centers.
- Exposure is taken from an explicit value, then the spectrum's coordinates, then equal exposure. An explicit value must broadcast
  to energy × pitch angle of the selected sample. Assuming equal exposure is recorded in the input metadata.

Retrieval and calibration use the `kaguya` extra, estimation `experimental`, and plotting `viz`.

## Reading results

```python
result.effective_field_nT       # B_eff
result.field_flags              # reasons the field is not constrained
result.field_unconstrained      # True when any field_flags is set
profile.interval_nT             # 95% interval from re-optimizing with R_m fixed
```

No flags does not mean the field is uniquely determined. Use the profile interval to decide, and check individually any result whose interval
reaches the search range (`interval_bounded=False`) or where a better solution was found (`improved_minimum=True`).
In windows where the count and Huber losses land in different minima, the count-loss profile interval may contain both.
Judge identifiability by the interval width, not by the difference between point estimates.

## Saving results

Estimates come back as typed dataclasses per method and are not saved to the Store automatically.
Save them yourself together with the settings, inputs, masks, bins, and a code hash.
For processing the full mission with fixed settings and code, see [ER Full-Period Batch](er-batch.md).

## Module layout

| Location | Role |
|---|---|
| `electron_reflection/common.py` | Shared input type `ElectronReflectionCounts`, exposure validation, boundary formula `mirror_boundary_sin2` |
| `electron_reflection/finite_bin.py` | finite-bin model, losses, loss-cone test, profiles |
| `electron_reflection/halekas.py` | Halekas model |
| `experimental/kaguya/er.py` | ESA1/ESA2, LMAG, and SPICE preparation, pitch-angle spectra, `paired_counts`, estimator calls |
| `experimental/kaguya/er_batch.py` | Full-period daily sharding, frozen settings, parallel fits, Store registration |
| `crates/sopran-native/src/finite_bin.rs` | finite-bin response, $D_\mathrm{out}$, losses, and optimization (Rust) |

## Retired estimators

The paired-count beta-binomial estimator (its count likelihood merged into finite-bin `loss` on 2026-10-10), binary surface, joint,
global-joint, incident, and integrated estimators, and their dedicated warm starts, likelihood scans, time series, catalogs, schemas, and evaluation helpers, have been removed.
Use `fit_finite_bin` and `fit_halekas` instead of the old `fit`, `fit_joint`, `fit_global_joint`, `fit_timeseries`, and `build`.
The former `sopran-er-finite-bin` JSONL CLI is also retired in favor of the PyO3 API. There are no compatibility aliases or fallbacks to old estimators.
Previously saved data remains in the Store and can be read as regular datasets.

## Validation

| Target | Tests |
|---|---|
| finite-bin, $D_\mathrm{out}$, losses (checked against scipy binomial and beta-binomial), count selection, loss-cone test, offset and prior, profile intervals, missing bins, fixed $B_\mathrm{eff}$ | `tests/test_er_finite_bin.py` |
| Halekas hard/probit recovery, $R_m<1$, search agreement | `test_electron_reflection.py`, `test_electron_reflection_subunity.py`, `test_halekas_search.py` |
| KAGUYA inputs, exposure, geometry, loading | `test_kaguya_er.py`, `test_kaguya_er_geometry.py`, `test_kaguya_pace.py` |
| The regular API does not load experiments | `test_experimental_boundary.py` |
