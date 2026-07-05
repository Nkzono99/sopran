from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SurfacePlan:
    body: str
    product: str
    parameters: dict[str, Any]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "body": self.body,
            "product": self.product,
            "parameters": metadata_value(self.parameters),
        }


@dataclass(frozen=True)
class SurfaceSource:
    source_id: str
    product: str
    provider: str
    filename: str
    description: str
    url: str | None = None
    landing_page: str | None = None
    original_url: str | None = None
    size: str | None = None
    version: str | None = None
    scale: float | None = None
    offset: float | None = None
    manual_note: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "product": self.product,
            "provider": self.provider,
            "filename": self.filename,
            "description": self.description,
            "url": self.url,
            "landing_page": self.landing_page,
            "original_url": self.original_url,
            "size": self.size,
            "version": self.version,
            "scale": self.scale,
            "offset": self.offset,
            "manual_note": self.manual_note,
        }


def metadata_value(value: Any) -> Any:
    if hasattr(value, "to_metadata"):
        return value.to_metadata()
    if isinstance(value, dict):
        return {str(key): metadata_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [metadata_value(item) for item in value]
    return value


def format_list(values: Any) -> str:
    items = tuple(str(value) for value in values)
    return ", ".join(items) if items else "none"
