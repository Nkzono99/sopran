# LRS (Plasma Waves And Radio)

Of LRS (Lunar Radar Sounder), SOPRAN reads the public spectra (CDF) of the two receivers that measure natural radio and plasma waves.

| Entry point | Receiver | Contents |
|---|---|---|
| `kg.lrs.npw` | NPW (Natural Plasma Wave) | Spectra of receivers 1 and 2 |
| `kg.lrs.wfc` | WFC-H (Waveform Capture, high-frequency side) | Electric-field spectra plus gain, mode, and other support data |

## Variables

| Entry point | Dimensions | Units | Meaning |
|---|---|---|---|
| `npw.rx1`, `npw.rx2` | `time, frequency` | dB | NPW spectra |
| `npw.mode` | `time` | flag | NPW mode |
| `wfc.ex_db`, `wfc.ey_db` | `time, frequency` | dB | Raw WFC spectra |
| `wfc.ex_field`, `wfc.ey_field` | `time, frequency` | dB uV/m | Field level after gain and band correction |
| `wfc.ex_power_spectral_density`, `wfc.ey_power_spectral_density` | `time, frequency` | (V/m)^2/Hz | Electric-field power spectral density |
| `wfc.gain` | `time` | dB | Gain decoded from the Gain flag |
| `wfc.mode`, `wfc.xymode`, `wfc.fband`, `wfc.omode`, `wfc.postgap` | `time` | flag | Raw Mode byte, the modes decoded from it, and the PostGap flag |
| `wfc.pdc_ti`, `wfc.pdc_ti_words` | `time` (`pdc_word`) | count | Spacecraft time counter (not UTC) |

Names directly under the instrument, such as `kg.lrs.wfc_ey_power_spectral_density`, reach the same endpoints.

```python
kg = spn.kaguya
time = spn.period("2008-04-01T00:00:00", "2008-04-01T02:00:00")

npw = kg.lrs.npw.rx1.load(time, missing="warn")
psd = kg.lrs.wfc.ey_power_spectral_density.load(time)

spn.stack(
    npw.spectrogram(y="frequency", log_color=True),
    psd.spectrogram(y="frequency", log_color=True),
    kg.lrs.wfc.gain.load(time).line(),
).plot()
```

## Source files

NPW has one file per day and WFC one file per two hours. A range starting at an odd hour, such as 01:00–01:30,
still reads the preceding 00:00 WFC file.

```text
raw/kaguya/pds3/
  sln-l-lrs-5-npw-spectrum-v1.0/YYYYMMDD/data/LRS_NPW_V010_YYYYMMDD.cdf
  sln-l-lrs-4-wfc-spectrum-v1.0/YYYYMMDD/data/LRS_WFC_V010_YYYYMMDDhhmmss.cdf
```

## Caching

LRS endpoints save what they read to the Store with `cache="use"` (default).
Raw NPW and WFC spectra go to the `normalized` layer; gain, field level, power spectral density, and modes go to `features`.
Reading the same period again does not reread the CDF. Results loaded with `missing="empty"` or `"warn"` while source files were missing are not saved.

## Corrections and missing values

- Field level and power spectral density follow the dB correction and bandwidth normalization of SPEDAS (`kgy_lrs_load.pro`) and lunarsat.
- Values filled by the CDF sparse-record padding are kept distinct from observed zeros. For WFC support variables UINT1 `254`,
  and for PDC-TI `[65534, 0, 65534]`, are treated as missing. These differ from the CDF `FILLVAL=0`.
- Times come from the CDF `Epoch` (UTC). `wfc_pdc_ti` is a 48-bit on-board counter built from high, middle, and low 16-bit words;
  it is not converted to UTC without a conversion table. The raw three words stay in `wfc_pdc_ti_words`.

## Limitations

- Only WFC-H spectra can be read. WFC-L waveforms (10 Hz–100 kHz) are a separate product from the public spectra and are not supported.
- There is no long-term comparison test with SPEDAS on real data yet.

Wave-event candidate extraction is in [Experimental](../../experimental/waves.md).

## Sources

- Y. Kasahara et al., "Plasma wave observation using waveform capture in the Lunar Radar Sounder on board the SELENE spacecraft,"
  *Earth, Planets and Space* 60, 341–351 (2008). [doi:10.1186/BF03352799](https://doi.org/10.1186/BF03352799)
- [DARTS KAGUYA archive](https://darts.isas.jaxa.jp/en/missions/kaguya)
