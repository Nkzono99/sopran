from __future__ import annotations

import argparse
import platform
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from shutil import which

WINDOWS_PY314_NATIVE_BACKENDS = ("aacgmv2", "apexpy", "cartopy", "geoviews")
WINDOWS_TOOLCHAIN_COMMAND = (
    "choco install -y visualstudio2022buildtools "
    "visualstudio2022-workload-vctools mingw"
)


@dataclass(frozen=True)
class EnvironmentProbe:
    platform_system: str
    python_version: str
    executables: Mapping[str, str | None]
    visual_studio_path: str | None


@dataclass(frozen=True)
class CheckItem:
    ok: bool
    message: str
    guidance: str = ""
    warning: bool = False


@dataclass(frozen=True)
class EnvironmentReport:
    items: tuple[CheckItem, ...]

    @property
    def exit_code(self) -> int:
        return 1 if any(not item.ok for item in self.items) else 0


def evaluate_environment(
    probe: EnvironmentProbe,
    *,
    native: bool = False,
) -> EnvironmentReport:
    items: list[CheckItem] = []
    if _is_windows_python314(probe):
        items.append(
            CheckItem(
                ok=True,
                warning=True,
                message=(
                    "Windows/Python 3.14 marker-gates native backends: "
                    + ", ".join(WINDOWS_PY314_NATIVE_BACKENDS)
                ),
                guidance=(
                    'Use pip install -e ".[full]" for the wheel-oriented stack, '
                    'or pip install -e ".[full,native]" after preparing native tools.'
                ),
            )
        )

    if native and probe.platform_system == "Windows":
        items.extend(_windows_native_checks(probe))

    if not items:
        items.append(CheckItem(ok=True, message="No SOPRAN environment issues detected."))
    return EnvironmentReport(items=tuple(items))


def current_probe() -> EnvironmentProbe:
    return EnvironmentProbe(
        platform_system=platform.system(),
        python_version=".".join(platform.python_version_tuple()[:2]),
        executables={
            "cl": which("cl"),
            "gcc": which("gcc"),
            "gfortran": which("gfortran"),
        },
        visual_studio_path=_visual_studio_path(),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check SOPRAN optional dependency toolchain readiness."
    )
    parser.add_argument(
        "--native",
        action="store_true",
        help="check source-build native backend prerequisites",
    )
    args = parser.parse_args(argv)

    report = evaluate_environment(current_probe(), native=args.native)
    for item in report.items:
        prefix = "OK"
        if not item.ok:
            prefix = "MISSING"
        elif item.warning:
            prefix = "WARN"
        print(f"[{prefix}] {item.message}")
        if item.guidance:
            print(f"      {item.guidance}")
    return report.exit_code


def _windows_native_checks(probe: EnvironmentProbe) -> tuple[CheckItem, ...]:
    has_msvc = bool(probe.executables.get("cl") or probe.visual_studio_path)
    has_gcc = bool(probe.executables.get("gcc"))
    has_gfortran = bool(probe.executables.get("gfortran"))
    return (
        CheckItem(
            ok=has_msvc,
            message="MSVC build tools detected."
            if has_msvc
            else "MSVC build tools are required for Windows native builds.",
            guidance="" if has_msvc else WINDOWS_TOOLCHAIN_COMMAND,
        ),
        CheckItem(
            ok=has_gcc and has_gfortran,
            message="gcc and gfortran detected."
            if has_gcc and has_gfortran
            else "gcc and gfortran are required for Fortran-backed native builds.",
            guidance="" if has_gcc and has_gfortran else WINDOWS_TOOLCHAIN_COMMAND,
        ),
        CheckItem(
            ok=True,
            warning=True,
            message="Cartopy source builds may also need GEOS/PROJ headers.",
            guidance=(
                "If cartopy fails on Python 3.14, use a Python version with a "
                "Cartopy wheel or a conda-forge environment."
            ),
        ),
    )


def _is_windows_python314(probe: EnvironmentProbe) -> bool:
    return probe.platform_system == "Windows" and _version_tuple(
        probe.python_version
    ) >= (3, 14)


def _version_tuple(version: str) -> tuple[int, int]:
    major, minor, *_ = version.split(".")
    return int(major), int(minor)


def _visual_studio_path() -> str | None:
    vswhere = (
        r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
    )
    try:
        result = subprocess.run(
            [
                vswhere,
                "-latest",
                "-products",
                "*",
                "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property",
                "installationPath",
            ],
            check=False,
            capture_output=True,
            encoding="utf-8",
        )
    except OSError:
        return None
    path = result.stdout.strip()
    return path or None


if __name__ == "__main__":
    raise SystemExit(main())
