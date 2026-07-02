from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tomllib

import sopran as spn
import sopran.schema_docs as schema_docs


def test_schema_reference_markdown_lists_builtin_instrument_schemas() -> None:
    markdown = spn.schema_reference_markdown()

    assert markdown.startswith("# Schema Reference")
    assert "## kaguya / esa1" in markdown
    assert "## artemis / fgm" in markdown
    assert "## moon / surface" in markdown
    assert "| name | dims | units | dtype | frame | aliases | description |" in markdown
    assert "| energy_flux | time, energy, look |" in markdown
    assert "eflux, differential_energy_flux" in markdown
    assert "| magnetic_field | time, component | nT |" in markdown
    assert "b, fgm" in markdown
    assert "| dem | lat, lon | m |" in markdown
    assert "shadow_map" in markdown


def test_schema_reference_docs_match_runtime_schema_output() -> None:
    docs = Path("docs/reference/schemas.md").read_text(encoding="utf-8")

    assert docs == spn.schema_reference_markdown()


def test_write_schema_reference_writes_runtime_output(tmp_path) -> None:
    output = tmp_path / "schemas.md"

    written = schema_docs.write_schema_reference(output)

    assert written == output
    assert output.read_text(encoding="utf-8") == spn.schema_reference_markdown()


def test_schema_reference_cli_supports_write_and_check(tmp_path) -> None:
    output = tmp_path / "schemas.md"

    assert schema_docs.main([str(output)]) == 0
    assert output.read_text(encoding="utf-8") == spn.schema_reference_markdown()
    assert schema_docs.main(["--check", str(output)]) == 0

    output.write_text("# stale\n", encoding="utf-8")

    assert schema_docs.main(["--check", str(output)]) == 1


def test_schema_docs_console_script_is_registered() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    assert project["scripts"]["sopran-schema-docs"] == "sopran.schema_docs:main"


def test_schema_docs_module_cli_runs_without_runtime_warning() -> None:
    env = {
        **os.environ,
        "PYTHONPATH": str(Path("src").resolve()),
    }

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sopran.schema_docs",
            "--check",
            "docs/reference/schemas.md",
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        env=env,
    )

    assert result.returncode == 0
    assert "RuntimeWarning" not in result.stderr
