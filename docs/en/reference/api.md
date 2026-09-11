# API Reference

The generated Python API reference is built on the primary reference page to
avoid duplicate mkdocstrings anchors in a single MkDocs build.

Use:

- [Primary API Reference](../../reference/api.md)
- [Schemas](schemas.md)
- [Configuration](configuration.md)
- [Status](status.md)

Core entry points:

| Object | Role |
| --- | --- |
| `spn.Store` | Data root, raw files, parquet datasets, registries |
| `spn.Project` | Analysis workspace and artifact context |
| `spn.View` / `spn.view` | Temporary analysis lens for time, region, frame, and backend overrides |
| `spn.Kaguya` | KAGUYA/SELENE mission API |
| `spn.Artemis` | ARTEMIS mission API |
| `spn.Moon` | Moon map API |
| `spn.PlotStack` | Stacked time-series visualization |
| `spn.FrameContext` | Frame-transform provenance boundary |
| `sopran.analysis.waves.detect_wave_candidates` | Mission-independent multi-label spectral wave detector |
| `sopran.analysis.waves.fit_background_residual_clustering` | Run-scoped exploratory residual clustering |
| `sopran.missions.kaguya.KAGUYA_WFC_V1` | Versioned KAGUYA WFC-H detector preset |
