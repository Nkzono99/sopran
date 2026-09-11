# Electron reflectometry and loss-cone estimation survey

This note summarizes the model choices behind SOPRAN's KAGUYA electron-reflectometry
implementation. The central recommendation is to estimate the loss-cone boundary from a
two-dimensional pitch-energy count model, while retaining energy-by-energy edge estimates
as diagnostics rather than as the primary estimator.

## Estimation approaches

### Energy-wise edge fitting

Fitting a step or cumulative transition independently at each energy is useful for inspection
and initialization. It is fragile when counts are low, coverage is missing, a secondary beam is
present, or the edge is broad. A second-stage fit of the extracted points also discards evidence
from energy bins where the edge is weak but not absent.

### Reflection coefficients

Affected/reference rate ratios remove much of the unknown incident spectrum. They remain
sensitive to exposure, sensor gain, pitch response, background, and the assignment of the two
hemispheres. These effects must therefore remain explicit in the forward model.

### Full two-dimensional fitting

The Halekas-style model fits a physically constrained boundary across the complete
pitch-energy distribution. A hard binary surface is the closest paper-reproduction baseline.
A response-convolved finite-width transition is a separate extension and should be compared
against that baseline rather than silently replacing it.

The transition width is not automatically a direct plasma parameter. It may combine pitch and
energy response, field variation during accumulation, time averaging, scattering, surface
backscatter, and model mismatch. Physical interpretation requires calibration or a hierarchical
model that separates these contributions.

## Recommended production model

The observation layer should retain raw counts $n_{ijs}$ and exposure $X_{ijs}$ for energy
$i$, pitch cell $j$, and sensor $s$. Expected counts are described by

$$
\mu_{ijs}=X_{ijs}I_iG_s\exp\left[b_i-A_i\{1-T_{ij}(R_m,\Delta U,\sigma)\}\right],
$$

on the affected hemisphere, with the loss term omitted on the reference hemisphere. Here
$I_i$ is the incident spectrum, $G_s$ is sensor gain, $b_i$ is a smooth energy-dependent
affected/reference baseline, $A_i$ is loss-cone contrast, and $T_{ij}$ is the response-averaged
transmission surface. A secondary beam is an optional additive component selected only when
its BIC improvement clears the configured evidence threshold.

ESA-S1 and ESA-S2 must remain separate surfaces in one joint likelihood. Their native energy
and pitch grids, exposure, response, dead time, background, and missing coverage are preserved.
The sensors are combined only after fitting to create an audit product.

## Pitch orientation and folding

The upper sensor rows in `plot_global_joint_effective_field_fit()` retain the full 0--180 degree
field of view. With the default `pitch_orientation="physical"`, the affected hemisphere is
flipped when necessary so that:

- 0--90 degrees on the left is Moon-outgoing/affected.
- 90--180 degrees on the right is Moon-incoming/reference.

This is an orientation change, not folding. `pitch_orientation="native"` restores 0 degrees as
$+B$ and 180 degrees as $-B$.

S1/S2 counts and exposures are first overlap-binned onto one common 0--180 degree global FOV.
Only then does the bottom row pair its symmetric bins as
$\alpha_f=\min(\alpha,180^\circ-\alpha)$ and display the affected/reference rate ratio. The
pre-fold sufficient statistics are retained in `GlobalJointModelFit.global_fov`.

Low counts are not converted to missing values. For the non-negative parts of corrected counts
$N_A,N_R$, normalized
exposures $Q_A,Q_R$, and the default Jeffreys prior $a=1/2$, the displayed posterior mean is

$$
E[\log r_A-\log r_R\mid N]
=\psi(N_A+a)-\log Q_A-\psi(N_R+a)+\log Q_R.
$$

