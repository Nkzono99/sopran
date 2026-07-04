# Installation

SOPRAN is currently intended to be used from a source checkout.

```bash
git clone https://github.com/Nkzono99/sopran.git
cd sopran
pip install -e .
```

## Extras

The plain `pip install -e .` path installs only the minimal dependencies needed
to import the top-level API. Use the `full` extra when you want the mission,
mapping, frame, and visualization backends in one environment.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[full]"
```

On Windows with Python 3.14, `aacgmv2`, `apexpy`, `cartopy`, and `geoviews`
are skipped by the `full` extra. They depend on C/C++/Fortran or geospatial
native libraries, or transitively require Cartopy, and can fall back to source
builds when compatible wheels are not available. SOPRAN keeps those
failure-prone backends in a separate `native` extra.

## Windows Setup

With Chocolatey, install Python and the native build toolchain from an
administrator PowerShell. The `full` extra remains wheel-oriented on Python
3.14 because the native backends are marker-gated there.

```powershell
choco install -y python314
choco install -y visualstudio2022buildtools visualstudio2022-workload-vctools mingw
refreshenv

python3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[full]"
```

Before attempting native builds, use SOPRAN's preflight check to inspect PATH
and toolchain availability.

```powershell
.\.venv\Scripts\sopran-env-check.exe --native
```

If you also want to attempt `aacgmv2`, `apexpy`, `cartopy`, and `geoviews`,
add the `native` extra.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[full,native]"
```

`native` is the source-build path. If Cartopy has no wheel for the current
Python 3.14 / Windows combination, it may need GEOS / PROJ setup in addition
to MSVC. If that path fails, use an interpreter with Cartopy wheels, such as
Python 3.13, or a conda-forge environment.

pip dependency metadata is not a good place to inspect local toolchains and
dynamically skip optional dependencies during installation, so SOPRAN uses
static markers plus `sopran-env-check` for preflight guidance.

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
$env:SOPRAN_DATA_ROOT = "F:/sopran_data"
$env:SOPRAN_CACHE_ROOT = "F:/sopran_cache"
```
