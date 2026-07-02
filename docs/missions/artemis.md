# ARTEMIS

ARTEMIS provides lunar-orbiting THEMIS probes P1 and P2 through a mission-first
API.

```python
art = spn.Artemis()
time = spn.day("2011-07-01")
plan = art.p1.fgm.magnetic_field.plan(time)
ion_plan = art.p1.esa.ion_energy_flux.plan(time)
```

## Implemented

- P1 and P2 probe objects.
- FGM `magnetic_field` endpoint with schema and plan objects.
- ESA `ion_energy_flux` endpoint with schema and plan objects.
- Store-backed normalized parquet loading for existing
  `artemis.<probe>.fgm.magnetic_field` and
  `artemis.<probe>.esa.ion_energy_flux` datasets.
- Project case context through `case.artemis.p1.fgm.magnetic_field` and
  `case.artemis.p1.esa.ion_energy_flux`.
- `line()` / `lines(components=...)` PlotItem generation for FGM vector panels
  and `spectrogram()` PlotItem generation for ESA energy spectra.
- Bilingual package guides via `art.guide(language="ja")`,
  `art.guide(language="en")`, `art.p1.fgm.guide(language=...)`, and
  `art.p1.esa.guide(language=...)`.

```python
stack = case.stack(
    case.artemis.p1.esa.ion_energy_flux.spectrogram(y="energy", log_color=True),
    case.artemis.p1.fgm.magnetic_field.lines(components="xyz"),
)
plot_result = stack.plot()
fig = plot_result.fig
```

## Next Work

- Connect CDAWeb/HAPI discovery.
- Add raw download policy and provenance.
- Preserve coordinate frame, vector component, and energy-bin metadata in the
  normalized schema.
