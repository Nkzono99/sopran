from __future__ import annotations

import tomllib
from pathlib import Path


def test_runtime_dependencies_include_space_map_and_viz_backends() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    names = {dependency.split(">=", 1)[0] for dependency in dependencies}

    assert {
        "cartopy",
        "cdasws",
        "datashader",
        "geopandas",
        "hapiclient",
        "holoviews",
        "hvplot",
        "pdr",
        "pds4-tools",
        "pyproj",
        "pyspedas",
        "rasterio",
        "rioxarray",
        "shapely",
        "spacepy",
        "spiceypy",
    } <= names
