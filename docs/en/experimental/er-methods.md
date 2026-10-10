# ER methods and code inventory

The retained estimators are **finite-bin and Halekas**. Use finite-bin with the
default beta-binomial count likelihood, optionally enabling D_out, and adopt
fields with `profile_mirror_ratio` intervals and `field_flags`. Use Huber 0.1 dex
for flux-only input or earlier-run comparisons and Halekas for fixed-backscatter comparisons.

| Entry point | Input and objective | Model and search |
|---|---|---|
| `fit_finite_bin_distribution` | Paired-count beta-binomial (default) or binomial likelihood; log10(a/r) Huber or squared loss | Finite bins, free bottom/scale, four beam shapes with continuous amplitude, optional D_out, loss-cone test; native DE + multi-start bounded Nelder–Mead |
| `profile_mirror_ratio` | A fitted observation | Fixed-Rm refits; likelihood interval for count losses |
| `fit_halekas_distribution` | Exposure-corrected paired-count natural-log ratio; squared loss | Fixed backscatter (default 0.1), outside 1; hard grid/refinement or probit width + L-BFGS-B |

Transport is selected with `FiniteBinFitSettings(angular_transport="out" / "none")`.
Probit edge width and D_out angular transport have distinct meanings.
Match units and masks before comparing RMSE; Gaussian BIC and Huber cost are
not interchangeable.

## Shared implementation

| Location | Responsibility |
|---|---|
| `electron_reflection/common.py` | `ElectronReflectionCounts`, exposure validation, `mirror_boundary_sin2` |
| `electron_reflection/__init__.py` | Explicit exports for the two estimators and shared input |
| `experimental/kaguya/er.py` | Shared ESA/LMAG/SPICE preparation, pitch readers, `paired_counts`, explicit fit methods |
| `crates/sopran-native/src/finite_bin.rs` | Finite-bin response, D_out, losses, beam amplitude, loss-cone test and optimization at the PyO3 problem boundary |

Prepare one sample with `KaguyaErInstrument.paired_counts(..., index=...)`.
Use `er.effective_field.fit_finite_bin(...)` or `fit_halekas(...)` explicitly.
Results are typed dataclasses; callers save settings and provenance.
Readers, calibration, pitch generation, magnetic interpolation and Store
stay in the standard API.

## Removed implementations

The former paired beta-binomial estimator (its count likelihood moved into the
finite-bin `loss` on 2026-10-10), binary-surface, joint, global-joint and incident/integrated
estimators and their warm starts, likelihood scans and beam diagnostics are removed.
Their dedicated timeseries, catalog, schema and research evaluation helpers are
removed as well. Use the standard `spn.omni` reader for OMNI.

The former `sopran-er-finite-bin` JSONL CLI is retired in favor of the finite-bin
PyO3 API. Historical research scripts and products remain as run records.
Scripts using removed APIs require saved source or explicit migration.
No compatibility aliases or fallback estimators are provided.

## Verification

- Finite-bin/D_out/losses (checked against scipy binomial and beta-binomial)/count
  selection/loss-cone test/offset and prior/profile interval/missing input/fixed field:
  `test_er_finite_bin.py`.
- Halekas recovery, sub-unity ratios and search oracle: `test_electron_reflection.py`,
  `test_electron_reflection_subunity.py`, `test_halekas_search.py`.
- KAGUYA pairing, exposure, geometry and readers: `test_kaguya_er.py`,
  `test_kaguya_er_geometry.py`, `test_kaguya_pace.py`.
- Opt-in namespace boundary: `test_experimental_boundary.py`.

See [ER usage](electron-reflectometry.md) for conventions and examples.
