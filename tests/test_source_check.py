from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from sopran import env_check
from sopran.missions.kaguya.files import KaguyaFileSource
from sopran.source_check import (
    SourceProbe,
    check_sources,
    default_probes,
    format_results,
)


class _ArchiveHandler(BaseHTTPRequestHandler):
    """A fake archive: each path answers like one failure mode of a real server."""

    flaky_calls = 0

    def do_HEAD(self) -> None:
        self._answer(head=True)

    def do_GET(self) -> None:
        self._answer(head=False)

    def _answer(self, *, head: bool) -> None:
        if self.path == "/ok":
            self._send(200)
        elif self.path == "/moved":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/missing":
            self._send(404)
        elif self.path == "/down":
            self._send(503)
        elif self.path == "/flaky":
            type(self).flaky_calls += 1
            self._send(503 if type(self).flaky_calls == 1 else 200)
        elif self.path == "/no-head":
            self._send(405 if head else 200)
        elif self.path == "/forbidden":
            self._send(403)
        elif self.path == "/slow":
            time.sleep(1.0)
            self._send(200)
        else:
            self._send(500)

    def _send(self, code: int) -> None:
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def archive() -> Iterator[str]:
    _ArchiveHandler.flaky_calls = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ArchiveHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _check(archive: str, path: str, **kwargs: object):
    options = {"timeout_seconds": 5.0, "retries": 0, "retry_delay_seconds": 0.0}
    options.update(kwargs)
    (result,) = check_sources(
        [SourceProbe(path.strip("/"), "test archive", archive + path)],
        **options,  # type: ignore[arg-type]
    )
    return result


def test_reachable_file_is_ok(archive: str) -> None:
    result = _check(archive, "/ok")

    assert result.status == "ok"
    assert result.http_status == 200
    assert not result.redirected


def test_redirect_is_ok_and_reports_the_new_location(archive: str) -> None:
    result = _check(archive, "/moved")

    assert result.status == "ok"
    assert result.redirected
    assert result.final_url == archive + "/ok"
    assert f"redirected to {archive}/ok" in "\n".join(format_results([result]))


def test_missing_file_points_to_a_moved_archive(archive: str) -> None:
    result = _check(archive, "/missing")

    assert result.status == "missing"
    assert result.http_status == 404
    assert "may have moved" in "\n".join(format_results([result]))


def test_server_error_is_unavailable_after_retries(archive: str) -> None:
    result = _check(archive, "/down", retries=2)

    assert result.status == "unavailable"
    assert result.http_status == 503
    assert result.attempts == 3
    assert "Usually temporary" in "\n".join(format_results([result]))


def test_transient_error_recovers_on_retry(archive: str) -> None:
    result = _check(archive, "/flaky", retries=1)

    assert result.status == "ok"
    assert result.attempts == 2


def test_head_rejected_falls_back_to_get(archive: str) -> None:
    assert _check(archive, "/no-head").status == "ok"


def test_refused_request_is_an_error_without_retry(archive: str) -> None:
    result = _check(archive, "/forbidden", retries=2)

    assert result.status == "error"
    assert result.attempts == 1


def test_timeout_is_unavailable(archive: str) -> None:
    result = _check(archive, "/slow", timeout_seconds=0.2)

    assert result.status == "unavailable"
    assert "no response within 0.2 s" in result.detail


def test_refused_connection_is_unavailable() -> None:
    result = _check("http://127.0.0.1:9", "/ok")

    assert result.status == "unavailable"
    assert result.detail.startswith("connection failed")


def test_default_probes_cover_each_archive_with_loader_urls() -> None:
    probes = default_probes()
    names = [probe.name for probe in probes]

    assert len(names) == len(set(names))
    assert {probe.provider for probe in probes} >= {
        "JAXA DARTS",
        "Kyoto University",
        "NASA NAIF",
        "NASA SPDF",
        "USGS Astrogeology",
    }
    pace = next(probe for probe in probes if probe.name == "kaguya.pace")
    assert pace.url == KaguyaFileSource(local_root=Path()).remote_url(
        "sln-l-pace-3-pbf1-v3.0/20080229/data/IPACE_PBF1_080229_ESA1_V003.dat.gz"
    )


def test_env_check_sources_exit_code_follows_probe_results(
    monkeypatch: pytest.MonkeyPatch,
    archive: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sopran.source_check as source_check

    probes = [SourceProbe("down", "test archive", archive + "/down")]
    monkeypatch.setattr(source_check, "default_probes", lambda: probes)
    monkeypatch.setattr(source_check.time, "sleep", lambda _seconds: None)

    assert env_check.main(["--sources", "--timeout", "5"]) == 1
    assert "[UNAVAILABLE] down (test archive) HTTP 503" in capsys.readouterr().out
    assert env_check.main([]) == 0


@pytest.mark.network
def test_remote_archives_are_reachable() -> None:
    """Run with ``pytest -m network``; this asks the real archives for headers."""

    results = check_sources()

    assert all(result.ok for result in results), "\n".join(format_results(results))
