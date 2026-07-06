# 可視化

解析では「異なる観測機器を同じ時間軸で見る」ことが多いため、SOPRAN は
`PlotStack` を公開 API として扱います。

## 1 panel quicklook

```python
counts = kg.esa1.counts.load(time)
counts.plot()
counts.quicklook("counts_spectrum", root="reports", y="energy", log_color=True)
```

`SopranArray.plot()` と `SopranArray.quicklook()` は既定で `mode="auto"` を使います。
1D は line、2D の `time x energy` は spectrogram、3D の
`time x energy x pitch_angle` は pitch/time と energy/time の 2 panel overview に
します。低レベルの xarray plot を直接呼びたい場合は `plot(mode="raw")` を使います。
spectrogram では横軸が `time`、縦軸が `energy` や `pitch_angle`、色が product の値です。
colorbar label には `energy_flux [eV/(cm^2 s sr eV)]` のように値名と単位が出ます。

```python
kg.esa1.energy_flux.plot(time)
kg.esa1.energy_flux.plot(
    time,
    ylim=(10.0, 10000.0),
    vmin=1.0e6,
    vmax=1.0e9,
)
```

KAGUYA PACE `energy_flux.plot()` は既定で energy 軸と color scale を log 表示にします。
汎用の spectrogram でも `yscale="log"`、`ylim=(low, high)`、`log_color=True`、
`vmin=...`、`vmax=...` を指定できます。

## 再ビン化してから見る

`SopranArray.rebin(axis=..., bins=...)` は、数値座標を持つ任意の軸を指定した
bin edge で再集計します。energy spectrum、pitch angle spectrum、frequency spectrum、
map の lon/lat などで同じ API を使えます。既定の集計は `sum` で、flux など平均したい
量では `reduction="mean"` を指定します。

```python
flux = kg.esa1.energy_flux.load(time)
coarse = flux.rebin(axis="energy", bins=[10, 30, 100, 300, 1000], reduction="mean")
coarse.plot(log_color=True)

pas = kg.esa1.energy_flux.pitch_angle_spectrum(time, magnetic_field=[1, 0, 0])
pas.rebin(
    bins={
        "energy": [10, 100, 1000, 10000],
        "pitch_angle": [0, 30, 60, 90, 120, 150, 180],
    }
).plot()
```

## multi-panel plot

```python
stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy", log_color=True),
    kg.esa1.quality.load(time).line(),
    art.p1.fgm.magnetic_field.load(time).lines(components="xyz"),
    wave_power.load(time).histogram(bins=50),
)

plot_result = stack.plot(backend="matplotlib")
plot_result.fig
```

`plot()` 済みの結果も `spn.stack()` に渡せます。notebook で endpoint を直接試しながら
後から panel 化したい場合に使えます。

```python
stack = spn.stack(
    spn.kaguya.esa1.energy_flux.plot(time, calibration="auto"),
    spn.kaguya.orbit.sza.plot(time),
)
stack.plot()
```

## spectrum peak を重ねる

`peak_trace(axis="energy")` は各時刻で最も強い energy bin の座標を返します。
`overlay()` を使うと、spectrogram と同じ panel にピーク候補線を重ねられます。
これは quicklook 用の候補抽出で、論文用の最終判定は利用者側で条件を明示して
確認してください。

```python
ima = kg.ima.counts.load(time)
peak = ima.peak_trace(axis="energy", min_value=5.0)

stack = spn.stack(
    ima.spectrogram(y="energy", log_color=True).overlay(
        peak.line(name="energy_peak")
    ),
    kg.lmag.magnetic_field.load(time).lines(components="xyz"),
)
stack.plot()
```

`max_peaks=2` のようにすると `time x peak` の複数線を返します。PACE の
`time x energy x look` のような配列では、既定で `look` などの余分な軸を `sum`
で畳み込んでからピーク候補を求めます。

## backend 側で細かく調整する

SOPRAN は代表的な引数だけを API として持ち、細かな体裁は backend-native object を
直接触る方針です。matplotlib backend では `PlotResult.fig` と `PlotResult.axes` を
そのまま使えます。

```python
result = stack.plot()
result.axes[0].set_ylim(10, 1000)
result.axes[0].tick_params(axis="x", rotation=30)
result.fig.suptitle("IMA / LMAG overview")
result.fig.tight_layout()
```

`quicklook()` で保存前に調整したい場合は `configure` に関数を渡します。

```python
def configure(result):
    result.axes[0].set_ylim(10, 1000)
    result.axes[-1].tick_params(axis="x", rotation=30)
    result.fig.suptitle("IMA / LMAG overview")

stack.quicklook("ima_lmag", root="reports", configure=configure)
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
| 値の分布を見る | `histogram(bins=...)` |
| 同じ時間 bin に集約する | `time_bins()` / `SampleTable` |
| ML 用の行列にする | `to_feature_matrix()` |
| provenance 付きで保存する | `quicklook(..., context=case)` |

長期・対話的可視化 backend の予定は [実装状況](../reference/status.md) に集約しています。
