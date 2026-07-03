# 可視化

解析では「異なる観測機器を同じ時間軸で見る」ことが多いため、SOPRAN は
`PlotStack` を公開 API として扱います。

## 1 panel quicklook

```python
counts = kg.esa1.counts.load(time)
counts.quicklook("counts_spectrum", root="reports", y="energy", log_color=True)
```

## multi-panel plot

```python
stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy", log_color=True),
    kg.esa1.quality.load(time).line(),
    art.p1.fgm.magnetic_field.load(time).lines(components="xyz"),
)

plot_result = stack.plot(backend="matplotlib")
plot_result.fig
```

## Case から作る

```python
stack = case.stack(
    case.kaguya.esa1.counts.spectrogram(y="energy", log_color=True),
    case.artemis.p1.esa.ion_energy_flux.spectrogram(y="energy", log_color=True),
    case.artemis.p1.fgm.magnetic_field.lines(components="xyz"),
)
stack.quicklook("wake_overview", root="reports", context=case)
```

## 可視化と feature table の違い

| 目的 | API |
| --- | --- |
| native cadence のまま並べる | `PlotStack` |
| 同じ時間 bin に集約する | `time_bins()` / `SampleTable` |
| ML 用の行列にする | `to_feature_matrix()` |
| provenance 付きで保存する | `quicklook(..., context=case)` |

長期・対話的可視化 backend の予定は [実装状況](../reference/status.md) に集約しています。
