# SOPRAN

Satellite Observation Package for Retrieval, Analysis, and Navigation.

SOPRAN is a Python-first package for retrieving, normalizing, storing,
analyzing, and visualizing lunar and planetary spacecraft observations. The
first target missions are KAGUYA/SELENE and ARTEMIS, with Moon surface maps
provided through a body-first API.

## Quick Start

For day-to-day notebooks, use the top-level shortcuts. They read the default
project/user configuration and do not require constructing mission objects.

```python
import sopran as spn

time = spn.day("2008-02-01")

counts = spn.kaguya.esa1.counts.load(time)
plot = spn.kaguya.esa1.energy_flux.plot(time, calibration="auto", log_color=True)
quicklook = spn.kaguya.esa1.energy_flux.load(time, calibration="auto").quicklook(
    "esa1_energy_flux",
    root="reports",
)
```

For spectrum-like products, `plot()` defaults to a spectrogram: time on x,
energy or pitch angle on y, and the product value on color. The colorbar label
includes the product name and units when available.

When several operations share a time range, region, frame, download policy, or
SPICE kernels, bind them with a `View`.

```python
view = spn.view(
    time=spn.day("2008-02-01"),
    region=spn.Region(lon=(120, 160), lat=(-45, -10), body="moon"),
    frame="SSE",
)

counts = view.kaguya.esa1.counts.load()
sza = view.moon.sza.compute(subsolar_lon_lat=(0.0, 0.0))
```

For reproducible studies, save the same context as a project case.

```python
project = spn.Project("projects/lunar_wake")
case = project.case("wake_20080201")

stack = case.stack(
    case.kaguya.esa1.energy_flux.spectrogram(y="energy", log_color=True),
    case.kaguya.esa1.quality.line(),
)
stack.quicklook("wake_overview", root="reports", context=case)
```

Use explicit mission objects only when you need to override store/source state
directly.

```python
store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store, download="never")
counts = kg.esa1.counts.load(time)
```

## API Layers

| Layer | Use it for |
| --- | --- |
| `spn.kaguya`, `spn.artemis`, `spn.moon` | Notebook-friendly shortcuts using default config |
| `spn.view(...)` | Temporary analysis context: time, region, frame, cache, backends |
| `spn.Project(...)` / `project.case(...)` | Workspace, artifacts, named reproducible cases |
| `spn.Kaguya(...)`, `spn.Artemis(...)`, `spn.Moon()` | Explicit low-level mission/body objects |
| `spn.Store(...)` | Raw files, normalized parquet, features, models, event/database products |
| `spn.stack(...)` | SPEDAS/tplot-like stacked quicklooks |

## Configuration

SOPRAN resolves configuration from explicit arguments, environment variables,
the nearest parent `sopran.toml`, user global config, and package defaults.

User global config is read from the OS user config directory, or from the
legacy `~/.sopran/config.toml` when that exists and the platform path does not.
Set `SOPRAN_CONFIG` to choose a specific file.

```toml
[store]
data_root = "F:/sopran_data"
cache_root = "F:/sopran_cache"

[defaults]
download = "missing"
cache = true
spice_kernels = ["kernels/naif0012.tls", "kernels/de421.bsp", "kernels/moon_pa.bpc"]

[backends]
frames = "spiceypy"
plot = "matplotlib"
```

Project workspaces can define their own `sopran.toml`. `spn.view(...)` and the
top-level shortcuts discover it from the current directory upward.

```toml
[defaults]
frame = "SSE"
cache = true

[defaults.region]
body = "moon"
lon = [120, 160]
lat = [-45, -10]
lon_domain = "0_360"

[cases.wake_20080201]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"
```

## Current Scope

Implemented vertical slices include:

- KAGUYA PACE raw discovery/decode, ESA1 `energy_flux`, pitch-angle products,
  coverage summaries, pipeline writes, and quicklooks
- KAGUYA LMAG/LRS readers and cached derived geometry/products
- ARTEMIS object API with normalized parquet readers
- Moon DEM/SVM loading, SZA computation, SPICE Sun geometry, and terrain-ray
  shadow maps
- Store manifests, schema/catalog metadata, event catalogs, PlotStack, and
  feature-table helpers
- Optional Rust/PyO3 backend for heavier PACE decode and pitch-angle work

Detailed status is tracked in `docs/reference/status.md`.

## Install

```powershell
python -m pip install -e .
python -m pip install -e ".[dev]"
```

Optional extras are split by area: `kaguya`, `artemis`, `moon`, `viz`,
`geospace`, `native`, `docs`, and `full`.

```powershell
python -m pip install -e ".[moon,viz]"
python -m pip install -e ".[full]"
```

## Documentation

MkDocs sources live under `docs/`.

```powershell
python -m pip install -e ".[docs]"
set PYTHONPATH=src
mkdocs serve
```

Start with:

- `docs/getting-started/installation.md`
- `docs/getting-started/first-analysis.md`
- `docs/concepts/project-case.md`
- `docs/reference/configuration.md`
- `docs/reference/status.md`

## Development

Common checks:

```powershell
python -m pytest -q
python -m compileall src
python -m ruff check src tests
python -m mypy src
cargo fmt --check
cargo test
```

The old exploratory repository is at `F:\idl\lunarsat` and is read-only
reference material for this rewrite.

## License

SOPRAN original code and documentation are licensed under Apache-2.0.

SPEDAS/PySPEDAS-derived ports must retain upstream notices. The current policy
is documented in `THIRD_PARTY_NOTICES.md`.
