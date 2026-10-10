# インストール

現時点ではリポジトリを clone して editable install する想定です。

```bash
git clone https://github.com/Nkzono99/sopran.git
cd sopran
pip install -e .
```

source checkout からの install では、PACE decode 用の Rust/PyO3 extension
`sopran._native` も同じ wheel に含めて build します。Rust toolchain と、Windows では
MSVC build tools が必要です。PyPI wheel を配布する段階では利用者側の Rust build は不要にする想定です。

## extras

通常の `pip install -e .` は、top-level API の import に必要な最小依存だけを入れます。
extra は、その経路で SOPRAN が実際に import する package だけを持ちます。

| extra | 用途 | 主な依存 |
| --- | --- | --- |
| `kaguya` | PACE・LMAG・LRS の読込、SPICE geometry | `cdflib`, `polars`, `pyarrow`, `scipy`, `spiceypy`, `xarray` |
| `artemis` | Store の正規化済み ARTEMIS dataset | `polars`, `pyarrow`, `xarray` |
| `moon` | GeoTIFF 地図、SPICE の太陽方向 | `rasterio`, `spiceypy` |
| `viz` | plot と PlotStack の対話表示 | `matplotlib`, `panel` |
| `analysis`, `experimental` | 補間・試作モデル | `scipy` |
| `full` | 上記をまとめて入れる | |

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[full]"
```

## Windows の定型セットアップ

source checkout からの install では Rust/PyO3 extension を build します。
Chocolatey を使う場合は、管理者 PowerShell で Python・Rust・MSVC build tools をそろえます。

```powershell
choco install -y python314
choco install -y rust visualstudio2022buildtools visualstudio2022-workload-vctools
refreshenv

python3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[full]"
```

build の前に、`sopran-env-check` で Rust toolchain と（Windows では）MSVC を確認できます。

```powershell
.\.venv\Scripts\sopran-env-check.exe --native
```

ドキュメントだけを確認する場合は、MkDocs の依存だけでも動かせます。

```bash
pip install mkdocs mkdocs-material "mkdocstrings[python]" pymdown-extensions numpy
set PYTHONPATH=src
mkdocs serve
```

リポジトリの extra を使う場合:

```bash
pip install -e ".[docs]"
```

## 確認コマンド

```powershell
$env:PYTHONPATH = "src"
$env:NO_MKDOCS_2_WARNING = "true"
python -m pytest -q
python -m mkdocs build --strict
```

## 保存先

`spn.Store()` の既定 root は `SOPRAN_DATA_ROOT` で指定できます。

```powershell
$env:SOPRAN_DATA_ROOT = "/path/to/sopran_data"
$env:SOPRAN_CACHE_ROOT = "/path/to/sopran_cache"
```
