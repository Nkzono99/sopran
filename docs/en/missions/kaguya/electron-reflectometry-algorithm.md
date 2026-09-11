# Electron-Reflectometry Estimation Algorithm

This page explains how SOPRAN estimates `mirror_ratio` and `effective_field`
from KAGUYA/PACE electron counts, starting from the physical assumptions. The
implementation entry point is `spn.kaguya.er.effective_field.fit(...)`.

## Boundary-centered global-count models

`GlobalJointFitSettings(loss_cone_model="fixed", edge_transition="hard",
secondary_beam="auto")` fits the affected-side ratio
$q=C[f+(1-f)T]+A_{beam}g$, with $C=1,f=0.1$; the reference ratio is 1.
Use `loss_cone_model="shared"` to fit one common $C,f$ pair, or `"flexible"`
(the unchanged default) for the previous energy-dependent model. Call
`fit_global_joint_effective_field(observations, settings=settings)` and
`plot_global_joint_effective_field_fit(result)` as before.

The constrained models ignore hemisphere knot count and contrast-family choice.
Their no-edge null fits one common hemisphere level. Fixed levels do not count
toward BIC. Hard pitch-bin integration is analytic; energy quadrature integrates
the incident spectrum and ratio together. This assumes uniform within-bin
response, with any supplied detector redistribution applied afterward; it is
not a complete measured instrument response. Measured predictions are therefore
not strictly binary. Hard objectives/gradients run in Rust. Optional smooth
transitions use one common intrinsic width and linear rate mixing in Python.
Beam center remains an independent fit parameter, not a prescribed potential.

Constrained hard, no-beam candidates also search a 25-point log-field by
31-point potential grid after local optimization, followed by up to two full
refinements. Only converged improvements replace the previous fit. This is an
independent per-window search, not a temporal prior; it does not guarantee a
global optimum. Disable with `boundary_grid_refinement=False`. Partial-parameter
beam screening is not affected.

!!! warning "Candidate product"
    The result is an observation-level effective quantity inferred from a
    loss-cone-like boundary in count data. It is not a magnetic-field vector or
    a direct measurement at one lunar-surface location. See the
    [full-period validation](electron-reflectometry-validation.md) for what has
    and has not been established.

## End-to-end map

The estimator does not read a magnetic field directly from an image. Its data
flow is:

```text
PACE raw counts + calibration + LMAG + spacecraft position
  -> energy/pitch/exposure array
  -> symmetric outward affected and inward reference count pairs
  -> no-edge / mirror / electrostatic count-likelihood fits
  -> BIC edge-model comparison
  -> support, bracketing, bound, and residual gates
  -> good / review / poor / reject
  -> mirror ratio R_m and B_eff = R_m B_sc
  -> profile-likelihood 95% interval (separate validation artifact)
```

The first stages construct comparable count pairs, the middle asks whether an
edge improves the likelihood enough, and the final gates ask whether that fit
is supportable as a physical candidate. Optimizer convergence, edge-model
selection, and a `good`/`review` grade are three different decisions.

## Suggested reading path

1. Start with energy, pitch angle, and counts in "What is observed."
2. Read "Magnetic mirroring and the loss cone" for the estimating equation.
3. Read "Count likelihood" to see how an image-like boundary becomes a number.
4. Read "Acceptance gates and quality grades" to distinguish numerical success
   from an accepted physical candidate.
5. Finish with "Interpretation boundary" before using `B_eff` scientifically.

## 1. What is observed

### Energy and pitch angle

Electron velocity can be decomposed into components parallel and perpendicular
to the magnetic field. Pitch angle $\alpha$ is the angle between the electron
velocity and $+\mathbf B$.

- $\alpha\simeq0^\circ$: motion along $+\mathbf B$
- $\alpha\simeq90^\circ$: motion nearly perpendicular to $\mathbf B$
- $\alpha\simeq180^\circ$: motion along $-\mathbf B$

