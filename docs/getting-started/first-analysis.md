# 最初の解析

KAGUYA ESA1 を例に、確認、読み込み、可視化までを一通り行います。

```python
import sopran as spn

view = spn.view(time=spn.day("2008-01-01"), frame="SSE")
```

## 読み込む前に見る

```python
view.kaguya.esa1.counts.info()
view.kaguya.esa1.counts.plan()
view.kaguya.esa1.counts.guide()               # 既定は日本語
view.kaguya.esa1.counts.guide(language="en")
```

## 読み込む

```python
esa1 = view.kaguya.esa1.load()
esa1.info()

ds = esa1.to_xarray()
counts = esa1.to_polars("counts", reduce_look="sum")
```

## 並べて見る

```python
stack = spn.stack(
    view.kaguya.esa1.counts.spectrogram(y="energy", log_color=True),
    view.kaguya.esa1.quality.line(),
)

plot_result = stack.plot()
plot_result.fig
```

期間を変えて探索したい場合は、新しい `View` を派生します。

```python
zoom = view.with_time("2008-01-01T03:00:00", "2008-01-01T04:00:00")
zoom.kaguya.esa1.counts.plot()
```

## 使い分け

| 目的 | API |
| --- | --- |
| データ構造を見る | `project.kaguya.esa1.counts.info()` / `schema()` |
| 期間や領域を変えながら見る | `project.view(...)` / `spn.view(...)` |
| まず中身を確認する | `info()` / `plan()` |
| メモリ上で解析する | `load()` / `to_xarray()` / `to_polars()` |
| 図として残す | `quicklook()` |
| 複数データを並べる | `spn.stack()` |
| 機械学習用にそろえる | `time_bins()` / `SampleTable` |
