# 時刻・単位・座標系

SOPRAN の時刻範囲は半開区間 `[start, stop)` です。日別 shard を追加しても境界の
サンプルを二重に数えないためです。

```python
time = spn.period("2008-02-01", "2008-02-02")
day = spn.day("2008-02-01")
month = spn.month("2008-02")
```

## TimeBins

```python
bins = spn.time_bins(time, cadence="10s", partial="drop")
bins.to_polars()
bins.metadata()
```

| `partial` | 動作 |
| --- | --- |
| `"error"` | 端数 bin があると例外 |
| `"keep"` | 端数 bin を残す |
| `"drop"` | 完全な bin だけを使う |
| `"custom"` | 明示 edge で作った grid |

## Alignment

複数データを機械学習や統計に入れるときは、まず bin を決めてから対応づけます。

```python
features = (
    spn.SampleTable(bins)
    .add(sza, method="nearest", tolerance="5s")
    .add(wave_power, method="max")
    .add(density, method="median")
    .collect(join="inner")
)

matrix = features.to_feature_matrix().select("sza", "wave_power")
```

| reducer | 意味 |
| --- | --- |
| `nearest` | bin center に最も近い値 |
| `center` | bin 内で center に最も近い値 |
| `mean` / `median` | bin 内集約 |
| `max` | bin 内最大 |
| `first` / `last` | bin 内の最初/最後 |

| `join` | 意味 |
| --- | --- |
| `outer` | 全 bin を残し、欠損は null |
| `inner` | 全 feature がある bin だけ残す |

## Resample Like

ある時刻列を別 instrument の実サンプル時刻へ合わせる場合は `resample_like` を使います。
`linear` の `tolerance` は補間点の前後にある source sample の両方に適用され、離れた
sample をまたぐ補間は欠損になります。
source 外側への `linear` 外挿はしません。pandas/polars/xarray の時刻は UTC として
`datetime64[ns]` に正規化してから合わせます。DataFrame 入力の `linear` は数値列だけを
補間します。source 側の時刻は一意である必要があります。pandas DataFrame の重複列名は
曖昧さを避けるため拒否します。Polars は `DataFrame` と `LazyFrame` の両方を受け取れます。

| method | 意味 |
| --- | --- |
| `nearest` | target 時刻に最も近い source sample |
| `previous` | target 時刻以前の最後の source sample |
| `next` | target 時刻以後の最初の source sample |
| `linear` | source sample 間の線形補間 |

```python
esa1 = kg.esa1.counts.load(time)
conn = kg.lmag.magnetic_connection.load(time, cache="use")
conn_on_esa1 = conn.resample_like(esa1, method="nearest", tolerance="2s")

altitude_on_esa1 = kg.orbit.altitude.load(time).resample_like(
    esa1,
    method="linear",
    tolerance="10s",
)
```

## FrameContext

座標系変換は `FrameContext` に provenance を集めます。

```python
frames = spn.FrameContext(
    spice_kernels=("kernels/naif0012.tls",),
    time_scale="utc",
)

b = kg.lmag.magnetic_field.load(time)
b_moon = b.transform("MOON_ME", context=frames)
```

同じ frame への変換は identity として provenance を残します。異なる frame への
3 成分ベクトル変換は `spiceypy` に委譲します。`SELENE_M_SPACECRAFT`, `MOON_ME`,
`SSE`, `GSE` などの非 identity 変換には、時刻 kernel と frame kernel を含む
SPICE kernel を `FrameContext(spice_kernels=...)` に渡してください。kernel が足りない
場合は推定せず `FrameTransformError` で止まります。
`FrameContext.metadata()` は Python 環境で見えている `available_backends` と、
SOPRAN が実装済みとして扱う `implemented_backends` を分けて返します。

```python
vectors_in_moon_me = frames.transform_vectors(
    [[1.0, 0.0, 0.0]],
    times=["2008-01-01T00:00:00"],
    source_frame="MOON_ME",
    target_frame="SELENE_M_SPACECRAFT",
)
```

SPICE / SpacePy backend の実装状況は [実装状況](../reference/status.md) を参照してください。
