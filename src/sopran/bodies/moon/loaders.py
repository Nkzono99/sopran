from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from sopran.core.errors import DatasetNotFoundError
from sopran.core.store import Store

from .dem import load_dem_raster
from .models import SurfaceSource
from .sources import canonical_source_id
from .svm import read_tsunakawa_svm_npy, read_tsunakawa_svm_text


def load_surface_raster(endpoint: Any, **parameters: Any) -> Any:
    store = parameters.pop("store", None)
    download = str(parameters.pop("download", "never"))
    path = parameters.pop("path", parameters.pop("filepath", None))
    plan = endpoint.plan(**parameters)
    source = str(plan.parameters.get("source", endpoint.default_source or ""))
    if endpoint.product == "dem":
        data_path = surface_data_path(
            endpoint=endpoint,
            source=source,
            path=path,
            store=store,
            download=download,
        )
        return load_dem_raster(endpoint, plan, data_path)
    if endpoint.product == "svm":
        data_path = surface_data_path(
            endpoint=endpoint,
            source=source,
            path=path,
            store=store,
            download=download,
        )
        if data_path.suffix.lower() == ".npy":
            return read_tsunakawa_svm_npy(
                data_path,
                source=canonical_source_id(source),
                body=endpoint.body.name,
                metadata=plan.to_metadata()["parameters"],
            )
        return read_tsunakawa_svm_text(
            data_path,
            source=canonical_source_id(source),
            body=endpoint.body.name,
            metadata=plan.to_metadata()["parameters"],
        )
    raise NotImplementedError(f"Moon.{plan.product}.load() is not implemented yet")


def surface_data_path(
    *,
    endpoint: Any,
    source: str,
    path: Any,
    store: Store | str | Path | None,
    download: str,
) -> Path:
    if path is not None:
        return Path(path)
    if download not in {"never", "missing", "always"}:
        raise ValueError("download must be 'never', 'missing', or 'always'")
    source_info = endpoint.source_info(source)
    resolved_store = coerce_store(store)
    candidate = resolved_store.raw_path("moon", endpoint.product, source_info.filename)
    if candidate.exists() and download != "always":
        return candidate
    if download in {"missing", "always"}:
        return cast(
            Path,
            endpoint.download(
                source=source_info.source_id,
                store=resolved_store,
                overwrite=download == "always",
            ),
        )
    raise DatasetNotFoundError(
        f"Moon.{endpoint.product} data is not available locally: {candidate}. "
        "Pass path= explicitly, set download='missing' for sources with a direct URL, "
        "or call acquisition_guide() for manual acquisition."
    )


def coerce_store(store: Store | str | Path | None) -> Store:
    if isinstance(store, Store):
        return store
    return Store(store)

def download_surface_source(
    source_info: SurfaceSource,
    *,
    product: str,
    store: Store | None,
    target: Path | str | None,
    overwrite: bool,
) -> Path:
    resolved_store = store or Store()
    target_path = (
        Path(target)
        if target is not None
        else resolved_store.raw_path("moon", product, source_info.filename)
    )
    if source_info.url is None:
        from sopran.core.errors import DownloadError

        raise DownloadError(
            f"Moon.{product} source requires manual acquisition: "
            f"{source_info.filename}. {source_info.manual_note or ''}".strip()
        )
    if not target_path.exists() or overwrite:
        _download_file(source_info.url, target_path, overwrite=overwrite)
    register_surface_download(resolved_store, target_path, source_info)
    return target_path


def register_surface_download(store: Store, path: Path, source: SurfaceSource) -> None:
    try:
        store.register_raw_file(
            path,
            mission="moon",
            provider=source.provider,
            provider_path=source.source_id,
            data_version=source.version,
            download_url=source.url,
        )
    except ValueError:
        return


def _download_file(url: str, target: Path, *, overwrite: bool = False) -> None:
    if target.exists() and not overwrite:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = temporary_download_path(target)
    try:
        with urllib.request.urlopen(url) as response, temp.open("wb") as output:
            shutil.copyfileobj(response, output)
        temp.replace(target)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def temporary_download_path(target: Path) -> Path:
    for _ in range(100):
        temp = target.with_name(f"{target.name}.{uuid4().hex}.tmp")
        if not temp.exists():
            return temp
    raise FileExistsError(f"Could not allocate temporary download path for {target}")