PACE records counts by energy channel and look direction. SOPRAN projects every
look direction onto the simultaneous LMAG field and constructs a
`time x energy x pitch_angle` count array. The main fitting quantities are:

| Symbol | Package quantity | Meaning |
| --- | --- | --- |
| $E_i$ | `energy_eV` | Representative energy-bin value [eV] |
| $\alpha_j$ | `pitch_deg` | Pitch angle folded into 0--90 degrees |
| $a_{ij}$ | `affected_counts` | Counts on the outward, loss-cone-affected side |
| $r_{ij}$ | `reference_counts` | Counts in the symmetric opposite hemisphere |
| $e^a_{ij},e^r_{ij}$ | exposure | Effective integration-time and response exposure |
| $B_{sc}$ | `b_sc_nT` | LMAG field magnitude at the spacecraft [nT] |

The affected side is not chosen after fitting. Because pitch zero follows
$+\mathbf B$, the default `auto` rule selects the low-pitch side when
$\mathbf B\cdot\mathbf r>0$, and the high-pitch side otherwise. Non-finite
geometry and exactly perpendicular $\mathbf B$ and $\mathbf r$ are rejected
as ambiguous.

### Why counts, not energy flux

Energy flux is useful for visualization, but it is a calibrated continuous
quantity rather than a direct sampling distribution for integer detections.
This estimator keeps integer counts and exposure separate, retains zero counts,
and evaluates a count likelihood. Its input must therefore have
`value="counts"` and count units.

## 2. Magnetic mirroring and the loss cone

### Minimal physics

When the field changes slowly on the electron gyro scale and collisions and
rapid time variation are negligible, the first adiabatic invariant

$$
\mu=\frac{m v_\perp^2}{2B}
$$

is approximately conserved. Ignoring electrostatic fields for the moment,
kinetic energy is also conserved. As an electron enters a stronger field, its
perpendicular energy increases until parallel velocity reaches zero and the
electron mirrors. For spacecraft pitch angle $\alpha$ and mirror-point field
$B_m$,

$$
\frac{\sin^2\alpha}{B_{sc}}=\frac{1}{B_m}.
$$

Let $\alpha_c$ separate electrons that reach the surface from those that
mirror first. Then

$$
\sin^2\alpha_c=\frac{B_{sc}}{B_m}=\frac{1}{R_m},
\qquad R_m=\frac{B_m}{B_{sc}}.
$$

Electrons at small angular distance from the Moon-directed field direction
preferentially reach the surface and are lost. Because the original pitch angle
is always measured from $+\mathbf B$, this Moon-directed center is either 0 or
180 degrees depending on geometry. The corresponding population is depleted in
the outward distribution returning to the spacecraft. SOPRAN treats that outward
hemisphere as affected and folds angular distance from its center into 0--90
degrees; this folded coordinate is $\alpha$ below. This depleted region is the
loss cone. Once its boundary $\alpha_c$ is known, $R_m$ can be estimated.

!!! example "Numerical example"
    If $B_{sc}=5\ \mathrm{nT}$ and the inferred boundary is
    $\alpha_c=30^\circ$, then $\sin^2 30^\circ=0.25$,
    $R_m=1/0.25=4$, and $B_{eff}=4\times5=20\ \mathrm{nT}$.
    The 30-degree boundary is nevertheless inferred statistically from a
    finite-width count pattern. The resulting 20 nT is an effective quantity
    under the mirror assumptions, not a magnetometer measurement at one
    surface point.

### Electrostatic curvature

A potential difference between the spacecraft and reflection region makes the
boundary energy dependent. SOPRAN uses the effective relation

$$
s_i\equiv\sin^2\alpha_c(E_i)
=\frac{1}{R_m}\left(1+\frac{\Delta U_{eff}}{E_i-U_{sc}}\right).
$$

`spacecraft_potential_eV` is $U_{sc}$, and `delta_u_eff_eV` is
$\Delta U_{eff}$. By implementation convention, positive
$\Delta U_{eff}$ expands the low-energy loss cone.

