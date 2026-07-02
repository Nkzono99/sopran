from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from sopran.bodies import Moon
from sopran.core.plotting import PlotItem, PlotStack, stack
from sopran.core.store import Store
from sopran.core.time import TimeRange, period
from sopran.maps import Region
from sopran.missions.artemis import Artemis
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
        config: dict[str, Any] = {}
        case_config: dict[str, Any] = {}
        config_path = self.root / "sopran.toml"
        if config_path.exists() or start is None or stop is None:
            config = self._read_config()
        if config:
            case_config = config.get("cases", {}).get(name, {})
        if (start is None or stop is None) and not case_config:
            raise KeyError(f"Case {name!r} is not defined in {config_path}")
        if start is None or stop is None:
            start = case_config["start"] if start is None else start
            stop = case_config["stop"] if stop is None else stop
        return Case(
            project=self,
            name=name,
            time=period(start, stop),
            defaults=config.get("defaults", {}),
            region=_case_region(config.get("defaults", {}), case_config),
        )

    def _read_config(self) -> dict[str, Any]:
        path = self.root / "sopran.toml"
        with path.open("rb") as handle:
            return tomllib.load(handle)


class Case:
    def __init__(
        self,
        *,
        project: Project,
        name: str,
        time: TimeRange,
        defaults: dict[str, Any] | None = None,
        region: Region | None = None,
    ) -> None:
        self.project = project
        self.name = name
        self.time = time
        defaults = defaults or {}
        self.frame = defaults.get("frame")
        self.cache = bool(defaults.get("cache", False))
        self.region = region
        self.kaguya = CaseKaguya(Kaguya(store=project.store), self)
        self.artemis = CaseMission(Artemis(store=project.store), self)
        self.moon = Moon()

    def stack(self, *items: PlotItem) -> PlotStack:
        return stack(*items)


class CaseKaguya:
    def __init__(self, mission: Kaguya, case: Case) -> None:
        self._mission = mission
        self._case = case

    def __getattr__(self, name: str):
        value = getattr(self._mission, name)
        if hasattr(value, "load"):
            return CaseInstrument(value, self._case)
        return value


class CaseMission:
    def __init__(self, mission, case: Case) -> None:
        self._mission = mission
        self._case = case

    def __getattr__(self, name: str):
        value = getattr(self._mission, name)
        return CaseNode(value, self._case)


class CaseNode:
    def __init__(self, value, case: Case) -> None:
        self._value = value
        self._case = case

    def load(self, time: TimeRange | None = None, **kwargs):
        return self._value.load(time or self._case.time, **kwargs)

    def plan(self, time: TimeRange | None = None, **kwargs):
        return self._value.plan(time or self._case.time, **kwargs)

    def plot(self, time: TimeRange | None = None, **kwargs):
        return self._value.plot(time or self._case.time, **kwargs)

    def line(self, time: TimeRange | None = None, **kwargs):
        line_method = getattr(self._value, "line", None)
        if line_method is not None:
            return line_method(time or self._case.time, **kwargs)
        from sopran.core.plotting import line

        return line(lambda: self.load(time).to_xarray(), **kwargs)

    def __getattr__(self, name: str):
        value = getattr(self._value, name)
        if hasattr(value, "load") or hasattr(value, "plan") or not callable(value):
            return CaseNode(value, self._case)
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

    def plot(self, time: TimeRange | None = None, **kwargs):
        return self._endpoint.plot(time or self._case.time, **kwargs)

    def line(self, time: TimeRange | None = None, **kwargs):
        return self._endpoint.line(time or self._case.time, **kwargs)

    def spectrogram(self, time: TimeRange | None = None, **kwargs):
        return self._endpoint.spectrogram(time or self._case.time, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._endpoint, name)


def _case_region(
    defaults: dict[str, Any],
    case_config: dict[str, Any],
) -> Region | None:
    region = case_config.get("region") or defaults.get("region")
    if region is None:
        return None
    lon = tuple(float(value) for value in region["lon"])
    lat = tuple(float(value) for value in region["lat"])
    if len(lon) != 2 or len(lat) != 2:
        raise ValueError("case region lon and lat must each contain two values")
    return Region(
        lon=lon,
        lat=lat,
        body=str(region.get("body", "moon")),
        lon_domain=region.get("lon_domain", "0_360"),
    )
