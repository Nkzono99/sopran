# Adding A Data Source

How to make a new mission's or body's data available through `spn.<name>`, `view.<name>`, and `spn.load("<name>...")`.
The smallest implementation is `src/sopran/missions/omni/` (OMNI); reading it alongside this page helps.

## 1. Register

Each data source registers itself in its package's `__init__.py`. Because `core` never imports missions, registration happens on the mission side.

```python
# src/sopran/missions/<name>/__init__.py
from sopran.core.sources import register_source

register_source("<name>", "sopran.missions.<name>.mission:<Mission>.from_view")
```

The second argument is `"module:attribute.path"` and is imported on first use.
The registered factory receives a `View` and returns an object bound to that view's time range, download policy, and Store.

```python
class Mission:
    def __init__(self, *, store: Store | None = None, download: DownloadMode | None = None,
                 view: View | None = None) -> None:
        self.store = store or Store()
        self.download = resolve_download_mode(download)   # leave policy resolution to one place
        self.view = view

    @classmethod
    def from_view(cls, view: View) -> "Mission":
        return cls(store=view.project.store, download=view.context.download, view=view)
```

Once `src/sopran/__init__.py` imports the package, registration is complete, and `spn.<name>`, `view.<name>`, `case.<name>`, and `spn.load("<name>.…")` all use the same object.

## 2. Write schemas

Write a `VariableSchema` per variable and group them in an `InstrumentSchema` per instrument. Units, dimensions, and frames are defined here.

```python
DENSITY = VariableSchema(name="density", dims=("time",), units="cm^-3", description="Proton density.")
SCHEMA = InstrumentSchema(mission="<name>", instrument="<instrument>", variables=(DENSITY,))
```

Mark quantities spanning many decades (fluxes, power spectral densities) with `log_scale=True`, and coordinates drawn on a log axis with `log_dims=("energy",)`.
Array and endpoint plots take their default logarithmic scales from these hints.

To list the schema in the reference, add it to `sopran.schema_docs.builtin_schemas()` and regenerate the page with
`python -m sopran.schema_docs`.

## 3. Build endpoints

Endpoints must not read files when they are merely retrieved as attributes. Provide at least:

| Method | Returns |
|---|---|
| `load(time=None, *, download=None, ...)` | `SopranArray`. Use `view.time` when `time` is omitted; if neither exists, raise with an example |
| `plot(time=None, **kwargs)` | `load(...).plot(...)` |
| `line()`, `lines()`, `spectrogram()`, … | PlotStack panels |
| `info()`, `schema()`, `guide()`, `example()` | Descriptions and definitions |
| `plan(time)` | Source files or dataset IDs to be read |

Place source files under `store.raw_path("<name>", "<provider>", ...)` with the provider's layout, and after retrieval record the URL and checksum with
`store.register_raw_file(...)`. Write downloads to a temporary file and replace atomically, keeping the previous file on failure.
When caching derived products, derive `variant_id` from settings and input content and register with `managed=True`.

## 4. Support Pipeline (when needed)

Subclass `PipelineBackend` and override only the operations you support. The endpoint's `pipeline(time)` returns a `Pipeline` with this backend attached.

```python
from sopran.core.pipeline import Pipeline, PipelineBackend

class MyBackend(PipelineBackend):
    def scan_pipeline(self, pipeline: Pipeline):
        ...   # return a polars.LazyFrame; stream(partition="day") is split from it automatically

    def run_pipeline(self, pipeline: Pipeline, *, mode, run_id, resume, only_failed, on_error, download):
        ...   # return a PipelineResult
```

Operations that are not overridden raise `PipelineError`. The PACE implementation is in `src/sopran/missions/kaguya/pipeline.py`.

## 5. Add documentation and tests

- Write the description returned by `guide()` in the package's `README.md` (English) and `README.ja.md`, and pass the public documentation URL to `GuidePage(url=...)`.
- Add a page under [Data](../data/index.md) in the public documentation, following the template in [Writing Documentation](documentation.md).
- Import optional dependencies lazily on the path that uses them and add them to an extra; `tests/test_project_metadata.py` checks that extras match actual imports.
- Test units, the distinction between missing values and zeros, half-open time ranges, and cache keys with synthetic data or fixtures.
