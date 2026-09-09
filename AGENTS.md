# SOPRAN Agent Guide

SOPRANは衛星データの取得・保存・解析・可視化を提供するPythonパッケージです。
重い数値処理は同梱のPyO3/Rust拡張へまとめて渡します。
全体ルールはこのファイル、仕様は`docs/`、一時的な進捗は`_handoff/`や
各解析出力のログに置きます。仕様・既定値は現行コードとテストで確認してください。

## 現在の構成

| 場所 | 責務 |
|---|---|
| `src/sopran/core/` | Store、config、Project/Case/View、データ型、pipeline、plotting、resampling |
| `src/sopran/missions/` | KAGUYA、ARTEMIS、OMNIなどのreader・機器・product API |
| `src/sopran/bodies/moon/` | DEM、shadow、SVMなどの月面product |
| `src/sopran/frames/` | 座標系、SPICE、時刻変換 |
| `src/sopran/analysis/` | ミッション非依存の解析。ERは`electron_reflection/` |
| `src/sopran/maps/` | 共通raster型。月固有productは`bodies/moon/`に置く |
| `crates/sopran-native/` | Pythonから`sopran._native`として呼ぶRust拡張 |
| `tests/` | 合成データ・fixture中心の回帰テスト |
| `docs/`, `docs/en/` | 日本語・英語ドキュメント。ナビゲーションは`mkdocs.yml` |
| `working/`, `_handoff/` | ローカル解析・生成物・引き継ぎ。通常はGit管理外 |

## APIと実装の境界

- 日常の入口は`spn.kaguya`、`spn.artemis`、`spn.moon`、`spn.omni`。
  共通の時刻・領域等は`spn.view(...)`、永続的な研究条件は`Project`/`Case`で扱う。
  明示的なmissionオブジェクトも独立したStore/source設定用に残す。
- プロセス内の既定値は`spn.config.use(...)`、一時変更は`spn.config.using(...)`。
  `Store(...)`の生成自体にはグローバル設定を変更する副作用を持たせない。
  設定解決は既存config/Project/View経由とし、機器ごとに別のグローバル状態を作らない。
- 公開APIには返り値型と単位・座標系・時刻・ビン情報を付ける。
  補完を失う`Any`の連鎖を避け、外部ライブラリとの境界で型を明確にする。
- 加工データは既存product/cacheの仕組みを使い、取得・計算・保存・再読込を透過的にする。
  パラメータ依存の結果は入力と設定を区別できるキーにするか、明示保存にする。
  異なる設定の結果を同じStore項目として再利用しない。
- ファイル探索はStore/layout/provider経由。パッケージ内へローカル絶対パスを埋め込まない。
  欠損値、ゼロ、未取得、校正・品質フラグを区別する。
- 任意依存は利用する経路で読み込む。`import sopran`に全ミッションの依存を要求しない。
  依存・build・extrasの定義は`pyproject.toml`を正とする。
- 可視化は既存plot APIを使い、軸とカラーに物理量・単位を表示する。
  科学画像は実データから作り、NaNとゼロ、候補解と採択解を区別する。

## データと実行中ジョブの保護

- 実データ、キャッシュ、secret、大量の図やfit結果はGitに入れない。
  外部データセットや旧実装`F:\idl\lunarsat`は、明示依頼なしに削除・移動・書換えしない。
  旧IDL/SPEDASは読み取り参照とし、移植時は出典・単位・補正条件を記録する。
- 長時間処理の再開・停止・並列数変更は、対象のコマンド、PID、ログ、出力先を確認して行う。
  Pythonプロセスの一括停止や、別ジョブの再起動は行わない。
- 実行中ジョブが参照する入力、コード、nativeバイナリを差し替える前に影響を確認する。
  設定・コードhashが変わる結果は別の出力先に分け、既存bindingを編集して再開条件を回避しない。
- 全期間計算や大量ダウンロードは要求された範囲・並列数に従い、まず少数ケースで検証する。
  一時的なPID、完了率、特定runの既定値はこのガイドやskillへ固定しない。

## 検証

リポジトリルートで対象環境のPythonを使います。Windowsの既存venvは
`.venv/Scripts/python.exe`。以下の`python`はその環境を有効化した場合の表記です。
依存導入は必要なextrasだけを選び、共有環境や実行中ジョブへの影響を先に確認します。

```powershell
# 狭い変更ではまず関連テスト。広い回帰確認はCI相当の環境で行う
python -m pytest -q tests/test_omni.py
python -m pytest -q
python -m compileall -q src
python -m ruff check src tests
python -m mypy src

# Rustを変更した場合
cargo test -p sopran-native
cargo fmt --all --check

# schemaまたはドキュメントを変更した場合
python -m sopran.schema_docs --check docs/reference/schemas.md
python -m sopran.schema_docs --language en --check docs/en/reference/schemas.md
python -m mkdocs build
```

CIの依存セット・手順は`.github/workflows/ci.yml`、docsとwheel配布は同ディレクトリの
`docs.yml`、`publish.yml`を確認します。IDL実行環境は前提にせず、合成データと
参照仕様・既存実データとの比較で検証します。実行したテスト、未実行の検証、
実データの対象範囲を区別して報告してください。

## 変更の進め方

- 前後に`git status --short`を確認し、既存の未コミット変更を保全する。
  手作業の編集は`apply_patch`、検索は`rg`を使い、無関係な整形・refactorを混ぜない。
- API・解析仕様の変更時は関連ドキュメントとテストも更新する。
  日本語説明でよいが、API名・外部仕様名は原名を保つ。数式は`$...$`、`$$...$$`を使う。
- commit、merge、push、リリースは依頼された場合だけ行う。
- 作業に応じて以下のローカルskillを読む。通常の小さな変更に全手順を強制しない。
  - [ER解析・長時間バッチ](.agents/skills/sopran-er-batch/SKILL.md)
  - [Rust backendの変更・性能検証](.agents/skills/sopran-native/SKILL.md)
