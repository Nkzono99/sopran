# Electron reflectometry Rust backend design

## Goal

The global S1/S2 hard-edge fit must become cheap enough to use as a first-pass
classifier over temporally integrated observations. The backend must preserve the
existing raw-count negative-binomial likelihood and must not introduce fine-grained
Python/Rust calls inside an optimizer iteration.

The first production target is the hard-transition family:

- `no_edge`, `mirror_only`, and `electrostatic`
- constant and energy-band contrast
- optional secondary beam
- one fixed reference-sensor gain, `n_sensor - 1` relative gains, and per-sensor dispersion
- finite energy-bin quadrature, detector response, known background, and dead time

Smooth transitions remain in Python until hard-fit equivalence and performance are
established.

## Measured baseline

The September 2026 profile used the same 20--1500 eV, 12-spectrum-knot settings as
the global population evaluation.

| Measurement | Result |
| --- | ---: |
| Hard fit wall time | 72.7 s |
| Time in `_objective` | 69.1 s (95%) |
| Time in `_predicted_surfaces` | 62.6 s (86%) |
| Objective calls | 12,315 |
| Sensor-surface calls | 24,732 |

Before the Rust backend, five hard-only real-data fits took 61--84 s, with a mean
of about 72 s. On the same two-sample smoke configuration, the Python baseline
had a 68.2 s median, the Rust objective implementation had an 8.01 s median, and
the Rust-side parallel finite-difference gradient implementation had a 4.18 s median. The final hard
path was therefore about 16 times faster than the matched Python baseline.

The 32-case `auto` evaluation still had a 39.9 s median and 147 s p90 because
smooth refinement remains in Python. Production consequently defaults to
hard-only; `auto` and `smooth` are explicit sensitivity-analysis modes.

Use `evaluate_global_joint_population.py --edge-transition hard` to reproduce a
hard-only population run with the same sampling and output schema as `auto`.
An identical two-sample CLI smoke run took a 46.9 s median with `hard` and a
69.8 s median with `auto` (1.49x); both samples produced identical selected
models and physical estimates. This small comparison supplements rather than
replaces the five-case and 32-case measurements above.

The dominant cost is not the hard boundary formula itself. SciPy L-BFGS-B estimates
gradients by finite differences, repeatedly crossing Python/NumPy code that allocates
small temporary arrays and loops over energy quadrature samples.

## Boundary

Add one stateful PyO3 class to the existing `sopran._native` extension:

```python
from sopran import _native

problem = _native.GlobalHardProblem(
    observations=packed_observations,
    layout=packed_layout,
    settings=packed_settings,
)

value = problem.objective(parameters)
value, gradient = problem.objective_and_gradient(parameters)
```

Construction copies and validates all immutable observation arrays once. Objective
calls pass only a contiguous parameter vector. The Python code remains responsible
for candidate orchestration, BIC gates, quality rules, result dataclasses, and plots.
This keeps policy in Python while moving the repeated numerical loop as one unit.

Do not expose separate FFI calls for transmission, interpolation, response matrices,
or likelihood terms. Those calls would occur tens of thousands of times per fit and
repeat the overhead problem seen in earlier Rust experiments.

## Rust data model

`GlobalHardProblem` owns a `Vec<SensorObservation>` and a compact `ParameterLayout`.
Each sensor stores contiguous row-major arrays:

- counts, exposure, validity mask, and affected-pitch mask
- energy quadrature samples and weights
- energy and pitch edges
- optional detector-response matrix
- known background counts and live-time capacity
- precomputed interpolation indices and weights for spectrum and baseline knots

Precompute every quantity independent of the parameter vector. In particular, avoid
searching knots, reshaping arrays, allocating rate surfaces, or rebuilding masks in
`objective()`.

The Rust implementation should use reusable scratch buffers owned by the problem.
`objective()` therefore needs mutable access guarded by the GIL-free fit call, or a
per-thread workspace when starts are evaluated in parallel.

## Gradient strategy

The first equivalence milestone may use finite differences entirely inside Rust. This
removes Python/NumPy overhead but does not reduce the number of likelihood evaluations.

The initial API exposes only `objective` and `objective_and_gradient`; SciPy retains
optimizer ownership. A later Rust `fit()` requires a separately reviewed optimizer,
stopping criteria, and result schema.

The current production path returns the objective and a Rayon-parallel finite-difference
gradient together. Analytic
derivatives are straightforward for spectrum knots, baseline knots, gain, dispersion,
contrast, beam parameters, and dead-time correction. The hard boundary is piecewise
differentiable after finite pitch-bin integration; derivatives are zero outside the
crossed pitch bin and analytic inside it. At exact bin-edge crossings, use a defined
one-sided derivative and verify optimizer stability with nearby starts.

Keeping SciPy with `jac=True` is the current bridge. Moving L-BFGS-B
into Rust is useful only after objective-plus-gradient equivalence is proven; it is not
required to eliminate the high-frequency FFI problem.

The negative-binomial value requires `lgamma`; its dispersion derivative requires
`digamma`. Select a maintained Rust special-function implementation explicitly before
coding and verify it against SciPy over the full production count and dispersion bounds,
including extreme and near-boundary values. Do not accept a crate solely because it
compiles.

## Equivalence tests

For fixed parameter vectors, compare Python and Rust for every candidate family:

1. predicted mean counts per sensor
2. normalized and incident surfaces
3. negative-binomial log likelihood
4. smoothness penalty and total objective
5. detector response, background, and dead-time edge cases
6. zero counts, missing cells, and both affected-side orientations

Use absolute and relative tolerances appropriate for `f64`; objective differences must
be much smaller than the BIC decision margins. Add finite-difference checks for every
finite-difference component now and every future analytic-gradient component away
from hard-boundary discontinuities.

