# KAGUYA LMAG geometry を可視化する

LMAG native time の磁場、軌道、月面接続をまず確認するための最小手順です。

## 前提

- KAGUYA LMAG raw file が `Store.raw_path("kaguya", "pds3")` 以下にある、または
  `download="missing"` で取得できる。
- raw file が無いときの挙動は `missing="empty" | "warn" | "error"` で選ぶ。

## LMAG 時刻列で見る

```python
import sopran as spn

store = spn.Store("data/store")
kg = spn.Kaguya(store=store, download="never")
time = spn.day("2008-01-01")

b = kg.lmag.magnetic_field.load(time)
bmag = kg.lmag.bmag.load(time)
altitude = kg.orbit.altitude.load(time, cache="use")
subpoint = kg.orbit.subpoint.load(time, cache="use")
```

```python
spn.stack(
    bmag.lines(),
    altitude.lines(),
).plot()
```

## 月面接続を見る

```python
conn = kg.lmag.magnetic_connection.load(time, cache="use")

conn.plot(kind="footpoint")
conn.plot(kind="incidence")
conn.plot(kind="distance")
```

`conn.to_xarray()` には `connected_any`、plus/minus 別の接続有無、footpoint lon/lat、
接続距離、incidence angle が入ります。

## ESA1 などの時刻列へ合わせる

```python
esa1 = kg.esa1.counts.load(time, missing="warn")
conn_on_esa1 = conn.resample_like(esa1, method="nearest", tolerance="2s")
altitude_on_esa1 = altitude.resample_like(esa1, method="linear", tolerance="10s")
```

`cache="use"` は同じ variant が Store にあれば再計算せず読みます。raw file が無い、
または一部の日だけ欠けて `missing="empty"` / `"warn"` になった場合、その派生 product は
Store cache に保存しません。
