# インストール

現時点ではリポジトリを clone して editable install する想定です。

```bash
git clone https://github.com/Nkzono99/sopran.git
cd sopran
pip install -e .
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
python -m pytest -q
python -m mkdocs build --strict
```

## 保存先

`spn.Store()` の既定 root は `SOPRAN_DATA_ROOT` で指定できます。

```powershell
$env:SOPRAN_DATA_ROOT = "F:/sopran_data"
$env:SOPRAN_CACHE_ROOT = "F:/sopran_cache"
```
