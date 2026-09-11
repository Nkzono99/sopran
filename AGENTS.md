# SOPRAN Agent Guide

SOPRANは衛星データの取得・保存・解析・可視化を提供するPythonパッケージです。
APIの階層・型・単位がデータの構造と意味を伝え、標準の入口から可視化まで進めること、
元ファイルとnative観測ビンへの直接アクセスを保つことを設計の基準とします。
重い数値処理は同梱のPyO3/Rust拡張へまとめて渡します。
全体ルールはこのファイル、仕様は`docs/`、一時的な進捗は`_handoff/`や
各解析出力のログに置きます。仕様・既定値は現行コードとテストで確認してください。
`docs/`は公開ライブラリの利用方法・仕様向けです。個別研究のテーマ設定、文献調査、
試行錯誤、run単位の研究評価は`working/`以下に置き、公開ドキュメントのナビゲーションへ追加しません。

## 現在の構成

| 場所 | 責務 |
|---|---|
| `src/sopran/core/` | Store、config、Project/Case/View、データ型、pipeline、plotting、resampling |
| `src/sopran/missions/` | KAGUYA、ARTEMIS、OMNIなどのreader・機器・product API |
| `src/sopran/bodies/moon/` | DEM、shadow、SVMなどの月面product |
| `src/sopran/frames/` | 座標系、SPICE、時刻変換 |
| `src/sopran/experimental/` | 明示importで使う試作。ER、波動候補、mission用adapter |
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
- 通常APIからexperimentalへ依存しない。試作を機器やルートへ再公開しない。
  試作にも型・単位・テストを付け、Storeキーを通常productと分ける。
  `experimental/README.md`で未確定点と正式化の条件を管理し、リリース前に棚卸しする。
  未公開APIの念のための互換aliasやshimは作らない。
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

<skills_system priority="1">

## Available Skills

<!-- SKILLS_TABLE_START -->
<usage>
When users ask you to perform tasks, check if any of the available skills below can help complete the task more effectively. Skills provide specialized capabilities and domain knowledge.

How to use skills:
- Invoke: `npx openskills read <skill-name>` (run in your shell)
  - For multiple: `npx openskills read skill-one,skill-two`
- The skill content will load with detailed instructions on how to complete the task
- Base directory provided in output for resolving bundled resources (references/, scripts/, assets/)

Usage notes:
- Only use skills listed in <available_skills> below
- Do not invoke a skill that is already loaded in your context
- Each skill invocation is stateless
</usage>

<available_skills>

<skill>
<name>natural-japanese</name>
<description>仕事の日本語文書を読みやすくわかりやすく書く・直すためのスキル。議事録（文字起こしからの議事録化を含む）、調査レポート・分析レポート、社内ガイド・マニュアル、リサーチメモ・ディスカッションペーパー・企画書・提案書・報告書・メール、スライド構成案といったビジネス文書の作成・校正、「結論から書いて」「論旨を明確に」「見出しを端的に」「専門用語をわかりやすく説明して」といった指示のいずれでも使用する。AI臭さの除去（「AIっぽい」「AI臭い」「機械翻訳っぽい」「不自然」「もっと自然な日本語に」「機械っぽい」「人間っぽくして」「単調」「〜することができる、と言えるだろう、のような言い回し」といった直接・間接・口語の指摘、AIで書いたと言われた/疑われた）、読みにくい・わかりにくい文章の改善依頼（語順がおかしい、一文が長い、何が言いたいか分からない、読点の位置がおかしい等）、note記事やブログ記事・エッセイの新規執筆（任意のテーマをゼロから書く・書き起こす依頼を含む）、既存文章のリライト・推敲、AI臭さの診断・採点（「この文章AIが書いた？」「AI臭さをスコアで出して」「どれくらいAIっぽいか判定して」という書き換えを伴わない依頼）、自分の文体を学ばせたい・プロファイル化したいという要望（過去の文章を読ませて自分らしく書いてほしいという依頼も含む）にも対応する。禁止語の除去、リズムの単調さ・段落構造の均質さ・英語統語の直訳調に加え、語順・読点・一文一義・主語述語の距離といった読みやすさの原則にも対応する。技術文書の章構成やMarkdownフォーマットの整形自体（一文一行化・引用ブロック・脚注記法など）は対象外——それは別スキルの領域であり、本スキルは文章の自然さ・読みやすさ・わかりやすさに特化する。</description>
<location>project</location>
</skill>

</available_skills>
<!-- SKILLS_TABLE_END -->

</skills_system>
