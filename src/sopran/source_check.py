"""Reachability checks for the remote archives SOPRAN downloads from.

Each probe asks for the headers of one known file, built with the same URL
functions the loaders use, so a moved archive shows up here before a long
download fails. Nothing is downloaded and the Store is never touched.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ProbeStatus = Literal["ok", "missing", "unavailable", "error"]

# Responses worth retrying: the archive answered, but only for now.
_TRANSIENT_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
_MISSING_CODES = frozenset({404, 410})
_HEAD_UNSUPPORTED_CODES = frozenset({405, 501})
USER_AGENT = "sopran-source-check"


@dataclass(frozen=True)
class SourceProbe:
    """One known remote file that stands for an archive."""

    name: str
    provider: str
    url: str


@dataclass(frozen=True)
class ProbeResult:
    probe: SourceProbe
    status: ProbeStatus
    http_status: int | None
    final_url: str | None
    elapsed_seconds: float
    attempts: int
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def redirected(self) -> bool:
        return self.final_url is not None and self.final_url != self.probe.url


Opener = Callable[[Request, float], tuple[int, str]]


def default_probes() -> tuple[SourceProbe, ...]:
    """Return one probe per archive, using the loaders' own URL builders."""

    from sopran.bodies.moon.sources import SURFACE_SOURCE_INFO
    from sopran.missions.artemis.cdaweb import artemis_filename, artemis_remote_dir
    from sopran.missions.kaguya.files import (
        KaguyaFileSource,
        iter_public_paths,
        lmag_public_templates,
        lrs_public_template,
        pace_pbf_public_template,
    )
    from sopran.missions.kaguya.pace import (
        PACE_CALIBRATION_BASE_URL,
        pace_calibration_remote_files,
    )
    from sopran.missions.kaguya.spice import (
        MOON_ME_SPICE_KERNELS,
        SELENE_STATIC_SPICE_KERNELS,
    )
    from sopran.missions.lunar_prospector.files import PPI_VOLUME_URL, lp_provider_path
    from sopran.missions.omni.hourly import BASE_URL as OMNI_BASE_URL
    from sopran.missions.omni.hro import hro_remote_url

    day = "2008-02-29"
    # Only remote_url() is used, so the local root is irrelevant.
    darts = KaguyaFileSource(local_root=Path())
    calibration = KaguyaFileSource(
        local_root=Path(), remote_base_url=PACE_CALIBRATION_BASE_URL
    )
    lrs_template, _resolution, _skip = lrs_public_template("NPW")
    probes = [
        SourceProbe(
            "kaguya.pace",
            "JAXA DARTS",
            darts.remote_url(iter_public_paths(pace_pbf_public_template("ESA1"), day)[0]),
        ),
        SourceProbe(
            "kaguya.lmag",
            "JAXA DARTS",
            darts.remote_url(iter_public_paths(lmag_public_templates()[0], day)[0]),
        ),
        SourceProbe(
            "kaguya.lrs",
            "JAXA DARTS",
            darts.remote_url(iter_public_paths(lrs_template, day)[0]),
        ),
        SourceProbe("kaguya.spice", "JAXA DARTS", SELENE_STATIC_SPICE_KERNELS[0].url),
        SourceProbe(
            "kaguya.pace.calibration",
            "Kyoto University",
            calibration.remote_url(pace_calibration_remote_files(["ESA1"])[0]),
        ),
        SourceProbe("spice.generic_kernels", "NASA NAIF", MOON_ME_SPICE_KERNELS[0].url),
        SourceProbe("omni.hourly", "NASA SPDF", OMNI_BASE_URL + "omni2_2008.dat"),
        SourceProbe(
            "lunar_prospector.er",
            "NASA PDS PPI",
            PPI_VOLUME_URL + str(lp_provider_path("ER_LO_TS", date(1998, 2, 1))),
        ),
        SourceProbe(
            "artemis.fgm",
            "NASA SPDF",
            artemis_remote_dir("thb", "fgm", 2011)
            + artemis_filename("thb", "fgm", date(2011, 7, 1), 1),
        ),
        SourceProbe("omni.hro", "NASA SPDF", hro_remote_url("hro_1min", 2008, 2)),
    ]
    probes.extend(
        SourceProbe(f"moon.dem.{source_id}", "USGS Astrogeology", info.url)
        for source_id, info in SURFACE_SOURCE_INFO.items()
        if info.url is not None
    )
    return tuple(probes)


