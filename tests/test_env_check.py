from __future__ import annotations

from sopran.env_check import EnvironmentProbe, evaluate_environment


def test_full_check_warns_about_marker_gated_windows_python314_backends() -> None:
    report = evaluate_environment(
        EnvironmentProbe(
            platform_system="Windows",
            python_version="3.14",
            executables={},
            visual_studio_path=None,
        )
    )

    assert report.exit_code == 0
    assert any("aacgmv2" in item.message for item in report.items)
    assert any("pip install -e \".[full,native]\"" in item.guidance for item in report.items)


def test_native_check_reports_missing_windows_toolchain() -> None:
    report = evaluate_environment(
        EnvironmentProbe(
            platform_system="Windows",
            python_version="3.14",
            executables={},
            visual_studio_path=None,
        ),
        native=True,
    )

    assert report.exit_code == 1
    assert any(not item.ok and "MSVC" in item.message for item in report.items)
    assert any("visualstudio2022buildtools" in item.guidance for item in report.items)
    assert any(not item.ok and "gfortran" in item.message for item in report.items)


def test_native_check_accepts_detected_windows_toolchain() -> None:
    report = evaluate_environment(
        EnvironmentProbe(
            platform_system="Windows",
            python_version="3.14",
            executables={
                "gcc": "C:/ProgramData/mingw64/bin/gcc.exe",
                "gfortran": "C:/ProgramData/mingw64/bin/gfortran.exe",
            },
            visual_studio_path="C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools",
        ),
        native=True,
    )

    assert report.exit_code == 0
    assert any(item.ok and "MSVC" in item.message for item in report.items)
    assert any(item.ok and "gfortran" in item.message for item in report.items)
