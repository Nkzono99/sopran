# Experimental Electron Reflectometry

ER estimates a reflection barrier from an energy-pitch distribution.
Numerical fit success does not establish physical magnetic-field accuracy.

See [ER methods and code](er-methods.md) for each estimator's input and objective.

## Folded finite-bin fitting with optional D_out

```python
from sopran.experimental.electron_reflection import (
    FiniteBinFitSettings, FiniteBinObservation, fit_finite_bin_distribution,
)
observation = FiniteBinObservation(
    energy_edges_eV=energy_edges, pitch_edges_deg=pitch_edges,
    incident_flux=reference_flux, observed_log_ratio_dex=log10_ratio,
    b_sc_nT=b_sc, fit_valid=valid,
)
settings = FiniteBinFitSettings(angular_transport="out", loss="huber", huber_delta_dex=0.1)
result = fit_finite_bin_distribution(observation, settings=settings)
```

`angular_transport="none"` is the default Diagonal model; `"out"` enables D_out.
The adapter exposes the same operation as
`er.effective_field.fit_finite_bin(observation, settings=settings)`.

`FiniteBinObservation.from_counts(counts, energy_edges_eV=..., pitch_edges_deg=...)`
prepares exposure-corrected log10 ratios with a 0.5 pseudocount. Defaults require
both counts >=5, >=3 pitch cells per energy and an exposure ratio in [0.01, 100].
Supply actual edges: positive energy and folded 0–90 degree pitch.
For already prepared ratios, construct the observation directly. Calibration and
potential corrections are upstream; preserve relative incident flux across pitch.

$$
N_{out}=D_{out}\{s[\rho+(1-\rho)P_0]N_{in}+N_{beam}\},
\qquad \sin^2\alpha_c=(1+\Delta U/E)/R_m.
$$

`bottom_ratio` is rho and `scale` is s; inside/outside levels are s*rho and s.
Beam is retained by default (`beam_enabled=False` disables it). The 17 templates
are none plus log-energy widths 0.15/0.30, pitch widths 10/20 deg and amplitudes
0.5/1/2/4. Template 0 is none; others are
`1 + 8*energy_index + 4*pitch_index + amplitude_index`.
The response uses split 17-point quadrature, eight pitch subdivisions by default
and ideal uniform log-energy/pitch averaging. Seeded DE (35 candidates, 180
generations, two seeds) and bounded Nelder–Mead (up to 650 iterations) run in Rust.
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
`local_converged` reports local termination, `at_bounds` lists free parameters
at search limits, and `field_unconstrained` flags contrast loss, an unseen barrier
or Rm at a search limit. False does not certify identification. Fixed-parameter
`evaluate` has `local_converged=False`. Settings are retained; Store saving is explicit.

## Fixed-backscatter Halekas distribution

Use `fit_halekas_distribution(counts, settings=HalekasFitSettings(...))`.
Both estimators share `ElectronReflectionCounts`, an energy-by-folded-pitch input.
Halekas minimizes squared residuals of the exposure-corrected natural-log ratio.
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
