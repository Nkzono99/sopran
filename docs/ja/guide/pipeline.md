# バッチ処理

数日から数か月分のデータを取得・デコードし、日別のParquetシャードとしてStoreに保存する作業には`Pipeline`を使います。
1日分をノートブックで調べるだけなら、`load()`と`write_parquet()`で足ります（[読み込んだ配列を扱う](arrays.md)）。

!!! note "対応しているデータ源"
    `Pipeline`の実行部（バックエンド）を持つのは、現在KAGUYA PACE（`esa1`、`esa2`、`ima`、`iea`）だけです。
    LRSなどバックエンドの無いエンドポイントで`run()`・`scan()`・`stream()`を呼ぶと`PipelineError`になります。

## 処理の段を並べる

`Pipeline`はエンドポイントの`pipeline(time)`から作り、段を並べて最後に`run()`で実行します。
段を追加しただけでは何も実行しません。

```python
time = spn.period("2008-01-01", "2008-01-04")

pipe = (
    spn.kaguya.esa1.energy_flux.pipeline(time)
    .calibrate(calibration="auto")
    .quicklook("esa1_energy_flux")
    .write("kaguya.esa1.energy_flux", layer="normalized", partition="day")
)
```

| 段 | 内容 |
|---|---|
| `download()`、`decode()`、`normalize()` | 元ファイルの取得、デコード、正規化を明示する |
| `calibrate(...)` | 校正を適用する（PACEの`energy_flux`） |
| `select_variables(...)` | 機器から複数の変数を選ぶ（機器の`pipeline()`から作ったとき） |
| `quicklook(name, ...)` | 保存後に、データセットの`preview/`へPNGとJSONを書く |
| `write(dataset_id, layer=..., partition="day")` | 保存先を決める。`partition="day"`で日別シャード |
| `from_normalized()` | 元ファイルではなく、Storeに保存済みのデータセットから読む |

## 実行前に確かめる

```python
pipe.plan()                    # 入力、段、出力先
result = pipe.run(dry_run=True)
print(result)                  # 実行せずに、同じ形式の結果を表示する
```

## 実行する

```python
result = pipe.run()
result.to_dict()               # 状態、run ID、出力データセット、ログのパス
```

既存のデータセットを壊さないよう、既定では出力先が既にあると止まります。

| 引数 | 動作 |
|---|---|
| `mode="create"`（既定） | 出力先が既にあれば止まる |
| `mode="append"` | シャードを追加する |
| `mode="replace"` | 置き換える。PACEの日別シャードとの組み合わせは未対応 |
| `resume=True` | 完了済みの範囲を再利用する。要求範囲がすべて完了していれば何もしない |
| `only_failed=True` | 失敗したシャードだけを作り直す |
| `on_error="continue"` | シャードが失敗しても続け、`failed`として記録する（既定は`"fail"`で止まる） |
| `download="never"` | この実行だけダウンロード方針を変える |

各実行にはrun IDが付き、データセットの`logs/<run_id>.json`に段ごとの開始・終了時刻、行数、シャード数を記録します。
マニフェストの来歴にも、段の一覧・期間・ダウンロード方針・run IDが入ります。

## 保存済みのデータを読む

```python
lazy = spn.kaguya.esa1.counts.pipeline(time).from_normalized().scan()      # Polars LazyFrame
frame = spn.kaguya.esa1.counts.pipeline(time).from_normalized().collect()

for day_frame in pipe.stream(partition="day"):
    process(day_frame)
```

`stream`は`"all"`と`"day"`に加え、PACEでは保存済みシャードごとの`"shard"`を使えます。

## 全期間の重い計算

全期間にわたるモデル当てはめのような重い処理は、日別シャード・再開・並列実行を前提にしたCLIを別に用意しています。
例として[ER全期間バッチ](../experimental/er-batch.md)を参照してください。
新しいデータ源で`Pipeline`を実行できるようにする方法は[データ源を追加する](../development/extending.md)にあります。
