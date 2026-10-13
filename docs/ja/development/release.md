# リリース

SOPRANは、GitHub ActionsからPyPIのTrusted Publishingで公開します。長期間有効なAPIトークンは使いません。

| 項目 | 値 |
|---|---|
| ワークフロー | `.github/workflows/publish.yml` |
| きっかけ | `v*`のタグのpush |
| PyPIのプロジェクト | `sopran` |
| GitHubのenvironment | `pypi` |
| 認証 | GitHub OIDCとPyPI Trusted Publisher |

## ワークフローが行うこと

1. `pyproject.toml`の`version`、`src/sopran/__init__.py`の`__version__`、タグから`v`を除いた値が一致するかを確かめる。
2. `python -m build --sdist`でソース配布物を作る。
3. `cibuildwheel`で、Linux・Windows・macOSのCPython 3.11〜3.14のwheelを作る。
4. 各wheelで`sopran._native`がimportできるかを確かめる。
5. `python -m twine check dist/*`でメタデータとREADMEを確かめる。
6. `pypa/gh-action-pypi-publish@release/v1`でPyPIへアップロードする。

## 手順

```powershell
# 1. pyproject.toml の version と src/sopran/__init__.py の __version__ を同じ値（例 0.1.0）にする

# 2. commit してタグを打つ
git add pyproject.toml src/sopran/__init__.py
git commit -m "Release v0.1.0"
git tag v0.1.0

# 3. タグを push すると公開のワークフローが動く
git push origin main
git push origin v0.1.0
```

3つの版の値が一致しないと、ビルドのジョブが失敗します。
リリースの前に、[試作API](../experimental/index.md#正式化継続廃止の判断)の棚卸しを行ってください。

## 事前の確認

```powershell
python -m build --sdist --wheel
python -m twine check dist/*

# 実行中のOS向けのwheelを試しに作る
python -m pip install "cibuildwheel>=2.23,<3"
python -m cibuildwheel --output-dir wheelhouse
```

## 初回だけ必要なPyPIの設定

PyPIに`sopran`のプロジェクトがまだ無い場合は、PyPIのアカウントのPublishingからpending publisherを作ります。

| PyPIの項目 | 値 |
|---|---|
| Project name | `sopran` |
| Owner | `Nkzono99` |
| Repository name | `sopran` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

pending publisherは名前の予約ではありません。初回の公開より前に同じ名前のプロジェクトが登録されると無効になります。
