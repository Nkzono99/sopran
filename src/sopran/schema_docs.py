from __future__ import annotations

from collections.abc import Iterable

from sopran.core.schema import InstrumentSchema


def builtin_schemas() -> tuple[InstrumentSchema, ...]:
    from sopran.missions.artemis.mission import ARTEMIS_FGM_SCHEMA
    from sopran.missions.kaguya.schema import KAGUYA_ESA1_SCHEMA

    return (
        KAGUYA_ESA1_SCHEMA,
        ARTEMIS_FGM_SCHEMA,
    )


def schema_reference_markdown(
    schemas: Iterable[InstrumentSchema] | None = None,
) -> str:
    selected = tuple(schemas) if schemas is not None else builtin_schemas()
    lines = [
        "# Schema Reference",
        "",
        "This page is generated from SOPRAN runtime schema objects.",
        "Update the schema objects first, then regenerate this page.",
        "",
    ]
    for schema in selected:
        lines.extend(
            (
                f"## {schema.mission} / {schema.instrument}",
                "",
                _schema_table(schema),
                "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _schema_table(schema: InstrumentSchema) -> str:
    markdown = schema.to_markdown()
    table_start = markdown.find("| name |")
    if table_start < 0:
        return markdown
    return markdown[table_start:]
