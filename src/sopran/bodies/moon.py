from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sopran.core.pages import InfoPage


@dataclass(frozen=True)
class SurfacePlan:
    body: str
    product: str
    parameters: dict[str, Any]


class Moon:
    """Body-first entry point for Moon surface products."""

    name = "moon"

    def __init__(self) -> None:
        self.dem = SurfaceEndpoint(self, "dem", "DEM")
        self.svm = SurfaceEndpoint(self, "svm", "SVM")
        self.shadow = SurfaceEndpoint(self, "shadow", "Shadow map")
        self.illumination = SurfaceEndpoint(self, "illumination", "Illumination map")

    def info(self) -> InfoPage:
        return InfoPage(
            title="Moon",
            lines=(
                "dem: digital elevation model endpoint",
                "svm: surface vector map endpoint",
                "shadow: terrain-aware shadow map endpoint skeleton",
                "illumination: terrain-aware illumination endpoint skeleton",
            ),
        )


class SurfaceEndpoint:
    def __init__(self, body: Moon, product: str, label: str) -> None:
        self.body = body
        self.product = product
        self.label = label

    def info(self) -> InfoPage:
        return InfoPage(
            title=f"Moon.{self.product}",
            lines=(
                f"{self.label} surface product.",
                "v0.1 implements planning only; load/compute backends are later milestones.",
            ),
        )

    def plan(self, **parameters: Any) -> SurfacePlan:
        return SurfacePlan(
            body=self.body.name,
            product=self.product,
            parameters=dict(parameters),
        )

    def load(self, **parameters: Any) -> None:
        plan = self.plan(**parameters)
        raise NotImplementedError(f"Moon.{plan.product}.load() is not implemented yet")

    def compute(self, **parameters: Any) -> None:
        plan = self.plan(**parameters)
        raise NotImplementedError(f"Moon.{plan.product}.compute() is not implemented yet")
