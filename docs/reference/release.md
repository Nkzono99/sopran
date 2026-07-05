# Release（PyPI 公開）

SOPRAN は PyPI Trusted Publishing を使って公開します。長期保存する API token は使いません。

## Workflow

| 項目 | 値 |
| --- | --- |
| GitHub workflow | `.github/workflows/publish.yml` |
| Trigger | `v*` tag push |
| PyPI project | `sopran` |
| GitHub environment | `pypi` |
| Authentication | GitHub OIDC / PyPI Trusted Publisher |

`publish` workflow は次を行います。

1. `pyproject.toml` の project version、`src/sopran/__init__.py` の `__version__`、
   tag の `v` を除いた値を照合する。
2. `python -m build --sdist` で source distribution を作る。
3. `cibuildwheel` で Linux / Windows / macOS の CPython 3.11-3.14 wheel を作る。
4. 各 wheel で `sopran._native` の import smoke test を実行する。
5. `python -m twine check dist/*` で metadata / README を確認する。
6. build artifact を PyPI publish job に渡す。
7. `pypa/gh-action-pypi-publish@release/v1` で PyPI に upload する。

## 初回だけ必要な PyPI 側設定

`sopran` project が PyPI に存在しない場合は、PyPI account の Publishing から pending
publisher を作ります。

| PyPI form | 入力値 |
| --- | --- |
| Project name | `sopran` |
| Owner | `Nkzono99` |
| Repository name | `sopran` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

pending publisher は名前の予約ではありません。初回 publish 前に同名 project が登録された場合は
無効になります。

## release 手順

```powershell
# 1. version を上げる
# pyproject.toml の version と src/sopran/__init__.py の __version__ を
# 0.1.0 など同じ値にする

# 2. commit して tag を打つ
git add pyproject.toml src/sopran/__init__.py
git commit -m "Release v0.1.0"
git tag v0.1.0

# 3. tag push で PyPI publish workflow を起動する
git push origin main
git push origin v0.1.0
```

`pyproject.toml` の `version = "0.1.0"`、`__version__ = "0.1.0"`、tag `v0.1.0`
が一致しない場合、build job は失敗します。

## 事前確認

local では次を確認します。

```powershell
python -m build --sdist --wheel
python -m twine check dist/*
```

platform wheel の事前確認を local で行う場合は、実行中の OS 向けに次を使います。

```powershell
python -m pip install "cibuildwheel>=2.23,<3"
python -m cibuildwheel --output-dir wheelhouse
```

PyPI Trusted Publishing の詳細は PyPI docs と Python Packaging User Guide を参照します。