def check_sources(
    probes: Sequence[SourceProbe] | None = None,
    *,
    timeout_seconds: float = 60.0,
    retries: int = 2,
    retry_delay_seconds: float = 5.0,
    opener: Opener | None = None,
) -> tuple[ProbeResult, ...]:
    """Probe archives in parallel; transient answers are retried ``retries`` times."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if retries < 0:
        raise ValueError("retries must be zero or positive")
    probes = default_probes() if probes is None else tuple(probes)
    if not probes:
        return ()
    open_headers = opener or _open_headers

    def run(probe: SourceProbe) -> ProbeResult:
        return _check_one(
            probe,
            timeout_seconds=timeout_seconds,
            retries=retries,
            retry_delay_seconds=retry_delay_seconds,
            opener=open_headers,
        )

    with ThreadPoolExecutor(max_workers=min(8, len(probes))) as pool:
        return tuple(pool.map(run, probes))


def _check_one(
    probe: SourceProbe,
    *,
    timeout_seconds: float,
    retries: int,
    retry_delay_seconds: float,
    opener: Opener,
) -> ProbeResult:
    started = time.monotonic()
    attempt = 0
    while True:
        attempt += 1
        result = _attempt(probe, timeout_seconds=timeout_seconds, opener=opener)
        if result[0] != "unavailable" or attempt > retries:
            break
        time.sleep(retry_delay_seconds)
    status, http_status, final_url, detail = result
    return ProbeResult(
        probe=probe,
        status=status,
        http_status=http_status,
        final_url=final_url,
        elapsed_seconds=time.monotonic() - started,
        attempts=attempt,
        detail=detail,
    )


def _attempt(
    probe: SourceProbe,
    *,
    timeout_seconds: float,
    opener: Opener,
) -> tuple[ProbeStatus, int | None, str | None, str]:
    headers = {"User-Agent": USER_AGENT}
    try:
        try:
            code, final_url = opener(
                Request(probe.url, method="HEAD", headers=headers), timeout_seconds
            )
        except HTTPError as exc:
            if exc.code not in _HEAD_UNSUPPORTED_CODES:
                raise
            # The body is never read; closing the response ends the transfer.
            code, final_url = opener(
                Request(probe.url, method="GET", headers=headers), timeout_seconds
            )
    except HTTPError as exc:
        if exc.code in _MISSING_CODES:
            return "missing", exc.code, None, "the file is not at this URL"
        if exc.code in _TRANSIENT_CODES:
            return "unavailable", exc.code, None, f"HTTP {exc.code} {exc.reason}"
        return "error", exc.code, None, f"HTTP {exc.code} {exc.reason}"
    except TimeoutError:
        return "unavailable", None, None, f"no response within {timeout_seconds:g} s"
    except URLError as exc:
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return "unavailable", None, None, f"no response within {timeout_seconds:g} s"
        return "unavailable", None, None, f"connection failed: {reason}"
    except OSError as exc:
        return "unavailable", None, None, f"connection failed: {exc}"
    return "ok", code, final_url, ""


def _open_headers(request: Request, timeout_seconds: float) -> tuple[int, str]:
    with urlopen(request, timeout=timeout_seconds) as response:
        return int(response.status), str(response.geturl())


_STATUS_LABELS: dict[ProbeStatus, str] = {
    "ok": "OK",
    "missing": "MISSING",
    "unavailable": "UNAVAILABLE",
    "error": "ERROR",
}

_STATUS_GUIDANCE: dict[ProbeStatus, str] = {
    "missing": "The archive answered but the file is gone: the archive may have moved "
    "or renamed its directories. Check the provider's site and update the URL in SOPRAN.",
    "unavailable": "The archive did not answer usefully (server error, timeout, or no "
    "network). Usually temporary; retry later or check the network from this machine.",
    "error": "The archive refused the request. Check access restrictions or proxies.",
}


def format_results(results: Sequence[ProbeResult]) -> list[str]:
    lines: list[str] = []
    for result in results:
        code = "" if result.http_status is None else f" HTTP {result.http_status}"
        retried = f", {result.attempts} attempts" if result.attempts > 1 else ""
        lines.append(
            f"[{_STATUS_LABELS[result.status]}] {result.probe.name} ({result.probe.provider})"
            f"{code}, {result.elapsed_seconds:.1f} s{retried}"
        )
        lines.append(f"      {result.probe.url}")
        if result.redirected:
            lines.append(f"      redirected to {result.final_url}")
        if result.detail:
            lines.append(f"      {result.detail}")
    for status in ("missing", "unavailable", "error"):
        if any(result.status == status for result in results):
            lines.append(f"{_STATUS_LABELS[status]}: {_STATUS_GUIDANCE[status]}")
    return lines
