# 設定

SOPRAN は、明示引数、環境変数、project config、user global config の順に設定を解決します。
`spn.view(...)` と `spn.kaguya` / `spn.moon` などの shortcut は、現在ディレクトリから
親方向に最初に見つかる `sopran.toml` を project config として使います。

```toml
[project]
artifact_root = "artifacts"

[defaults]
frame = "SSE"
cache = true

[store]
data_root = "data"
cache_root = "cache"

[backends]
frames = "spiceypy"
plot = "matplotlib"

[cases.example]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"

[cases.example.region]
body = "moon"
lon = [350, 10]
lat = [-5, 5]
lon_domain = "0_360"
```

## 優先順位

| 設定 | 優先順位 |
| --- | --- |
| Project root | 明示引数 > 親方向に見つかった `sopran.toml` > user global `[project].root` > current directory |
| Store root | 明示引数 > 環境変数 > project `[store]` > user global `[store]` > default |
| artifact root | 明示引数 > `SOPRAN_ARTIFACT_ROOT` > project `[project]` > user global `[project]` > project root |
| defaults | project `[defaults]` > user global `[defaults]` > package default |
| backend | 明示 override > project `[backends]` > user global `[backends]` > `auto` |
| case region | `[cases.<name>.region]` > `[defaults.region]` |

通常の解析では backend を指定する必要はありません。`auto` のままにすると、座標変換なら
frame pair に応じて `spiceypy` や `spacepy` などが選ばれます。backend を固定したい解析だけ
`project.view(..., backend={"frames": "spiceypy"})` のように override します。

## user global config

project directory を作らずに使う場合、`spn.view(...)`、`spn.kaguya`、`spn.moon`、
`spn.Store()`、`spn.Kaguya()` は user global config を参照します。
設定ファイルの場所は `SOPRAN_CONFIG` で明示できます。
未指定の場合は OS 標準の user config directory を使います。既存の
`~/.sopran/config.toml` があり、標準 path に config がない場合は legacy path として読みます。

```toml
[store]
data_root = "F:/sopran_data"
cache_root = "F:/sopran_cache"

[defaults]
frame = "SSE"
cache = true
download = "missing"

[backends]
frames = "spiceypy"
plot = "matplotlib"
```

```python
import sopran as spn

view = spn.view(time=spn.day("2008-02-01"))
view.kaguya.esa1.counts.plot()

counts = spn.kaguya.esa1.counts.load(spn.day("2008-02-01"))
```

## 環境変数

| 変数 | 役割 |
| --- | --- |
| `SOPRAN_CONFIG` | user global config の path |
| `SOPRAN_DATA_ROOT` | `Store()` と `Project(...)` の既定 data root |
| `SOPRAN_CACHE_ROOT` | 既定 cache root。未指定なら `<data root>/cache` |
| `SOPRAN_ARTIFACT_ROOT` | `Project.save(...)` の既定出力先 |
| `SOPRAN_DOWNLOAD_MODE` | mission download policy。未指定時は `missing` |
| `SOPRAN_OFFLINE` | truthy のとき download policy を `never` にする |

`spn.Store("F:/data")` のように明示 root を渡した場合は、環境変数よりも明示引数が優先されます。
`spn.Project("workspace")` が store を自動生成する場合は、環境変数が `[store]` より優先されます。

不正な設定は `ConfigError` を送出します。
