# ARTEMIS

ARTEMIS は THEMIS P1/P2 探査機を月周辺ミッションとして扱う API です。

```python
art = spn.Artemis()
time = spn.day("2011-07-01")

plan = art.p1.fgm.magnetic_field.plan(time)
ion = art.p1.esa.ion_energy_flux
```

## Endpoint

| probe | instrument | endpoint | 表示 |
| --- | --- | --- | --- |
| `p1` / `p2` | `fgm` | `magnetic_field` | `.lines(components="xyz")` |
| `p1` / `p2` | `esa` | `ion_energy_flux` | `.spectrogram(y="energy")` |

## PlotStack

```python
stack = spn.stack(
    art.p1.esa.ion_energy_flux.spectrogram(time, y="energy", log_color=True),
    art.p1.fgm.magnetic_field.lines(time, components="xyz"),
)
plot_result = stack.plot()
```

## Store

ARTEMIS endpoint は normalized parquet が `Store` にある場合に読みます。

```python
lazy = store.scan_dataset("artemis.p1.fgm.magnetic_field", layer="normalized")
frame = lazy.collect()
```

Raw discovery、CDAWeb/HAPI、CDF download の現状は [実装状況](../../reference/status.md)
に集約しています。
