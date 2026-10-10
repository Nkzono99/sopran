# Experimental APIs

This namespace contains reusable research code, not supported instrument APIs.
Import the specific model or adapter explicitly. Importing `sopran` or
`sopran.experimental` does not load these implementations.

## Inventory

| Modules | Status and open questions | Promotion requirements |
|---|---|---|
| `electron_reflection.finite_bin` | Folded finite-bin bottom/scale model, beta-binomial count likelihood (Huber for flux-only input), optional D_out, loss-cone test and Rm profile | Recovery against an independent forward model (e.g. test-particle tracing) and independent field validation; convergence is separate from identification |
| `electron_reflection.halekas` | Fixed-backscatter hard/probit distribution comparison | Defined uncertainty limits and representative independent comparisons |
| `electron_reflection.common` | Shared paired-count input, exposure validation and boundary convention | Preserve input units, masks, zero/missing distinctions |
| `kaguya.er` | Shared ESA/LMAG/SPICE input preparation and explicit estimator calls | Calibration, pairing, exposure, geometry and reader regression tests |
| `waves`, `kaguya.waves` | Candidate detectors, ridge tracking, clustering and presets | Frozen feature/quality contracts, calibrated labels and instrument comparisons |

ER inventory reviewed: 2026-10-02; finite-bin count likelihood added 2026-10-10. Finite-bin and Halekas are the retained
estimators. Paired-count, binary, joint, global-joint and incident models,
their dedicated research helpers and the former standalone JSONL CLI are retired.
See `docs/experimental/er-methods.md`.
Historical runners, source snapshots and saved products stay under `working/`.
No ER fit or wave candidate is promoted by this cleanup.

## Rules

- Dependencies point from experiments to standard APIs, never the reverse.
- Optional model dependencies belong in the `experimental` extra. Use mission
  and plotting extras separately.
- Keep typed inputs, units, missing/zero semantics and focused regressions.
- ER results are returned without automatic Store writes. Save settings and
  provenance with each result; do not reuse another model's stored product.
- Native kernels are private implementation details in `sopran._native`.
- Put runs, large outputs, research reports and surveys under `working/`.
- Before release, decide whether to promote, retain or remove each experiment.
  Promotion requires documentation and tests; numerical agreement alone
  does not imply physical accuracy.
- Removed experimental imports have no compatibility aliases or fallback.

Usage: `docs/experimental/`.
