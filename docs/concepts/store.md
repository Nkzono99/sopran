# Store（保存場所）

`Store` は物理データの置き場所です。解析 workspace を表す `Project` とは分けます。

```python
store = spn.Store("F:/sopran_data")
```

## root の決め方

`Store()` に root を渡さない場合は環境変数を読みます。

| 項目 | 解決順 |
| --- | --- |
| data root | 明示引数 > `SOPRAN_DATA_ROOT` > `sopran_data` |
| cache root | 明示引数 > `SOPRAN_CACHE_ROOT` > `<data root>/cache` |

```powershell
$env:SOPRAN_DATA_ROOT = "F:/sopran_data"
$env:SOPRAN_CACHE_ROOT = "F:/sopran_cache"
```

`Project("workspace")` から作る場合は、環境変数が `sopran.toml` の `[store]` より優先されます。

## レイヤ

```text
raw files -> decode -> normalized shards -> catalog.parquet -> scan()
                       -> features / databases
                       -> quicklook png/html/json
```

| layer | 主な用途 |
| --- | --- |
| `raw` | provider 由来の元ファイル。名前は変えない |
| `normalized` | 観測機器の値を Polars で読める parquet にしたもの |
| `features` | binning、alignment、派生指標 |
| `models` | 較正・推定・学習モデル |
| `databases` | 利用者定義の curated product |

## dataset の中身

```text
dataset.json      # dataset ID, time coverage, provenance, managed
schema.json       # variables, dims, units, frame
catalog.parquet   # shard path, start/stop, row count, checksum, status（索引）
shards/           # parquet files と <shard>.sopran.json（shardごとの付属JSON、正本）
```

## よく使う操作

| 操作 | 使う API |
| --- | --- |
| raw file の保存場所を得る | `store.raw_path("kaguya", "pds3")` |
| raw file manifest を作る | `store.register_raw_file(...)` |
| raw file index を作る | `store.raw_files(refresh=True)` |
| dataset index を作る | `store.datasets(refresh=True)` |
| parquet dataset を読む | `store.scan_dataset(dataset_id, layer=...)` |
| checksum を確認する | `record.verify_checksums()` |
| 失敗 shard を見る | `record.failed_shards()` |

## マシン間の同期（rsync）

Store rootの下はファイルのまま`rsync`で運べる。次の約束で、送り先の置き場所が違っても同じdatasetとして使える。

- Store内の参照はすべてroot相対である。Store外のファイルは、checksumと元の場所の手がかりとして記録するだけで、探索には使わない。
- sopranが自動で作るcacheのvariant IDは、設定と入力の内容（raw manifestのchecksum等）から決まる。同じ処理はどのマシンでも同じIDになり、運んだ結果がそのまま再利用される。
- 各shardは一時ファイルに書いてからrenameする。shardごとの付属JSON（`<shard>.sopran.json`）が正本で、`catalog.parquet`はそこから作り直せる索引である。
  別のマシンやジョブが同じdatasetの別shardを書いても、運んだ後に索引を作り直せば合流する。
- `registry/`・`cache/`・datasetの`work/`・`*.sopran-tmp*`・`*.sopran-bak*`はマシン固有で、同期しない。
  registryはmanifestの変化を検知して自動で作り直される。
- `managed=True`のdatasetは、sopranが自動で作り再利用するもの（coverage、軌道・幾何量、磁力線接続、LRS、pitch angle spectrumのcache等）である。
  同期の既定はこれだけを対象にする。試行錯誤のdatasetは名前を指定して選ぶ。

```powershell
sopran-store --data-root F:/sopran_data sync-list > files.txt
sopran-store --data-root F:/sopran_data sync-list --dataset kaguya.er.paired_distributions --raw spice > files.txt
rsync -av --delay-updates --files-from=files.txt F:/sopran_data/ host:/data/sopran_data/
ssh host sopran-store --data-root /data/sopran_data rebuild
ssh host sopran-store --data-root /data/sopran_data verify
```

1行目はmanagedなdatasetだけ、2行目は名前とraw配下を指定する例である。
`rebuild`は付属JSONから索引を作り直し、`verify`は欠けたshardやchecksumの違いを表示する。
`sopran-store`は`python -m sopran.core.sync`と同じである。`--delay-updates`は、転送した全ファイルを最後にまとめて置き換える。
`rebuild`は、付属JSONのない古いdatasetにも付属JSONを作る（移行）。
Pythonからは`store.rebuild()`、`record.rebuild_catalog()`、`record.verify_shards()`、`store.file_reference(path)`を使う。

## database product

利用者定義の表や event list は `databases` layer に置けます。

```python
db = store.database("lunar_wake", create=True)
product = db.register_product(
    name="event_table",
    schema=kg.esa1.schema(),
    description="hand-curated lunar wake events",
)

lazy = db.products()[0].scan()
```

定説化した現象や手動 curated event は `event_catalog()` からも扱えます。
`write_events()` は `time_start` / `time_stop` / `phenomenon` / `detector`
などの列を持つ表を `databases` layer に保存し、`counts()` は日別・月別に
event 数を集計します。

```python
catalog = store.event_catalog("lunar_wake", create=True)
catalog.write_events(events, time_coverage=spn.month("2008-02"), overwrite=True)
monthly = catalog.counts(freq="month", by=("instrument",))
```

観測データの有無や finite sample 数は event catalog ではなく、各 endpoint の
`coverage()` で確認します。これは解釈済み event ではなく、Store の `features`
layer に保存される availability summary です。

```python
coverage = kg.esa1.energy_flux.coverage(time, freq="day", cache="use")
```
