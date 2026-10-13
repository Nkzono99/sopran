# ARTEMIS

ARTEMISは、THEMISのP1（THEMIS-B）とP2（THEMIS-C）を月周回軌道で運用するミッションです。
SOPRANはNASA SPDF（CDAWeb）のLevel 2の日別CDFを取得してStoreに置き、FGMとESAの量を読みます。

## 入口

- `p1.fgm.magnetic_field`：スピン周期（約3秒）の磁場ベクトル（GSE、nT）。
- `p1.esa.ion_energy_flux`、`p1.esa.electron_energy_flux`：微分エネルギーフラックス。
  エネルギーは記録ごとの座標`energy`（`time, energy_bin`）。
- `p1.esa.ion_density`、`p1.esa.ion_velocity`（GSE）、`p1.esa.electron_density`：地上処理のモーメント。
- `p2`も同じ構成です。ESAは`mode="reduced"`（既定）・`"full"`・`"burst"`を選べます。

## 例

```python
import sopran as spn

art = spn.artemis
time = spn.period("2011-07-01T06:00", "2011-07-01T08:00")

stack = spn.stack(
    art.p1.esa.ion_energy_flux.spectrogram(time),
    art.p1.fgm.magnetic_field.lines(time, components="xyz"),
)
plot_result = stack.plot()
```

取得方針は`download=`（`missing`・`never`・`always`）、ファイルが無い日の扱いは`missing=`（`empty`・`warn`・`error`）で指定します。
詳しくは公開ドキュメントのARTEMISのページを見てください。
