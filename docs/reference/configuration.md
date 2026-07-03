# 設定

解析 workspace には `sopran.toml` を置けます。

```toml
[project]
artifact_root = "artifacts"

[defaults]
frame = "SSE"
cache = true

[store]
data_root = "data"
cache_root = "cache"

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
| Store root | 明示引数 > 環境変数 > `[store]` > default |
| artifact root | 明示引数 > `SOPRAN_ARTIFACT_ROOT` > `[project]` > project root |
| case region | `[cases.<name>.region]` > `[defaults.region]` |

## 環境変数

| 変数 | 役割 |
| --- | --- |
| `SOPRAN_DATA_ROOT` | `Store()` と `Project(...)` の既定 data root |
| `SOPRAN_CACHE_ROOT` | 既定 cache root。未指定なら `<data root>/cache` |
| `SOPRAN_ARTIFACT_ROOT` | `Project.save(...)` の既定出力先 |
| `SOPRAN_DOWNLOAD_MODE` | mission download policy |
| `SOPRAN_OFFLINE` | truthy のとき download policy を `never` にする |

`spn.Store("F:/data")` のように明示 root を渡した場合は、環境変数よりも明示引数が優先されます。
`spn.Project("workspace")` が store を自動生成する場合は、環境変数が `[store]` より優先されます。

不正な設定は `ConfigError` を送出します。
