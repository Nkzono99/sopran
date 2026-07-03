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

```python
vectors_in_moon_me = frames.transform_vectors(
    [[1.0, 0.0, 0.0]],
    times=["2008-01-01T00:00:00"],
    source_frame="MOON_ME",
    target_frame="SELENE_M_SPACECRAFT",
)
```

SPICE / SpacePy backend の実装状況は [実装状況](../reference/status.md) を参照してください。
