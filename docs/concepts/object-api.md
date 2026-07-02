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

`GuidePage` carries language metadata so package guides and public docs can
share the same bilingual contract:

```python
page = kg.guide(language="ja")
page.language
page.available_languages
page.language_switcher()  # "Lang: 日本語/English" when both languages exist
page.source               # current package resource path
page.sources              # language-specific package resource paths
page.url                  # current public docs URL, if configured
page.urls                 # language-specific public docs URLs, if configured
page.to_markdown(language="en")
page.with_language("en")  # switches body, source, and URL together
page.show()               # prints the same Markdown, including the switcher
```

Mission, instrument, and variable endpoints should pass the same `language=`
keyword through to their package guide resources. KAGUYA, ARTEMIS, and Moon
surface guides currently expose Japanese and English guide pages.

`Project` and `Case` provide analysis context:

```python
project = spn.Project("projects/lunar_wake")
case = project.case("wake_20080201")

counts = case.kaguya.esa1.counts.load()
plan = case.artemis.p1.fgm.magnetic_field.plan()
dem = case.moon.dem.plan(source="kaguya.tc.dem", region=case.region)
```