For end-to-end validation, refit the existing 32-case gallery and compare selected
model, transition, beam decision, mirror ratio, effective field, delta-U, BIC, and
reconstruction residual. Any model-selection difference must be investigated rather
than accepted as floating-point noise.

## Rust optimizer evaluation

The backend now evaluates hard-edge candidates, including the optional secondary beam,
without returning to Python/NumPy for individual likelihood calls. SciPy owns only the
bounded L-BFGS-B iteration and candidate orchestration.

Do not replace SciPy with a generic "SciPy for Rust" crate as one dependency change. The
required behavior is specifically box-constrained L-BFGS-B, including stopping rules,
bound diagnostics, and reproducible convergence from existing starts. The candidates are:

- [`argmin`](https://argmin-rs.org/): mature optimizer framework, but its documented
  L-BFGS solver is not a drop-in L-BFGS-B replacement.
- [`lbfgsb`](https://docs.rs/lbfgsb/): direct box-constrained API, but it wraps the
  classic L-BFGS-B implementation and needs wheel/platform validation.
- [`lbfgsb-rs-pure`](https://docs.rs/lbfgsb-rs-pure/): a direct pure-Rust port with
  bounds and iteration callbacks. Version 0.1.2 is the closest functional match, but
  it is still too new to replace SciPy without end-to-end convergence tests.
- [`basin`](https://github.com/jolars/basin): native Rust L-BFGS-B candidate, currently
  too young to adopt without a dedicated equivalence and maintenance review.

The next optimizer milestone is an optional Rust-owned fit entry point behind the same
packed problem. It must run alongside SciPy in benchmarks and match final objective,
active bounds, physical parameters, BIC decisions, and failure classification before it
can become the default. Moving the objective and beam path to Rust is independent of that
decision and already removes the high-frequency FFI/NumPy cost.

## Performance gates

### 16-second record-likelihood trial

The numbers below are a historical v2 baseline. That run applied coverage and
affected-side hard filters and shared mirror ratio rather than effective field
inside each window. It must not be used as a current scientific result; a new
full-day run is required for production timing and selection fractions.

The 2008-08-20 full-day trial retained eight native records per complete 16-second
window as independent likelihood terms. It used six worker processes, two Rayon threads
per worker, eight spectrum knots, one optimizer start, 120-iteration candidate limits,
hard edges, and beam disabled for the first pass.

| Measurement | Result |
| --- | ---: |
| Fixed UTC windows | 5,400 |
| Completed fits | 1,726 |
| Failed / skipped | 21 / 3,653 |
| Selected edges | 425 |
| Fit time p50 / p90 / max | 8.55 / 11.32 / 15.89 s |
| Wall time | 2,463 s (41.1 min) |

The separate 16-observation beam microbenchmark measured 10.82 ms for one Python
objective and 2.72 ms for the matched Rust objective (4.0x), with an absolute objective
difference of $7.9\times10^{-10}$. Computing four selected finite-difference components
took 6.15 ms versus 14.35 ms for all 29 components. These kernel measurements explain
the screening improvement but do not replace the full-day performance gate.

Measure the same fixed real-data cases before each stage. The exploratory measurements
above were single runs without warm-up on a 13th Gen Intel Core i7-1360P. The five cases
were `20080820-01-02`, `20081126-01-01`, `20071227-01-01`, `20080620-01-01`, and
`20090304-01-01`. Production benchmark artifacts must record CPU, thread limits,
build profile, case IDs, warm-up, repetitions, dependency versions, and commit.

| Stage | Required result |
| --- | --- |
| Rust objective, Rust finite differences | at least 3x faster than Python hard fit |
| Rust objective plus gradient | median below 15% of the matched Python baseline |
| Production batch | p90 below 20% of baseline with identical model decisions |

Report median, p90, maximum, objective-call count, and model agreement. Do not claim a
speedup from a micro-kernel benchmark alone.

## Dataset-scale implication

The current 120 s evaluation cadence selects one native S1/S2 pair nearest each bucket
center; it is downsampling, not temporal integration. Eight sampled days contained
74,520 native joint pairs but only 1,297 two-minute samples, a ratio of 57.5. Applying
that ratio to the 50,011 two-minute samples gives roughly 2.9 million native joint
pairs over the available period.

Even a 10 s hard fit is too expensive for every native pair. Production processing
should therefore:

1. align native S1/S2 records;
2. group contiguous records into 8, 16, or 32 s likelihood windows;
3. run a cheap hard-edge or two-dimensional evidence screen;
4. run the full hard fit only on supported windows;
5. refine with the smooth model only for edge candidates and ambiguous cases.

For the current negative-binomial model, do not simply sum counts and exposure while
reusing the same dispersion: independent NB variables are not generally closed under
that operation. Retain one likelihood term per record and share physical parameters
within the window. A summed representation is allowed only after deriving and testing
its effective dispersion, and only when field direction, response, background, and
dead-time variation satisfy explicit aggregation tolerances. This windowed likelihood
uses more information than selecting one representative record without asserting an
invalid NB equivalence.

## Implementation order

1. Add packed Rust structs and a fixed-vector objective without Python fallback.
2. Add Python/Rust equivalence tests for identity response and no beam. (complete)
3. Add detector response, background, dead time, contrast band, grouped records, and beam. (complete)
4. Benchmark Rust finite differences on the fixed five-case set.
5. Add objective-plus-gradient and connect SciPy with `jac=True`. (complete, finite difference)
6. Run the 32-case selection-equivalence and runtime gate.
7. Keep the native hard backend as the production default and retain Python as a
   tested reference implementation.
