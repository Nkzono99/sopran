# 時刻をそろえる

機器ごとに時刻の刻みは異なります。図に並べるだけなら元の時刻のまま描けば十分ですが（[可視化](plotting.md)）、
値を比べたり統計・機械学習に入れたりするには、時刻を明示的にそろえる必要があります。
SOPRANには2つの方法があります。

| 目的 | 方法 |
|---|---|
| ある機器の観測時刻に、別の機器の値を対応させる | `resample_like` |
| 一定幅の時間ビンを作り、各機器の値をビンごとに集約した表を作る | `time_bins` + `SampleTable` |

## 別の機器の時刻に合わせる

```python
esa1 = spn.kaguya.esa1.counts.load(time)
conn = spn.kaguya.lmag.magnetic_connection.load(time)

conn_on_esa1 = conn.resample_like(esa1, method="nearest", tolerance="2s")
altitude_on_esa1 = spn.kaguya.orbit.altitude.load(time).resample_like(
    esa1, method="linear", tolerance="10s",
)
```

| `method` | 対応させる値 |
|---|---|
| `nearest` | 目標時刻に最も近いサンプル |
| `previous` | 目標時刻以前の最後のサンプル |
| `next` | 目標時刻以後の最初のサンプル |
| `linear` | 前後のサンプルの線形補間 |

`tolerance`より離れたサンプルしか無い時刻は欠損になります。`linear`では前後の両方のサンプルにこの条件をかけるため、
データの切れ目をまたいだ補間はしません。範囲外への外挿もしません。

関数版の`spn.resample_like(source, target, ...)`は、`SopranArray`のほか
pandas・Polars（`DataFrame`、`LazyFrame`）・xarrayのオブジェクトも受け取ります。
時刻はUTCの`datetime64[ns]`にそろえてから対応させます。元のデータ（`source`）の時刻に重複があると例外になります。
DataFrameを`linear`で補間するときは数値の列だけを補間し、列名が重複したpandasのDataFrameは受け付けません。

## 時間ビンを作る

```python
bins = spn.time_bins(time, cadence="10s", partial="drop")
bins.to_polars()     # index, start, stop, center, duration_seconds, is_partial
```

期間が`cadence`で割り切れないときの扱いを`partial`で決めます。

| `partial` | 動作 |
|---|---|
| `"error"`（既定） | 例外にする |
| `"keep"` | 末尾の短いビンを残す |
| `"drop"` | 末尾の短いビンを捨てる |

イベントごとの区間のように幅がそろわないビンは、`spn.time_bins(edges=[...])`で境界の列から作ります。
ビンはすべて`[start, stop)`の半開区間です。

## ビンごとに集約した表を作る

```python
features = (
    spn.SampleTable(bins)
    .add(sza, method="nearest", tolerance="5s")
    .add(wave_power, method="max")
    .add(density, method="median")
    .collect(join="inner")
)
```

| `method` | ビンに入れる値 |
|---|---|
| `nearest` | ビン中心に最も近いサンプル（ビンの外も含む。`tolerance`で制限） |
| `center` | ビン内で中心に最も近いサンプル |
| `mean`、`median`、`max` | ビン内の集約 |
| `first`、`last` | ビン内の最初・最後のサンプル |

| `collect`の引数 | 効果 |
|---|---|
| `join="outer"`（既定） | 全ビンを残し、値の無い所は欠損 |
| `join="inner"` | 全変数がそろったビンだけ残す |
| `fill=値` | `outer`で残った欠損を埋める |
| `quality_mask=配列` | 品質フラグが0・False・欠損のビンを落とす。`join`と`fill`より先に適用する |

すべての変数に同じ`method`を使う場合は、`spn.align(sza, density, grid=bins, method="nearest", tolerance="5s")`と書けます。
`time × component`のベクトルは`magnetic_field_x`、`magnetic_field_y`のような列に展開します。
現在対応しているのは時系列とベクトルで、スペクトルはまだ直接ビンに入れられません。

## 結果を使う

| 呼び出し | 返り値 |
|---|---|
| `features.to_polars()` | 時刻と変数ごとの列を持つ表。`layout="long"`で縦長 |
| `features.to_feature_frame()` | 変数の列だけの表（`include_time=True`で時刻も） |
| `features.to_feature_matrix()` | 数値行列と列名・時刻・来歴を持つ`FeatureMatrix` |
| `features.metadata()` | ビン・変数ごとの集約方法・結合方法の記録 |
| `features.write_dataset(store, "analysis.wake_context", context=case)` | Storeの`features`層に保存 |

`FeatureMatrix`は`select("sza", "wave_power")`で列を選び、`write_parquet`・`write_npz`で保存して
`FeatureMatrix.read_parquet`・`read_npz`で読み戻せます。
