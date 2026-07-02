from __future__ import annotations

from dataclasses import dataclass


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
