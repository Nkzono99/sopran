# 期間・領域・解析条件

このページは、期間と領域の指定方法、それらを束ねる`View`、作業場所の`Project`、名前付きの条件`Case`の仕様をまとめます。
流れを先に掴みたい場合は[解析条件を残す](../start/reproducible.md)を読んでください。

## 期間は半開区間で指定する

SOPRANの期間（`TimeRange`）は開始を含み、終了を含みません。日ごとのシャードをつなげても、
境界のサンプルを二重に数えないためです。

```python
spn.period("2008-02-01T03:00", "2008-02-01T04:00")
spn.day("2008-02-01")      # 2008-02-01 00:00 から 2008-02-02 00:00 まで
spn.month("2008-02")
spn.year("2008")
```

ISO 8601の文字列と`datetime`を受け付けます。タイムゾーンのない時刻はUTCとして扱います。
`TimeRange`は`start`、`stop`（UTCの`datetime`）と、文字列の`start_iso`、`stop_iso`を持ちます。

## 領域は経度の定義域と一緒に持つ

```python
region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")

region.crosses_lon_boundary        # True（0/360度をまたぐ）
region.contains(355, 0)            # True
region.to_lon_domain("-180_180")   # 経度を -180〜180 で表した Region
```

経度の既定は東経正・0〜360度、緯度は惑星中心緯度です。`lon_domain`、`lon_direction`、`lat_type`で変えられます。
月面マップでの座標の扱いは[月面マップ](../data/moon/index.md)にあります。

## View

`View`は期間・領域と処理条件を束ねた、変更不可のオブジェクトです。

```python
view = spn.view(
    time=spn.day("2008-02-01"),
    region=spn.Region(lon=(120, 160), lat=(-45, -10), body="moon"),
    frame="SSE",
    download="never",
)
```

| 種類 | 引数 | 効果 |
|---|---|---|
| 選択 | `time`（または`start`と`stop`） | エンドポイントの既定の期間になる |
| 選択 | `region` | 月面マップの既定の領域になる |
| 選択 | `mission`、`instrument`、`product`、`quality` | 解析条件として記録する |
| 処理 | `download` | ミッションのダウンロード方針になる |
| 処理 | `spice_kernels`、`time_scale`、`backend` | `view.frame_context()`が作る`FrameContext`に入る |
| 処理 | `frame`、`cache` | 解析条件として記録する |

`view.kaguya`、`view.artemis`、`view.omni`、`view.moon`は、それぞれ`spn.Kaguya`などの実体です。
メソッドで期間を省くと`view.time`を使います。登録済みのデータ源は`view.source("kaguya")`でも取り出せます。

条件を変えるときは新しい`View`を作ります。

```python
view.with_time("2008-02-01T03:00", "2008-02-01T04:00")
view.with_region(None)
view.with_context(frame="GSE", download="missing")
```

`spn.view(...)`は、カレントディレクトリから親へたどって最初に見つかった`sopran.toml`を
Projectの設定として使います。`spn.kaguya`などの短い入口も同じです。

## Project

`Project`は解析テーマの作業ディレクトリです。

```python
project = spn.Project("projects/lunar_wake")
project = spn.Project("projects/lunar_wake", store=spn.Store("/path/to/sopran_data"))
```

| 項目 | 内容 |
|---|---|
| `project.root` | 作業ディレクトリ。`sopran.toml`を置く |
| `project.store` | 使うStore。省略時は[設定](configuration.md)の優先順位で決まる |
| `project.artifact_root` | `project.save()`の保存先 |
| `project.view(...)` | このProjectの既定値を使う`View` |
| `project.kaguya`など | 期間を持たないミッションの実体 |

## Case

`Case`は`sopran.toml`に名前付きで保存した解析条件です。

```toml
[defaults]
frame = "SSE"

[defaults.region]           # 領域を持たないCaseの既定
body = "moon"
lon = [120, 160]
lat = [-45, -10]

[cases.wake_20080201]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"

[cases.wake_20080201.context]   # frame, cache, download, quality, time_scale
download = "never"

[cases.wake_20080201.region]
body = "moon"
lon = [130, 150]
lat = [-30, -20]
```

```python
case = project.case("wake_20080201")
case.kaguya.esa1.counts.load()
case.with_time("2008-02-01T03:00", "2008-02-01T04:00")   # View を返す
case.view                                                # Case と同じ条件の View
```

各キーは、Caseの値、セッション設定、Projectの`[defaults]`、ユーザー設定の順に解決します。
ただし`download`だけは、セッション設定と環境変数（`SOPRAN_OFFLINE`など）がCaseの値より優先します（[設定](configuration.md#優先順位)）。
`project.case(name, start=..., stop=...)`は、`sopran.toml`に書かずにその場でCaseを作ります。

`project.save_case(name, view)`は`View`の期間・領域・処理条件を`sopran.toml`へ追記し、
同じ内容を`cases/<name>.json`にも書きます。同名のCaseがあると止まります。上書きは未実装なので、
変えたいときは`sopran.toml`を編集してください。

## 来歴を記録する

`context=`は、図・成果物・データセットに解析条件を書き込む共通の引数です。

| 呼び出し | 記録先 |
|---|---|
| `plot(..., context=case)`、`quicklook(..., context=case)` | 図のJSON |
| `project.save(array, "interim/name", context=case)` | NetCDFと同名のJSON |
| `write_parquet(..., context=case)`、`write_dataset(..., context=case)` | Storeのマニフェスト |

`context`には`Case`、`View`、`metadata()`か`to_metadata()`を持つオブジェクト、JSONにできる辞書を渡せます。
`Case`ならCase名・Projectの場所・Storeの場所・期間・領域・既定値が入ります。

`project.save(value, name)`は、`to_xarray()`を持つ値をNetCDFとして`artifact_root`の下に保存し、
期間・出典・相対パスをJSONに記録します。Projectの中に置くのは一時的な成果物です。
複数の解析で再利用するデータは[Store](store.md)に保存してください。
