from __future__ import annotations

import io
import ipaddress
import socket
from email.message import Message
from typing import Any

import pytest

from sopran.missions.kaguya import files as kaguya_files
from sopran.missions.kaguya.pace import PACE_CALIBRATION_BASE_URL

_LOOPBACK_NAMES = {"localhost", "localhost.localdomain"}


class NetworkAccessError(RuntimeError):
    """Raised when a test tries to reach a non-loopback host."""


def _is_loopback(host: object) -> bool:
    if not isinstance(host, str):
        return False
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite independent of DARTS, NAIF, Kyoto, and other remote servers.

    Local test servers on loopback addresses stay reachable. Tests that exercise a
    download path replace the transport (``urlopen``, ``_download_file``) or the source.
    """

    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host is not None and not _is_loopback(host):
            raise NetworkAccessError(f"Network access is disabled in tests: {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    def _check_address(address: Any) -> None:
        if isinstance(address, tuple) and address and not _is_loopback(address[0]):
            raise NetworkAccessError(f"Network access is disabled in tests: {address[0]}")

    def guarded_connect(self: socket.socket, address: Any) -> None:
        _check_address(address)
        real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        _check_address(address)
        return real_connect_ex(self, address)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)


class _CalibrationResponse(io.BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = Message()
        self.headers["Content-Length"] = str(len(payload))

    def __enter__(self) -> _CalibrationResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


@pytest.fixture(autouse=True)
def _offline_pace_calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve header-only PACE calibration tables instead of the Kyoto server.

    PACE loads fetch calibration tables with ``download="missing"``. The tables
    parse to all-NaN calibration, which is enough for tests that check counts,
    files, and plotting; tests that need calibration values pass a
    ``PaceCalibration`` or patch ``urlopen`` themselves.
    """

    real_urlopen = kaguya_files.urlopen

    def fake_urlopen(url: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(url, str) and url.startswith(PACE_CALIBRATION_BASE_URL):
            return _CalibrationResponse(b"# synthetic PACE calibration table for tests\n")
        return real_urlopen(url, *args, **kwargs)

    monkeypatch.setattr(kaguya_files, "urlopen", fake_urlopen)


@pytest.fixture(autouse=True)
def _close_matplotlib_figures():
    yield
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    plt.close("all")
