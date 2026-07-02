from __future__ import annotations

import numpy as np
import polars as pl
import pytest
import xarray as xr

import sopran as spn
from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.missions.kaguya.schema import KAGUYA_ESA1_SCHEMA


def test_validate_schema_accepts_selected_polars_variables() -> None:
    frame = pl.DataFrame(
        {
            "time": ["2008-02-01T00:00:08Z"],
            "energy": [0],
            "counts": [64],
        }
    )

    assert spn.validate_schema(
        frame,
        KAGUYA_ESA1_SCHEMA,
        variables=("counts",),
    ) is frame


def test_validate_schema_rejects_xarray_variable_dim_mismatch() -> None:
    dataset = xr.Dataset(
        data_vars={
            "counts": (("time",), np.array([64])),
        },
        coords={"time": ["2008-02-01T00:00:08Z"]},
    )

    with pytest.raises(spn.SchemaError, match="counts.*dims"):
        spn.validate_schema(
            dataset,
            KAGUYA_ESA1_SCHEMA,
            variables=("counts",),
        )


def test_validate_schema_rejects_polars_dtype_mismatch() -> None:
    schema = InstrumentSchema(
        mission="kaguya",
        instrument="esa1",
        variables=(
            VariableSchema(
                name="counts",
                dims=("time",),
                dtype="uint64",
            ),
        ),
    )
    frame = pl.DataFrame({"counts": [64]})

    with pytest.raises(spn.SchemaError, match="counts.*dtype"):
        spn.validate_schema(frame, schema)
