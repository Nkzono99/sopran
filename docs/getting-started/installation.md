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
用途別 backend までまとめて入れる場合は `full` extra を使います。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[full]"
```

Windows の Python 3.14 では、`aacgmv2`, `apexpy`, `cartopy`, `geoviews` は `full` から
自動的に外れます。これらは C/C++/Fortran や geospatial native library に依存するか、
Cartopy を transitively 要求し、wheel がない環境では source build に落ちやすいためです。
SOPRAN の metadata では、失敗しやすい backend を `native` extra に分けています。

## Windows の定型セットアップ

Chocolatey を使う場合は、管理者 PowerShell で Python と build toolchain をそろえます。
Rust/PyO3 extension は通常 install でも build されます。`full` だけなら Cartopy などの追加
native backend は Python 3.14 で marker により除外されます。

```powershell
choco install -y python314
choco install -y rust
choco install -y visualstudio2022buildtools visualstudio2022-workload-vctools mingw
refreshenv

python3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[full]"
```

native build を試す前に、SOPRAN 側の preflight check で PATH と toolchain を確認できます。

```powershell
.\.venv\Scripts\sopran-env-check.exe --native
```

`aacgmv2`, `apexpy`, `cartopy`, `geoviews` も含めて試す場合は `native` extra を足します。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[full,native]"
```

`native` は source build を許可する経路です。Cartopy は Python 3.14 / Windows で wheel が
ない場合、MSVC に加えて GEOS / PROJ 系の設定が必要になることがあります。失敗する場合は
Python 3.13 など Cartopy wheel がある interpreter、または conda-forge の利用を検討します。

pip の dependency metadata は install 中にローカル toolchain を調べて optional dependency を
動的に skip する用途には向かないため、SOPRAN では static marker と `sopran-env-check` で
事前に分岐します。

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
$env:SOPRAN_DATA_ROOT = "F:/sopran_data"
$env:SOPRAN_CACHE_ROOT = "F:/sopran_cache"
```
