# KAGUYA/SELENE

KAGUYA/SELENE は SOPRAN の最初の月ミッション API です。ミッション、観測機器、
変数の順にたどります。

```python
kg = spn.Kaguya()
time = spn.day("2008-01-01")

counts = kg.esa1.counts.load(time)
b = kg.lmag.magnetic_field.load(time)
bgse = kg.lmag.magnetic_field_gse.load(time)
conn = kg.lmag.magnetic_connection.load(time, cache="use")
sza = kg.orbit.sza.load(time, sun_vector=(1.0, 0.0, 0.0), cache="use")
wfc = kg.lrs.wfc.ey_power_spectral_density.load(time, cache="use")
```

## Endpoint

| instrument | endpoint | 主な用途 |
| --- | --- | --- |
| `esa1` | `counts` | PACE ESA1 raw counts |
| `esa1` | `energy_flux` | 未較正 differential energy-flux placeholder |
| `esa1` | `quality` | quality flag |
| `lmag` | `magnetic_field` | Moon Mean Earth frame の磁場 vector |
| `lmag` | `magnetic_field_gse` | GSE frame の磁場 vector |
| `lmag` | `magnetic_field_magnitude` | LMAG 磁場強度 `|B|` |
| `lmag` | `magnetic_connection` | local straight field line と球面月面の接続 |
| `lrs` | `npw_rx1`, `npw_rx2` | NPW spectrum |
| `lrs` | `wfc_ey_power_spectral_density` | WFC electric-field power spectral density |
| `orbit` | `position` | LMAG native time の MOON_ME 位置 |
| `orbit` | `position_gse` | LMAG native time の GSE 位置 |
| `orbit` | `radial_distance` | 月中心からの距離 |
| `orbit` | `altitude` | 球面月半径からの高度 |
| `orbit` | `subpoint` | 球面月面上の lon/lat |
| `orbit` | `sza` | 明示した太陽方向 vector に対する球面 subpoint SZA |

## 派生 geometry と時刻合わせ

LMAG native time のまま可視化したい場合は、派生 product を直接読みます。
`cache="use"` は同じ variant が Store にあれば再計算せず読みます。
magnetic connection は `connected_any`、plus/minus 別の接続有無、footpoint lon/lat、
距離、incidence angle を返します。

```python
frames = spn.FrameContext(spice_kernels=("kaguya.tm",))
conn = kg.lmag.magnetic_connection.load(time, cache="use")
sza = kg.orbit.sza.load(time, sun_vector=(1.0, 0.0, 0.0), cache="use")
position_gse = kg.orbit.position_gse.load(time, cache="use")
position_sse = kg.orbit.position.load(time, frame="SSE", context=frames)
conn.plot(kind="footpoint")
conn.plot(kind="altitude")
conn.plot(kind="incidence")
conn.plot(kind="distance")
```

PACE/ESA1 など別 instrument の時刻列に合わせる場合は `resample_like` を使います。

```python
esa1 = kg.esa1.counts.load(time)
conn_on_esa1 = conn.resample_like(esa1, method="nearest", tolerance="2s")
```

ESA1、LMAG、LRS、および LMAG 由来の orbit / magnetic connection load は raw file
が無い場合の挙動を `missing="empty" | "warn" | "error"` で選べます。

LRS endpoint も `cache="use"` / `"refresh"` / `"never"` を受け取ります。NPW と raw WFC
は `normalized` layer、WFC gain / field / power spectral density / decoded mode は `features`
layer に保存され、同じ時刻範囲を次に読むと CDF の再読を避けます。`refresh` は対象
dataset を現在の時刻範囲で再生成して上書きします。

派生配列は `SopranArray.write_parquet()` で Store に保存できます。operation metadata は
manifest の `parameters.operations` に残ります。

```python
cal = kg.esa1.load_calibration(download="never")
esa1_data = kg.esa1.load(time, calibration=cal)
pas = esa1_data.pitch_angle_spectrum(
    magnetic_field=[1.0, 0.0, 0.0],
    pitch_bins=[0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0],
)
pas.write_parquet(
    kg.store,
    dataset_id="kaguya.esa1.pitch_angle_spectrum",
    layer="features",
    mission="kaguya",
    instrument="esa1",
)
```

## raw path

KAGUYA PDS3 archive は `Store.raw_path("kaguya", "pds3")` 以下に置きます。

```text
raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/YYYYMMDD/data/IPACE_PBF1_YYMMDD_ESA1_V003.dat.gz
  sln-l-lmag-3-mag-ts-v1.0/nominal/YYYYMMDD/data/MAG_TSYYYYMMDD.dat
  sln-l-lrs-5-npw-spectrum-v1.0/YYYYMMDD/data/LRS_NPW_V010_YYYYMMDD.cdf
  sln-l-lrs-4-wfc-spectrum-v1.0/YYYYMMDD/data/LRS_WFC_V010_YYYYMMDDhhmmss.cdf
```

WFC CDF は 2 時間 slot なので、01:00-01:30 のような odd-hour 窓でも直前の
00:00 file が候補になります。

## よく使う確認

```python
kg.info()
kg.esa1.counts.plan(time)
kg.esa1.load_calibration(download="never")
kg.lmag.magnetic_field.lines(time, components="xyz")
kg.lmag.magnetic_field_gse.lines(time, components="xyz")
kg.lmag.magnetic_connection.plot(time, kind="footpoint")
kg.lrs.wfc.ey_power_spectral_density.spectrogram(time, y="frequency", log_color=True)
```

PACE ESA1 の詳細は [PACE ESA1](esa1.md) を参照してください。較正や SPEDAS parity
の現状は [実装状況](../../reference/status.md) に集約しています。
