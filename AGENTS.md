# SOPRAN Agent Guide

このリポジトリは `SOPRAN` (Satellite Observation Package for Retrieval,
Analysis, and Navigation) を開発するための場所です。月・惑星圏の衛星データを
Python から一貫した使用感で扱い、必要な重い処理は Rust に逃がす方針で進めます。

## 目的

- KAGUYA/SELENE、ARTEMIS などの衛星データ解析をまず月周辺ミッションから整備する。
- ミッションごとのデータ形式・測定器差分は `projects/<mission>` に閉じ込める。
- 利用者向け API はできるだけ共通化し、時刻範囲、instrument、product、座標系、
  metadata、dataset root を同じ考え方で扱えるようにする。
- IDL/SPEDAS スクリプトの挙動を読み解き、公開 API としては pure Python + Rust で
  再実装する。

## 参照元

- 旧実装の参考場所: `F:\idl\lunarsat`
- 旧実装は解析しながら育った作業リポジトリなので、設計や文章を丸写ししない。
- 有用な reader、dataset layout、KAGUYA 処理、Rust backend の境界は参考にしてよい。
- 旧リポジトリや既存データセットを変更・削除・移動しない。必要な場合は明示確認する。

## 想定構成

まだ初期化中のため、最初の実装では次の方向を優先します。

```text
src/sopran/
  core/              # 共通データモデル、loader protocol、dataset registry
  projects/
    kaguya/          # KAGUYA/SELENE 固有 reader と product builder
    artemis/         # ARTEMIS 固有 reader と product builder
  frames/            # 座標系、SPICE、時刻変換
  analysis/          # mission 非依存の解析補助
  plotting/          # 可視化補助
crates/
  sopran-backend/    # 重い decode、binning、fit、shard 処理
docs/
tests/
```

## 設計方針

- Python API を主入口にする。Rust は backend、CLI、batch 境界で使い、細かすぎる FFI を
  乱立させない。
- mission 固有の loader と instrument 差分は隠蔽しすぎない。共通化は
  `TimeRange`, `Dataset`, `Product`, `Instrument`, `Metadata`, `CoordinateFrame`
  など自然な境界から始める。
- SPEDAS/tplot に近い使用感は目指すが、IDL common block やグローバル状態は公開 API に
  持ち込まない。
- データファイルの探索は dataset registry / layout 経由にし、解析コードに絶対パスを
  直接埋め込まない。
- 大量処理は日別 shard や chunk 単位で中間成果物とログが残る形にする。
- 解析ノート由来の一時処理を package API に入れる前に、再利用可能な reader、変換、
  product builder、workflow のどれなのかを分ける。

## コーディング規約

- Python は typed dataclass / pathlib / 明示的な型境界を優先する。
- 配列処理は `numpy`、表形式は必要に応じて `pandas` または `polars`、CDF は `cdflib`、
  SPICE は `spiceypy` など、標準的なライブラリを優先する。
- Rust は決定的で重い処理、バイナリ decode、binning、fit、shard 出力などに使う。
- public API は小さく保ち、mission 固有 API は `sopran.missions.<mission>` に置く。
- ドキュメントと利用者向け説明は日本語でよい。API 名、ファイル名、外部仕様名は英語のままにする。
- ファイル検索は `rg`、手作業の編集は `apply_patch` を優先する。

## データ安全

- 実データ、ダウンロードキャッシュ、大きな生成物、secret は git に入れない。
- `datasets/`, `data/`, `cache/`, `outputs/`, `working/` は原則として作業生成物扱いにする。
- ユーザーが明示しない限り、外部データセットの削除、再配置、再帰的な書き換えを行わない。
- 旧 `lunarsat` 側のファイルは読み取り参考に留める。

## 検証

スキャフォールド後は、変更内容に応じて次の確認を用意・実行します。

```powershell
python -m pytest -q
python -m compileall src
cargo test
cargo fmt --check
```

環境作成スクリプトや smoke script を追加したら、この節を実際のコマンドに更新してください。

## Git 運用

- 変更前後に `git status --short` を確認する。
- ユーザーが明示しない限り、既存変更を revert しない。
- タスクに関係しない refactor や大きな整形を混ぜない。
- 設計変更を伴う場合は README または `docs/` も同時に更新する。
