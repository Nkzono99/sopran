# Project、View、Case（解析単位）

SOPRAN では、データ構造と解析条件を分けて扱います。

| オブジェクト | 役割 |
| --- | --- |
| `Store` | raw data、download cache、normalized parquet、features、registry の保存場所 |
| `Project` | どの `Store` を使うか、成果物をどこに出すか、既定値をどうするかという解析環境 |
| `View` | time、region、frame、cache、backend override などを束ねた一時的な解析 lens |
| `Case` | 名前を付けて保存した `View`。論文図、イベント解析、再実行したい条件の単位 |

`Project` 配下の data tree は、どのようなデータがあるかを表します。

```python
project = spn.Project("projects/lunar_wake", store=store)

project.kaguya.esa1.counts.info()
project.kaguya.esa1.counts.schema()
project.moon.sza.info()
```

## View で探索する

期間を何度も変えて見る探索作業では、`Case` ではなく `View` を使います。

```python
view = project.view(time=spn.day("2008-02-01"), frame="SSE")

view.kaguya.esa1.counts.plot()
view.artemis.p1.fgm.magnetic_field.plan()

zoom = view.with_time("2008-02-01T03:00:00", "2008-02-01T04:00:00")
zoom.kaguya.esa1.counts.plot()
```

`View` は immutable に扱います。`with_time(...)` は元の `view` を変更せず、新しい
`View` を返します。

`View` の中は、対象を表す `selection` と、処理方法を表す `context` に分けています。

| 層 | 例 | 意味 |
| --- | --- | --- |
| selection | `time`, `region`, `mission`, `instrument`, `product`, `quality` | 何を切り出すか |
| context | `frame`, `cache`, `download`, `backends`, `spice_kernels`, `time_scale` | どう処理・変換するか |

通常利用では backend を指定しません。`FrameContext` などが用途に応じて `spiceypy`、
`spacepy` などを自動選択します。研究上 backend を固定したいときだけ override します。

```python
view = project.view(
    time=spn.day("2008-02-01"),
    backend={"frames": "spiceypy"},
)
```

## Case と sopran.toml

良い条件が見つかったら、`View` を `Case` として保存できます。

```python
project.save_case("wake_20080201", zoom)
case = project.case("wake_20080201")
```

`sopran.toml` には保存済み case と project 既定値を書けます。

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

dem = case.moon.dem.plan(source="lro.lola.dem_118m")
shadow = case.moon.shadow.plan(dem=dem)
```

一時的に期間だけを変えたい場合は、保存済み `Case` から `View` を派生します。

```python
case.with_time("2008-02-01T03:00:00", "2008-02-01T04:00:00").kaguya.esa1.counts.plot()
```

## provenance

plot、feature table、artifact に `context=case` または `context=view` を渡すと、解析条件を metadata に
残せます。

```python
stack = case.stack(
    case.kaguya.esa1.counts.spectrogram(y="energy"),
    case.artemis.p1.fgm.magnetic_field.lines(components="xyz"),
)
result = stack.quicklook("wake_overview", root="reports", context=case)
```

一時成果物は `Project.save(...)`、再利用するデータは `Store` に保存します。
