# KAGUYA LRS を読む

LRS は NPW と WFC の public CDF を読み、スペクトルと派生電場量を `SopranArray`
として返します。

## 前提

- raw CDF は `Store.raw_path("kaguya", "pds3")` 以下の provider path に置く。
- WFC CDF は 2 時間 slot です。01:00-01:30 のような範囲でも直前の 00:00 file を
  探します。

```text
raw/kaguya/pds3/
  sln-l-lrs-5-npw-spectrum-v1.0/YYYYMMDD/data/LRS_NPW_V010_YYYYMMDD.cdf
  sln-l-lrs-4-wfc-spectrum-v1.0/YYYYMMDD/data/LRS_WFC_V010_YYYYMMDDhhmmss.cdf
```

## 読み込み

```python
import sopran as spn

store = spn.Store("data/store")
kg = spn.Kaguya(store=store, download="never")
time = spn.period("2008-04-01T00:00:00Z", "2008-04-01T02:00:00Z")

npw = kg.lrs.npw.rx1.load(time, cache="use", missing="warn")
wfc_power = kg.lrs.wfc.ey_power_spectral_density.load(time, cache="use")
gain = kg.lrs.wfc.gain.load(time, cache="use")
```

`cache="use"` は同じ時刻範囲の Store product があれば CDF を再読せず使います。
raw WFC / NPW は `normalized` layer、WFC gain / field / PSD / mode は `features` layer に
保存します。raw file が欠けて `missing="empty"` / `"warn"` になった場合、その
partial product は cache に保存しません。

## 可視化

```python
spn.stack(wfc_power.spectrogram(y="frequency", log_color=True)).plot()

spn.stack(
    npw.spectrogram(y="frequency", log_color=True),
    gain.lines(),
).plot()
```

WFC の `wfc_ex_field` / `wfc_ey_field` と
`wfc_ex_power_spectral_density` / `wfc_ey_power_spectral_density` は、SPEDAS/lunarsat
実装の dB 補正と bandwidth 正規化に合わせています。実データを使った長期の parity
test は今後の作業です。
