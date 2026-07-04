from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sopran.core.errors import SchemaError


@dataclass(frozen=True)
class VariableSchema:
    name: str
    dims: tuple[str, ...]
    units: str | None = None
    dtype: str | None = None
    frame: str | None = None
    description: str = ""
    aliases: tuple[str, ...] = ()

    def __call__(self) -> VariableSchema:
        return self

    def to_metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dims": list(self.dims),
            "units": self.units,
            "dtype": self.dtype,
            "frame": self.frame,
            "description": self.description,
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True)
class InstrumentSchema:
    mission: str
    instrument: str
    variables: tuple[VariableSchema, ...]

    def variable(self, name: str) -> VariableSchema:
        for variable in self.variables:
            if name == variable.name or name in variable.aliases:
                return variable
        raise KeyError(name)

    def to_metadata(self, *, schema_version: str | None = None) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "mission": self.mission,
            "instrument": self.instrument,
            "variables": [variable.to_metadata() for variable in self.variables],
        }
        if schema_version is not None:
            metadata["schema_version"] = schema_version
        return metadata

    def to_markdown(self) -> str:
        rows = [
            f"# {self.mission} / {self.instrument} schema",
            "",
            "| name | dims | units | dtype | frame | aliases | description |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        rows.extend(
            " | ".join(
                (
                    "| " + _markdown_cell(variable.name),
                    _markdown_cell(", ".join(variable.dims)),
                    _markdown_cell(variable.units),
                    _markdown_cell(variable.dtype),
                    _markdown_cell(variable.frame),
                    _markdown_cell(", ".join(variable.aliases)),
                    _markdown_cell(variable.description) + " |",
                )
            )
            for variable in self.variables
        )
        return "\n".join(rows)


def validate_schema(
    data: Any,
    schema: InstrumentSchema,
    *,
    variables: tuple[str, ...] | list[str] | None = None,
) -> Any:
    """Validate that data exposes the selected schema variables."""

    selected = _selected_variables(schema, variables)
    names = _available_names(data)
    missing = [
        variable.name
        for variable in selected
        if variable.name not in names and not any(alias in names for alias in variable.aliases)
    ]
    if missing:
        raise SchemaError(
            "Schema validation failed; missing variables: "
            + ", ".join(missing)
            + f". Available variables: {', '.join(sorted(names)) or '(none)'}"
        )
    _validate_dtypes(data, selected)
    _validate_units(data, selected)
    _validate_frames(data, selected)
    _validate_xarray_dims(data, selected)
    return data


def _selected_variables(
    schema: InstrumentSchema,
    variables: tuple[str, ...] | list[str] | None,
) -> tuple[VariableSchema, ...]:
    if variables is None:
        return schema.variables
    return tuple(schema.variable(name) for name in variables)


