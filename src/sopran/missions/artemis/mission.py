from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files

from sopran.core.pages import GuidePage, InfoPage
from sopran.core.schema import VariableSchema
from sopran.core.time import TimeRange


ARTEMIS_MAGNETIC_FIELD = VariableSchema(
    name="magnetic_field",
    aliases=("b", "fgm"),
    dims=("time", "component"),
    units="nT",
    description="ARTEMIS fluxgate magnetic field vector.",
)


class Artemis:
    """Object-oriented entry point for ARTEMIS probes."""

    def __init__(self) -> None:
        self.p1 = ArtemisProbe(self, "p1")
        self.p2 = ArtemisProbe(self, "p2")

    def info(self) -> InfoPage:
        return InfoPage(
            title="ARTEMIS",
            lines=(
                "p1: ARTEMIS P1 probe",
                "p2: ARTEMIS P2 probe",
            ),
        )

    def guide(self) -> GuidePage:
        return _read_guide(title="ARTEMIS")


class ArtemisProbe:
    def __init__(self, mission: Artemis, probe: str) -> None:
        self.mission = mission
        self.probe = probe
        self.fgm = ArtemisFgmInstrument(self)

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"ARTEMIS.{self.probe.upper()}",
            lines=("fgm: fluxgate magnetometer",),
        )

    def guide(self) -> GuidePage:
        return self.mission.guide()


class ArtemisFgmInstrument:
    def __init__(self, probe: ArtemisProbe) -> None:
        self.probe = probe
        self.magnetic_field = ArtemisVariableEndpoint(
            instrument=self,
            schema=ARTEMIS_MAGNETIC_FIELD,
        )
        self.b = self.magnetic_field

    @property
    def dataset_prefix(self) -> str:
        return f"artemis.{self.probe.probe}.fgm"

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"ARTEMIS.{self.probe.probe.upper()}.FGM",
            lines=(f"{ARTEMIS_MAGNETIC_FIELD.name}: {ARTEMIS_MAGNETIC_FIELD.description}",),
        )

    def guide(self) -> GuidePage:
        return self.probe.guide()


@dataclass(frozen=True)
class ArtemisLoadPlan:
    dataset_id: str
    time: TimeRange


class ArtemisVariableEndpoint:
    def __init__(self, instrument: ArtemisFgmInstrument, schema: VariableSchema) -> None:
        self.instrument = instrument
        self._schema = schema
        self.name = schema.name

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"{self.instrument.dataset_prefix}.{self.name}",
            lines=(
                f"description: {self._schema.description}",
                f"dims: {self._schema.dims}",
                f"units: {self._schema.units}",
            ),
        )

    def schema(self) -> VariableSchema:
        return self._schema

    def guide(self) -> GuidePage:
        return self.instrument.guide()

    def plan(self, time: TimeRange) -> ArtemisLoadPlan:
        return ArtemisLoadPlan(
            dataset_id=f"{self.instrument.dataset_prefix}.{self.name}",
            time=time,
        )

    def load(self, time: TimeRange):
        probe = self.instrument.probe.probe.upper()
        raise NotImplementedError(f"ARTEMIS {probe} FGM load is not implemented yet")


def _read_guide(*, title: str) -> GuidePage:
    markdown = files("sopran.missions.artemis").joinpath("README.md").read_text(
        encoding="utf-8"
    )
    return GuidePage(
        title=title,
        markdown=markdown,
        source="sopran.missions.artemis/README.md",
    )
