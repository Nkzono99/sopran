# Pipeline（バッチ処理）

`Pipeline` は download、decode、normalize、quicklook、parquet 保存を遅延実行する
batch API です。

```text
source -> download -> decode -> normalize -> select -> quicklook -> write
```

```python
pipe = (
    kg.esa1.counts.pipeline(time)
    .download()
    .decode()
    .normalize()
    .quicklook("counts", frame="SSE")
    .write("kaguya.esa1.counts", layer="normalized")
)
```

## 実行

| 呼び出し | 目的 |
| --- | --- |
| `pipe.plan()` | 実行計画を確認する |
| `pipe.run(dry_run=True)` | 実行せずに結果形式を確認する |
| `pipe.run()` | 実行する |
| `pipe.run(mode="append")` | 既存 dataset に追加する |
| `pipe.run(mode="replace")` | 明示的に置き換える |
| `pipe.run(resume=True)` | 完了済み shard を再利用する |

```python
plan = pipe.plan()
result = pipe.run(dry_run=True)
print(result)
```

## Store から読む

```python
frame = (
    kg.esa1.counts.pipeline(time)
    .from_normalized()
    .collect()
)
```

長い期間では partition ごとに処理できます。

```python
for day_frame in pipe.stream(partition="day"):
    process(day_frame)
```

## 実行 backend

`Pipeline` はデータ endpoint の `pipeline(time)` から作ります。scan・stream・run は、
その source の `PipelineBackend` が実行します。現在 backend を持つのは KAGUYA PACE
（`kg.esa1` など）で、実装は `sopran.missions.kaguya.pipeline` にあります。
backend のない endpoint（LRS など）や、直接作った `Pipeline` の実行は `PipelineError` になります。
新しい source は `PipelineBackend` を継承し、対応する操作だけを override します。
`stream(partition="all" | "day")` は `scan_pipeline` から自動で分割されます。

実装済み backend と未実装 backend の一覧は [実装状況](../reference/status.md) に集約しています。