`DeltaU_eff` is a nuisance parameter for curvature. The default spacecraft
potential is 0 eV and no independent potential measurement is used. Do not
interpret the fitted value directly as lunar surface potential. The model name
`electrostatic` labels an energy-dependent-boundary hypothesis.

### The returned estimand

For an accepted $R_m$, SOPRAN computes

$$
B_{eff}=R_m B_{sc}.
$$

This is an **effective mirror-side field magnitude** under the model assumptions.

- It is scalar, not a magnetic-field vector.
- It does not determine a reflection point or field-line footpoint.
- It may absorb finite-gyroradius, nonadiabatic, electrostatic, temporal, and
  instrument-response effects.
- It has not been shown to share the same estimand as the Tsunakawa SVM surface
  value.

## 3. Constructing KAGUYA inputs

The full-period catalog performs these steps for each day:

1. Read PACE ESA1 raw counts and angle/INFO calibration.
2. Interpolate LMAG field vectors and orbit position to the relevant times.
3. Select the native PACE record nearest the center of each ten-minute bucket.
4. Project look directions onto the field and bin 0--180 degrees into 16 bins.
5. Pair symmetric $\alpha$ and $180^\circ-\alpha$ bins and fold to 0--90.
6. Determine affected/reference hemispheres from $\mathbf B\cdot\mathbf r$.
7. Fit each timestamp independently.
8. Compute SZA from SPICE and write a provenance-bearing daily Parquet shard.

The ten-minute cadence is not a ten-minute average. It is one systematic sample
per occupied bucket. Empty buckets and records without sufficient pitch/energy
support cannot become accepted candidates.

Exposure is the sum of effective exposures for look cells entering a pitch bin.
The PACE reader uses integration time, geometric factor, and the current
calibration duty factor. Only the paired ratio $e^a/e^r$, not absolute flux,
is identified by this likelihood. Archive rows record
`exposure_mode="calibrated"`.

PACE event-count and trash-count telemetry corrections are selected with
`count_correction`. `"trash"` distributes the two trash counters over each
energy/polar cell, while `"event"` scales each adjacent pair of energy channels
to its event counter. `"event_trash"` applies both in the same trash-then-event
order as SPEDAS `/cntcorr`.
The ER-specific `spn.kaguya.er.pitch_angle_spectrum()` and
`pitch_angle_spectra()` APIs default to `"event_trash"`. The lower-level raw-data
API `spn.kaguya.esa1.counts.pitch_angle_spectrum()` retains the backward-compatible
`"none"` default so correction remains explicit there.

```python
pitch_counts = spn.kaguya.er.pitch_angle_spectra(
    time,
    count_correction="event_trash",
)
```

The count likelihood does not replace observations with corrected fractional
counts. It keeps raw count $n$ and represents correction multiplier $m$ through
effective exposure $e/m$, so for cells with $m>0$ the rate $n/(e/m)=nm/e$
equals the SPEDAS corrected rate. A zero event count gives $m=0$, which cannot
be represented by a positive raw count and finite exposure; such cells are
excluded from fitting and counted in observation metadata as
`invalid_exposure_count_cells`. This treats event/trash telemetry as a known
retention factor; its own statistical uncertainty is not yet included in the
likelihood. With `value="energy_flux"`, the same multiplier is applied directly
to the value.

!!! note "ESA1-only limitation"
    KAGUYA is three-axis stabilized, and the PACE design uses both ESA-S1 and
    ESA-S2 to obtain the complete three-dimensional electron distribution. The
    present catalog bins only available ESA1 look directions. In the fixed
    18-day cross-sensor check, edge-evidence strength covaried, but only one of
    1,772 common timestamps was `good/review` for both sensors. ESA2 coordinates,
    hemisphere mapping, and response require audit before a joint likelihood
    with sensor-specific nuisance parameters can replace the ESA1-only model.

## 4. Count likelihood

### Conditioning on paired totals

For each energy $i$ and folded pitch bin $j$, define

$$
n_{ij}=a_{ij}+r_{ij}.
$$

