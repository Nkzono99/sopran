# 開発環境と検証

SOPRANのコードやドキュメントを変更するための環境の作り方と、変更後に通すべき検証をまとめます。
利用者としてのインストールは[インストール](../start/install.md)を参照してください。

## 環境を作る

```bash
git clone https://github.com/Nkzono99/sopran.git
cd sopran
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev,full,docs]"     # Windows は .venv\Scripts\python.exe
```

`pip install -e .`は、Rust拡張`sopran._native`もビルドしてソースツリーに置きます。
Rustのコードだけを変えたときは、次のコマンドで拡張を作り直せます。

```bash
python -m maturin develop --release
python -c "import sopran._native as native; print(native.__file__)"
```

ビルドに必要なツールは`sopran-env-check --native`で確かめられます。
`maturin develop`はソースツリーの中の拡張を置き換えるため、同じソースツリーで長時間のジョブが動いているときは、
別のコピーと別の仮想環境で作業してください。

## 検証のコマンド

リポジトリのルートで、仮想環境の`python`を使って実行します。変更した範囲に関係するものを選んでください。

| 対象 | コマンド |
|---|---|
| 関連するテスト / 全体 | `python -m pytest -q tests/test_omni.py` / `python -m pytest -q` |
| 構文・lint・型 | `python -m compileall -q src` / `python -m ruff check src tests` / `python -m mypy src` |
| Rust | `cargo test -p sopran-native` / `cargo fmt --all --check` |
| スキーマを変えたとき | `python -m sopran.schema_docs --check docs/ja/reference/schemas.md` / `python -m sopran.schema_docs --language en --check docs/en/reference/schemas.md` |
| ドキュメントを変えたとき | `python -m mkdocs build --strict` |
| 外部の配布元への接続 | `python -m pytest -m network` / `sopran-env-check --sources` |

テストは合成データとfixtureを中心にしています。IDLの実行環境は前提にせず、SPEDASの挙動との比較は
参照仕様・合成データ・既存の実データで行います。

通常のテストは外部と通信しません。`tests/conftest.py`がループバック以外への接続を止め、取得の経路は`urlopen`などを差し替えて確かめます。
外部へ通信するテストには`@pytest.mark.network`を付けます。これは既定では選ばれず、`-m network`を指定したときだけ実行されます。

## CI

| ワークフロー | 内容 |
|---|---|
| `.github/workflows/ci.yml` | `[dev,kaguya,moon,viz,docs,experimental]`を入れて、pytest、compileall、スキーマのページの確認、ruff、mypyを実行する |
| `.github/workflows/sources.yml` | 毎週月曜と手動実行で、`sopran-env-check --sources`により外部の配布元への接続を確かめる |
| `.github/workflows/docs.yml` | `mkdocs build --strict`でドキュメントを作り、`main`ブランチではGitHub Pagesへ公開する |
| `.github/workflows/publish.yml` | `v*`タグで、sdistと各OS・CPython 3.11〜3.14のwheelを作り、PyPIへ公開する（[リリース](release.md)） |

## スーパーコンピューター

京都大学のスーパーコンピューターでの環境構築とジョブの雛形は`scripts/hpc/kyoto/`にあります。
使い方は[ER全期間バッチ](../experimental/er-batch.md#京都大学のスーパーコンピューターで動かす)を参照してください。
