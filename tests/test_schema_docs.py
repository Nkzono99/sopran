from __future__ import annotations

from pathlib import Path

import sopran as spn


def test_schema_reference_markdown_lists_builtin_instrument_schemas() -> None:
    markdown = spn.schema_reference_markdown()

    assert markdown.startswith("# Schema Reference")
    assert "## kaguya / esa1" in markdown
    assert "## artemis / fgm" in markdown
    assert "| name | dims | units | dtype | frame | aliases | description |" in markdown
    assert "| energy_flux | time, energy, look |" in markdown
    assert "eflux, differential_energy_flux" in markdown
    assert "| magnetic_field | time, component | nT |" in markdown
    assert "b, fgm" in markdown


def test_schema_reference_docs_match_runtime_schema_output() -> None:
    docs = Path("docs/reference/schemas.md").read_text(encoding="utf-8")

    assert docs == spn.schema_reference_markdown()
