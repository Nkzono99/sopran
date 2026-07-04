# Missions

Mission modules expose spacecraft, probes, instruments, variable endpoints,
file discovery, and load/plot entry points.

```python
mission.instrument.variable.plan(time)
mission.instrument.variable.load(time)
mission.instrument.variable.guide()
```

Attribute access is side-effect free. Download, decode, parquet scan, and plot
operations happen only through explicit execution calls.

## Targets

| Mission | Entry point | Main scope |
| --- | --- | --- |
| KAGUYA/SELENE | `spn.Kaguya()` | PACE ESA1/ESA2/IMA/IEA, LMAG, LRS, PDS3 archive |
| ARTEMIS | `spn.Artemis()` | P1/P2, FGM, ESA normalized parquet |

Details:

- [KAGUYA/SELENE](kaguya/index.md)
- [ARTEMIS](artemis/index.md)
- [Status](../reference/status.md)
