# 設定

SOPRANの設定で主に決めるのは、データの保存先（Store）とダウンロード方針の2つです。
設定はセッション・ユーザー設定ファイル・環境変数・Projectの`sopran.toml`から読み、引数で明示した値が常に優先します。

## まず保存先を決める

何も設定しないと、`spn.kaguya`・`spn.Kaguya()`・`spn.Store()`のどれも、Projectのルートの下の`sopran_data/`を使います。
`sopran.toml`が無ければProjectのルートはカレントディレクトリなので、作業場所ごとに別のStoreができてしまいます。
最初に次のどれかで保存先を決めてください。

| 方法 | 効く範囲 | 書き方 |
|---|---|---|
| セッション設定 | 実行中のPythonプロセス | `spn.config.use(store="/path/to/sopran_data")` |
| ユーザー設定ファイル | そのユーザーの全プロセス | `spn.config.save_user(store="/path/to/sopran_data")` |
| 環境変数 | 環境変数を引き継ぐプロセス | `SOPRAN_DATA_ROOT=/path/to/sopran_data` |
| Projectの`sopran.toml` | そのProjectの中 | `[store] data_root = "data"` |

## セッション設定

```python
import sopran as spn

spn.config.use(store="/path/to/sopran_data", download="never")

with spn.config.using(store="/path/to/other_data"):
    spn.kaguya.esa1.counts.load(time)     # この中だけ別のStore

spn.config.reset()                        # セッション設定を消す
```

`use`と`using`は`store`（または`data_root`と`cache_root`）、`project`、`artifact_root`、`download`、
`frame`、`cache`、`backends`を受け取ります。設定ファイルは書き換えません。

`spn.Store("/path")`はStoreのオブジェクトを作るだけで、`spn.kaguya`が使うStoreは変わりません。
短い入口の保存先を変えるには`spn.config.use(store=...)`を使います。

## ユーザー設定ファイル

`spn.config.save_user(...)`は、同じ引数をユーザー設定ファイルに保存します。直接編集しても構いません。

| OS | 場所 |
|---|---|
| Windows | `%APPDATA%\sopran\config.toml` |
| macOS | `~/Library/Application Support/sopran/config.toml` |
| Linux | `$XDG_CONFIG_HOME/sopran/config.toml`（未設定なら`~/.config/sopran/config.toml`） |

環境変数`SOPRAN_CONFIG`でファイルを指定することもできます。上の場所にファイルが無く、
古い`~/.sopran/config.toml`がある場合はそちらを読みます。相対パスは設定ファイルのディレクトリを基準に解決します。

```toml
[store]
data_root = "/path/to/sopran_data"
cache_root = "/path/to/sopran_cache"   # 省略時は <data_root>/cache

[defaults]
download = "missing"
frame = "SSE"
cache = true

[backends]
frames = "spiceypy"
plot = "matplotlib"

[project]
root = "/path/to/default_project"       # 短い入口が使う既定のProject
artifact_root = "artifacts"
```

## Projectの`sopran.toml`

`spn.view(...)`と`spn.kaguya`などの短い入口は、カレントディレクトリから親へたどって最初に見つかった
`sopran.toml`をProjectの設定にします。相対パスはProjectのディレクトリを基準に解決します。

```toml
[project]
artifact_root = "artifacts"

[store]
data_root = "data"
cache_root = "cache"

[defaults]
frame = "SSE"
download = "never"

[defaults.region]
body = "moon"
lon = [350, 10]
lat = [-5, 5]
lon_domain = "0_360"

[backends]
frames = "spiceypy"

[cases.example]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"
```

`[cases.*]`の書き方は[期間・領域・解析条件](views-cases.md#case)にあります。

## 環境変数

| 変数 | 役割 |
|---|---|
| `SOPRAN_CONFIG` | ユーザー設定ファイルのパス |
| `SOPRAN_DATA_ROOT` | Storeのルート |
| `SOPRAN_CACHE_ROOT` | キャッシュのルート。未指定なら`<Storeのルート>/cache` |
| `SOPRAN_ARTIFACT_ROOT` | `project.save()`の保存先 |
| `SOPRAN_DOWNLOAD_MODE` | ダウンロード方針の既定 |
| `SOPRAN_OFFLINE` | `1`、`true`、`yes`、`on`のとき、ダウンロード方針の既定を`never`にする |

## ダウンロード方針

| 値 | 動作 |
|---|---|
| `missing`（既定） | Storeに無い元ファイルだけを取得する |
| `never` | 通信しない。必要なファイルが無ければ例外、または空の結果（`missing=`の指定による） |
| `always` | 既存のファイルがあっても取得し直す |

ミッションのオブジェクト（`spn.Kaguya(download=...)`）、`View`、各`load(download=...)`で指定できます。
スーパーコンピューターの計算ノードのように外部へ通信できない環境では、`SOPRAN_OFFLINE=1`を設定してください。
環境変数は設定ファイル（`sopran.toml`、ユーザー設定）より優先するので、ファイルに`download = "missing"`と書いてあっても
その計算機では通信しません。コードで明示した値（引数、`spn.config.use`）は環境変数より優先します。

## 優先順位

上にある値ほど優先します。

| 設定 | 優先順位 |
|---|---|
| Storeのルート | 引数（`Store(root)`、`store=`） > セッション > `SOPRAN_DATA_ROOT` > Projectの`[store]` > ユーザー設定の`[store]` > `<Projectのルート>/sopran_data` |
| キャッシュのルート | 上と同じ順で`cache_root`・`SOPRAN_CACHE_ROOT`を探し、無ければ`<Storeのルート>/cache` |
| Projectのルート（短い入口・`spn.view`・`spn.Store()`） | セッションの`project=` > 親方向で最初に見つかった`sopran.toml` > ユーザー設定の`[project].root` > カレントディレクトリ |
| 成果物の保存先 | 引数 > セッション > `SOPRAN_ARTIFACT_ROOT` > Projectの`[project]` > ユーザー設定の`[project]` > Projectのルート |
| ダウンロード | 引数（`load`・ミッション・`View`） > セッション > `SOPRAN_OFFLINE` > `SOPRAN_DOWNLOAD_MODE` > Caseの値 > Projectの`[defaults]` > ユーザー設定の`[defaults]` > `missing` |
| `frame`・`cache` | 引数 > セッション > Projectの`[defaults]` > ユーザー設定の`[defaults]` |
| バックエンド | 引数 > セッション > Projectの`[backends]` > ユーザー設定の`[backends]` > 自動選択 |
| Caseの領域 | `[cases.<name>.region]` > `[defaults.region]` |

Storeのルートとダウンロード方針は、`spn.kaguya`のような短い入口、`spn.Kaguya()`のような明示的なオブジェクト、
`spn.Store()`、`View`・`Case`のどこから使っても同じ順で決まります。

バックエンドは通常指定しません。座標変換では変換元と変換先の座標系から自動で選びます
（[座標変換](frames.md)）。

不正な値（未知のダウンロード方針、表でないはずのキーなど）は`ConfigError`になります。
