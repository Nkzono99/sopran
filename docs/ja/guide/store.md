# Storeにデータを保存する

`Store`は、取得した元ファイル・SOPRANが作った中間データ・利用者が採用した解析結果を、1つのルートの下に層を分けて置く仕組みです。
解析の作業場所である`Project`とは分けて持ち、複数のProjectや計算機から同じStoreを使えます。
保存先の決め方は[設定](configuration.md)、ディレクトリとファイルの詳細は[Storeのファイル構造](../reference/store-layout.md)にあります。

```python
store = spn.Store("/path/to/sopran_data")
```

## 層ごとに置くもの

| 層 | 置くもの | 作るもの |
|---|---|---|
| `raw` | 配布元から取得した元ファイル。名前とディレクトリ構成は配布元のまま | ダウンロード |
| `normalized` | 機器の標準的な物理量（カウント、エネルギーフラックス、磁場など）をParquetにしたもの | Pipeline、`write_parquet` |
| `features` | SOPRANが計算した派生量（軌道幾何、ピッチ角スペクトル、データの有無の集計など） | キャッシュ、`write_parquet` |
| `models` | 校正やモデル当てはめの結果 | 試作API、`write_parquet` |
| `databases` | 利用者や研究テーマごとに採用した表（イベント一覧など） | `store.database`、`store.event_catalog` |
| `cache` | 再生成できる一時ファイル | 内部処理 |
| `registry` | 検索用の索引 | 自動 |

`raw/`の元ファイルには、取得元URL・チェックサム・取得日時を書いた付属JSON（`<ファイル名>.sopran.json`）が付きます。

## キャッシュで計算をやり直さない

軌道幾何・磁力線の接続・LRSのスペクトル・ピッチ角スペクトルなどは、`cache=`で計算結果をStoreに残せます。

| `cache` | 動作 |
|---|---|
| `"use"`（既定） | 同じ引数の結果があれば読み、無ければ計算して保存する |
| `"refresh"` | 計算し直して上書きする |
| `"never"` | 保存せず、その場で計算する |

保存先は`features`層などのデータセットの下に、計算条件ごとの`variants/<variant_id>/`として分かれます。
`variant_id`は引数と入力ファイルの内容から決まるため、条件の違う結果を取り違えることはありません。
入力の元ファイルが一部欠けて`missing="empty"`や`"warn"`で読んだ結果は、不完全なのでキャッシュに保存しません。

## データの有無を集計する

各エンドポイントの`coverage()`は、日ごとか月ごとに、観測サンプル数と取得済みファイル数を集計した表を返します。

```python
daily = spn.kaguya.esa1.counts.coverage(spn.month("2008-02"), freq="day")
```

列は`sample_count`、`finite_sample_count`、`sample_time_count`、`expected_remote_files`、
`available_source_files`です。結果は`features`層に`<dataset>.coverage`として保存して再利用します。
これは観測の有無の集計で、解釈を加えたイベントではありません。

## Storeの中を探す

```python
store.datasets(refresh=True)                       # 全データセットの一覧（Polars）
store.datasets(layer="features", mission="kaguya")
store.raw_files(refresh=True, mission="kaguya")    # 元ファイルの一覧

lazy = store.scan_dataset("kaguya.esa1.counts", layer="normalized")   # Polars LazyFrame
frame = lazy.filter(...).collect()
```

`store.dataset(dataset_id, layer=...)`はデータセットの記録（`DatasetRecord`）を返します。

| 操作 | 呼び出し |
|---|---|
| 完了したシャードを読む | `record.scan()` |
| シャードの状態を見る | `record.shards(status="failed")`、`record.failed_shards()` |
| シャードのチェックサムを確かめる | `record.verify_checksums()`、`record.verify_shards()` |
| 入力の元ファイルまで含めて確かめる | `store.verify_dataset(dataset_id, layer=...)` |
| カタログを付属JSONから作り直す | `record.rebuild_catalog()`、`store.rebuild()` |

## 研究テーマのデータベース

採用した解析結果は`databases`層に、テーマごとの名前空間としてまとめます。

```python
db = store.database("lunar_wake", create=True)
db.register_product(name="event_table", schema=schema, description="hand-curated lunar wake events")
db.adopt_dataset(record, description="aligned context features")   # 既存データセットを移動せずに登録
db.products()
db.product("event_table").scan()
```

`adopt_dataset`は`features`層などにあるデータセットを、場所を変えずにデータベースの一覧へ加えます。

## イベントカタログ

人が選んだイベントや検出器の出力は、`event_catalog`で検証付きの表として保存できます。

```python
catalog = store.event_catalog("lunar_wake", create=True)
catalog.write_events(events, time_coverage=spn.month("2008-02"), overwrite=True)

monthly = catalog.counts(freq="month", by=("instrument",))
rates = catalog.rates(exposure, freq="day", by=("phenomenon",))
```

`events`は`time_start`、`time_stop`、`mission`、`instrument`、`phenomenon`、`confidence`、`detector`、
`detector_version`の列を持つ表です。`rates`は、検出器が実際に判定できた時間（`exposure_seconds`）で
件数を割った発生率を返し、イベントが0件の期間も0として残します。
観測できなかった期間を0件と区別するため、`exposure`には判定できた時間を別に集計して渡します。

## 別の計算機へ運ぶ

Storeはファイルのまま`rsync`で運べる形に保っています。手順は[Storeを別マシンへ運ぶ](store-sync.md)にあります。
