# Effective Field From Electron Reflectometry

`KAGUYA.er.effective_field` pairs Moonward and anti-Moonward electron counts and
infers an effective mirror field from the loss-cone boundary. This product is
currently a candidate product.

Detailed material is split by purpose:

- [Estimation algorithm](electron-reflectometry-algorithm.md): physical assumptions, count likelihood, model selection, and grading
- [Full-period validation](electron-reflectometry-validation.md): coverage, selection function, image audit, and SVM comparison

## Estimand

The primary estimate is the mirror ratio:

\[
R_m = \frac{B_{\mathrm{eff}}}{B_{\mathrm{sc}}}.
\]

`B_eff` is derived as `R_m * |B_sc|`. It is not a magnetic-field vector, a
direct surface-field measurement, or a replacement for the Tsunakawa SVM. It
is an observation-level effective quantity that may include magnetic mirroring,
electrostatic fields, finite-gyroradius effects, and temporal variability.

The boundary model is

\[
\sin^2 \alpha_c(E) = \frac{1}{R_m}
\left(1 + \frac{\Delta U_{\mathrm{eff}}}{E-U_{\mathrm{sc}}}\right).
\]

`DeltaU_eff` is a nuisance parameter for low-energy curvature and is not a
surface-potential measurement without independent validation. Set `U_sc` with
`EffectiveFieldFitSettings(spacecraft_potential_eV=...)`; the default is 0 eV.

## Input And Likelihood

The input is a full-pitch **count** spectrum with dimensions
`time x energy x pitch_angle`. The estimator uses a beta-binomial likelihood
conditional on each affected/reference pair total. It does not fit a logged
energy-flux ratio. Zero counts are retained and overdispersion is estimated.

Per-bin exposure is applied when available. KAGUYA PACE count pitch spectra
store exposure as an auxiliary coordinate. `exposure_mode` records whether it
was `calibrated`, `relative`, `explicit`, or `assumed_equal`.

PACE commands `0x11` (TOFCAL) and `0x12` (POSCAL) retain ESA EC-N look counts;
they are no longer blanket-excluded. The `esa_look_quality_v2` policy rejects
the SPEDAS-invalid combination `mode=0x29, type=1, svs_tbl=0`, internal-count
commands, unvalidated commands, and unsupported look formats. Per-sensor outputs store the
retained record mode and type in the `pace_data_mode` and `pace_data_type`
coordinates. Combined S1/S2 outputs use sensor-qualified coordinates such as
`pace_data_mode_esa_s1`. `pace_data_mode_policy` records the exclusion rule.
Raw-count access is not affected.

The affected side is not chosen by fit quality. With `affected_side="auto"`,
magnetic-field and position vectors in the same frame determine the outgoing
hemisphere from the sign of `B dot r`.

## Model Selection

Three nested models are fitted to the same data.

| model | meaning |
| --- | --- |
| `no_edge` | Constant affected/reference ratio within each energy |
| `mirror_only` | Energy-independent mirror boundary |
| `electrostatic` | Energy-dependent boundary with `DeltaU_eff` |

The two-dimensional count-ratio model is

\[
\log q(E_i,\alpha_j) = \beta_i + A(E_i)\,T(E_i,\alpha_j),
\]

where `beta_i` is a per-energy baseline and `T` is the smooth pitch-angle
transition implied by the boundary equation. The default
`contrast_model="auto"` compares constant contrast with a log-energy band:

\[
T(E,\alpha) = \Phi\!\left(
\frac{\ln\sin^2\alpha -
\ln\left[(1+\Delta U_{\mathrm{eff}}/(E-U_{\mathrm{sc}}))/R_m\right]}
{\sigma_{\ln B}}
\right).
\]

Here `Phi` is the standard-normal cumulative distribution function. Audit plots
show the exposure-corrected
`log[(affected + 0.5) / (reference + 0.5)]` surface, but optimization uses the
beta-binomial likelihood of the original counts rather than least squares on
this pseudocount ratio.

\[
A(E) = A_{\mathrm{floor}} + (A_{\mathrm{peak}}-A_{\mathrm{floor}})
\exp\left[-\frac{(\ln E-\ln E_c)^2}{2w^2}\right].
\]

The band is a low-dimensional nuisance model for an edge that is detectable
only over part of the energy range because of sensor response, count statistics,
or the electron distribution. Do not interpret `E_c` directly as an energy
cutoff, spacecraft potential, or energy-calibration shift. Potential-driven
boundary curvature is represented separately by `DeltaU_eff`. The former
per-energy free contrast remains available with `contrast_model="free"`.

A horizontal energy step shared by all pitch bins is kept separate from the
mirror boundary. A linear log-energy trend and one change point are fitted
post hoc to the selected two-dimensional model's per-energy baseline and
recorded as `energy_ratio_step_*`. This diagnostic does not participate in edge
selection. It describes a step in the affected/reference ratio, not an absolute
spectral cutoff, spacecraft potential, or energy-calibration shift.

\[
\beta(E) = c_0 + c_1\ln E + s\,\mathbf{1}(E \ge E_c).
\]

By default, a more complex model must improve BIC by at least 6. Fits stuck at
mirror-ratio, transition-width, `DeltaU_eff`, or band excess-contrast,
center, or width bounds are not
accepted. At least 80% of retained energies must have one observed pitch bin on
each boundary side, and at least 50% must have two on each side. A
profile-likelihood 95% interval is computed for an accepted mirror ratio.

