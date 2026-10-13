# 解析条件を残す

イベント解析では、同じ期間・領域・座標系で複数の機器を見比べ、良い条件が見つかったら名前を付けて残します。
SOPRANでは、一時的な条件を`View`、名前を付けて保存した条件を`Case`、それらを置く作業場所を`Project`で扱います。

## Viewで期間と領域を束ねる

```python
import sopran as spn

view = spn.view(
    time=spn.day("2008-02-01"),
    region=spn.Region(lon=(120, 160), lat=(-45, -10), body="moon"),
    frame="SSE",
)

view.kaguya.esa1.counts.load()            # 期間を省略すると view の期間を使う
view.kaguya.lmag.magnetic_field.plot()
view.moon.sza.compute(subsolar_lon_lat=(0.0, 0.0))   # 領域も view から受け取る
```

`view.kaguya`は`spn.Kaguya`そのもので、期間・領域・ダウンロード方針・SPICEカーネルの既定値だけが
`view`に結び付いています。`frame="SSE"`は解析条件として記録されます。データの座標変換は
[座標変換](../guide/frames.md)の`transform()`で明示します。
期間だけを変えたいときは、新しい`View`を派生させます。元の`view`は変わりません。

```python
zoom = view.with_time("2008-02-01T03:00:00", "2008-02-01T04:00:00")
zoom.kaguya.esa1.counts.plot()
```

## Projectに作業場所を作る

`Project`は解析テーマごとのディレクトリです。設定ファイル`sopran.toml`と、保存した条件・成果物を置きます。

```python
project = spn.Project("projects/lunar_wake")
view = project.view(time=spn.day("2008-02-01"), frame="SSE")
```

## Caseとして名前を付けて保存する

```python
project.save_case("wake_20080201", zoom)
case = project.case("wake_20080201")

case.kaguya.esa1.counts.load()   # 保存した期間・領域で読む
```

保存した条件は`projects/lunar_wake/sopran.toml`に追記され、手で編集もできます。

```toml
[cases.wake_20080201]
start = "2008-02-01T03:00:00Z"
stop = "2008-02-01T04:00:00Z"

[cases.wake_20080201.context]
frame = "SSE"

[cases.wake_20080201.region]
body = "moon"
lon = [120.0, 160.0]
lat = [-45.0, -10.0]
lon_domain = "0_360"
lon_direction = "east_positive"
lat_type = "planetocentric"
```

## 図と一緒に条件を保存する

`quicklook()`に`context=case`を渡すと、図のJSONにCaseの名前・期間・領域・Storeの場所が記録されます。
後から図を見たときに、どの条件で作ったかを確かめられます。

```python
stack = spn.stack(
    case.kaguya.esa1.counts.spectrogram(y="energy", log_color=True),
    case.kaguya.lmag.magnetic_field.lines(components="xyz"),
)
stack.quicklook("wake_overview", root="reports", context=case)
```

計算途中の配列は`project.save(array, "interim/name", context=case)`でNetCDFとして残せます。
複数の解析で再利用するデータは、Projectではなく[Store](../guide/store.md)に保存します。

## 次に読む

ここまでで基本の流れは終わりです。以降は目的に合わせて参照してください。

- `View`・`Case`の全オプションと`sopran.toml`の書き方: [期間・領域・解析条件](../guide/views-cases.md)
- 複数パネルの図の組み立て: [可視化](../guide/plotting.md)
- 機器ごとの変数と注意点: [データ一覧](../data/index.md)
