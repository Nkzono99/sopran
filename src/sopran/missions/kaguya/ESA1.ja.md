# PACE ESA1

PACE ESA1 は KAGUYA/SELENE の electron spectrum analyzer です。SOPRAN ではまず
raw PBF record を読み、`counts`, `energy_flux`, `energy`, `quality` を共通 schema に
沿って扱えるようにします。

## 主な変数

- `counts`: ESA1 count spectrum。
- `energy_flux`: energy bin ごとの flux 形式。ただし現状は未較正 placeholder。
- `energy`: energy bin center。現状は placeholder index。
- `quality`: record quality flag。

PACE の FOV / INFO calibration table は低レベル reader で読み込めます。

```python
from sopran.missions.kaguya import PaceCalibration, read_pace_fov, read_pace_info

cal = PaceCalibration(
    fov=read_pace_fov(["esas1-ch_angle", "esas1-pol_angle-RAM0"]),
    info=read_pace_info(["ESA-S1_ENE_POL_AZ_GFACTOR_4X16_20090828.dat"]),
)
cal.coverage("ESA1")
```

これは table を構造化する入口であり、物理較正済み `energy_flux`、energy 座標、
look-angle 座標への適用はまだ今後の作業です。

## 例

```python
import sopran as spn

kg = spn.Kaguya()
time = spn.day("2008-01-01")

flux = kg.esa1.energy_flux.load(time)
flux.plot()
```

`energy_flux` などの variable endpoint からもこの guide を参照します。
