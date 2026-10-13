# Installation

SOPRAN is not on PyPI yet. Clone the repository and install it. Python 3.11 or later is required.

```bash
git clone https://github.com/Nkzono99/sopran.git
cd sopran
python -m pip install -e ".[full]"
```

`[full]` installs everything needed for KAGUYA, ARTEMIS, Moon maps, and plotting.
If you know which data you need, pick only the extras from the table below.

## Building the Rust extension

A source install also builds the Rust extension `sopran._native`, which handles PACE decoding and pitch-angle binning.
You need a Rust toolchain, and on Windows the MSVC build tools.
Check them with `sopran-env-check` (it also works after installation).

```powershell
.\.venv\Scripts\sopran-env-check.exe --native
```

On Windows, Chocolatey in an administrator PowerShell sets everything up:

```powershell
choco install -y python314
choco install -y rust visualstudio2022buildtools visualstudio2022-workload-vctools
refreshenv

python3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[full]"
```

## Choosing extras

`pip install -e .` installs only `numpy` and `pandas`; `import sopran` and the top-level entry points work,
but nothing else. Each extra contains only the packages SOPRAN actually imports on that path.

| Extra | Use it for | Packages |
|---|---|---|
| `kaguya` | Loading PACE, LMAG, and LRS; SPICE geometry | `cdflib`, `polars`, `pyarrow`, `scipy`, `spiceypy`, `xarray` |
| `artemis` | Retrieving and reading ARTEMIS (THEMIS-B, C) CDF files | `cdflib`, `xarray` |
| `moon` | GeoTIFF Moon maps, SPICE Sun direction | `rasterio`, `spiceypy` |
| `viz` | Plots and interactive PlotStack views | `matplotlib`, `panel` |
| `analysis`, `experimental` | Interpolation and experimental models | `scipy` |
| `full` | All of the above | |

Loading OMNI needs `xarray`, and plotting it needs `matplotlib`; `[kaguya,viz]` covers both.

```powershell
python -m pip install -e ".[kaguya,viz]"
```

## Checking the installation

```python
import sopran as spn

spn.kaguya.info()     # list of KAGUYA instruments
```

If the list prints, you are ready. Decide where to store data and continue with [First Plot](quickstart.md).
Development dependencies (`[dev]`) and how to run the tests are in [Setup And Checks](../development/setup.md).
