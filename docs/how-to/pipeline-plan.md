# Pipeline を計画する

## チェックリスト

- どの source から読むか決める
- 実行 stage を並べる
- 出力 dataset ID を決める
- まず `dry_run=True` で確認する

```python
pipe = (
    kg.esa1.counts.pipeline(time)
    .download()
    .decode()
    .normalize()
    .quicklook("counts", frame="SSE", aggregation={"mode": "native"})
    .write("kaguya.esa1.counts", layer="normalized")
)
```

## 実行前確認

```python
plan = pipe.plan()
dry = pipe.run(dry_run=True)

plan.to_dict()
dry.to_dict()
print(dry)
```

## 実行後に見るもの

```python
result = pipe.run()
result.to_dict()
```

`PipelineResult` は run parameters、出力 dataset、quicklook path、metadata path を
JSON にしやすい形で返します。

既存 normalized dataset を読むだけなら、stage を実行せず `from_normalized()` を使います。

```python
frame = (
    kg.esa1.counts.pipeline(time)
    .from_normalized()
    .collect()
)
```
