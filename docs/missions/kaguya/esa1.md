# KAGUYA PACE ESA1

PACE ESA1 は電子スペクトルの endpoint です。まずは `counts` を読み、必要なら
parquet 保存や PlotStack に渡します。

```python
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")

counts = kg.esa1.counts.load(time)
flux = kg.esa1.energy_flux.load(time)
counts.to_xarray()
counts.to_polars()
```

## endpoint

| endpoint | dims | 使い方 |
| --- | --- | --- |
| `kg.esa1.counts` | `time, energy, look` | raw counts の確認、quicklook |
| `kg.esa1.energy_flux` | `time, energy, look` | INFO table による counts からの energy flux 較正 |
| `kg.esa1.quality` | `time` | flag panel、mask、alignment |

`energy_flux` は `counts / (integ_t * gfactor * efficiency)` を使う Python reference
実装です。既定の `efficiency` は 0.6 です。INFO table は既定で自動ロードされます。
INFO table が無い場合は `kg.esa1.energy_flux.load(...)` は明示エラーになります。
`energy` 座標は現時点では channel index で、物理 eV calibration はまだ限定的です。
raw file が無い場合の挙動は `missing="empty" | "warn" | "error"` で選びます。

## quicklook

まず単体の energy flux を見る場合は `plot()` が最短です。横軸は `time`、縦軸は
`energy`、色が `energy_flux` で、colorbar には
`energy_flux [eV/(cm^2 s sr eV)]` のように単位付きの値ラベルが出ます。

```python
kg.esa1.energy_flux.plot(time, log_color=True)
```

複数 panel を残す場合は `stack()` を使います。

```python
stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy", log_color=True),
    kg.esa1.quality.load(time).line(),
)
stack.quicklook("kaguya_esa1", root="reports")
```

## parquet

```python
record = (
    kg.esa1.energy_flux.pipeline(spn.period("2008-01-01", "2008-01-03"))
    .calibrate(calibration="auto")
    .write("kaguya.esa1.energy_flux", layer="normalized", partition="day")
    .run()
)
```

raw counts を保存する場合は calibration stage を使いません。

```python
record = (
    kg.esa1.counts.pipeline(spn.period("2008-01-01", "2008-01-03"))
    .write("kaguya.esa1.counts", layer="normalized", partition="day")
    .run()
)
```

look-angle 座標や長期検証の現状は
[実装状況](../../reference/status.md) にまとめています。
