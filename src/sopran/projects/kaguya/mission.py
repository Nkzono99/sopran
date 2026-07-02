from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sopran import Store
from sopran.projects.kaguya.files import (
    KaguyaFileSource,
    iter_public_paths,
    lmag_public_templates,
    pace_pbf_public_template,
)
from sopran.projects.kaguya.sensors import normalize_sensor

DownloadMode = Literal["never", "missing", "always"]


class Kaguya:
    """Object-oriented entry point for KAGUYA/SELENE public data."""

    def __init__(
        self,
        *,
        store: Store | None = None,
        data_root: Path | str | None = None,
        fallback_roots: list[Path | str] | tuple[Path | str, ...] = (),
        source: KaguyaFileSource | None = None,
    ) -> None:
        self.store = store or Store()
        if source is None:
            local_root = Path(data_root) if data_root is not None else self.store.raw_path("kaguya", "pds3")
            source = KaguyaFileSource(
                local_root=local_root,
                fallback_roots=tuple(Path(root) for root in fallback_roots),
            )
        self.source = source
        self.esa1 = PaceInstrument(self, "ESA1")
        self.esa2 = PaceInstrument(self, "ESA2")
        self.ima = PaceInstrument(self, "IMA")
        self.iea = PaceInstrument(self, "IEA")
        self.lmag = LmagInstrument(self)


@dataclass(frozen=True)
class KaguyaQuery:
    instrument: KaguyaInstrument
    start: object
    stop: object | None = None

    def remote_files(self) -> list[str]:
        return self.instrument.remote_files(self.start, self.stop)

    def remote_urls(self) -> list[str]:
        return [self.instrument.mission.source.remote_url(path) for path in self.remote_files()]

    def files(self, *, download: DownloadMode = "never", overwrite: bool = False) -> list[Path]:
        paths: list[Path] = []
        for remote_file in self.remote_files():
            path = self.instrument.mission.source.local_path(remote_file)
            if download == "never":
                if path.exists():
                    paths.append(path)
                continue
            if download == "missing":
                path = self.instrument.mission.source.download(remote_file, overwrite=False)
            elif download == "always":
                path = self.instrument.mission.source.download(remote_file, overwrite=True)
            else:
                raise ValueError("download must be 'never', 'missing', or 'always'")
            if overwrite or path.exists():
                paths.append(path)
        return paths


class KaguyaInstrument:
    def __init__(self, mission: Kaguya, name: str) -> None:
        self.mission = mission
        self.name = name

    def select(self, start: object, stop: object | None = None) -> KaguyaQuery:
        return KaguyaQuery(self, start, stop)

    def remote_files(self, start: object, stop: object | None = None) -> list[str]:
        raise NotImplementedError


class PaceInstrument(KaguyaInstrument):
    def __init__(self, mission: Kaguya, sensor: object, *, version: str = "003") -> None:
        self.sensor = normalize_sensor(sensor)
        self.version = version
        super().__init__(mission, self.sensor)

    def remote_files(self, start: object, stop: object | None = None) -> list[str]:
        template = pace_pbf_public_template(self.sensor, version=self.version)
        return iter_public_paths(template, start, stop)


class LmagInstrument(KaguyaInstrument):
    def __init__(self, mission: Kaguya, *, version: str = "1.0") -> None:
        self.version = version
        super().__init__(mission, "LMAG")

    def remote_files(self, start: object, stop: object | None = None) -> list[str]:
        paths: list[str] = []
        for template in lmag_public_templates(version=self.version):
            paths.extend(iter_public_paths(template, start, stop))
        return paths