`observed_log_ratio_std` stores the corresponding uncertainty
$\sqrt{\psi_1(N_A+a)+\psi_1(N_R+a)}$. `normalized_min_counts` and
`normalized_max_log10_std` define the `reliable` mask; they do not discard lower-count or
one-sided cells. The count likelihood used for fitting is unchanged.
Signed corrected counts remain available separately. With overlap allocation, background
subtraction, or dead-time inversion this is a diagnostic quasi-posterior: its standard deviation
covers Poisson sampling only, not negative-binomial overdispersion or covariance between split
cells.

`GlobalPitchCountObservation` accepts raw integer event counts only. `from_spectrum()` rejects an
explicit non-count value/unit, and dead-time correction requires detector-sample capacity instead
of inferring it from one integration-time scalar.

## Time-series extension

A short-window hierarchical model should share slowly varying $R_m$, $\Delta U$, and sensor
gain while allowing incident spectrum and beam amplitude to vary by record. This can stabilize
low-count boundaries, separate transient beams from persistent mirror structure, and preserve
continuous uncertainty instead of reducing every record to an accepted/rejected flag.
An approximately 16-second accumulation is a useful literature-scale starting point, but the
final duration should be tested against 32- and 64-second windows using held-out likelihood and
temporal stability rather than imposed as a per-cell count threshold.
The current `pitch_angle_spectra(..., cadence_seconds=...)` option is decimation: it selects one
native record per cadence bucket and does not accumulate counts for that duration. Use
`effective_field.fit_timeseries(..., integration="16s")` for short-window integration. It retains
each native record as an independent likelihood term, preserving the half-bin sweep offset, while
sharing physical parameters and S1/S2-specific nuisance parameters within the window. It is not
yet a temporal-prior model.

## Validation sequence

1. Reproduce the published hard two-dimensional model and published examples.
2. Test synthetic recovery across count level, zero counts, overdispersion, missing coverage,
   response width, beam contamination, gain mismatch, and energy offsets.
3. Calibrate end to end with particle tracing and the instrument response.
4. Compare hard and finite-width models with held-out predictive density and residual maps.
5. Validate against independent magnetic-field products only after selection effects are fixed.

## Current implementation

`fit_global_joint_effective_field()` implements the first production stage with a joint
negative-binomial raw-count likelihood. It shares the incident spectrum, $R_m$, $\Delta U$,
contrast, and smooth hemisphere baseline while retaining sensor-specific gain, dispersion,
response, and missing cells. Production defaults to `edge_transition="hard"`; explicit
`edge_transition="auto"` fits hard and smooth latent edges separately and compares them by BIC.
Both are integrated over each ESA energy and
pitch bin using linear-energy top-hat responses and then passed through the detector response.
Energy uses eight-point and smooth pitch uses 64-point Gauss--Legendre quadrature by default;
bins crossing the spacecraft potential are excluded consistently across candidates. The hard
candidate integrates the overlap with each pitch bin analytically. Only the smooth candidate adds
$\sigma_{\ln B}$, so an edge sharper than the instrument resolution is represented by the
lower-dimensional hard model instead of a width pinned to an arbitrary lower bound. The
selected form and its evidence are exposed as `transition_model` and
`smooth_transition_delta_bic`; a positive delta supports smooth and a negative delta supports
hard. `sigma_ln_b` is `None` for the hard model.

Constant and log-energy-band contrast families are selected independently within the mirror-only
and electrostatic boundary models, after the same physical-quality gates are applied.

The post-fit `GlobalNormalizedFlux` is a diagnostic product. It is folded from a common global
FOV containing overlap-binned counts, exposures, and the response-convolved predictions used by
the likelihood. It is not a pre-fit mixture of S1 and S2 and must not be substituted for the
sensor-native count likelihood.

For population processing, the four-start hard fit runs first. An eight-point smooth screen then
optimizes only the added physical parameters while holding the hard-fit nuisance solution fixed.
The 64-point smooth model is refined from one screened start only when the screen improves on hard.
The contrast-band screen uses eight pitch quadrature points and profiles both the contrast and
physical boundary parameters; fixing the boundary missed known bands. The secondary-beam screen
varies only beam parameters. Only promising candidates receive a full-parameter refinement. Screen
evidence is stored separately in `*_screen_delta_bic`; `*_refined` states whether the full fit ran.

