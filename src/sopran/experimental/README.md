# Experimental APIs

This namespace contains reusable research code, not supported instrument APIs.
There are no compatibility shims for former imports or `Kaguya.er`.
Import the specific model or adapter explicitly. `import sopran` and
`import sopran.experimental` do not load experimental implementations.

## Inventory

| Modules | Status and open questions | Promotion requirements |
|---|---|---|
| `electron_reflection.model`, `binary_surface`, `halekas` | Competing edge/count/distribution models; physical identifiability unresolved | Defined estimator, assumptions, units, uncertainty limits, synthetic recovery and independent comparisons |
| `electron_reflection.joint`, `global_joint` | Sensor response, normalization and selection under evaluation | Response/zero-count tests, frozen selection policy and representative comparisons |
| `electron_reflection.incident`, `integrated`, `temporal`, `identifiability` | Incident shape, beam separation and warm starts under evaluation | Recovery and optimizer stability across input regimes; measured runtime |
| `electron_reflection.beam_diagnostics`, `upstream` | Diagnostic decomposition and context matching | Explicit conventions and scope, source/units and reproducible examples |
| `kaguya.er`, `er_timeseries`, `er_catalog`, `schema` | KAGUYA adapters and candidate products | Stable model contract plus reader, geometry, cache and cadence tests |
| `kaguya.er_*validation`, `er_population` | Research evaluation helpers | Demonstrated reuse beyond a particular study; otherwise move to `working/` |
| `waves`, `kaguya.waves` | Candidate detectors, ridge tracking, clustering and presets | Frozen feature/quality contracts, calibrated labels where claimed, instrument comparisons |

Last boundary review: 2026-09-11, after checkpoint `d5208e9`.
No ER fit or wave candidate is promoted by this reorganization.

## Rules

- Dependencies point from experiments to standard APIs, never the reverse.
- Optional model dependencies belong in the `experimental` extra. Use the
  mission and plotting extras separately when needed.
- Keep typed inputs, units, missing/zero semantics, and focused regression tests.
- ER defaults use `experimental.kaguya.er.*` Store IDs. Do not publish trial
  products under a standard product's cache key. Preserve settings and provenance.
- Rust kernels remain private implementation details in `sopran._native`.
- Put run scripts, large outputs, research reports and literature surveys under
  `working/`, not in this package or the public documentation navigation.
- Before each release, decide for each row: promote, retain with a stated
  unresolved question, or remove. Promotion requires documentation and tests;
  numerical agreement does not imply physical accuracy.

Usage and migration: `docs/experimental/`.