The model conditions on this total and predicts the probability $p_{ij}$ that
a count belongs to the affected side. If the exposure-corrected rate ratio is
$q_{ij}=\lambda^a_{ij}/\lambda^r_{ij}$, then

$$
\operatorname{logit}(p_{ij})
=\log q_{ij}+\log\frac{e^a_{ij}}{e^r_{ij}}.
$$

Conditioning removes the need for a separate total-intensity nuisance parameter
in every cell. Equal exposure gives $p=q/(1+q)$.

For example, a cell with equal exposures, `affected=20`, and `reference=40`
has an observed affected fraction of $20/(20+40)=1/3$. If the two exposures
differ by a factor of two, the raw count ratio is not directly comparable and
the $\log(e^a/e^r)$ term corrects it. This is why the estimator requires
counts and exposure separately instead of fitting an energy-flux image.

### Beta-binomial likelihood

A binomial model can underestimate variability from temporal structure,
unresolved angular structure, and response error. SOPRAN instead uses

$$
a_{ij}\mid n_{ij},p_{ij},\kappa
\sim\operatorname{BetaBinomial}
\left(n_{ij},p_{ij}\kappa,(1-p_{ij})\kappa\right).
$$

The shared concentration $\kappa$ approaches a binomial model when large and
allows more overdispersion when small. Optimization evaluates this likelihood on
the original integer counts. The exposure-corrected pseudocount display

$$
\log\frac{a_{ij}+0.5}{r_{ij}+0.5}
-\log\frac{e^a_{ij}}{e^r_{ij}}
$$

is used only for plots and predictive diagnostics, not as a least-squares target.

## 5. Boundary-surface parameterization

### Smooth transition

Finite pitch bins, angular response, and time variation blur a perfect step.
SOPRAN models

$$
T_{ij}=\Phi\left(
\frac{\ln\sin^2\alpha_j-\ln s_i}{\sigma_{\ln B}}
\right),
$$

where $\Phi$ is the standard-normal CDF and $s_i$ is the loss-cone
boundary. Smaller `sigma_ln_b` means a sharper transition. The rate-ratio
surface is

$$
\log q_{ij}=\beta_i+A(E_i)T_{ij}.
$$

The per-energy baseline $\beta_i$ absorbs spectral variation. Non-negative
$A(E_i)$ describes contrast between the inside and outside of the loss cone.

### Contrast models

| `contrast_model` | $A(E)$ | Role |
| --- | --- | --- |
| `constant` | One value for all energies | Simplest and most stable |
| `band` | Gaussian in log energy plus a floor | Edge visible over a limited energy band |
| `free` | One value per energy | Flexible sensitivity model with many parameters |
| `auto` | BIC comparison of `constant` and `band` | Default |

The band model is

$$
A(E)=A_{floor}+(A_{peak}-A_{floor})
\exp\left[-\frac{(\ln E-\ln E_c)^2}{2w^2}\right].
$$

Its center $E_c$ marks where the edge is most detectable. It is not an
absolute spectral cutoff, spacecraft potential, or calibration shift.

## 6. Nested models and BIC

### Positive boundary-field ratios

`HalekasFitSettings`, `EffectiveFieldFitSettings`, and `BinaryLossConeFitSettings`
now default to `mirror_ratio_bounds=(0.001, 1000.0)`. Any finite positive
ordered bounds are supported, including an interval wholly below one. Zero,
negative values, and infinity are invalid numerical bounds. Explicitly use
`(1.001, 1000.0)` to retain the old domain restriction.
Explicit bounds loaded from previously saved settings are not automatically migrated.

The returned $B_{eff}=R_mB_{sc}$ is a boundary-model field. It is not necessarily
the maximum field along a path including the spacecraft, nor the crustal
component alone. Sub-unity ratios have no magnetic-only loss-cone boundary,
but can have an electrostatic boundary with negative potential. Allowing
them is not proof that the inferred parameter equals the physical surface
field. Existing no-edge comparisons, boundary-support and quality gates remain.

