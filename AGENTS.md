# SOPRAN Agent Guide

SOPRANは衛星データの取得・保存・解析・可視化を提供するPythonパッケージです。
APIの階層・型・単位でデータの意味を伝え、標準の入口から可視化まで進める設計にします。
元ファイルとnative観測ビンへの直接アクセスを保ち、重い数値処理は同梱のPyO3/Rust拡張へまとめて渡します。
仕様・既定値は現行コードとテストで確認してください。

## 判断と文章

- 結論・根拠・次の行動を、肯定形で直接書く。否定は誤解の訂正や具体的な制約に絞る。
- 主張と根拠を一貫して追える構成にし、判断に影響する数値・前提・不確かさを該当する説明に添える。一般的な留保の反復は省く。
- 観測事実と作業仮説を区別する。証拠の強さと検証コストから有力な仮説を選び、見直しの条件と必要最小限の検証を示す。
- 低優先度の候補は保留し、有力な仮説の検証に集中する。具体的な反証や判断を変える新しい証拠が得られたら見直す。
- 結果は「現時点で何を採用し、次に何を調べるか」まで示し、許可された可逆的な作業はその判断に沿って進める。
- 会話・日本語文書は日本語、`docs/en/` は英語で書く。API名・外部仕様名は原名を保つ。数式は `$...$` / `$$...$$`、画像はMarkdownで埋め込む。

## 実装と記録の置き場所

| 場所 | 責務 |
|---|---|
| `src/sopran/core/` | Store、config、Project/Case/View、データ型、pipeline、plotting、resampling |
| `src/sopran/missions/` | KAGUYA・ARTEMIS・OMNIなどのreader・機器・product API |
| `src/sopran/bodies/moon/` | DEM・shadow・SVMなどの月面product |
| `src/sopran/frames/`, `src/sopran/maps/` | 座標・時刻変換、共通raster型 |
| `src/sopran/experimental/` | 明示importで使うER・波動候補・mission用adapterの試作 |
| `crates/sopran-native/` | `sopran._native` として呼ぶRust拡張 |
| `tests/` | 合成データ・fixture中心の回帰テスト |
| `docs/`, `docs/en/` | 公開APIの仕様・利用方法。ナビゲーションは `mkdocs.yml` |
| `working/`, `_handoff/` | Git管理外の個別研究・試行錯誤・生成物・進捗・ログ |

個別研究のテーマ設定・文献調査・run単位の評価は `working/` に置き、公開docsのナビゲーションへ追加しません。
全体ルールはこのファイル、再利用可能な仕様は `docs/`、一時的な進捗は `_handoff/` や解析出力のログに記録します。

## APIと実装の境界

- 日常の入口は `spn.kaguya` / `spn.artemis` / `spn.moon` / `spn.omni`。時刻・領域は `spn.view(...)`、永続的な研究条件は `Project` / `Case`、独立したStore/source設定は明示的なmissionオブジェクトで扱う。
- プロセスの既定値は `spn.config.use(...)`、一時変更は `spn.config.using(...)`。設定は既存config/Project/View経由で解決し、Store生成でグローバル設定を変えたり、機器ごとに別のグローバル状態を作ったりしない。
- 公開APIには返り値型・単位・座標系・時刻・ビン情報を付ける。外部ライブラリとの型境界を明確にし、`Any` の連鎖を避ける。
- 加工データは既存product/cacheで取得・計算・保存・再読込する。入力と設定を区別できるキー、または明示保存を使い、異なる設定の結果を同じStore項目として再利用しない。
- ファイル探索はStore/layout/provider経由とし、ローカル絶対パスをパッケージへ埋め込まない。欠損・ゼロ・未取得・校正・品質フラグを区別する。
- 任意依存は利用する経路で読み込み、`import sopran` に全ミッションの依存を要求しない。依存・build・extrasは `pyproject.toml` を正とする。
- 通常APIからexperimentalへ依存せず、試作を機器やルートへ再公開しない。試作にも型・単位・テストを付け、Storeキーを通常productと分ける。未確定点と正式化の条件は `src/sopran/experimental/README.md` で管理し、リリース前に棚卸しする。未公開APIの互換aliasやshimは作らない。
- 可視化は既存plot APIを使い、軸とカラーに物理量・単位を示す。科学画像は実データから作り、NaNとゼロ、候補解と採択解を区別する。

## データと実行中ジョブの保護

- 実データ・キャッシュ・secret・大量の図やfit結果はGitに入れない。外部データセットや旧実装 `F:\idl\lunarsat` は明示依頼なしに削除・移動・書換えしない。
- 旧IDL/SPEDASは読み取り参照とし、移植時は出典・単位・補正条件を記録する。
- 長時間処理の再開・停止・並列数変更はコマンド・PID・ログ・出力先を確認して行う。Pythonプロセスの一括停止や別ジョブの再起動は行わない。
- 実行中ジョブの入力・コード・nativeバイナリを差し替える前に影響を確認する。設定・コードhashが変わる結果は別の出力先に置き、既存bindingを編集して再開条件を回避しない。
- 全期間計算・大量ダウンロードは要求された範囲・並列数で、まず少数ケースを検証する。一時的なPID・完了率・run固有の既定値はこのガイドやskillへ固定しない。

## 変更と検証

- 編集前後に `git status --short` を確認し、既存の未コミット変更を保全する。検索は `rg`、手作業の編集は `apply_patch` を使い、無関係な整形・refactorを混ぜない。
- API・解析仕様を変えたら関連ドキュメントとテストを更新する。commit・merge・push・リリースは依頼された場合だけ行う。
- 対象環境のPythonを使う。Windowsの既存venvは `.venv/Scripts/python.exe`。依存は必要なextrasだけ導入し、共有環境・実行中ジョブへの影響を先に確認する。
- 狭い変更は関連テスト、広い回帰確認はCI相当の環境で行う。IDL実行環境を前提にせず、合成データ・参照仕様・既存実データで比較する。報告では実行済みと未実行の検証、実データの対象範囲を区別する。

リポジトリルートから、有効化した対象venvの `python` で実行します。

| 対象 | コマンド |
|---|---|
| 関連テスト / 全体テスト | `python -m pytest -q tests/test_omni.py` / `python -m pytest -q` |
| 構文・lint・型 | `python -m compileall -q src` / `python -m ruff check src tests` / `python -m mypy src` |
| Rust変更 | `cargo test -p sopran-native` / `cargo fmt --all --check` |
| schema変更 | `python -m sopran.schema_docs --check docs/reference/schemas.md` / `python -m sopran.schema_docs --language en --check docs/en/reference/schemas.md` |
| docs変更 | `python -m mkdocs build` |

CIの依存セット・手順は `.github/workflows/ci.yml`、docsとwheel配布は同ディレクトリの `docs.yml` / `publish.yml` を確認します。

## 作業に応じて読むskill

利用できるskillを確認して必要なものを読み、読み込み済みのものは再読込しません。通常の小さな変更に全手順を強制しません。

- ER解析・長時間バッチ: [.agents/skills/sopran-er-batch/SKILL.md](.agents/skills/sopran-er-batch/SKILL.md)
- Rust backend・性能検証: [.agents/skills/sopran-native/SKILL.md](.agents/skills/sopran-native/SKILL.md)
- 日本語文書の作成・推敲: 利用可能な `natural-japanese`。OpenSkillsでは `npx openskills read natural-japanese` で読みます。
