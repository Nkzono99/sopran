from __future__ import annotations

from sopran.env_check import EnvironmentProbe, evaluate_environment


def _probe(system: str, **executables: str) -> EnvironmentProbe:
    return EnvironmentProbe(
        platform_system=system,
        python_version="3.14",
        executables=executables,
        visual_studio_path=None,
    )


def test_default_check_has_no_marker_gated_backends() -> None:
    report = evaluate_environment(_probe("Windows"))

    assert report.exit_code == 0
    assert [item.message for item in report.items] == ["No SOPRAN environment issues detected."]


def test_native_check_reports_missing_rust_and_msvc_on_windows() -> None:
    report = evaluate_environment(_probe("Windows"), native=True)

    assert report.exit_code == 1
    assert any(not item.ok and "cargo" in item.message for item in report.items)
    assert any(not item.ok and "MSVC" in item.message for item in report.items)
    assert any("visualstudio2022buildtools" in item.guidance for item in report.items)


def test_native_check_accepts_detected_toolchain() -> None:
    windows = EnvironmentProbe(
        platform_system="Windows",
        python_version="3.14",
        executables={"cargo": "C:/Users/me/.cargo/bin/cargo.exe"},
        visual_studio_path="C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools",
    )
    linux = _probe("Linux", cargo="/home/me/.cargo/bin/cargo")

    assert evaluate_environment(windows, native=True).exit_code == 0
    linux_report = evaluate_environment(linux, native=True)
    assert linux_report.exit_code == 0
    assert not any("MSVC" in item.message for item in linux_report.items)
