# Experimental Electron Reflectometry

ER estimates a reflection barrier from an energy-pitch distribution.
Numerical fit success does not establish physical magnetic-field accuracy.

See [ER methods and code](er-methods.md) for each estimator's input and objective.

## Folded finite-bin fitting with optional D_out

The default objective is the beta-binomial likelihood of paired counts.
`angular_transport="none"` (default) is the Diagonal model; `"out"` enables D_out.

```python
from sopran.experimental.electron_reflection import (
    FiniteBinFitSettings, FiniteBinObservation, fit_finite_bin_distribution,
    profile_mirror_ratio,
)
# counts is ElectronReflectionCounts; edges are the calibrated bin edges.
observation = FiniteBinObservation.from_counts(
    counts, energy_edges_eV=energy_edges, pitch_edges_deg=folded_pitch_edges,
)
result = fit_finite_bin_distribution(observation, settings=FiniteBinFitSettings())
profile = profile_mirror_ratio(observation, result)
```

The adapter exposes `er.effective_field.fit_finite_bin(...)` and
`er.effective_field.profile_finite_bin(observation, result)`.

| `loss` | Data | Use |
|---|---|---|
| `"beta_binomial"` (default) | affected count given affected + reference | Main analysis; concentration phi absorbs systematic over-dispersion |
| `"binomial"` | same | Statistical-noise-only comparison |
| `"huber"` (0.1 dex) | log10(a/r) | Flux-only input, comparison with earlier runs |
| `"squared"` | log10(a/r) | Comparison |

Count losses model the affected count as binomial in n = a + r with
q = lambda/(1+lambda), lambda = x 10^c R, where R is the model ratio, x the
affected/reference exposure ratio and c `model_offset_dex`. The beta-binomial
has mean q and concentration phi, fitted jointly. `objective_sum` is a deviance
(-2 log L relative to the saturated binomial), so differences read on a chi-square scale.

`from_counts` defaults to `selection="total"`, `min_counts=1`, keeping cells with
a + r >= 1, including a = 0 inside the loss cone. `selection="paired",
min_counts=5` is the former D-gallery cut; selecting on the affected count
censors deep loss-cone cells and biases rho upward (synthetic truth rho = 0.15:
0.18–0.6 with paired + Huber, 0.15 with total + beta-binomial). Both selections
require >=3 pitch cells per energy and an exposure ratio in [0.01, 100].
Log10 ratios use a 0.5 pseudocount for RMSE and plots. Calibration and potential
corrections are upstream; preserve relative incident flux across pitch.

$$
N_{out}=D_{out}\{s[\rho+(1-\rho)P_0]N_{in}+N_{beam}\},
\qquad \sin^2\alpha_c=(1+\Delta U/E)/R_m.
$$

`bottom_ratio` is rho and `scale` is s; inside/outside levels are s*rho and s.
Beam is retained by default (`beam_enabled=False` disables it). Its four shapes are
log-energy widths 0.15/0.30 and pitch widths 10/20 deg; the amplitude is a
continuous golden-section optimum within `beam_amplitude_bounds` (0.25–8) at
each evaluation. `beam_template` is 0 (none) or `1 + 2*energy_index + pitch_index`;
`beam_amplitude` reports the amplitude.
`model_offset_dex` adds a known log10 affected/reference efficiency to the model.
`scale_prior_sigma_dex` places a zero-centred Gaussian prior on log10 s (count
losses only); combine it with an offset to centre it on a calibration.

The response uses split 17-point quadrature, eight pitch subdivisions by default
and ideal uniform log-energy/pitch averaging. Seeded DE (35 candidates, 180
generations, two seeds) and bounded Nelder–Mead (up to 650 iterations) run in Rust.
Without `starts`, Nelder–Mead also refines twelve starts (Rm 1.2/2/5/20 by
DeltaU −50/0/+50 eV); DE alone missed the best basin in 2 of 7 KAGUYA windows.
There are no optimizer callbacks to Python or silent Python fallbacks.

Huber is r² for |r|<=0.1 dex and 0.2|r|−0.01 otherwise. `objective_sum` and
`objective_mean` are distinct from `root_mean_square_error_dex`.
Equal bounds fix a parameter: `(area_mean_nT/b_sc, area_mean_nT/b_sc)` for
`mirror_ratio_bounds` fixes Beff while DeltaU and other nuisance parameters refit.
Fixed `(0.1, 0.1)` bottom and `(1, 1)` scale give a finite-bin 0.1/1 comparison.

`d_out[j_out, j_in]` is a transition probability with unit column sums. Use
`100 * result.d_out` for a 0–30% display and `transport_pitch_edges_deg` as edges.
This reduced axisymmetric diffusion has no energy mixing, no flux across folded
pitch 0/90 deg and stationary isotropic flux. `sigma_deg` corresponds to RMS
directional deflection in the small-angle limit; at large values it is not a
Gaussian pitch-difference standard deviation. Zero width recovers Diagonal.

