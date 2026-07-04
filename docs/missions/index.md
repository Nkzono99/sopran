# ミッション

ミッション module は spacecraft、instrument、variable endpoint、file discovery、
load/plot の入口を提供します。

```python
mission.instrument.variable.plan(time)
mission.instrument.variable.load(time)
mission.instrument.variable.guide()
```

属性アクセスだけでは副作用を起こしません。download、decode、parquet scan、
plot は `load()`、`run()`、`plot()`、`quicklook()` などの明示的な呼び出しで行います。

## 対象

| ミッション | 入口 | 主な対象 |
| --- | --- | --- |
| KAGUYA/SELENE | `spn.Kaguya()` | PACE ESA1/ESA2/IMA/IEA、LMAG、LRS、PDS3 archive |
| ARTEMIS | `spn.Artemis()` | P1/P2、FGM、ESA normalized parquet |

詳細:

- [KAGUYA/SELENE](kaguya/index.md)
- [ARTEMIS](artemis/index.md)
- [実装状況](../reference/status.md)
