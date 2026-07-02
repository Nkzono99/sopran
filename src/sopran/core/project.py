from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from sopran.core.store import Store
from sopran.core.time import TimeRange, period
from sopran.missions.kaguya import Kaguya


class Project:
    """Analysis workspace that supplies case context to mission objects."""

    def __init__(self, root: Path | str, *, store: Store | None = None) -> None:
        self.root = Path(root)
        self.store = store or Store(self.root / "data")

    def case(
        self,
        name: str,
        *,
        start: object | None = None,
        stop: object | None = None,
    ) -> Case:
        if start is None or stop is None:
            config = self._read_config()
            try:
                case_config = config["cases"][name]
            except KeyError as exc:
                config_path = self.root / "sopran.toml"
                raise KeyError(f"Case {name!r} is not defined in {config_path}") from exc
            start = case_config["start"] if start is None else start
            stop = case_config["stop"] if stop is None else stop
        return Case(project=self, name=name, time=period(start, stop))

    def _read_config(self) -> dict[str, Any]:
        path = self.root / "sopran.toml"
        with path.open("rb") as handle:
            return tomllib.load(handle)


class Case:
    def __init__(self, *, project: Project, name: str, time: TimeRange) -> None:
        self.project = project
        self.name = name
        self.time = time
        self.kaguya = CaseKaguya(Kaguya(store=project.store), self)


class CaseKaguya:
    def __init__(self, mission: Kaguya, case: Case) -> None:
        self._mission = mission
        self._case = case

    def __getattr__(self, name: str):
        value = getattr(self._mission, name)
        if hasattr(value, "load"):
            return CaseInstrument(value, self._case)
        return value


class CaseInstrument:
    def __init__(self, instrument, case: Case) -> None:
        self._instrument = instrument
        self._case = case

    def load(self, time: TimeRange | None = None, **kwargs):
        return self._instrument.load(time or self._case.time, **kwargs)

    def plan(self, time: TimeRange | None = None):
        return self._instrument.plan(time or self._case.time)

    def pipeline(self, time: TimeRange | None = None):
        return self._instrument.pipeline(time or self._case.time)

    def __getattr__(self, name: str):
        value = getattr(self._instrument, name)
        if hasattr(value, "load") and hasattr(value, "plan"):
            return CaseVariableEndpoint(value, self._case)
        return value


class CaseVariableEndpoint:
    def __init__(self, endpoint, case: Case) -> None:
        self._endpoint = endpoint
        self._case = case

    def load(self, time: TimeRange | None = None, **kwargs):
        return self._endpoint.load(time or self._case.time, **kwargs)

    def plan(self, time: TimeRange | None = None):
        return self._endpoint.plan(time or self._case.time)

    def __getattr__(self, name: str):
        return getattr(self._endpoint, name)
