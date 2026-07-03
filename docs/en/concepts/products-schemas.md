# Products And Schemas

SOPRAN stores variable names, dimensions, units, frames, and aliases in
`VariableSchema` objects. Documentation, validation, and dataset manifests share
the same schema source.

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

## Where Used

| Use | API |
| --- | --- |
| Endpoint variables | `endpoint.schema()` |
| Loaded-data validation | `spn.validate_schema(data, schema)` |
| Schema reference generation | `python -m sopran.schema_docs docs/reference/schemas.md` |
| Single-variable parquet write | `SopranArray.write_parquet(store, ...)` |

Built-in schemas are listed in [Schemas](../reference/schemas.md).
