from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path
from typing import Sequence

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


def write_schema_reference(
    path: Path | str,
    schemas: Iterable[InstrumentSchema] | None = None,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(schema_reference_markdown(schemas), encoding="utf-8")
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sopran-schema-docs",
        description="Generate SOPRAN schema reference markdown.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="docs/reference/schemas.md",
        help="Markdown output path.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Return non-zero when the output path is stale.",
    )
    args = parser.parse_args(argv)
    path = Path(args.path)
    expected = schema_reference_markdown()
    if args.check:
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            return 1
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(expected, encoding="utf-8")
    return 0


def _schema_table(schema: InstrumentSchema) -> str:
    markdown = schema.to_markdown()
    table_start = markdown.find("| name |")
    if table_start < 0:
        return markdown
    return markdown[table_start:]


if __name__ == "__main__":
    raise SystemExit(main())
