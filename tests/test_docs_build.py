from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sopran.core.pages import public_doc_urls


def test_mkdocs_build_includes_language_switcher_in_header(tmp_path: Path) -> None:
    env = os.environ.copy()
    src = str(Path("src").resolve())
    env["PYTHONPATH"] = (
        src if not env.get("PYTHONPATH") else f"{src}{os.pathsep}{env['PYTHONPATH']}"
    )
    env["NO_MKDOCS_2_WARNING"] = "true"
    site_dir = tmp_path / "site"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "--strict",
            "--site-dir",
            str(site_dir),
        ],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "mkdocs build failed\n\n"
        f"STDOUT:\n{result.stdout}\n\n"
        f"STDERR:\n{result.stderr}"
    )
    assert "Warning from the Material for MkDocs team" not in result.stderr
    assert "MkDocs 2.0" not in result.stderr

    index = (site_dir / "index.html").read_text(encoding="utf-8")
    english_index = (site_dir / "en" / "index.html").read_text(encoding="utf-8")

    assert "sopran-language-switcher" in index
    assert "sopran-language-switcher__toggle" in index
    assert index.count("sopran-language-switcher__link--active") == 1
    assert english_index.count("sopran-language-switcher__link--active") == 1
    assert 'aria-current="page"' in index
    assert 'aria-current="page"' in english_index
    assert "Lang: 日本語/English" in index
    assert 'aria-label="Lang: 日本語/English"' in index
    assert '<html lang="ja"' in index
    assert '<html lang="en"' in english_index
    assert "月周辺の衛星観測データ" in index
    assert "spacecraft observations around the Moon" in english_index

    # Each language has its own navigation: English tabs stay under /en/.
    assert "はじめる" in index
    assert "Getting Started" in english_index
    assert 'href="start/install/" class="md-tabs__link"' in english_index
    assert "はじめる" not in english_index

    # Pages that guide() links to from the package.
    for path in ("data/kaguya/", "data/kaguya/pace/", "data/artemis/", "data/moon/"):
        urls = public_doc_urls(path)
        for language, root in (("ja", site_dir), ("en", site_dir / "en")):
            assert urls[language] is not None
            assert (root / path / "index.html").exists(), urls[language]

    for relative in _primary_docs_pages():
        if relative == Path("index.md"):
            continue
        ja_html = _built_page(site_dir, relative).read_text(encoding="utf-8")
        en_html = _built_page(site_dir / "en", relative).read_text(encoding="utf-8")
        ja_to_en = _relative_href(
            _built_page(site_dir, relative),
            _page_dir(site_dir / "en", relative),
        )
        en_to_ja = _relative_href(
            _built_page(site_dir / "en", relative),
            _page_dir(site_dir, relative),
        )
        assert f'href="{ja_to_en}"' in ja_html, relative
        assert f'href="{en_to_ja}"' in en_html, relative


def test_every_primary_docs_page_has_english_mirror() -> None:
    missing = [
        str(Path("docs") / "en" / relative)
        for relative in _primary_docs_pages()
        if not (Path("docs") / "en" / relative).exists()
    ]
    extra = [
        str(Path("docs") / "en" / relative)
        for relative in _english_docs_pages()
        if not (Path("docs") / "ja" / relative).exists()
    ]

    assert missing == []
    assert extra == []


def test_every_docs_page_is_in_the_navigation() -> None:
    config = Path("mkdocs.yml").read_text(encoding="utf-8")

    for relative in _primary_docs_pages():
        assert f": {relative.as_posix()}" in config, relative


def _primary_docs_pages() -> list[Path]:
    docs_root = Path("docs") / "ja"
    return sorted(path.relative_to(docs_root) for path in docs_root.rglob("*.md"))


def _english_docs_pages() -> list[Path]:
    docs_root = Path("docs") / "en"
    return sorted(path.relative_to(docs_root) for path in docs_root.rglob("*.md"))


def _built_page(site_root: Path, source_relative: Path) -> Path:
    if source_relative == Path("index.md"):
        return site_root / "index.html"
    if source_relative.name == "index.md":
        return site_root / source_relative.parent / "index.html"
    return site_root / source_relative.with_suffix("") / "index.html"


def _page_dir(site_root: Path, source_relative: Path) -> Path:
    return _built_page(site_root, source_relative).parent


def _relative_href(page_path: Path, target_dir: Path) -> str:
    relative = os.path.relpath(target_dir, start=page_path.parent).replace(os.sep, "/")
    return f"{relative}/"
