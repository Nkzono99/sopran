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

    assert "sopran-language-switcher" in index
    assert "Lang: 日本語/English" in index
    assert 'aria-label="Lang: 日本語/English"' in index
    assert (site_dir / "en" / "index.html").exists()
