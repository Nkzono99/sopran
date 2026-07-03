# 最初の解析

KAGUYA ESA1 を例に、確認、読み込み、可視化までを一通り行います。

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")
```

## 読み込む前に見る

```python
kg.esa1.counts.info()
kg.esa1.counts.plan(time)
kg.esa1.counts.guide()               # 既定は日本語
kg.esa1.counts.guide(language="en")
```

## 読み込む

```python
esa1 = kg.esa1.load(time)
esa1.info()

ds = esa1.to_xarray()
counts = esa1.to_polars("counts", reduce_look="sum")
```

## 並べて見る

```python
stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy", log_color=True),
    kg.esa1.quality.load(time).line(),
)

plot_result = stack.plot()
plot_result.fig
```

## 使い分け

| 目的 | API |
| --- | --- |
| まず中身を確認する | `info()` / `plan()` |
| メモリ上で解析する | `load()` / `to_xarray()` / `to_polars()` |
| 図として残す | `quicklook()` |
| 複数データを並べる | `spn.stack()` |
| 機械学習用にそろえる | `time_bins()` / `SampleTable` |
