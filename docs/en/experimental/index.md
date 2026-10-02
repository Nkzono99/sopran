# Experimental APIs

`sopran.experimental` contains opt-in, reusable research models and adapters.
Names, defaults and storage formats may change or disappear without compatibility
aliases. Importing `sopran` does not load these implementations.

```shell
python -m pip install "sopran[kaguya,viz,experimental]"
```

| Scope | Import |
|---|---|
| ER estimators | `sopran.experimental.electron_reflection` |
| KAGUYA ER adapter | `sopran.experimental.kaguya.er.KaguyaErInstrument` |
| Wave candidates, ridges and clusters | `sopran.experimental.waves` |
| WFC presets and candidate quality rules | `sopran.experimental.kaguya.waves` |

See [ER usage](electron-reflectometry.md) and [wave candidates](waves.md).
The [ER method inventory](er-methods.md) distinguishes estimator entry points and objectives.
Instrument readers, calibration, native bins, frames, Store and plotting remain
in the standard API. `Kaguya.er` and root-level ER symbols have been removed.
Former `sopran.analysis` and `sopran.missions.kaguya.er*` imports have no shims.
Shared magnetic interpolation remains in `missions.kaguya.magnetic_geometry`.

ER retains finite-bin and Halekas. Each returns a typed fit result for callers
to save with settings and provenance. Historical Store products remain
accessible through the standard dataset reader.

The inventory in `src/sopran/experimental/README.md` records open questions and
promotion requirements. Review it before each release: promote, retain, or
remove. Promotion needs typed contracts, units, provenance, regression tests and
documented validation limits. Numerical agreement is not physical validation.
Individual runs, research reports and literature reviews belong in `working/`.
