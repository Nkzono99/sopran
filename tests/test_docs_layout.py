from __future__ import annotations

from pathlib import Path


def test_root_markdown_is_limited_to_repo_entrypoints() -> None:
    allowed = {
        "AGENTS.md",
        "README.md",
        "THIRD_PARTY_NOTICES.md",
    }
    root_markdown = {path.name for path in Path(".").glob("*.md")}

    assert root_markdown <= allowed
