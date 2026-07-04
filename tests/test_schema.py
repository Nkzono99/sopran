from __future__ import annotations

import numpy as np
import polars as pl
import pytest
import xarray as xr

import sopran as spn
from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.missions.kaguya.schema import KAGUYA_ESA1_SCHEMA


def test_schema_classes_are_exported_from_top_level() -> None:
    assert spn.InstrumentSchema is InstrumentSchema
    assert spn.VariableSchema is VariableSchema


def test_instrument_schema_exports_machine_readable_metadata() -> None:
    schema = InstrumentSchema(
        mission="artemis",
        instrument="fgm",
        variables=(
            VariableSchema(
                name="magnetic_field",
                dims=("time", "component"),
                units="nT",
                dtype="float64",
                frame="SSE",
                description="Vector magnetic field.",
                aliases=("b",),
            ),
        ),
    )

    assert schema.to_metadata(schema_version="0.1") == {
        "mission": "artemis",
        "instrument": "fgm",
        "schema_version": "0.1",
        "variables": [
            {
                "name": "magnetic_field",
                "dims": ["time", "component"],
                "units": "nT",
                "dtype": "float64",
                "frame": "SSE",
                "description": "Vector magnetic field.",
                "aliases": ["b"],
            }
        ],
    }


def test_instrument_schema_exports_markdown_variable_table() -> None:
    schema = InstrumentSchema(
        mission="artemis",
        instrument="fgm",
        variables=(
            VariableSchema(
                name="magnetic_field",
                dims=("time", "component"),
                units="nT",
                dtype="float64",
                frame="SSE",
                description="Vector magnetic field.",
                aliases=("b",),
            ),
        ),
    )

    assert schema.to_markdown() == "\n".join(
        [
            "# artemis / fgm schema",
            "",
            "| name | dims | units | dtype | frame | aliases | description |",
            "| --- | --- | --- | --- | --- | --- | --- |",
            "| magnetic_field | time, component | nT | float64 | SSE | b | "
            "Vector magnetic field. |",
        ]
    )


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


def test_validate_schema_rejects_xarray_frame_mismatch() -> None:
    schema = InstrumentSchema(
        mission="artemis",
        instrument="fgm",
        variables=(
            VariableSchema(
                name="magnetic_field",
                dims=("time", "component"),
                frame="SSE",
            ),
        ),
    )
    dataset = xr.Dataset(
        data_vars={
            "magnetic_field": (
                ("time", "component"),
                np.array([[1.0, 2.0, 3.0]]),
                {"frame": "GSE"},
            ),
        },
        coords={"time": ["2011-07-01T00:00:00Z"], "component": ["x", "y", "z"]},
    )

    with pytest.raises(spn.SchemaError, match="magnetic_field.*frame"):
        spn.validate_schema(dataset, schema)


def test_validate_schema_rejects_xarray_units_mismatch() -> None:
    schema = InstrumentSchema(
        mission="artemis",
        instrument="fgm",
        variables=(
            VariableSchema(
                name="magnetic_field",
                dims=("time", "component"),
                units="nT",
            ),
        ),
    )
    dataset = xr.Dataset(
        data_vars={
            "magnetic_field": (
                ("time", "component"),
                np.array([[1.0, 2.0, 3.0]]),
                {"units": "T"},
            ),
        },
        coords={"time": ["2011-07-01T00:00:00Z"], "component": ["x", "y", "z"]},
    )

    with pytest.raises(spn.SchemaError, match="magnetic_field.*units"):
        spn.validate_schema(dataset, schema)
