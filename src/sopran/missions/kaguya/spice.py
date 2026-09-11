from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Literal
from urllib.request import urlretrieve
from uuid import uuid4

from sopran.core.store import Store
from sopran.core.time import TimeRange

DownloadMode = Literal["never", "missing", "always"]
NAIF_GENERIC_KERNEL_BASE_URL = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels"
SELENE_SPICE_ARCHIVE_BASE_URL = (
    "https://data.darts.isas.jaxa.jp/pub/pds3/"
    "sln-l-spice-6-v1.0/slnsp_1000/data"
)


@dataclass(frozen=True)
class SpiceKernelSpec:
    relative_path: tuple[str, ...]
    url: str

    @property
    def provider_path(self) -> str:
        return "/".join(self.relative_path)


MOON_ME_SPICE_KERNELS: tuple[SpiceKernelSpec, ...] = (
    SpiceKernelSpec(
        ("generic_kernels", "lsk", "naif0012.tls"),
        f"{NAIF_GENERIC_KERNEL_BASE_URL}/lsk/naif0012.tls",
    ),
    SpiceKernelSpec(
        ("generic_kernels", "fk", "satellites", "moon_080317.tf"),
        f"{NAIF_GENERIC_KERNEL_BASE_URL}/fk/satellites/moon_080317.tf",
    ),
    SpiceKernelSpec(
        ("generic_kernels", "fk", "satellites", "moon_assoc_me.tf"),
        f"{NAIF_GENERIC_KERNEL_BASE_URL}/fk/satellites/moon_assoc_me.tf",
    ),
    SpiceKernelSpec(
        ("generic_kernels", "pck", "pck00010.tpc"),
        f"{NAIF_GENERIC_KERNEL_BASE_URL}/pck/pck00010.tpc",
    ),
    SpiceKernelSpec(
        ("generic_kernels", "pck", "moon_pa_de421_1900-2050.bpc"),
        f"{NAIF_GENERIC_KERNEL_BASE_URL}/pck/moon_pa_de421_1900-2050.bpc",
    ),
    SpiceKernelSpec(
        ("generic_kernels", "spk", "planets", "de421.bsp"),
        f"{NAIF_GENERIC_KERNEL_BASE_URL}/spk/planets/a_old_versions/de421.bsp",
    ),
)

SELENE_STATIC_SPICE_KERNELS: tuple[SpiceKernelSpec, ...] = (
    SpiceKernelSpec(
        ("selene", "fk", "SEL_V01.TF"),
        f"{SELENE_SPICE_ARCHIVE_BASE_URL}/fk/SEL_V01.TF",
    ),
    SpiceKernelSpec(
        ("selene", "sclk", "SEL_M_V01.TSC"),
        f"{SELENE_SPICE_ARCHIVE_BASE_URL}/sclk/SEL_M_V01.TSC",
    ),
    SpiceKernelSpec(
        ("selene", "spk", "SEL_M_071020_090610_SGMH_02.BSP"),
        (
            f"{SELENE_SPICE_ARCHIVE_BASE_URL}/spk/"
            "SEL_M_071020_090610_SGMH_02.BSP"
        ),
    ),
)


def moon_me_spice_kernels(
    store: Store,
    *,
    download: DownloadMode = "missing",
) -> tuple[Path, ...]:
    """Return local NAIF generic kernels required for MOON_ME Sun geometry."""

    _validate_download_mode(download)
    paths: list[Path] = []
    missing: list[Path] = []
    for spec in MOON_ME_SPICE_KERNELS:
        target = store.raw_path("spice", "kernels", *spec.relative_path)
        if target.exists() and download != "always":
            _register_kernel(store, spec, target)
            paths.append(target)
            continue
        if download == "never":
            missing.append(target)
            continue
        _download_file(spec.url, target, overwrite=download == "always")
        _register_kernel(store, spec, target)
        paths.append(target)
    if missing:
        raise FileNotFoundError(
            "Missing local NAIF Moon ME SPICE kernels:\n"
            + "\n".join(str(path) for path in missing)
        )
    return tuple(paths)


def selene_spice_kernels(
    store: Store,
    time: TimeRange,
    *,
    download: DownloadMode = "missing",
) -> tuple[Path, ...]:
    """Return Moon and date-scoped SELENE attitude kernels for vector transforms."""

    _validate_download_mode(download)
    paths = list(moon_me_spice_kernels(store, download=download))
    specs = (*SELENE_STATIC_SPICE_KERNELS, *_selene_ck_specs(time))
    missing: list[Path] = []
    for spec in specs:
        target = store.raw_path("spice", "kernels", *spec.relative_path)
        if target.exists() and download != "always":
            _register_kernel(store, spec, target, provider="darts-selene-spice")
            paths.append(target)
            continue
        if download == "never":
            missing.append(target)
            continue
        _download_file(spec.url, target, overwrite=download == "always")
        _register_kernel(store, spec, target, provider="darts-selene-spice")
        paths.append(target)
    if missing:
        raise FileNotFoundError(
            "Missing local SELENE SPICE kernels:\n"
            + "\n".join(str(path) for path in missing)
        )
    return tuple(paths)


def _selene_ck_specs(time: TimeRange) -> tuple[SpiceKernelSpec, ...]:
    final = (time.stop - timedelta(microseconds=1)).date()
    current_year = time.start.year
    current_month = time.start.month
    months: list[tuple[int, int]] = []
    while (current_year, current_month) <= (final.year, final.month):
        months.append((current_year, current_month))
        current_month += 1
        if current_month == 13:
            current_year += 1
            current_month = 1
    specs: list[SpiceKernelSpec] = []
    for year, month in months:
        stamp = f"{year:04d}{month:02d}"
        if stamp < "200710" or stamp > "200906":
            raise ValueError(
                "SELENE attitude CK coverage is limited to 2007-10 through 2009-06"
            )
        filename = f"SEL_M_{stamp}_S_V03.BC"
        specs.append(
            SpiceKernelSpec(
                ("selene", "ck", filename),
                f"{SELENE_SPICE_ARCHIVE_BASE_URL}/ck/{filename}",
            )
        )
    return tuple(specs)


def _download_file(url: str, target: Path, *, overwrite: bool = False) -> None:
    if target.exists() and not overwrite:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = _temporary_download_path(target)
    try:
        urlretrieve(url, temp)
        temp.replace(target)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _register_kernel(
    store: Store,
    spec: SpiceKernelSpec,
    target: Path,
    *,
    provider: str = "naif-generic-kernels",
) -> None:
    store.register_raw_file(
        target,
        mission="spice",
        provider=provider,
        provider_path=spec.provider_path,
        download_url=spec.url,
    )


def _temporary_download_path(target: Path) -> Path:
    for _ in range(100):
        temp = target.with_name(f"{target.name}.{uuid4().hex}.tmp")
        if not temp.exists():
            return temp
    raise FileExistsError(f"Could not allocate temporary download path for {target}")


def _validate_download_mode(download: str) -> None:
    if download not in {"never", "missing", "always"}:
        raise ValueError("download must be 'never', 'missing', or 'always'")


__all__ = [
    "MOON_ME_SPICE_KERNELS",
    "NAIF_GENERIC_KERNEL_BASE_URL",
    "SELENE_SPICE_ARCHIVE_BASE_URL",
    "SELENE_STATIC_SPICE_KERNELS",
    "SpiceKernelSpec",
    "moon_me_spice_kernels",
    "selene_spice_kernels",
]
