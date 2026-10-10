# Installation

SOPRAN is currently intended to be used from a source checkout.

```bash
git clone https://github.com/Nkzono99/sopran.git
cd sopran
pip install -e .
```

Source-checkout installs also build the Rust/PyO3 PACE decode extension as
`sopran._native` inside the same wheel. This requires a Rust toolchain and, on
Windows, MSVC build tools. Once binary wheels are published, normal users should
not need a local Rust build for this extension.

## Extras

The plain `pip install -e .` path installs only the minimal dependencies needed
to import the top-level API. Each extra lists only the packages SOPRAN imports on
that path.

| extra | use | main packages |
| --- | --- | --- |
| `kaguya` | PACE, LMAG and LRS readers, SPICE geometry | `cdflib`, `polars`, `pyarrow`, `scipy`, `spiceypy`, `xarray` |
| `artemis` | normalized ARTEMIS datasets in the Store | `polars`, `pyarrow`, `xarray` |
| `moon` | GeoTIFF maps, SPICE Sun direction | `rasterio`, `spiceypy` |
| `viz` | plots and interactive PlotStack | `matplotlib`, `panel` |
| `analysis`, `experimental` | interpolation and research models | `scipy` |
| `full` | all of the above | |

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[full]"
```

## Windows Setup

A source-checkout install builds the Rust/PyO3 extension. With Chocolatey,
install Python, Rust and the MSVC build tools from an administrator PowerShell.

```powershell
choco install -y python314
choco install -y rust visualstudio2022buildtools visualstudio2022-workload-vctools
refreshenv

python3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[full]"
```

Before building, `sopran-env-check` reports the Rust toolchain and, on Windows,
the MSVC build tools.

```powershell
.\.venv\Scripts\sopran-env-check.exe --native
```

For documentation work only, the MkDocs toolchain is enough.

```bash
pip install mkdocs mkdocs-material "mkdocstrings[python]" pymdown-extensions numpy
set PYTHONPATH=src
mkdocs serve
```

The repository also defines a docs extra:

```bash
pip install -e ".[docs]"
```

## Checks

```powershell
$env:PYTHONPATH = "src"
$env:NO_MKDOCS_2_WARNING = "true"
python -m pytest -q
python -m mkdocs build --strict
```

## Store Defaults

`spn.Store()` reads its default root from `SOPRAN_DATA_ROOT`.

```powershell
$env:SOPRAN_DATA_ROOT = "/path/to/sopran_data"
$env:SOPRAN_CACHE_ROOT = "/path/to/sopran_cache"
```
