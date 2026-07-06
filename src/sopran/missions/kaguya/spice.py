from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.request import urlretrieve
from uuid import uuid4

from sopran.core.store import Store

DownloadMode = Literal["never", "missing", "always"]
NAIF_GENERIC_KERNEL_BASE_URL = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels"


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


def _register_kernel(store: Store, spec: SpiceKernelSpec, target: Path) -> None:
    store.register_raw_file(
        target,
        mission="spice",
        provider="naif-generic-kernels",
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
    "SpiceKernelSpec",
    "moon_me_spice_kernels",
]
