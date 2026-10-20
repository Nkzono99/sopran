# ER Model Definitions

This page defines the model, objective, numerics, and quality checks of the two estimators used in [Electron Reflectometry](er.md).
Both take `ElectronReflectionCounts` over energy × folded pitch angle (affected and reference counts and exposures).

## finite-bin model

```python
from sopran.experimental.electron_reflection import (
    FiniteBinFitSettings, FiniteBinObservation, fit_finite_bin_distribution, profile_mirror_ratio,
)

observation = FiniteBinObservation.from_counts(
    counts, energy_edges_eV=energy_edges, pitch_edges_deg=folded_pitch_edges,
)
result = fit_finite_bin_distribution(observation, settings=FiniteBinFitSettings())
profile = profile_mirror_ratio(observation, result)
```

### Model equation

The incident flux, integrated over solid angle, is multiplied by the reflectance and a beam, moved by the angular transport $D_\mathrm{out}$,
and mapped back to observed ratios through ideal bin responses uniform in log energy and pitch angle.

$$
N_\mathrm{out} = D_\mathrm{out}\left\{ s\left[\rho + (1-\rho)P_0\right] N_\mathrm{in} + N_\mathrm{beam} \right\},
\qquad
\sin^2\alpha_c = \frac{1 + \Delta U / E}{R_m}.
$$

| Symbol | Name in `result.parameters` | Meaning |
|---|---|---|
| $R_m$ | `mirror_ratio` | Magnetic mirror ratio; $B_\mathrm{eff} = R_m B_\mathrm{sc}$ (`result.effective_field_nT`) |
| $\Delta U$ | `delta_u_eV` | Potential difference, surface minus spacecraft (eV) |
| $\rho$ | `bottom_ratio` | Relative level inside the loss cone; inside is $s\rho$, outside $s$ |
| $s$ | `scale` | Overall scale |
| | `sigma_deg` | Diffusion strength of $D_\mathrm{out}$ |
| $\phi$ | `concentration` | Beta-binomial concentration |
| $\alpha_c$ | | Pitch angle of the loss-cone boundary |
| $P_0$ | | Reflection indicator: 1 outside the boundary, 0 inside |

Search ranges are set with `mirror_ratio_bounds`, `delta_u_bounds_eV`, `bottom_ratio_bounds`, `scale_bounds`,
`sigma_bounds_deg`, and `concentration_bounds` in `FiniteBinFitSettings`.

The **beam** is enabled by default and disabled with `beam_enabled=False`. There are four shapes combining log-energy widths 0.15 and 0.30
with pitch widths 10° and 20°. The amplitude is chosen continuously within `beam_amplitude_bounds` (default 0.25–8)
by a one-dimensional golden-section search per shape at every evaluation.
By default (`beam_energy="delta_u"`) the centre energy is $-\Delta U$ and the beam is active only for $\Delta U < 0$,
following Halekas et al. (2008, 2011) for secondary electrons accelerated from a negatively charged surface.
With `beam_energy="free"`, the centre is fitted within `beam_energy_bounds_eV` (default 20–200 eV) as a seventh parameter
(`FiniteBinParameters.beam_energy_eV`, starting at 45 eV), and the beam is active whatever the sign of $\Delta U$,
so that a low-energy excess unrelated to $\Delta U$ does not produce a spurious negative $\Delta U$.
In results, `beam_template` is 0 for no beam, otherwise `1 + 2*energy_index + pitch_index`;
the amplitude is `beam_amplitude` and the centre `beam_energy_eV` ($-\Delta U$ for `delta_u`).

A **known efficiency ratio** is added to the model ratio as the observation's `model_offset_dex` (log10 of the affected/reference efficiency ratio).
`scale_prior_sigma_dex` places a zero-centered Gaussian prior on $\log_{10}s$ (count losses only).
Together with the offset, it moves the prior center to a calibration value.

### Angular transport $D_\mathrm{out}$

Enable it with `FiniteBinFitSettings(angular_transport="out")`; the default `"none"` is diagonal (no transport).

`result.d_out[j_out, j_in]` is the probability of moving from a source bin to a destination bin, and each column sums to 1. Its axis edges are
`result.transport_pitch_edges_deg`; use `100 * result.d_out` to display percentages.
It acts after reflection and the beam and never mixes energies. It is axisymmetric diffusion with no-flux boundaries at 0° and 90° of the folded hemisphere,
which keeps an isotropic flux stationary. `sigma_deg` is a diffusion parameter that matches the RMS direction change in the small-angle limit;
for large values it is not the simple Gaussian standard deviation of pitch-angle differences. Zero reproduces the diagonal case.

### Objective

