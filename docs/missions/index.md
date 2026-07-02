# Missions

Mission modules provide object-oriented access to spacecraft, instruments,
variables, file discovery, and data loading.

Current mission modules:

- KAGUYA/SELENE
- ARTEMIS

The common pattern is:

```python
mission.instrument.variable.plan(time)
mission.instrument.variable.load(time)
mission.instrument.variable.guide()
```

Attribute navigation should stay side-effect free. Network access, raw decode,
parquet scan, and plotting should happen only at explicit execution methods.