## Boundary-centered revision (opt-in implementation)

`GlobalJointFitSettings(loss_cone_model="fixed")` now anchors $C=1,f=0.1$;
`"shared"` fits one energy-independent $C,f$ pair. `"flexible"` retains the
previous model and remains the default. Both alternatives reuse native-record
S1/S2 count likelihood, energy quadrature, analytic hard pitch-bin integration,
and beam auto selection. The hard objective runs in Rust. Optional smooth
transitions use arithmetic rate mixing and one shared width in Python.
The no-edge null retains one common hemisphere level, including in fixed mode.
Fixed levels do not count toward BIC or parameter-at-bound rejection.
The existing baseline log bounds constrain $\log C$ and contrast amplitude bounds
constrain $-\log f$. Baseline knot count and contrast-family selection are ignored
in these two modes. These changes implement the first comparison stages below;
held-out-day evaluation, bootstrap uncertainty, and temporal priors remain pending.

The two targeted 2008-08-20 comparisons favor the fixed-level Halekas-style
model for visually apparent boundary placement, not uniformly for predictive
error. Native-count likelihoods and folded-map log-SSE cannot be ranked by
comparing their BIC values. Two selected examples do not establish population
performance.

Before adding more residual baselines, compare an anchored model

$$
q(E,\alpha)=C[f+(1-f)T(E,\alpha;R_m,\Delta U)]+A_{beam}g(E,\alpha).
$$

Start from $C=1,f=0.1$, a hard boundary, positive $R_m$, and integration over
the measured energy/pitch response. Then relax only global inner/outer levels,
add an optional surface-outgoing excess, and finally test one shared intrinsic
transition width if instrument response is insufficient. Do not simultaneously
restore free energy-row baselines or a freely centered contrast band. Beam
energy/potential coupling requires spacecraft-potential and response validation;
do not equate the beam center to $|\Delta U|$ without those constraints.

Keep the existing separate, pre-fold S1/S2 raw-count likelihood, including zero
counts and reference observations with $q=1$. A response-integrated hard model
is not binary at the measured-cell level. Retain equal-weight map log-SSE as a
paper-style benchmark, and provide comparison plots with a shared observation
normalization rather than candidate-dependent normalization alone.

Validate the successive models on identical observations/objectives, synthetic
ratios below/equal/above one, beams and low-count cases, then held-out days
including no-edge examples. Evaluate boundary bias, predictive residuals,
false positives, and temporal stability separately. Resample native records
for uncertainty; equal-best binary grid ranges are not confidence intervals.
Temporal priors should follow, not conceal, single-window bias checks.

The constrained alternatives are opt-in and have not replaced the default
flexible model. Comparison artifacts are in
`working/kaguya-er-fit-review/boundary-centered-validation-v2/`. Common-display
plots use count/exposure ratios without fitted gain or incident normalization;
they are not absolute calibrated hemisphere-flux ratios. The fit still includes
gain in its native-count likelihood. See the
[algorithm page](electron-reflectometry-algorithm.md) for the current API.

## Key references

- [Halekas et al. (2008), lunar surface potential from electron reflectometry](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2008JA013194)
- [Halekas et al. (2010), lunar crustal magnetic fields](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2009JE003516)
- [Halekas et al. (2011), ARTEMIS surface-charging measurements](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2011JA016542)
- [Mitchell et al. (2007), Mars electron-reflectometry field map](https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2005JE002564)
- [NASA PDS Lunar Prospector ER Level 4 data](https://pds.nasa.gov/ds-view/pds/viewProfile.jsp?dsid=LP-L-ER-4-ELECTRON-DATA-V1.0)
