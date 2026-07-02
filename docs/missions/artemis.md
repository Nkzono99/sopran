# ARTEMIS

ARTEMIS provides lunar-orbiting THEMIS probes P1 and P2 through a mission-first
API.

```python
art = spn.Artemis()
time = spn.day("2011-07-01")
plan = art.p1.fgm.magnetic_field.plan(time)
```

## Implemented

- P1 and P2 probe objects.
- FGM `magnetic_field` endpoint with schema and plan objects.
- Store-backed normalized parquet loading for existing
  `artemis.<probe>.fgm.magnetic_field` datasets.
- Project case context through `case.artemis.p1.fgm.magnetic_field`.
- `line()` PlotItem generation for FGM vector panels.
- Bilingual package guides via `art.guide(language="ja")`,
  `art.guide(language="en")`, and `art.p1.fgm.guide(language=...)`.

```python
stack = case.stack(
    case.artemis.p1.fgm.magnetic_field.line(),
)
fig = stack.plot()
```

## Next Work

- Connect CDAWeb/HAPI discovery.
- Add raw download policy and provenance.
- Preserve coordinate frame and vector component metadata in the normalized
  schema.
