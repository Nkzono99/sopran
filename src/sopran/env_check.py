from __future__ import annotations

import argparse
import platform
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from shutil import which

RUST_INSTALL_GUIDANCE = "Install Rust with rustup: https://rustup.rs"
WINDOWS_TOOLCHAIN_COMMAND = (
    "choco install -y rust visualstudio2022buildtools visualstudio2022-workload-vctools"
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
    """Check prerequisites; ``native`` checks a source build of ``sopran._native``."""

    items: list[CheckItem] = []
    if native:
        items.extend(_native_build_checks(probe))
    if not items:
        items.append(CheckItem(ok=True, message="No SOPRAN environment issues detected."))
    return EnvironmentReport(items=tuple(items))


def current_probe() -> EnvironmentProbe:
    return EnvironmentProbe(
        platform_system=platform.system(),
        python_version=".".join(platform.python_version_tuple()[:2]),
        executables={
            "cargo": which("cargo"),
            "cl": which("cl"),
        },
        visual_studio_path=_visual_studio_path(),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check prerequisites for building SOPRAN from source, "
        "and optionally whether the remote data archives are reachable."
    )
    parser.add_argument(
        "--native",
        action="store_true",
        help="check the Rust toolchain for building the sopran._native extension",
    )
    parser.add_argument(
        "--sources",
        action="store_true",
        help="ask each remote archive for the headers of one known file (no download)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="seconds to wait for each archive with --sources (default: 60)",
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
    if not args.sources:
        return report.exit_code

    from sopran.source_check import check_sources, format_results

    results = check_sources(timeout_seconds=args.timeout)
    for line in format_results(results):
        print(line)
    return 1 if report.exit_code or not all(result.ok for result in results) else 0


def _native_build_checks(probe: EnvironmentProbe) -> tuple[CheckItem, ...]:
    has_cargo = bool(probe.executables.get("cargo"))
    items = [
        CheckItem(
            ok=has_cargo,
            message="Rust toolchain (cargo) detected."
            if has_cargo
            else "Rust toolchain (cargo) is required to build sopran._native from source.",
            guidance="" if has_cargo else RUST_INSTALL_GUIDANCE,
        )
    ]
    if probe.platform_system == "Windows":
        has_msvc = bool(probe.executables.get("cl") or probe.visual_studio_path)
        items.append(
            CheckItem(
                ok=has_msvc,
                message="MSVC build tools detected."
                if has_msvc
                else "MSVC build tools are required to link the Rust extension on Windows.",
                guidance="" if has_msvc else WINDOWS_TOOLCHAIN_COMMAND,
            )
        )
    return tuple(items)


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
