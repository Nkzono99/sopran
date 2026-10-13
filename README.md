# SOPRAN

Satellite Observation Package for Retrieval, Analysis, and Navigation.

SOPRAN is a Python package for retrieving, storing, analyzing, and visualizing
spacecraft observations around the Moon. It reads KAGUYA/SELENE, ARTEMIS, and
OMNI data, and Moon terrain, magnetic, and illumination maps, with one calling style.

The API follows the data: mission, instrument, physical quantity, and its axes.
Standard paths lead from retrieval to labeled plots, while source files and
native records stay accessible. Rust handles heavy kernels internally.

Documentation (Japanese and English): https://nkzono99.github.io/sopran/

## Quick Start

```python
import sopran as spn

spn.config.use(store="/path/to/sopran_data")
time = spn.day("2008-02-01")

spn.kaguya.esa1.energy_flux.plot(time)          # retrieve, calibrate, and plot
flux = spn.kaguya.esa1.energy_flux.load(time)   # SopranArray with units and provenance
flux.quicklook("esa1_energy_flux", root="reports")
```

Bind a time range and region once with a `View`, and save named analysis
conditions as a `Case` in a project:

```python
view = spn.view(
    time=spn.day("2008-02-01"),
    region=spn.Region(lon=(120, 160), lat=(-45, -10), body="moon"),
)
stack = spn.stack(
    view.kaguya.esa1.counts.spectrogram(y="energy", log_color=True),
    view.kaguya.lmag.magnetic_field.lines(components="xyz"),
)
stack.plot()

project = spn.Project("projects/lunar_wake")
project.save_case("wake_20080201", view)
```

| Entry point | Use it for |
|---|---|
| `spn.kaguya`, `spn.artemis`, `spn.omni`, `spn.moon` | Data sources bound to the default configuration |
| `spn.config.use(...)` | Session defaults: Store location, download policy |
| `spn.view(...)`, `spn.Project(...)` | Time range, region, and saved analysis conditions |
| `spn.Store(...)` | Raw files, Parquet datasets, caches, databases |
| `spn.stack(...)` | Multi-panel time-series figures (like SPEDAS `tplot`) |
| `sopran.experimental` | Explicitly imported research APIs without compatibility guarantees |

What is implemented for each data source is listed in the
[data overview](https://nkzono99.github.io/sopran/en/data/).

## Install

SOPRAN is installed from a source checkout, which also builds the bundled Rust
extension (a Rust toolchain is required; on Windows also the MSVC build tools).

```powershell
python -m pip install -e ".[full]"
```

Extras are split by area (`kaguya`, `artemis`, `moon`, `viz`, `analysis`,
`experimental`, `full`, `docs`, `dev`); each lists only the packages SOPRAN
imports on that path. See
[Installation](https://nkzono99.github.io/sopran/en/start/install/).

## Documentation sources

The documentation sources are in `docs/ja/` (primary) and `docs/en/` (mirror at
the same paths). How they are organized is described in
`docs/en/development/documentation.md`.

```powershell
python -m pip install -e ".[docs]"
python -m mkdocs serve
```

## Development

```powershell
python -m pip install -e ".[dev,full,docs]"
python -m pytest -q
python -m compileall -q src
python -m ruff check src tests
python -m mypy src
cargo test -p sopran-native
cargo fmt --all --check
python -m mkdocs build --strict
```

See [Setup And Checks](https://nkzono99.github.io/sopran/en/development/setup/).

## License

SOPRAN original code and documentation are licensed under Apache-2.0.

SPEDAS/PySPEDAS-derived ports must retain upstream notices. The current policy
is documented in `THIRD_PARTY_NOTICES.md`.
