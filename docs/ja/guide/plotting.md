# 可視化

SOPRANの図は、1つの配列をすぐに見る`plot()`と、複数の機器を同じ時間軸に縦に並べる`PlotStack`の2本立てです。
どちらもMatplotlibで描き、軸とカラーバーに変数名と単位を表示します。作図には`viz` extraが必要です。

## 1つの配列を見る

```python
flux = spn.kaguya.esa1.energy_flux.load(time)
result = flux.plot()
```

`plot()`は配列の次元から図の種類を選びます（`mode="auto"`）。

| 次元 | 既定の図 |
|---|---|
| `time`のみ | 折れ線 |
| `time × energy × pitch_angle` | ピッチ角と時刻、エネルギーと時刻の2段 |
| それ以外の2次元以上（`time × energy`、`time × energy × look`など） | スペクトログラム。横軸が時刻、縦軸が`energy`などの座標、色が値。余分な次元は`reduction`（既定`"sum"`）で畳む |

`mode`に`"line"`、`"spectrogram"`、`"pitch"`、`"energy"`を渡すと種類を固定できます。
xarrayの`plot()`を直接使いたいときは`mode="raw"`を指定します。
磁場のようなベクトルは、下の`lines(components="xyz")`で成分ごとの折れ線にします。

表示範囲と目盛りは次の引数で調整します。

| 引数 | 例 |
|---|---|
| 縦軸の範囲・目盛り | `ylim=(10, 10000)`、`yscale="log"` |
| 色の範囲・対数 | `vmin=1e6`、`vmax=1e9`、`log_color=True` |
| 縦軸に使う座標 | `y="energy"` |

エネルギーフラックスのように何桁にもまたがる量は、スキーマの指定（`log_scale`、`log_dims`）に従って、色とエネルギー軸を既定で対数表示にします。
現在はPACEの`energy_flux`とARTEMISの`ion_energy_flux`・`electron_energy_flux`がこの指定を持ちます。線形に戻すときは`yscale="linear"`、`log_color=False`を渡します。
既定は配列の`plot()`・`quicklook()`・`spectrogram()`でも、エンドポイントの`spn.kaguya.esa1.energy_flux.plot(time)`でも同じです。

## 複数の機器を並べる

時間軸を共有する多段図は`spn.stack()`で作ります。SPEDASの`tplot`に相当します。

```python
stack = spn.stack(
    spn.kaguya.esa1.counts.load(time).spectrogram(y="energy", log_color=True),
    spn.kaguya.lmag.magnetic_field.load(time).lines(components="xyz"),
    spn.kaguya.orbit.altitude.load(time, cache="use").line(),
)
result = stack.plot()
```

パネルは配列のメソッドで作ります。

| メソッド | パネル |
|---|---|
| `spectrogram(y=...)` | スペクトログラム。`log_color`、`ylim`、`vmin`、`vmax`も指定できる |
| `line()` | 1次元の時系列 |
| `lines(components="xyz")` | ベクトルの成分。`components="xz"`のように一部も選べる |
| `histogram(bins=50)` | 値の分布 |
| `pitch_spectrogram()`、`energy_spectrogram(pitch=(0, 30))` | ピッチ角スペクトルの断面 |

各パネルは機器ごとの元の時刻のまま描き、時間方向の補間はしません。値を同じ時刻にそろえて比較したい場合は
[時刻をそろえる](alignment.md)の方法を使います。

`spectrogram()`などはエンドポイントからも呼べます。この場合は`stack.plot()`を実行したときに読み込みます。

```python
view = spn.view(time=time)
stack = spn.stack(
    view.kaguya.esa1.energy_flux.spectrogram(y="energy"),
    view.kaguya.lmag.magnetic_field.lines(components="xyz"),
)
stack.plan()     # 何を読むかを実行前に確認する
```

`plot()`済みの結果も`spn.stack()`に渡せます。ノートブックで1つずつ試した図を、後から1枚に並べ直せます。

## スペクトルのピークを重ねる

`peak_trace(axis="energy")`は、各時刻で値が最大になるエネルギーを時系列として返します。
`overlay()`でスペクトログラムに重ねて表示できます。

```python
ima = spn.kaguya.ima.counts.load(time)
peak = ima.peak_trace(axis="energy", min_value=5.0)

spn.stack(
    ima.spectrogram(y="energy", log_color=True).overlay(peak.line(name="energy_peak")),
).plot()
```

`max_peaks=2`で複数のピークを、`method="prominence"`で突出度による選択を使えます。
`look`のような余分な次元は、既定で合計してから求めます。これは目視確認のための候補抽出で、
解析に使う判定基準は利用者が条件を決めて確かめてください。

## Matplotlibで細部を調整する

`plot()`の返り値`PlotResult`は、Matplotlibの`fig`と`axes`をそのまま持っています。

```python
result = stack.plot()
result.axes[0].set_ylim(10, 1000)
result.fig.suptitle("IMA / LMAG")
```

保存前に同じ調整をしたいときは、関数を`configure`に渡します。

```python
def configure(result):
    result.axes[-1].tick_params(axis="x", rotation=30)
    result.fig.tight_layout()

stack.quicklook("ima_lmag", root="reports", configure=configure)
```

## 図を保存する

`quicklook(name, root=...)`は、図と作成条件をまとめて保存します。`SopranArray`と`PlotStack`の両方にあります。

| `formats` | 保存されるもの |
|---|---|
| `("png",)`（既定） | PNGと、同名のJSON |
| `("png", "html")` | 上記に加え、画像と記録を並べた簡易HTML |

JSONには、パネルの種類・軸・色の指定、期間、座標系、処理履歴を記録します。
`context=view`や`context=case`を渡すと、その解析条件も記録します（[期間・領域・解析条件](views-cases.md)）。

ブラウザで対話的に確かめたい場合は`stack.explore()`でPanelのアプリを作れます。