def _markdown_cell(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|")


def _available_names(data: Any) -> set[str]:
    if hasattr(data, "collect_schema"):
        return set(data.collect_schema().names())
    if hasattr(data, "schema") and isinstance(data.schema, dict):
        return set(data.schema)
    if hasattr(data, "columns"):
        return {str(column) for column in data.columns}
    if hasattr(data, "data_vars") and hasattr(data, "coords"):
        return {str(name) for name in (*data.data_vars, *data.coords)}
    if hasattr(data, "name") and data.name is not None:
        return {str(data.name)}
    raise SchemaError(f"Unsupported data object for schema validation: {type(data).__name__}")


def _validate_xarray_dims(data: Any, variables: tuple[VariableSchema, ...]) -> None:
    if hasattr(data, "data_vars") and hasattr(data, "coords"):
        for variable in variables:
            name = _matching_name(data, variable)
            if name is None:
                continue
            dims = tuple(data[name].dims)
            if dims != variable.dims:
                raise SchemaError(
                    f"Schema validation failed; {variable.name} dims are {dims}, "
                    f"expected {variable.dims}"
                )
        return
    if hasattr(data, "dims") and hasattr(data, "name"):
        if len(variables) != 1:
            return
        variable = variables[0]
        name = data.name
        if name != variable.name and name not in variable.aliases:
            return
        dims = tuple(data.dims)
        if dims != variable.dims:
            raise SchemaError(
                f"Schema validation failed; {variable.name} dims are {dims}, "
                f"expected {variable.dims}"
            )


def _validate_dtypes(data: Any, variables: tuple[VariableSchema, ...]) -> None:
    for variable in variables:
        if variable.dtype is None:
            continue
        name = _matching_name(data, variable)
        if name is None:
            continue
        actual = _dtype_for_name(data, name)
        if actual is None:
            continue
        expected = _normalize_dtype(variable.dtype)
        if _normalize_dtype(actual) != expected:
            raise SchemaError(
                f"Schema validation failed; {variable.name} dtype is {actual}, "
                f"expected {variable.dtype}"
            )


def _dtype_for_name(data: Any, name: str) -> str | None:
    if hasattr(data, "collect_schema"):
        return str(data.collect_schema().get(name))
    if hasattr(data, "schema") and isinstance(data.schema, dict):
        dtype = data.schema.get(name)
        return str(dtype) if dtype is not None else None
    if hasattr(data, "__getitem__"):
        try:
            item = data[name]
        except (KeyError, TypeError):
            return None
        dtype = getattr(item, "dtype", None)
        return str(dtype) if dtype is not None else None
    return None


def _normalize_dtype(dtype: str) -> str:
    normalized = str(dtype).lower().replace("_", "").replace(" ", "")
    aliases = {
        "float": "float64",
        "double": "float64",
        "float64": "float64",
        "f64": "float64",
        "float32": "float32",
        "f32": "float32",
        "int": "int64",
        "int64": "int64",
        "i64": "int64",
        "int32": "int32",
        "i32": "int32",
        "uint64": "uint64",
        "u64": "uint64",
        "uint32": "uint32",
        "u32": "uint32",
        "str": "string",
        "string": "string",
        "utf8": "string",
        "object": "object",
        "bool": "bool",
        "boolean": "bool",
    }
    return aliases.get(normalized, normalized)


def _validate_frames(data: Any, variables: tuple[VariableSchema, ...]) -> None:
    for variable in variables:
        if variable.frame is None:
            continue
        name = _matching_name(data, variable)
        if name is None:
            continue
        actual = _frame_for_name(data, name)
        if actual is None:
            continue
        if _normalize_frame(actual) != _normalize_frame(variable.frame):
            raise SchemaError(
                f"Schema validation failed; {variable.name} frame is {actual}, "
                f"expected {variable.frame}"
            )


def _frame_for_name(data: Any, name: str) -> str | None:
    attrs = getattr(data, "attrs", {})
    if hasattr(data, "data_vars") and hasattr(data, "__getitem__"):
        variable_attrs = getattr(data[name], "attrs", {})
        value = variable_attrs.get("frame") or attrs.get("frame")
        return str(value) if value is not None else None
    if getattr(data, "name", None) == name:
        value = attrs.get("frame")
        return str(value) if value is not None else None
    return None


def _validate_units(data: Any, variables: tuple[VariableSchema, ...]) -> None:
    for variable in variables:
        if variable.units is None:
            continue
        name = _matching_name(data, variable)
        if name is None:
            continue
        actual = _unit_for_name(data, name)
        if actual is None:
            continue
        if _normalize_unit(actual) != _normalize_unit(variable.units):
            raise SchemaError(
                f"Schema validation failed; {variable.name} units are {actual}, "
                f"expected {variable.units}"
            )


def _unit_for_name(data: Any, name: str) -> str | None:
    attrs = getattr(data, "attrs", {})
    if hasattr(data, "data_vars") and hasattr(data, "__getitem__"):
        variable_attrs = getattr(data[name], "attrs", {})
        value = variable_attrs.get("units") or attrs.get("units")
        return str(value) if value is not None else None
    if getattr(data, "name", None) == name:
        value = attrs.get("units")
        return str(value) if value is not None else None
    return None


def _normalize_unit(unit: str) -> str:
    return str(unit).strip()


def _normalize_frame(frame: str) -> str:
    return str(frame).strip().upper()


def _matching_name(data: Any, variable: VariableSchema) -> str | None:
    names = _available_names(data)
    if variable.name in names:
        return variable.name
    for alias in variable.aliases:
        if alias in names:
            return alias
    return None
