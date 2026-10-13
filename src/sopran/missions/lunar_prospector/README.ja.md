# Lunar Prospector

Lunar Prospector（1998年1月〜1999年7月）の磁力計（MAG）と電子反射計（ER）のLevel 1Bデータを、
PDS PPIノードの日別ASCII表から読みます。表は必要に応じて取得し、Storeに置きます。

## 入口

- `mag.magnetic_field`（SSE）、`mag.magnetic_field_sel`（SEL）：5秒値の磁場（nT）。
- `mag.magnetic_field_rms`：5秒平均内の磁場のRMS。
- `mag.position`（SSE）、`mag.position_sel`（SEL）：月中心からの探査機の位置（km）。
- `er.electron_flux`：約80秒の全方向の電子微分数フラックス（15エネルギー）。エネルギーは`energy`座標。
- `er.electron_flux_3d`：3次元電子分布（15エネルギー×88視線方向）。`theta`・`phi`・自転を除いた探査機座標の磁場を座標に持つ。

## 例

```python
import sopran as spn

lp = spn.lunar_prospector
time = spn.period("1998-02-01T00:00", "1998-02-01T06:00")

spn.stack(
    lp.er.electron_flux.spectrogram(time),
    lp.mag.magnetic_field.lines(time, components="xyz"),
).plot()
```

詳しくは公開ドキュメントのLunar Prospectorのページを見てください。
