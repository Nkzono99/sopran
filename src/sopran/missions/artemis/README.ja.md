# ARTEMIS

ARTEMIS は THEMIS P1/P2 探査機を月周辺ミッションとして扱うための mission-first API です。
現在の SOPRAN 実装では FGM magnetic field endpoint と ESA ion energy flux endpoint を中心に、
normalized parquet store から読み出す導線と PlotStack 連携を整備しています。

## Endpoints

- `p1.fgm.magnetic_field`: P1 fluxgate magnetic field vector。
- `p2.fgm.magnetic_field`: P2 fluxgate magnetic field vector。
- `p1.esa.ion_energy_flux`: P1 ESA ion differential energy flux。
- `p2.esa.ion_energy_flux`: P2 ESA ion differential energy flux。

## 例

```python
import sopran as spn

art = spn.Artemis()
time = spn.day("2011-07-01")

plan = art.p1.fgm.magnetic_field.plan(time)
ion_plan = art.p1.esa.ion_energy_flux.plan(time)
item = art.p1.fgm.magnetic_field.line(time)
plot_result = spn.stack(item).plot()
fig = plot_result.fig
```

## 次の作業

- CDAWeb/HAPI discovery と raw download policy の接続。
- store-backed normalized parquet loading の拡張。
- coordinate frame、vector component、energy bin metadata の保存。
