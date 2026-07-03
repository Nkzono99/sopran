# KAGUYA/SELENE

KAGUYA/SELENE は SOPRAN の最初の月ミッション API です。ミッション、観測機器、
変数の順にたどります。

```python
kg = spn.Kaguya()
time = spn.day("2008-01-01")

counts = kg.esa1.counts.load(time)
b = kg.lmag.magnetic_field.load(time)
```

## Endpoint

| instrument | endpoint | 主な用途 |
| --- | --- | --- |
| `esa1` | `counts` | PACE ESA1 raw counts |
| `esa1` | `energy_flux` | ESA1 differential energy flux |
| `esa1` | `quality` | quality flag |
| `lmag` | `magnetic_field` | Moon Mean Earth frame の磁場 vector |

## raw path

KAGUYA PDS3 archive は `Store.raw_path("kaguya", "pds3")` 以下に置きます。

```text
raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/YYYYMMDD/data/IPACE_PBF1_YYMMDD_ESA1_V003.dat.gz
  sln-l-lmag-3-mag-ts-v1.0/nominal/YYYYMMDD/data/MAG_TSYYYYMMDD.dat
```

## よく使う確認

```python
kg.info()
kg.esa1.counts.plan(time)
kg.esa1.load_calibration(download="never")
kg.lmag.magnetic_field.lines(time, components="xyz")
```

PACE ESA1 の詳細は [PACE ESA1](esa1.md) を参照してください。較正や SPEDAS parity
の現状は [実装状況](../../reference/status.md) に集約しています。
