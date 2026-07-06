# PlotStack を作る

## チェックリスト

- 並べたい panel を決める
- spectrum は `spectrogram(y=...)` を使う
- vector は `lines(components=...)` を使う
- 値の分布は `histogram(bins=...)` を使う
- 保存する場合は `quicklook()` に `root` を渡す

## loaded object から作る

```python
sza = kg.orbit.sza.load(time, cache="use")

stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy", log_color=True),
    kg.esa1.quality.load(time).line(),
    sza.histogram(bins=36),
)

plan = stack.plan()
plot_result = stack.plot(backend="matplotlib")
figure = plot_result.fig
```

## spectrum peak を重ねる

```python
ima = kg.ima.counts.load(time)
peak = ima.peak_trace(axis="energy", min_value=5.0)

stack = spn.stack(
    ima.spectrogram(y="energy", log_color=True).overlay(
        peak.line(name="energy_peak")
    ),
    kg.lmag.magnetic_field.load(time).lines(components="xyz"),
)

plot_result = stack.plot(backend="matplotlib")
```

## 保存前に matplotlib で調整する

```python
def configure(result):
    result.axes[0].set_ylim(10, 1000)
    result.axes[-1].tick_params(axis="x", rotation=30)
    result.fig.tight_layout()

quicklook = stack.quicklook(
    "ima_lmag_overview",
    root="reports",
    formats=("png", "html"),
    configure=configure,
)
```

## Case から作る

```python
stack = case.stack(
    case.kaguya.esa1.counts.spectrogram(y="energy", log_color=True),
    case.kaguya.esa1.quality.line(),
    case.artemis.p1.esa.ion_energy_flux.spectrogram(y="energy", log_color=True),
    case.artemis.p1.fgm.magnetic_field.lines(components="xyz"),
)

quicklook = stack.quicklook(
    "wake_overview",
    root="reports",
    formats=("png", "html"),
    context=case,
)
```

## 出力

| 出力 | 内容 |
| --- | --- |
| `.png` | 静的 quicklook |
| `.html` | 画像と metadata を含む簡易 report |
| `.json` | panels、time axis、context、provenance |
