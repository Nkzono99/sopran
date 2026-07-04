# Load KAGUYA LRS

LRS reads NPW and WFC public CDF files and returns spectra and derived electric
field products as `SopranArray` objects.

## Prerequisites

- Raw CDF files live under provider paths below `Store.raw_path("kaguya", "pds3")`.
- WFC CDFs are 2-hour slots. A window such as 01:00-01:30 still plans the
  preceding 00:00 file.

```text
raw/kaguya/pds3/
  sln-l-lrs-5-npw-spectrum-v1.0/YYYYMMDD/data/LRS_NPW_V010_YYYYMMDD.cdf
  sln-l-lrs-4-wfc-spectrum-v1.0/YYYYMMDD/data/LRS_WFC_V010_YYYYMMDDhhmmss.cdf
```

## Load

```python
import sopran as spn

store = spn.Store("data/store")
kg = spn.Kaguya(store=store, download="never")
time = spn.period("2008-04-01T00:00:00Z", "2008-04-01T02:00:00Z")

npw = kg.lrs.npw.rx1.load(time, cache="use", missing="warn")
wfc_power = kg.lrs.wfc.ey_power_spectral_density.load(time, cache="use")
gain = kg.lrs.wfc.gain.load(time, cache="use")
```

`cache="use"` reuses a matching Store product instead of decoding CDF again.
Raw WFC / NPW products are stored in the `normalized` layer; WFC gain, field,
PSD, and mode products are stored in `features`. If raw files are missing and
`missing="empty"` / `"warn"` returns a partial product, that partial product is
not cached.

## Plot

```python
spn.stack(wfc_power.spectrogram(y="frequency", log_color=True)).plot()

spn.stack(
    npw.spectrogram(y="frequency", log_color=True),
    gain.lines(),
).plot()
```

WFC `wfc_ex_field` / `wfc_ey_field` and
`wfc_ex_power_spectral_density` / `wfc_ey_power_spectral_density` follow the dB
correction and bandwidth normalization used by SPEDAS/lunarsat-style readers.
Long-span real-data parity tests are still future work.
