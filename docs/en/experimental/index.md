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
Instrument readers, calibration, native bins, frames, Store and plotting remain
in the standard API. `Kaguya.er` and root-level ER symbols have been removed.
Former `sopran.analysis` and `sopran.missions.kaguya.er*` imports have no shims.
Shared magnetic interpolation remains in `missions.kaguya.magnetic_geometry`.

ER defaults use `experimental.kaguya.er.*` Store keys, separate from former
products. Existing data is neither deleted nor migrated automatically.
Model settings remain part of variant metadata.

The inventory in `src/sopran/experimental/README.md` records open questions and
promotion requirements. Review it before each release: promote, retain, or
remove. Promotion needs typed contracts, units, provenance, regression tests and
documented validation limits. Numerical agreement is not physical validation.
Individual runs, research reports and literature reviews belong in `working/`.
