# Project と Case（解析単位）

`Project` は解析 workspace、`Case` は特定の期間・領域・既定値を表します。

```python
project = spn.Project("projects/lunar_wake", store=store)
case = project.case("wake_20080201")
```

## sopran.toml

```toml
[defaults]
frame = "SSE"
cache = true

[cases.wake_20080201]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"

[cases.wake_20080201.region]
body = "moon"
lon = [120, 160]
lat = [-45, -10]
lon_domain = "0_360"
```

## Case から使う

`Case` 経由では time や region を繰り返し渡さずに済みます。

```python
case.kaguya.esa1.counts.load()
case.artemis.p1.fgm.magnetic_field.plan()

dem = case.moon.dem.plan(source="kaguya.tc.dem")
shadow = case.moon.shadow.plan(dem=dem)
```

## provenance

plot、feature table、artifact に `context=case` を渡すと、解析条件を metadata に
残せます。

```python
stack = case.stack(
    case.kaguya.esa1.counts.spectrogram(y="energy"),
    case.artemis.p1.fgm.magnetic_field.lines(components="xyz"),
)
result = stack.quicklook("wake_overview", root="reports", context=case)
```

一時成果物は `Project.save(...)`、再利用するデータは `Store` に保存します。
