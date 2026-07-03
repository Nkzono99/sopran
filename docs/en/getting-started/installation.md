# Installation

SOPRAN is currently intended to be used from a source checkout.

```bash
git clone https://github.com/Nkzono99/sopran.git
cd sopran
pip install -e .
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
python -m pytest -q
python -m mkdocs build --strict
```

## Store Defaults

`spn.Store()` reads its default root from `SOPRAN_DATA_ROOT`.

```powershell
$env:SOPRAN_DATA_ROOT = "F:/sopran_data"
$env:SOPRAN_CACHE_ROOT = "F:/sopran_cache"
```