Missing incident bins are log-interpolated per energy, with nearest values at
the ends; they remain excluded from the objective. Their assumed flux can feed
observed angles through D. `interpolated_incident_bins` reports their count;
inactive energy rows retain NaN reconstructions.
`local_converged` reports local termination and `at_bounds` lists free parameters
at search limits. `field_unconstrained` is true when any `field_flags` entry is set:
`no_contrast` (rho >= 0.99), `barrier_unobserved` (all cells on one side),
`field_at_search_bound`, `boundary_rows_insufficient` (fewer than
`min_boundary_rows`, default 3, energy rows with cells on both sides of the
boundary) or `loss_cone_unsupported` (count losses with `loss_cone_delta_bic <= 0`).
`loss_cone_delta_objective` compares free per-energy levels without (rho = 1) and
with the fitted loss cone at the fitted beam, so an energy-only step does not count
as pitch structure; `loss_cone_delta_bic` subtracts k ln N for the free Rm/rho/DeltaU.
In 288 KAGUYA windows 21% were flagged (33% with Rm <= 1, 11% with Rm > 1).

A false flag does not certify identification; use `profile_mirror_ratio` before
adopting a field. It fixes Rm on a grid (default ±1 dex, 21 points) and refits the
rest from neighbours. For count losses delta objective <= 3.84 gives a 95%
interval with interpolated ends; `interval_bounded=False` means the interval
reached the grid end, and `improved_minimum=True` means the fit missed a better
basin, returned as `minimum_fit`. For example, 2008-02-10 03:03:36 UTC fits
124.7 nT with a 95% interval of 15.7–124.7 nT that includes the ~17 nT Huber solution.
Fixed-parameter `evaluate` has `local_converged=False`. Settings are retained;
Store saving is explicit.

## Fixed-backscatter Halekas distribution

Use `fit_halekas_distribution(counts, settings=HalekasFitSettings(...))`.
Both estimators share `ElectronReflectionCounts`, an energy-by-folded-pitch input.
Halekas minimizes squared residuals of the exposure-corrected natural-log ratio.
Cells with a + r below `min_cell_total_counts` (default 1) are excluded; empty
cells would otherwise read as a pseudocount ratio of one.
Its RMSE uses natural logarithms; divide by `np.log(10)` to compare with dex RMSE
on the same input and mask.

The default `edge_transition="hard"` evaluates fixed backscatter (default 0.1)
and outside level 1 at bin centers, using grid search and refinement for Rm and
delta U. `"probit"` adds edge width and uses multistart L-BFGS-B seeded from the
hard fit. D_out, beam, free bottom and free scale belong to finite-bin.
Probit width and angular transport have distinct meanings.

## KAGUYA input

```python
import sopran as spn
from sopran.experimental.kaguya.er import KaguyaErInstrument
from sopran.experimental.electron_reflection import (
    FiniteBinObservation, FiniteBinFitSettings, HalekasFitSettings,
)

er = KaguyaErInstrument(spn.Kaguya())
pitch_counts = er.pitch_angle_spectrum(spn.day("2008-04-26"))
counts = er.paired_counts(
    pitch_counts, index=0, magnetic_field=magnetic_field, position=position,
)
comparison = er.effective_field.fit_halekas(counts, settings=HalekasFitSettings())
observation = FiniteBinObservation.from_counts(
    counts, energy_edges_eV=energy_edges, pitch_edges_deg=folded_pitch_edges,
)
result = er.effective_field.fit_finite_bin(
    observation, settings=FiniteBinFitSettings(angular_transport="out"),
)
```

Geometry vectors must share a frame. `paired_counts` selects one time sample and
pairs symmetric hemispheres: low pitch is affected when +B points outward,
otherwise high pitch. An explicit low/high selection is also supported.
Supply actual calibrated bin edges for finite-bin input.
Exposure resolves from an explicit array, the spectrum coordinate, or a recorded
equal-exposure assumption. An explicit array broadcasts to the selected
sample's energy-by-pitch cells.

`pitch_angle_spectra(..., align=False)` preserves independent native sensor times.
The combined and separate readers share calibration, ESA/LMAG loading and SPICE
preparation. Use `kaguya`, `experimental`, and `viz` extras as needed.

## Results and migration

Each estimator returns its own typed result without automatic Store writes.
Save settings, inputs, masks, bins and code hashes with the result.
B_eff is Rm times Bsc in nT; delta U is surface minus spacecraft in eV.
These effective parameters are not a crustal-field vector or a validated
absolute surface potential.

The paired-count, binary, joint and global-joint estimators and their dedicated
timeseries, catalog, schema, likelihood-scan and evaluation helpers are removed.
Use `fit_finite_bin` / `fit_halekas` instead of former `fit`, `fit_joint`,
`fit_global_joint`, `fit_timeseries` or `build` methods.
Stored products remain accessible through the standard Store dataset reader.