| `loss` | Observable | Use |
|---|---|---|
| `"beta_binomial"` (default) | Affected counts given affected + reference trials | Main analysis; systematic overdispersion is absorbed by the concentration $\phi$ |
| `"binomial"` | Same | Comparison assuming statistical errors only |
| `"huber"` (default 0.1 dex) | $\log_{10}(a/r)$ | Flux-only inputs, comparison with earlier analyses |
| `"squared"` | $\log_{10}(a/r)$ | Comparison |

Count losses treat the affected count $a$ as binomial with $n = a + r$ trials. The affected probability is $q = \lambda/(1+\lambda)$
with $\lambda = x\,10^{c}R$, where $R$ is the model ratio, $x$ the affected/reference exposure ratio, and $c$ `model_offset_dex`.
The beta-binomial has mean $q$ and concentration $\phi$, estimated jointly with the other parameters.
`objective_sum` is the $-2\log L$ difference from the saturated binomial likelihood (the deviance), so differences between two fits read on a χ² scale.
Count losses need an observation with counts (created with `from_counts`).

The Huber objective of a residual $r$ is $r^2$ for $|r| \le 0.1$ and $0.2|r| - 0.01$ otherwise.
`objective_sum` and the per-cell `objective_mean` are returned. `root_mean_square_error_dex` is computed separately from squared residuals
and is distinct from the objective value.

### Cells used in the fit

`from_counts` defaults to `selection="total"` and `min_counts=1`, keeping cells with $a + r \ge 1$.
Cells with $a = 0$ enter the objective as information from inside the loss cone.
`selection="paired", min_counts=5` is the earlier selection that requires at least five counts on both sides. Because it selects on affected counts,
cells deep in the loss cone drop out and $\rho$ is biased upward. On synthetic counts with true $\rho = 0.15$,
paired + Huber gave 0.18–0.6 and total + beta-binomial gave 0.15.

With either selection, only energies with at least three pitch angles and exposure ratios between 0.01 and 100 are fitted.
Log ratios use a pseudocount of 0.5 and serve RMSE and figures. Instrument calibration and potential corrections happen before this fit,
and the incident flux keeps relative values across pitch angles within each energy.

Missing incident bins are interpolated in log flux within the same energy, with the nearest value at the ends.
Interpolated bins are returned in `interpolated_incident_bins`, and the missing cells themselves are not added to the objective.
Interpolated incident flux flows into observed cells through $D_\mathrm{out}$, so many gaps make input assumptions matter.
Reconstructions for unused energy rows stay NaN.

### Numerics

Reflection boundaries and beams are evaluated with composite 17-point Gauss quadrature, and each pitch bin is split into 8 by default.
The search uses seeded differential evolution (35 candidates, 180 generations, 2 seeds) and bounded Nelder–Mead (up to 650 iterations).
When `starts` is omitted, Nelder–Mead also starts from 12 points: $R_m$ = 1.2, 2, 5, 20 and $\Delta U$ = −50, 0, +50 eV,
because differential evolution alone missed the best minimum in 2 of 7 KAGUYA windows.
Everything from the response to the optimization runs in Rust, with no Python callbacks and no implicit fallback to Python.

### Quality checks

`local_converged` reports local solver termination, and `at_bounds` that a free parameter sits at its search bound.
`field_unconstrained` is True when any of the following `field_flags` is set.

| Flag | Condition |
|---|---|
| `no_contrast` | $\rho \ge 0.99$ |
| `barrier_unobserved` | All fitted cells lie on one side of the boundary |
| `field_at_search_bound` | $R_m$ at its search bound |
| `boundary_rows_insufficient` | Fewer energy rows with cells on both sides of the boundary than `min_boundary_rows` (default 3) |
| `loss_cone_unsupported` | `loss_cone_delta_bic` ≤ 0 with a count loss |

`loss_cone_delta_objective` is the objective difference between two models that allow free levels per energy row: no loss cone ($\rho = 1$)
and the fitted loss cone, with the same beam. A step only in energy is explained by both, so this difference measures whether pitch-angle structure is needed.
`loss_cone_delta_bic` subtracts $k\ln N$, where $k$ is the number of free parameters among $R_m$, $\rho$, and $\Delta U$.
On real data a certain fraction of windows is `loss_cone_unsupported`, and the fraction is higher for solutions with $R_m \le 1$.

### Profile intervals

No flags is not proof of identifiability, so adopt field values through `profile_mirror_ratio`.
It fixes $R_m$ on a grid (default ±1 dex, 21 points) and re-optimizes the other parameters from nearby solutions.
With count losses, $\Delta$`objective` ≤ 3.84 defines the 95% interval, with ends interpolated between grid points.