The Halekas hard fit searches 512 log-spaced positive ratios and 601 potential
values by default, batching the potential axis. It refines the neighborhood
of the best grid point twice on 17-by-17 grids; set `hard_refinement_steps=0`
to disable this. Grid search with local refinement is not a global-optimum
or confidence-interval guarantee. The probit optimizer uses $\log R_m$, not
$\log(R_m-1)$. Equivalent binary masks cannot uniquely identify parameters.

Global joint bounds still enforce the configured ratio range for every native
record through a shared boundary-field parameter. The implicit post-fit
`Rm > 1` veto is removed, and electrostatic starts include a sub-unity ratio
with negative potential. Timeseries caches now use `global_joint_timeseries_v7`.

### Model selection

The staged rule in this section applies to `fit_effective_field()`, which pairs
symmetric pitch bins before fitting. The production S1/S2 raw-count path,
`fit_global_joint_effective_field()`, compares both `mirror_only` and
`electrostatic` directly with `no_edge`. Only when mirror is supported must
electrostatic also improve on mirror. If electrostatic fails a quality gate and
mirror remains supported, the production path falls back to mirror.

Three models are fitted to the same retained cells.

| Model | Pitch dependence | Free physical parameters |
| --- | --- | --- |
| `no_edge` | None | None |
| `mirror_only` | Yes | $R_m,\sigma_{\ln B}$ |
| `electrostatic` | Yes | $R_m,\sigma_{\ln B},\Delta U_{eff}$ |

All models also contain per-energy baselines and concentration; edge models add
contrast parameters. The optimizer is bounded L-BFGS-B with three starts and up
to 4,000 iterations by default.

Model complexity is penalized with

$$
\mathrm{BIC}=k\ln N-2\ln\hat L,
$$

where $k$ is the parameter count and $N$ is the number of valid paired cells.
SOPRAN defines improvement as `BIC_simple - BIC_complex` and requires at least 6.

1. Reject the edge unless `mirror_only` improves over `no_edge` by at least 6.
2. If an edge is supported, choose `electrostatic` only when it improves over
   `mirror_only` by a further 6.
3. Under `contrast_model="auto"`, choose `band` only when it improves over
   `constant` by at least 6.

BIC is a rule for trading fit against complexity within this candidate family;
it is not proof that the selected physical explanation is true.

When `spectrum_smoothness > 0`, optimization uses a penalized incident spectrum, so the reported
BIC is not the strict BIC of an unregularized maximum-likelihood estimate. Production population
runs use `0.0`; regularized sensitivity studies should treat BIC differences as approximate and
report held-out likelihood as well.

## 7. Acceptance gates

A converged optimizer does not automatically produce `B_eff`.

| Gate | Default | Typical failure `reason` |
| --- | --- | --- |
| Retained energy | At least 3 bins | `insufficient_energy_support` |
| Pitch support | At least 6 cells per retained energy across each sensor window | Energy row removed |
| Total counts | At least 100 | `insufficient_total_counts` |
| Edge evidence | BIC improvement at least 6 | `no_edge_evidence` |
| Physical bounds | $R_m,\Delta U,\sigma$ not at a bound | `edge_parameter_at_bound` |
| Band bounds | Excess, center, and width not at a bound | `contrast_band_parameter_at_bound` |
| Boundary bracket | One bin on each side for at least 80% of energies | `insufficient_boundary_bracketing` |
| Strict bracket | Two bins on each side for at least 50% of energies | Same |

Bracketing prevents a nominal boundary outside the observed pitch range. If an
identical pitch bin occurs in repeated records, it is counted only once for this
gate. If an
electrostatic candidate fails a gate but the mirror-only fit passes, selection
falls back to mirror-only.

`success=True` means a numerical model result exists. `edge_supported=True`
means an edge model survived the evidence and physical gates. Scientific use
must inspect `edge_supported` and `quality_grade`, not `success` alone.

## 8. Predictive quality grade

