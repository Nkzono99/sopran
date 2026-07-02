# Products And Schemas

SOPRAN keeps variable metadata in code. A variable schema records:

- stable variable name
- dimensions
- units
- description
- aliases

Endpoint metadata, validation, documentation tables, and aliases should derive
from schema objects where possible.

Example variables:

```text
kaguya.esa1.counts
kaguya.esa1.quality
artemis.p1.fgm.magnetic_field
```

Standard instrument quantities belong in the `normalized` layer. Higher-level
derived quantities, such as pitch-angle distributions or event context, belong
in `features` or `databases`.
