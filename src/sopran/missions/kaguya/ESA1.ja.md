# PACE ESA1

PACE ESA1 は KAGUYA/SELENE の electron spectrum analyzer です。SOPRAN ではまず
raw PBF record を読み、`counts`, `energy_flux`, `energy`, `quality` を共通 schema に
沿って扱えるようにします。

## 主な変数

- `counts`: ESA1 count spectrum。
- `energy_flux`: energy bin ごとの flux 形式。
- `energy`: energy bin center。
- `quality`: record quality flag。

## 例

```python
import sopran as spn

kg = spn.Kaguya()
time = spn.day("2008-01-01")

flux = kg.esa1.energy_flux.load(time)
flux.plot()
```

`energy_flux` などの variable endpoint からもこの guide を参照します。