## API

```python
import sopran as spn

settings = spn.EffectiveFieldFitSettings(
    spacecraft_potential_eV=0.0,
    contrast_model="auto",
    profile_likelihood=True,
)

result = spn.kaguya.er.effective_field.fit(
    pitch_counts,
    magnetic_field=magnetic_field,
    position=spacecraft_position,
    affected_side="auto",
    settings=settings,
    cache="use",
)

frame = result.to_pandas()
```

With `cache="use"`, SOPRAN reads a covering Store variant or fits and writes
`features/kaguya/er/effective_field`. For already paired counts, use the
mission-independent `spn.ElectronReflectionCounts` and
`spn.fit_effective_field(...)` API.

To integrate all native records into 16-second windows and fit the global 2-D
count model while retaining separate ESA-S1/S2 likelihoods, use:

```python
fits = spn.kaguya.er.effective_field.fit_timeseries(
    spn.day("2008-08-20"),
    integration="16s",
    workers=8,
)

frame = fits.to_pandas()
```

PACE normally supplies about eight two-second records per complete window. The
four-of-eight value is stored as a `window_coverage` diagnostic target, not used
as a hard fit filter. Each native record remains an independent
negative-binomial likelihood term while the physical parameters and S1/S2-specific
gain, background, and dispersion are shared within the window. This retains the
half-bin offset between upward and downward energy sweeps. The shared physical
quantity is $B_\mathrm{eff}$, with each record using
$R_{m,i}=B_\mathrm{eff}/B_{\mathrm{sc},i}$. Sparse sampling, gaps, and
affected-side reversals remain in the likelihood through their available counts
and exposures. `window_coverage`, `max_record_gap_seconds`, and
`affected_side_changed` are stored as diagnostics. Only empty windows and mixed
PACE modes are rejected before fitting. The
default uses the Rust hard-edge path and SPEDAS-compatible `event_trash` count
correction. Results are cached in Store under an exact-range variant as
`kaguya.er.global_joint_effective_field`.

Build the legacy ten-minute representative-record catalog with:

```python
catalog = spn.kaguya.er.effective_field.build_archive(
    cadence="10min",
    pitch_bins=16,
    workers=8,
)

fits = catalog.scan()
```

The output uses `date=YYYY-MM-DD` Parquet shards. `build-state.json` records
`complete`, `missing`, `no_data`, or `failed` for every day and completed shards
are reused on restart. Every row retains `sampling_cadence_seconds`.

## Quality Columns

Inspect at least:

- `edge_supported` and `selected_model`
- `no_edge_delta_bic` and `electrostatic_delta_bic` (the default curvature gate is 1 BIC)
- `contrast_model`, `contrast_band_center`, and `contrast_band_width_ln`
- `contrast_band_floor_log_ratio` and `contrast_band_peak_log_ratio`
- `contrast_band_delta_bic`
- `edge_candidate_model` and `edge_candidate_contrast_model`
- `boundary_bracket_fraction` and `strict_boundary_bracket_fraction`
- `energy_ratio_step_supported`, `energy_ratio_step_center`, and
  `energy_ratio_step_log_ratio`
- `energy_ratio_step_delta_bic` and `energy_ratio_step_direction`
- `mirror_ratio_ci95_low/high`
- `bound_stuck`, `profile_truncated`, and `reason`
- `n_energy_bins`, `n_cells`, and `total_counts`
- `affected_side` and `exposure_mode`
- `quality_grade` and `quality_reasons`
- `edge_fit_log_ratio_residual_p90_abs`
- `edge_fit_pitch_pattern_correlation` and `edge_fit_pitch_pattern_nrmse`
- `edge_fit_standardized_residual_inlier_fraction`

Rows with `edge_supported=False` have null `mirror_ratio` and `effective_field`.

| grade | intended use |
| --- | --- |
| `good` | Strong edge support and predictive agreement with the observed 2-D surface; primary analysis. |
| `review` | Supported edge with weaker residual or pitch-pattern agreement; include in the primary map and compare with `good` alone. |
| `poor` | Formally supported edge with weak predictive agreement; sensitivity analysis and visual review only. |
| `reject` | No physical edge selected because of no-edge, bound, or boundary-support gates. |

## Current Validation State

Synthetic beta-binomial tests cover constant and log-energy-band contrast,
mirror-only and electrostatic boundaries, no-edge data, and the separate
energy-ratio step.

The full ten-minute catalog contains 473 complete days, 109 missing days, and
55,702 fit rows. `good + review` contains 2,470 rows (4.43%) with median
`B_eff=9.18 nT`. In an existing time-stratified image audit of 70 edge
candidates, 38/40 `good + review` cases were clear or plausible.

However, Spearman correlation with the radial-subpoint Tsunakawa SVM is only
0.081 for `good + review` and 0.001 after removing energy-step cases. At a
straight-local footpoint the correlation remains 0.043 and only 46.4% of
`good + review` rows connect. Candidate selection has useful internal evidence,
but external validation as a lunar surface-field map has not passed. The
full-period variant also disabled profile likelihood and has no per-row
intervals. Exact results, sampling limitations, selection bias, and reproduction commands are in the
[full-period validation](electron-reflectometry-validation.md).
