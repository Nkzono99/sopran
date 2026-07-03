# Parquet に保存する

## チェックリスト

- raw file が `Store.raw` にある
- 保存する variable を決める
- 上書きするか、追加するか、dry-run するかを決める
- `partition` を日別にするか決める

## 単一読み込みから保存

```python
esa1 = kg.esa1.load(time)

record = esa1.write_parquet(
    store,
    variable="counts",
    reduce_look="sum",
)

frame = record.scan().collect()
```

## Pipeline で保存

```python
pipe = (
    kg.esa1.pipeline(spn.period("2008-01-01", "2008-01-03"))
    .decode()
    .select_variables("counts")
    .write("kaguya.esa1.counts", layer="normalized", partition="day")
)

pipe.run(dry_run=True)
result = pipe.run()
```

## 実行 mode

| mode | 用途 |
| --- | --- |
| default | 既存 dataset があると保守的に止める |
| `append` | shard を追加する |
| `replace` | 明示的に置き換える |
| `resume=True` | 完了済み catalog を再利用する |
| `only_failed=True` | 失敗 shard だけを再実行する |

Resume や failed shard の詳細は [実装状況](../reference/status.md) に集約しています。