After edge acceptance, SOPRAN checks how well the selected model reproduces the
observed two-dimensional count-ratio surface.

| Metric | `good` | `review` | Purpose |
| --- | ---: | ---: | --- |
| Absolute log-ratio residual p90 | <= 2.0 | <= 2.5 | Residual tail |
| Pitch-pattern correlation | >= 0.75 | >= 0.50 | Baseline-removed shape |
| Pitch-pattern NRMSE | <= 0.75 | <= 1.00 | Relative pitch-shape error |
| Fraction inside 3-sigma standardized residual | >= 0.90 | >= 0.75 | Count-likelihood outliers |

All `good` thresholds produce `good`; all weaker thresholds produce `review`;
other accepted edges are `poor`. Rows without an accepted edge are `reject`.
The thresholds are operating values calibrated against current review panels,
not probabilities learned from independent ground truth.

## 9. Profile-likelihood interval

Ordinary `fit(...)` fixes $\log R_m$ on a grid and reoptimizes the other
parameters. Intersections with the one-degree-of-freedom 95% deviance threshold

$$
2\{\ln\hat L-\ln L(R_m)\}=3.84146
$$

define the profile interval. If no intersection is reached before the search or
global bound, `profile_truncated=True`.

!!! warning "Full-period archive exception"
    `EffectiveFieldFitSettings` defaults to `profile_likelihood=True`, but the
    daily archive builder defaults to `False` for tractability. The primary
    archive therefore contains no intervals, but a separate validation artifact
    refits all 2,470 accepted rows. Of these, 807 (32.67%) did not reach a 95%
    crossing within the profile search range and have `profile_truncated=True`.
    The point-estimate distribution is not an uncertainty distribution.

## 10. Separate energy-ratio-step diagnostic

A change point is fitted post hoc to the selected model's baseline:

$$
\beta(E)=c_0+c_1\ln E+s\,\mathbf1(E\ge E_c).
$$

At least three energy bins are required on each side and BIC must improve by 6.
This diagnostic does not influence edge selection. Its center describes a step
in the affected/reference ratio, not an absolute spectral cutoff or potential.
The full-period accepted set has 1,847 step-positive rows out of 2,470, leaving
623 for a necessary no-step sensitivity comparison.

## 11. API and pseudocode

### Global-FOV folding and low counts

After fitting, S1/S2 raw counts, corrected counts, exposure, and gain/incident-spectrum-adjusted
exposure are overlap-binned onto one common 0--180 degree grid. Symmetric global-FOV bins are then
paired and folded to 0--90 degrees. The folded observation uses the Jeffreys Poisson-rate
posterior

$$
L_{obs}=\psi(N_A+1/2)-\log Q_A-\psi(N_R+1/2)+\log Q_R,
$$

with uncertainty

$$
\sigma_L=\sqrt{\psi_1(N_A+1/2)+\psi_1(N_R+1/2)}.
$$

Consequently a zero count on one side remains a finite, uncertain diagnostic rather than becoming
NaN. `GlobalNormalizedFlux.reliable` marks cells above the configured raw-count threshold and
below the configured posterior-uncertainty threshold; the fit itself continues to use every valid
sensor-native count cell.
When finite bins are fractionally overlap-allocated, or background/dead-time corrections are
active, this is a diagnostic quasi-posterior. Its uncertainty contains Poisson sampling only;
signed corrected counts are retained separately in `GlobalFullFOV.corrected_counts`.

```python
import sopran as spn

time = spn.period("2008-08-02T00:00:00Z", "2008-08-02T00:10:00Z")
magnetic_field = spn.kaguya.lmag.magnetic_field.load(time)
position = spn.kaguya.orbit.position.load(time)
pitch_counts = spn.kaguya.esa1.counts.pitch_angle_spectrum(
    time,
    magnetic_field=magnetic_field,
    pitch_bins=16,
)

settings = spn.EffectiveFieldFitSettings(
    contrast_model="auto",
    spacecraft_potential_eV=0.0,
    profile_likelihood=True,
)
fits = spn.kaguya.er.effective_field.fit(
    pitch_counts,
    magnetic_field=magnetic_field,
    position=position,
    affected_side="auto",
    settings=settings,
)

accepted = fits.to_pandas().query("quality_grade in ['good', 'review']")
```

