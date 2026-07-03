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
