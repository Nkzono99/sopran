# Product と Schema（データ定義）

SOPRAN は変数名、dimensions、units、frame、aliases を `VariableSchema` として
コード側に持ちます。ドキュメント表、validation、dataset manifest は同じ schema
から作ります。

```python
schema = spn.InstrumentSchema(
    mission="my_mission",
    instrument="my_sensor",
    variables=(
        spn.VariableSchema(name="density", dims=("time",), units="cm^-3"),
    ),
)

schema.to_markdown()
schema.to_metadata(schema_version="0.1")
```

## 使う場面

| 場面 | API |
| --- | --- |
| endpoint の変数一覧を見る | `endpoint.schema()` |
| loaded data を検証する | `spn.validate_schema(data, schema)` |
| schema reference を更新する | `python -m sopran.schema_docs docs/reference/schemas.md` |
| parquet に保存する | `SopranArray.write_parquet(store, ...)` |

## レイヤとの対応

| 種類 | Store layer |
| --- | --- |
| 観測機器の標準量 | `normalized` |
| 時間 bin にそろえた派生量 | `features` |
| 利用者定義の event table | `databases` |

Built-in schema の一覧は [スキーマ](../reference/schemas.md) を参照してください。
