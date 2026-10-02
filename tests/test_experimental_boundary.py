from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def _run(code: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_standard_entry_points_do_not_import_experiments_or_optional_backends() -> None:
    _run('''
        import importlib.abc
        import sys

        blocked = (
            "sopran.experimental", "scipy", "matplotlib", "spiceypy", "cdflib", "xarray"
        )

        class BlockOptional(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if any(
                    fullname == prefix or fullname.startswith(prefix + ".") for prefix in blocked
                ):
                    raise AssertionError("Unexpected import: " + fullname)

        sys.meta_path.insert(0, BlockOptional())
        import sopran as spn
        from sopran.missions.kaguya import read_pace_pbf, KaguyaPaceData

        mission = spn.Kaguya(download="never")
        assert mission.esa1.counts is not None
        assert mission.esa1.energy_flux is not None
        assert mission.lrs.wfc_ey_power_spectral_density is not None
        assert callable(read_pace_pbf)
        assert KaguyaPaceData is not None
        assert not hasattr(mission, "er")
        assert not hasattr(spn, "fit_effective_field")
        assert not hasattr(spn, "ElectronReflectionCounts")
        assert "## kaguya / er" not in spn.schema_reference_markdown()
        assert not any(
            name == "scipy" or name.startswith("sopran.experimental") for name in sys.modules
        )
    ''')


def test_experimental_namespace_is_lightweight_and_opt_in() -> None:
    _run('''
        import sys
        import sopran as spn

        assert "sopran.experimental" not in sys.modules
        namespace = spn.experimental
        import sopran.experimental as explicit
        assert namespace is explicit
        assert not any(name.startswith("sopran.experimental.") for name in sys.modules)
        assert "scipy" not in sys.modules
        import sopran.experimental.kaguya
        assert "scipy" not in sys.modules
    ''')


def test_standard_linear_resampling_does_not_import_experiments() -> None:
    pytest.importorskip("xarray")
    pytest.importorskip("scipy")
    _run('''
        import importlib.abc
        import sys

        class BlockExperimental(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.startswith("sopran.experimental"):
                    raise AssertionError("Unexpected import: " + fullname)

        sys.meta_path.insert(0, BlockExperimental())
        import numpy as np
        import xarray as xr
        import sopran as spn

        source = xr.DataArray(
            [[0.0, 10.0], [2.0, 14.0]],
            dims=("time", "component"),
            coords={"time": np.array(
                ["2008-04-26T00:00:00", "2008-04-26T00:00:02"], dtype="datetime64[ns]"
            )},
        )
        target = xr.DataArray(
            [0.0], dims="time",
            coords={"time": np.array(["2008-04-26T00:00:01"], dtype="datetime64[ns]")},
        )
        result = spn.resample_like(source, target, method="linear")
        np.testing.assert_allclose(result.values, [[1.0, 12.0]])
    ''')


def test_standard_modules_do_not_depend_on_experimental_implementations() -> None:
    root = Path(__file__).parents[1] / "src" / "sopran"
    violations = []
    for path in root.rglob("*.py"):
        if "experimental" in path.relative_to(root).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [node.module or ""]
            else:
                continue
            if any(name.startswith("sopran.experimental") for name in imports):
                violations.append(f"{path}:{node.lineno}")
    assert not violations, violations


def test_experimental_er_requires_explicit_adapter_and_explicit_estimator(tmp_path) -> None:
    pytest.importorskip("scipy")
    import sopran as spn
    from sopran.experimental.kaguya.er import KaguyaErInstrument

    mission = spn.Kaguya(store=spn.Store(tmp_path), download="never")
    adapter = KaguyaErInstrument(mission)
    assert adapter.mission is mission
    assert callable(adapter.effective_field.fit_finite_bin)
    assert callable(adapter.effective_field.fit_halekas)
    assert not hasattr(adapter.effective_field, "fit_timeseries")
    assert not hasattr(adapter.effective_field, "fit_global_joint")
    assert not hasattr(mission, "er")
