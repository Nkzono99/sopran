from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path

from sopran.core.schema import InstrumentSchema


def builtin_schemas() -> tuple[InstrumentSchema, ...]:
    from sopran.bodies.moon import MOON_SURFACE_SCHEMA
    from sopran.missions.artemis.mission import ARTEMIS_ESA_SCHEMA, ARTEMIS_FGM_SCHEMA
    from sopran.missions.kaguya.schema import (
        KAGUYA_ESA1_SCHEMA,
        KAGUYA_ESA2_SCHEMA,
        KAGUYA_IEA_SCHEMA,
        KAGUYA_IMA_SCHEMA,
        KAGUYA_LMAG_CONNECTION_SCHEMA,
        KAGUYA_LMAG_SCHEMA,
        KAGUYA_LRS_SCHEMA,
        KAGUYA_ORBIT_SCHEMA,
    )
    from sopran.missions.omni.hro import OMNI_HRO_SCHEMA

    return (
        KAGUYA_ESA1_SCHEMA,
        KAGUYA_ESA2_SCHEMA,
        KAGUYA_IMA_SCHEMA,
        KAGUYA_IEA_SCHEMA,
        KAGUYA_LMAG_SCHEMA,
        KAGUYA_LRS_SCHEMA,
        KAGUYA_ORBIT_SCHEMA,
        KAGUYA_LMAG_CONNECTION_SCHEMA,
        ARTEMIS_FGM_SCHEMA,
        ARTEMIS_ESA_SCHEMA,
        MOON_SURFACE_SCHEMA,
        OMNI_HRO_SCHEMA,
    )


def schema_reference_markdown(
    schemas: Iterable[InstrumentSchema] | None = None,
    *,
    language: str = "ja",
) -> str:
    selected = tuple(schemas) if schemas is not None else builtin_schemas()
    if language == "ja":
        lines = [
            "# スキーマ",
            "",
            "このページはSOPRANのスキーマ定義（`InstrumentSchema`）から自動生成しています。",
            "手で編集せず、コードのスキーマを変えてから",
            "`python -m sopran.schema_docs docs/ja/reference/schemas.md`で作り直してください。",
            "列は変数名、次元、単位、データ型、座標系、別名、説明です。",
            "",
        ]
    elif language == "en":
        lines = [
            "# Schemas",
            "",
            "This page is generated from the SOPRAN schema definitions (`InstrumentSchema`).",
            "Do not edit it by hand: change the schema in code, then regenerate it with",
            "`python -m sopran.schema_docs --language en docs/en/reference/schemas.md`.",
            "The columns are the variable name, dimensions, units, data type, frame,",
            "aliases, and description.",
            "",
        ]
    else:
        raise ValueError(f"unsupported schema docs language: {language}")
    for schema, title in zip(selected, _section_titles(selected), strict=True):
        lines.extend(
            (
                f"## {title}",
                "",
                _schema_table(schema),
                "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _section_titles(schemas: Sequence[InstrumentSchema]) -> list[str]:
    """Return one unique heading per schema, naming the product when a pair repeats."""

    from sopran.missions.kaguya.schema import KAGUYA_LMAG_CONNECTION_SCHEMA

    titles: list[str] = []
    for schema in schemas:
        title = f"{schema.mission} / {schema.instrument}"
        if schema is KAGUYA_LMAG_CONNECTION_SCHEMA:
            title = f"{title} / magnetic_connection"
        count = sum(existing.split(" (")[0] == title for existing in titles)
        titles.append(title if count == 0 else f"{title} ({count + 1})")
    return titles


def write_schema_reference(
    path: Path | str,
    schemas: Iterable[InstrumentSchema] | None = None,
    *,
    language: str = "ja",
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        schema_reference_markdown(schemas, language=language),
        encoding="utf-8",
    )
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sopran-schema-docs",
        description="Generate SOPRAN schema reference markdown.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="docs/ja/reference/schemas.md",
        help="Markdown output path.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Return non-zero when the output path is stale.",
    )
    parser.add_argument(
        "--language",
        choices=("ja", "en"),
        default="ja",
        help="Documentation language.",
    )
    args = parser.parse_args(argv)
    path = Path(args.path)
    expected = schema_reference_markdown(language=args.language)
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
