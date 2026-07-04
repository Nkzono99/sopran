from __future__ import annotations

from pathlib import Path


def test_publish_workflow_uses_pypi_trusted_publishing() -> None:
    workflow = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")

    assert "tags:" in workflow
    assert '- "v*"' in workflow
    assert "Check tag matches package version" in workflow
    assert "python -m build" in workflow
    assert "python -m twine check dist/*" in workflow
    assert "actions/upload-artifact@v5" in workflow
    assert "actions/download-artifact@v6" in workflow
    assert "pypa/gh-action-pypi-publish@release/v1" in workflow
    assert "name: pypi" in workflow
    assert "id-token: write" in workflow
    assert "secrets." not in workflow
    assert "password:" not in workflow


def test_ci_workflow_runs_core_verification_commands() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "branches:" in workflow
    assert "python -m pytest -q" in workflow
    assert "python -m compileall src" in workflow
    assert "python -m sopran.schema_docs --check docs/reference/schemas.md" in workflow
    assert (
        "python -m sopran.schema_docs --language en --check docs/en/reference/schemas.md"
        in workflow
    )
    assert "python -m ruff check src tests" in workflow
    assert "Type check" in workflow
    assert "continue-on-error: true" not in workflow
    assert "python -m mypy src" in workflow


def test_docs_workflow_installs_package_docs_extra_before_build() -> None:
    workflow = Path(".github/workflows/docs.yml").read_text(encoding="utf-8")

    assert 'python -m pip install -e ".[docs]"' in workflow
    assert "mkdocs build --strict" in workflow
