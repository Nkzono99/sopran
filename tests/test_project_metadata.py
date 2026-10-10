from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement

# Required on a code path without a direct import: polars.DataFrame.to_pandas().
INDIRECT_REQUIREMENTS = {"pyarrow"}


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


def test_package_build_uses_maturin_for_integrated_native_extension() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["build-system"]["build-backend"] == "maturin"
    assert pyproject["build-system"]["requires"] == ["maturin>=1.9,<2"]
    assert pyproject["tool"]["maturin"]["manifest-path"] == "crates/sopran-native/Cargo.toml"
    assert pyproject["tool"]["maturin"]["python-source"] == "src"
    assert pyproject["tool"]["maturin"]["module-name"] == "sopran._native"
    assert pyproject["tool"]["maturin"]["features"] == ["extension-module"]


def test_extras_list_only_packages_that_sopran_imports() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    optional_dependencies = pyproject["project"]["optional-dependencies"]
    imported = _imported_top_level_modules(Path("src/sopran"))

    assert set(optional_dependencies) == {
        "analysis",
        "artemis",
        "dev",
        "docs",
        "experimental",
        "full",
        "kaguya",
        "moon",
        "viz",
    }
    runtime_extras = set(optional_dependencies) - {"dev", "docs"}
    for extra in runtime_extras:
        names = _dependency_names(optional_dependencies[extra]) - INDIRECT_REQUIREMENTS
        assert names <= imported, (extra, sorted(names - imported))
    union = set().union(
        *(_dependency_names(optional_dependencies[extra]) for extra in runtime_extras - {"full"})
    )
    assert _dependency_names(optional_dependencies["full"]) == union
    assert {"cdflib", "spiceypy", "scipy"} <= _dependency_names(optional_dependencies["kaguya"])
    assert {"rasterio", "spiceypy"} <= _dependency_names(optional_dependencies["moon"])
    assert {"matplotlib", "panel"} <= _dependency_names(optional_dependencies["viz"])


def test_install_docs_describe_full_extra_and_rust_toolchain() -> None:
    docs = [
        Path("docs/getting-started/installation.md").read_text(encoding="utf-8"),
        Path("docs/en/getting-started/installation.md").read_text(encoding="utf-8"),
    ]

    for document in docs:
        assert 'pip install -e ".[full]"' in document
        assert "rust visualstudio2022buildtools visualstudio2022-workload-vctools" in document
        assert "sopran-env-check.exe --native" in document


def _imported_top_level_modules(root: Path) -> set[str]:
    import ast

    modules: set[str] = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
            elif (
                isinstance(node, ast.Call)
                and getattr(node.func, "attr", getattr(node.func, "id", None))
                == "import_module"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                modules.add(node.args[0].value.split(".")[0])
    return modules


def _dependency_names(dependencies: list[str]) -> set[str]:
    return {
        Requirement(dependency).name
        for dependency in dependencies
    }