| Result | Meaning |
|---|---|
| `interval_nT` | 95% interval of $B_\mathrm{eff}$ |
| `interval_bounded=False` | The interval reached the edge of the grid |
| `improved_minimum=True` | The fit missed a better minimum, returned as `minimum_fit` |

Results of `evaluate` with fixed parameters have `local_converged` False.

### Fixing parameters

Equal lower and upper bounds fix a parameter. For example, to fix $B_\mathrm{eff}$ to a regional mean field and refit $\Delta U$ and the rest, use
`mirror_ratio_bounds=(area_mean_nT / b_sc, area_mean_nT / b_sc)`.
`bottom_ratio_bounds=(0.1, 0.1)` and `scale_bounds=(1, 1)` compare finite-bin at the fixed 0.1/1 levels.

## Halekas model

```python
from sopran.experimental.electron_reflection import HalekasFitSettings, fit_halekas_distribution

result = fit_halekas_distribution(counts, settings=HalekasFitSettings())
```

Halekas minimizes squared residuals of exposure-corrected natural-log ratios. Cells with $a + r$ below `min_cell_total_counts` (default 1) are dropped,
because empty cells get a ratio of 1 from the pseudocount and would look like the loss cone is absent.
`root_mean_square_error` is in natural-log units; divide by `np.log(10)` before comparing with a dex RMSE on the same input and mask.

| `edge_transition` | Model and search |
|---|---|
| `"hard"` (default) | Binary distribution with fixed backscatter (default 0.1) and outer level 1, evaluated at bin centers; grid search and refinement over $R_m$ and $\Delta U$ |
| `"probit"` | Same levels with a boundary width; L-BFGS-B starting from the hard solution and others |

Free `bottom`, `scale`, beams, and $D_\mathrm{out}$ belong to finite-bin. The probit width (boundary smoothing) and
$D_\mathrm{out}$ (transport between angles) are different parameters. When comparing RMSE, match units and masks,
and do not compare the Halekas Gaussian BIC with Huber values directly.

## For comparison: the robust mirror-transmission model

```python
from sopran.experimental.electron_reflection.mirror_transmission import (
    MirrorTransmissionSettings, fit_mirror_transmission, fit_mirror_transmission_variants, ratio_from_counts,
)

energy, pitch, ratio, b_sc = ratio_from_counts(counts)      # affected/reference rate ratio
fit = fit_mirror_transmission(energy, pitch, ratio, b_sc, settings=MirrorTransmissionSettings())
variants = fit_mirror_transmission_variants(energy, pitch, ratio, b_sc)   # four nested models
```

A comparison estimator ported from lunarsat (`robust_mirror_transmission_log_ratio_v1`). The natural log of the ratio is
modelled as $a_j + A_j\,P(E_j,\alpha_k)$ with per-energy baseline $a_j$ and contrast $A_j$ nuisance terms; only the
boundary and width shared across energy are estimated.

$$
\sin^2\alpha_c = p_0\left(1 + \frac{\Delta U + \beta_1 s^2 + \beta_2 s^3}{E - U_\mathrm{sc}}\right),\quad
s = \frac{E_*}{E - U_\mathrm{sc} + E_*},\qquad
P = \Phi\!\left(\frac{\ln\sin^2\alpha - \ln\sin^2\alpha_c}{\sigma(E)}\right)
$$

| Symbol | Name | Meaning |
|---|---|---|
| $p_0$ | `p0` | High-energy asymptote of $B_\mathrm{sc}/B_\mathrm{eff}$; `b_eff_nT = b_sc_reference_nT / p0` |
| $\Delta U$ | `delta_u_eff_eV` | Potential term (fixed to 0 in `mirror_only`) |
| $\beta_1, \beta_2$ | `smooth_beta1_eV`, `smooth_beta2_eV` | Low-energy correction of `smooth_low_energy`; the high-energy limit is unchanged |
| $\sigma$ | `sigma_ln_b` | Log-width of the boundary; `energy_broadened` uses $\sqrt{\sigma^2 + (U_w/(E+E_0))^2}$ |

The loss is `soft_l1` (`robust_f_scale` = 0.2) with `scipy.optimize.least_squares`. `fit.success` requires both optimiser
convergence and a boundary inside $0<\sin^2\alpha_c<1$; compare variants through the difference from
`no_edge_rmse_log` (row means only) and through `aic_log`/`bic_log`. Relative to the lunarsat version only the initial guess
(per-row threshold crossings) is simplified; model, bounds and loss are the same. Its input and objective differ from the
finite-bin count likelihood, so the numbers are not compared directly.
