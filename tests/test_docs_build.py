from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_mkdocs_build_includes_language_switcher_in_header(tmp_path: Path) -> None:
    env = os.environ.copy()
    src = str(Path("src").resolve())
    env["PYTHONPATH"] = (
        src if not env.get("PYTHONPATH") else f"{src}{os.pathsep}{env['PYTHONPATH']}"
    )
    site_dir = tmp_path / "site"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "--strict",
            "--site-dir",
            str(site_dir),
        ],
        check=True,
        env=env,
    )

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
    assert (site_dir / "en" / "index.html").exists()
    assert "SOPRAN は" in index
    assert "Getting Started" in index
    assert "Missions" in index
    assert "Status" in index
    assert (site_dir / "missions" / "kaguya" / "index.html").exists()
    assert (site_dir / "missions" / "kaguya" / "esa1" / "index.html").exists()
    assert (site_dir / "missions" / "artemis" / "index.html").exists()
    assert (site_dir / "maps" / "moon" / "index.html").exists()
    assert (site_dir / "reference" / "status" / "index.html").exists()
    assert "SOPRAN is the" in english_index
    assert (site_dir / "en" / "missions" / "kaguya" / "index.html").exists()
    assert (site_dir / "en" / "reference" / "status" / "index.html").exists()

    kaguya_ja = (site_dir / "missions" / "kaguya" / "index.html").read_text(
        encoding="utf-8"
    )
    kaguya_en = (site_dir / "en" / "missions" / "kaguya" / "index.html").read_text(
        encoding="utf-8"
    )

    assert 'href="../../en/missions/kaguya/"' in kaguya_ja
    assert 'href="../../../missions/kaguya/"' in kaguya_en
    assert "KAGUYA/SELENE は" in kaguya_ja
    assert "KAGUYA/SELENE is" in kaguya_en


def test_every_primary_docs_page_has_english_mirror() -> None:
    docs_root = Path("docs")
    primary_pages = sorted(
        path.relative_to(docs_root)
        for path in docs_root.rglob("*.md")
        if path.relative_to(docs_root).parts[0] != "en"
    )

    missing = [
        str(Path("docs") / "en" / relative)
        for relative in primary_pages
        if not (docs_root / "en" / relative).exists()
    ]

    assert missing == []