Conceptually:

```text
for each timestamp:
    construct symmetric affected/reference count pairs
    discard unsupported energy rows
    fit no_edge
    fit mirror_only with constant and/or band contrast
    fit electrostatic with the selected contrast family
    select by nested BIC improvements
    reject critical bound hits and unbracketed boundaries
    compute predictive diagnostics and quality grade
    optionally profile mirror_ratio
    diagnose a separate energy-ratio step
    emit B_eff only when an edge model survives the gates
```

Production defaults to `edge_transition="hard"`, which can use the Rust backend.
Smooth transitions remain substantially more expensive in Python and are enabled
explicitly with `edge_transition="auto"` or `"smooth"` for sensitivity analysis.

Build the day-sharded archive with:

```python
catalog = spn.kaguya.er.effective_field.build_archive(
    cadence="10min",
    pitch_bins=16,
    workers=8,
)
fits = catalog.scan()
```

### Global joint band contrast and initialization

For a localized band, `contrast_floor=0` means that no depletion is required
outside the band. Reaching its default zero lower bound is permitted during
screening, contrast selection, and final quality checks. The diagnostic
`at_bounds` still records it. The floor upper bound and other contrast and
physical parameter bounds remain rejection conditions.

When the constant candidate fails quality checks, hard band refinement uses
the larger of `contrast_refine_optimizer_starts` and
`effective_field.optimizer_starts`. Optional smooth refinement keeps its
separate settings. Seeded multistart fits include a canonical initialization
and independent starts in addition to the inherited fit. A single start can
still miss a competing optimum.

## 12. Interpretation boundary

### Supported statements

- A selected loss-cone-like model is supported for one paired-count surface.
- `mirror_ratio` locates that boundary relative to the spacecraft field.
- `B_eff` is the scalar $R_mB_{sc}$ under the same assumptions.
- `quality_grade` filters candidates by predictive agreement with the observed
  surface.

### Unsupported statements

- `B_eff` equals the field at the spacecraft's radial lunar subpoint.
- `DeltaU_eff` or the energy step directly measures surface potential.
- Accepted fraction is the occurrence rate of magnetic anomalies.
- The old 95% audit with fitted boundaries visible establishes precision,
  accuracy, or recall across all timestamps.
- The ten-minute catalog represents all native-cadence observations.

Repeating the same review without fitted boundaries gave 58.2% binary agreement
and Cohen's kappa 0.074. Only 15 of 40 accepted ten-minute records persisted in
another nearby two-minute record. Outstanding effects include footpoint and
external-field uncertainty, finite gyroradius and nonadiabatic motion,
solar-wind/wake/magnetotail regime, ESA1/ESA2 response, spacecraft potential,
and temporal correlation. Particle tracing in
[Halekas et al. (2010)](https://doi.org/10.1029/2009JE003516) shows reduced
electron-reflectometry sensitivity to small-scale magnetization, which is why
the adiabatic relation must not be equated directly with a true surface field.

## References

- Saito et al. (2009), [Low Energy Charged Particle Measurement by MAP-PACE Onboard KAGUYA](https://doi.org/10.2322/tstj.7.Tk_7)
- Halekas et al. (2008), [Lunar Prospector observations of the electrostatic potential of the lunar surface and its response to incident currents](https://doi.org/10.1029/2008JA013194)
- Halekas et al. (2010), [How strong are lunar crustal magnetic fields at the surface? Considerations from a reexamination of the electron reflectometry technique](https://doi.org/10.1029/2009JE003516)
- Kato et al. (2017), [Global mapping of the lunar magnetic anomalies by electron reflection method](https://www2.jpgu.org/meeting/2017/PDF2017/P-PS08_all_e.pdf)
