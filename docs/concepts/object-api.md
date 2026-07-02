# Object API

SOPRAN uses object navigation for discoverability:

```python
kg = spn.Kaguya()
kg.esa1.counts
kg.esa1.energy_flux
art = spn.Artemis()
art.p1.fgm.magnetic_field
```

Attribute access returns endpoint objects only. It should not download, decode,
scan, collect, or compute data. Execution happens at explicit methods:

- `load(time)`: load typed data into memory.
- `plot(time)`: convenience load-and-plot path.
- `plan(time)`: inspect files, dataset IDs, or execution intent.
- `schema()`: inspect variables, dimensions, units, and aliases.
- `guide()`: return a Markdown guide object for notebooks and docs.
- `help()`: interactive alias for `guide()`.
- `example()`: return a short runnable Markdown example when implemented.

Loaded objects such as `SopranArray` also expose `info()`. It returns an
`InfoPage` with variable dimensions, time coverage, units, description, and
input file count when available, so notebook displays and console output use the
same lightweight page model as mission and endpoint objects.
`SopranArray.schema` is the underlying `VariableSchema`; it is callable, so
`SopranArray.schema()` returns the same object for endpoint-like access.
`SopranArray.trange` aliases the loaded `TimeRange`, and
`SopranArray.metadata` returns a JSON-ready provenance snapshot with the object
type, name, time range, variable schema, source files, and optional derived
operations.
APIs that accept `context=` can use either `context=loaded` or
`context=loaded.metadata`; both record the same loaded-object provenance.
For table workflows, `SopranArray.to_polars()` flattens the loaded xarray
coordinates and values into a Polars DataFrame, and `to_pandas()` returns the
same table as a pandas DataFrame.
Common xarray operations such as `sel()`, `where()`, and `mean()` are delegated
thinly and return another `SopranArray`, so schema dimensions and provenance stay
available after simple filtering or reduction:

```python
subset = counts.sel(energy=slice(100, 1000)).mean("energy")
subset.to_polars()
subset.quicklook("counts_energy_band")
```

`resample()` uses a thin SOPRAN wrapper around xarray's resampler. Basic
aggregations such as `mean()`, `sum()`, `median()`, `max()`, `first()`, and
`last()` return another `SopranArray`:

```python
hourly = quality.resample(time="1h").mean()
counts_10s = counts.resample(time="10s").sum()
hourly.to_polars()
hourly.metadata["operations"]
```

When a loaded object already carries derived-operation metadata, `quicklook()`
records it under the quicklook `metadata.operations` field and
`write_parquet(store, ...)` records it under the Store manifest
`parameters.operations` field. Explicit user-supplied `metadata["operations"]`
or `parameters["operations"]` takes precedence.

Use `SopranArray.write_parquet(store, ...)` when a single loaded variable should
be persisted as a SOPRAN dataset with `dataset.json`, `schema.json`,
`catalog.parquet`, and one or more Parquet shards:

```python
quality = kg.esa1.load(time).quality
record = quality.write_parquet(
    store,
    dataset_id="kaguya.esa1.quality",
    mission="kaguya",
    instrument="esa1",
)
```

`GuidePage` carries language metadata so package guides and public docs can
share the same bilingual contract:

```python
page = kg.guide()       # Japanese by default
page_en = kg.guide(language="en")
page.language
page.available_languages
page.language_switcher()  # "Lang: 日本語/English" when both languages exist
page.source               # current package resource path
page.sources              # language-specific package resource paths
page.url                  # current public docs URL, if configured
page.urls                 # language-specific public docs URLs, if configured
page.to_metadata()        # JSON-ready language/source/URL state
page.to_markdown(language="en")
page.with_language("en")  # switches body, source, and URL together
page.open(language="en")  # opens the matching public docs URL when configured
page.show()               # prints the same Markdown, including the switcher
```

Mission, instrument, and variable endpoints should pass the same `language=`
keyword through to their package guide resources. The default language is
Japanese (`language="ja"`); English is selected explicitly with `language="en"`.
KAGUYA, ARTEMIS, and Moon surface guides currently expose Japanese and English
guide pages.
The MkDocs site header uses the same public label, `Lang: 日本語/English`, so
notebook guides, package guides, and published docs share one language-switching
surface.

`Project` and `Case` provide analysis context:

```python
project = spn.Project("projects/lunar_wake")
case = project.case("wake_20080201")

counts = case.kaguya.esa1.counts.load()
plan = case.artemis.p1.fgm.magnetic_field.plan()
dem = case.moon.dem.plan(source="kaguya.tc.dem", region=case.region)
```
