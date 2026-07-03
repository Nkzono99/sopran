from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement

WINDOWS_PY314_SOURCE_BACKENDS = {
    "aacgmv2",
    "apexpy",
    "cartopy",
    "geoviews",
}


def test_default_runtime_dependencies_stay_lightweight_for_editable_install() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    names = _dependency_names(dependencies)

    assert {"numpy", "pandas"} <= names
    assert names.isdisjoint(
        {
            "aacgmv2",
            "apexpy",
            "cartopy",
            "geopandas",
            "pdr",
            "pds4-tools",
            "pyproj",
            "pyspedas",
            "rasterio",
            "rioxarray",
            "shapely",
            "spacepy",
            "spiceypy",
        }
    )


def test_optional_extras_include_space_map_and_viz_backends() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    optional_dependencies = pyproject["project"]["optional-dependencies"]

    assert {
        "aacgmv2",
        "apexpy",
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
    } <= _dependency_names(optional_dependencies["full"])
    assert {
        "cartopy",
        "geopandas",
        "pyogrio",
        "pyproj",
        "rasterio",
        "rioxarray",
        "shapely",
    } <= _dependency_names(optional_dependencies["moon"])
    assert {"aacgmv2", "apexpy", "plasmapy", "spacepy", "sunpy"} <= _dependency_names(
        optional_dependencies["geospace"]
    )
    assert {"cdasws", "hapiclient", "pyspedas", "spacepy"} <= _dependency_names(
        optional_dependencies["artemis"]
    )
    assert {"pdr", "pds4-tools", "spiceypy"} <= _dependency_names(
        optional_dependencies["kaguya"]
    )
    assert {"datashader", "geoviews", "holoviews", "hvplot", "panel"} <= _dependency_names(
        optional_dependencies["viz"]
    )


def test_source_build_backends_are_marked_out_for_windows_python314() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    optional_dependencies = pyproject["project"]["optional-dependencies"]

    for extra, names in {
        "full": WINDOWS_PY314_SOURCE_BACKENDS,
        "geospace": {"aacgmv2", "apexpy"},
        "moon": {"cartopy"},
        "viz": {"geoviews"},
    }.items():
        requirements = _requirements_by_name(optional_dependencies[extra])
        for name in names:
            requirement = requirements[name]

            assert requirement.marker is not None
            assert not _marker_allows(
                requirement, platform_system="Windows", python_version="3.14"
            )
            assert _marker_allows(
                requirement, platform_system="Windows", python_version="3.13"
            )
            assert _marker_allows(
                requirement, platform_system="Linux", python_version="3.14"
            )


def test_install_docs_describe_full_and_windows_native_toolchain_paths() -> None:
    docs = [
        Path("docs/getting-started/installation.md").read_text(encoding="utf-8"),
        Path("docs/en/getting-started/installation.md").read_text(encoding="utf-8"),
    ]

    for document in docs:
        assert 'pip install -e ".[full]"' in document
        assert 'pip install -e ".[full,native]"' in document
        assert "visualstudio2022buildtools visualstudio2022-workload-vctools" in document
        assert "Python 3.14" in document


def _dependency_names(dependencies: list[str]) -> set[str]:
    return {
        Requirement(dependency).name
        for dependency in dependencies
    }


def _requirements_by_name(dependencies: list[str]) -> dict[str, Requirement]:
    return {
        Requirement(dependency).name: Requirement(dependency)
        for dependency in dependencies
    }


def _marker_allows(
    requirement: Requirement,
    *,
    platform_system: str,
    python_version: str,
) -> bool:
    if requirement.marker is None:
        return True
    return requirement.marker.evaluate(
        {
            "platform_system": platform_system,
            "python_version": python_version,
        }
    )
