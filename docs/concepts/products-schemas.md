# Products And Schemas

SOPRAN keeps variable metadata in code. A variable schema records:

- stable variable name
- dimensions
- units
- dtype
- coordinate frame
- description
- aliases

Endpoint metadata, validation, documentation tables, and aliases should derive
from schema objects where possible.

Schema classes are public:

```python
schema = spn.InstrumentSchema(
    mission="my_mission",
    instrument="my_sensor",
    variables=(
        spn.VariableSchema(name="density", dims=("time",), units="cm^-3"),
    ),
)

metadata = schema.to_metadata(schema_version="0.1")
table = schema.to_markdown()
```

`to_metadata()` is the shared machine-readable representation used by
`schema.json` and documentation generation. `to_markdown()` creates a variable
table that can be embedded in mission and instrument guides.
`VariableSchema` is callable and returns itself. This keeps loaded objects that
store a schema as an attribute compatible with endpoint-style `loaded.schema()`
access.
The built-in schema reference at [Schema Reference](../reference/schemas.md)
is generated from the same runtime schema objects exposed by
`spn.schema_reference_markdown()`.

Regenerate it after schema changes:

```powershell
python -m sopran.schema_docs docs/reference/schemas.md
python -m sopran.schema_docs --check docs/reference/schemas.md
```

Use `validate_schema()` before returning loaded data or before trusting a
derived table. Pass `variables=...` when only one product has been loaded from a
larger instrument schema:

```python
frame = spn.validate_schema(frame, kg.esa1.schema(), variables=("counts",))
dataset = spn.validate_schema(dataset, kg.esa1.schema())
```

Table-like data is checked for selected variable names or aliases. xarray
datasets and arrays are also checked against `VariableSchema.dims`. When
`VariableSchema.dtype` is set, Polars, pandas, and xarray dtypes are checked as
well. When `VariableSchema.units` or `VariableSchema.frame` is set and the
xarray variable or DataArray has matching metadata attributes, those values are
checked too. Validation failures raise `SchemaError`.
Loaded `SopranArray` objects can export the same variable to table form with
`to_polars()` or `to_pandas()`, preserving dimension coordinates as columns.
They can also write that one variable directly into a `Store` with
`write_parquet(store, ...)`; SOPRAN builds a one-variable `InstrumentSchema` and
records the variable metadata in the resulting `schema.json`.

`Store.write_parquet_dataset()` runs this check automatically when the dataset
`product` resolves to a variable in the supplied schema. Derived features whose
product names are outside the instrument schema can still be written with their
own schema.
Aligned feature datasets created by `AlignmentResult.write_dataset()` preserve
source xarray/DataArray `units` and `frame` attributes when they are present, so
derived `features` layer tables remain inspectable through `schema.json`.

`schema.json` preserves `units`, `dtype`, and `frame` when they are present on
`VariableSchema`. Vector and position products should use these fields to keep
component dtype and coordinate frame metadata discoverable.

Example variables:

```text
kaguya.esa1.counts
kaguya.esa1.quality
artemis.p1.fgm.magnetic_field
```

Standard instrument quantities belong in the `normalized` layer. Higher-level
derived quantities, such as pitch-angle distributions or event context, belong
in `features` or `databases`.
