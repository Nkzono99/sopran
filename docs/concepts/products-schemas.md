# Products And Schemas

SOPRAN keeps variable metadata in code. A variable schema records:

- stable variable name
- dimensions
- units
- description
- aliases

Endpoint metadata, validation, documentation tables, and aliases should derive
from schema objects where possible.

Use `validate_schema()` before returning loaded data or before trusting a
derived table. Pass `variables=...` when only one product has been loaded from a
larger instrument schema:

```python
frame = spn.validate_schema(frame, kg.esa1.schema(), variables=("counts",))
dataset = spn.validate_schema(dataset, kg.esa1.schema())
```

Table-like data is checked for selected variable names or aliases. xarray
datasets and arrays are also checked against `VariableSchema.dims`. Validation
failures raise `SchemaError`.

`Store.write_parquet_dataset()` runs this check automatically when the dataset
`product` resolves to a variable in the supplied schema. Derived features whose
product names are outside the instrument schema can still be written with their
own schema.

Example variables:

```text
kaguya.esa1.counts
kaguya.esa1.quality
artemis.p1.fgm.magnetic_field
```

Standard instrument quantities belong in the `normalized` layer. Higher-level
derived quantities, such as pitch-angle distributions or event context, belong
in `features` or `databases`.
