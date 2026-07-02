from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sopran.core.errors import SchemaError


@dataclass(frozen=True)
class VariableSchema:
    name: str
    dims: tuple[str, ...]
    units: str | None = None
    description: str = ""
    aliases: tuple[str, ...] = ()


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
    _validate_xarray_dims(data, selected)
    return data


def _selected_variables(
    schema: InstrumentSchema,
    variables: tuple[str, ...] | list[str] | None,
) -> tuple[VariableSchema, ...]:
    if variables is None:
        return schema.variables
    return tuple(schema.variable(name) for name in variables)


def _available_names(data: Any) -> set[str]:
    if hasattr(data, "collect_schema"):
        return set(data.collect_schema().names())
    if hasattr(data, "schema") and isinstance(getattr(data, "schema"), dict):
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


def _matching_name(data: Any, variable: VariableSchema) -> str | None:
    names = _available_names(data)
    if variable.name in names:
        return variable.name
    for alias in variable.aliases:
        if alias in names:
            return alias
    return None
