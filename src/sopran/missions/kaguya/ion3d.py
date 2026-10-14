"""KAGUYA PACE IMA/IEA 3-D ion distributions.

Port of SPEDAS ``kgy_ima_get3d`` / ``kgy_iea_get3d`` (Y. Harada) for the record
types they support: IMA 0x40-0x43 and IEA 0x80-0x81. Each record becomes
``32 energy steps x nbins`` in the SPEDAS ``sabin`` order (``bin = polar +
azimuth * n_polar``), with INFO-table energies, angles and geometric factors
placed by the energy/polar sequence numbers. Units follow
``kgy_pace_convert_units`` and moments ``kgy_n_3d`` / ``kgy_j_3d``.

Angles give the direction of particle motion in ``SELENE_M_SPACECRAFT``.
IMA mass channels are summed and the ions are treated as protons, as in
SPEDAS. Unlike SPEDAS, a cell whose mass channels are all fill values stays NaN
instead of becoming zero, so missing and zero counts remain distinct.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np

from sopran.core.time import TimeRange
from sopran.frames import FrameContext, normalize_frame
from sopran.missions.kaguya.pace import PaceCalibration, PaceData, PaceRecord
from sopran.missions.kaguya.pitch import CountCorrection, pace_count_correction_factor

IonUnits = Literal["counts", "rate", "eflux", "flux", "df"]
AngleSource = Literal["info", "fov"]

ION_SENSORS = {"IMA": 2, "IEA": 3}
#: Proton mass in eV / (km/s)^2, the value used by SPEDAS for IMA and IEA.
PROTON_MASS_EV = 5.6856591e-6 * 1836.0
#: SPEDAS uses the gfactor of this azimuth channel for IMA type 0x40 (cf. momcal.c).
TYPE40_GFACTOR_CHANNEL = 4
SPACECRAFT_FRAME = "SELENE_M_SPACECRAFT"

# (sensor, record type) -> (INFO table key, n_polar, n_azimuth)
ION_RECORD_LAYOUTS: dict[tuple[str, int], tuple[str, int, int]] = {
    ("IMA", 0x40): ("4x16", 4, 1),
    ("IMA", 0x41): ("16x64", 16, 64),
    ("IMA", 0x42): ("4x16", 4, 16),
    ("IMA", 0x43): ("4x16", 4, 16),
    ("IEA", 0x80): ("4x16", 4, 16),
    ("IEA", 0x81): ("16x64", 16, 64),
}


@dataclass(frozen=True)
class PaceIonGrid:
    """Energy and angle grid of one record type and RAM table (``32 x nbins``)."""

    ram: int
    energy_eV: np.ndarray
    denergy_eV: np.ndarray
    theta_deg: np.ndarray
    phi_deg: np.ndarray
    dtheta_deg: np.ndarray
    dphi_deg: np.ndarray
    gfactor: np.ndarray
    valid: np.ndarray
    sequence_fallback: bool = False

    @property
    def domega_sr(self) -> np.ndarray:
        theta = np.deg2rad(self.theta_deg)
        return np.asarray(
            2.0
            * np.deg2rad(self.dphi_deg)
            * np.cos(theta)
            * np.sin(0.5 * np.deg2rad(self.dtheta_deg))
        )

    def directions(self) -> np.ndarray:
        """Unit vectors of particle motion, ``(32, nbins, 3)``."""

        theta = np.deg2rad(self.theta_deg)
        phi = np.deg2rad(self.phi_deg)
        return np.stack(
            (np.cos(theta) * np.cos(phi), np.cos(theta) * np.sin(phi), np.sin(theta)), axis=-1
        )


@dataclass(frozen=True)
class PaceIon3D:
    """Time series of one IMA/IEA record type as SPEDAS-style 3-D distributions.

    ``counts`` is ``(n_record, 32, nbins)``; energies, angles and geometric
    factors live in ``grids`` and ``grid_index`` maps each record to its grid.
    ``time`` and ``end_time`` bound each accumulation; ``integration_s`` is the
    per-step accumulation time ``16 / sampl_time`` used for unit conversion.
    """

    sensor: str
    record_type: int
    time: np.ndarray
    end_time: np.ndarray
    integration_s: np.ndarray
    counts: np.ndarray
    grid_index: np.ndarray
    grids: tuple[PaceIonGrid, ...]
    n_polar: int
    n_azimuth: int
    count_correction: str = "none"
    angles: str = "info"
    efficiency: float = 0.6
    mass_eV: float = PROTON_MASS_EV
    charge: float = 1.0
    frame: str = SPACECRAFT_FRAME
    files: tuple[Path, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def n_records(self) -> int:
        return int(self.counts.shape[0])

    @property
    def center_time(self) -> np.ndarray:
        return np.asarray(self.time + (self.end_time - self.time) // 2)

    def select(self, mask: Any) -> PaceIon3D:
        """Subset of records by boolean mask or index array."""

        index = np.arange(self.n_records)[np.asarray(mask)]
        return replace(
            self,
            time=self.time[index],
            end_time=self.end_time[index],
            integration_s=self.integration_s[index],
            counts=self.counts[index],
            grid_index=self.grid_index[index],
        )

    def between(self, start: Any, stop: Any) -> PaceIon3D:
        """Records whose centre lies in ``[start, stop)``."""

        centre = self.center_time
        return self.select(
            (centre >= np.datetime64(start, "ns")) & (centre < np.datetime64(stop, "ns"))
        )

    def grid_values(self, name: str, records: Any = None) -> np.ndarray:
        """Per-record ``(n, 32, nbins)`` copy of a grid attribute such as ``energy_eV``."""

        index = self._records(records)
        stack = np.stack([np.asarray(getattr(grid, name)) for grid in self.grids])
        return np.asarray(stack[self.grid_index[index]])

    def to_units(self, units: IonUnits, records: Any = None) -> np.ndarray:
        """Counts converted as in ``kgy_pace_convert_units`` (no dead-time correction).

        ``rate`` [1/s], ``eflux`` [eV/(cm^2 s sr eV)], ``flux`` [1/(cm^2 s sr eV)],
        ``df`` [1/(cm^3 (km/s)^3)]. Bins without a positive geometric factor are NaN.
        """

        index = self._records(records)
        counts = self.counts[index]
        if units == "counts":
            return np.array(counts, copy=True)
        dt = self.integration_s[index][:, None, None]
        if units == "rate":
            return np.asarray(counts / dt)
        scale = np.stack([self._unit_scale(grid, units) for grid in self.grids])
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.asarray(counts / (dt * scale[self.grid_index[index]]))

    def density(
        self, *, energy_range: tuple[float, float] | None = None, chunk: int = 256
    ) -> np.ndarray:
        """Number density [cm^-3] (``kgy_n_3d``) per record."""

        out = np.full(self.n_records, np.nan)
        weights = [self._moment_weights(grid, energy_range)[0] for grid in self.grids]
        for index in self._chunks(chunk):
            df = self.to_units("df", index)
            w = np.stack(weights)[self.grid_index[index]]
            out[index] = np.nansum(df * w, axis=(1, 2))
        return out

    def number_flux(
        self,
        *,
        energy_range: tuple[float, float] | None = None,
        frame: str | None = None,
        context: FrameContext | None = None,
        chunk: int = 256,
    ) -> np.ndarray:
        """Number flux vector [cm^-2 s^-1] (``kgy_j_3d``), ``(n, 3)`` in ``frame``."""

        out = np.full((self.n_records, 3), np.nan)
        weights = [self._moment_weights(grid, energy_range)[1] for grid in self.grids]
        for index in self._chunks(chunk):
            df = self.to_units("df", index)
            w = np.stack(weights)[self.grid_index[index]]
            out[index] = np.einsum("nkb,nkbi->ni", np.nan_to_num(df), w)
        valid = np.isfinite(self.counts).any(axis=(1, 2))
        out[~valid] = np.nan
        return self._rotate(out, frame, context)

    def velocity(
        self,
        *,
        energy_range: tuple[float, float] | None = None,
        frame: str | None = None,
        context: FrameContext | None = None,
    ) -> np.ndarray:
        """Bulk velocity [km/s] = flux / density, ``(n, 3)`` in ``frame``."""

        density = self.density(energy_range=energy_range)
        flux = self.number_flux(energy_range=energy_range, frame=frame, context=context)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.asarray(flux / density[:, None] / 1e5)

    def directions(
        self,
        records: Any = None,
        *,
        frame: str | None = None,
        context: FrameContext | None = None,
    ) -> np.ndarray:
        """Unit vectors of particle motion per bin, ``(n, 32, nbins, 3)`` in ``frame``."""

        index = self._records(records)
        base = np.stack([grid.directions() for grid in self.grids])[self.grid_index[index]]
        target = normalize_frame(frame or self.frame)
        if target == normalize_frame(self.frame):
            return np.asarray(base)
        matrices = self.rotation_matrices(target, context=context, records=index)
        return np.asarray(np.einsum("nij,nkbj->nkbi", matrices, base))

    def rotation_matrices(
        self, frame: str, *, context: FrameContext | None, records: Any = None
    ) -> np.ndarray:
        """``(n, 3, 3)`` matrices taking ``self.frame`` vectors to ``frame`` at record centres."""

        index = self._records(records)
        if context is None:
            raise ValueError(
                "frame conversion needs a FrameContext with SELENE kernels "
                "(sopran.missions.kaguya.selene_spice_kernels)"
            )
        times = self.center_time[index].astype("datetime64[ns]").astype("int64") / 1e9
        columns = []
        for axis in np.eye(3):
            vectors = np.broadcast_to(axis, (len(index), 3))
            columns.append(
                np.asarray(
                    context.transform_vectors(
                        vectors,
                        times=times,
                        source_frame=self.frame,
                        target_frame=frame,
                        missing="nan",
                    ),
                    dtype=float,
                )
            )
        return np.stack(columns, axis=-1)

    def to_xarray(self, units: IonUnits = "counts") -> Any:
        """xarray Dataset with ``units`` values and the per-grid calibration."""

        import xarray as xr

        nbins = self.counts.shape[2]
        grid_vars = {
            name: (
                ("grid", "energy_step", "bin"),
                np.stack([np.asarray(getattr(g, name)) for g in self.grids]),
            )
            for name in (
                "energy_eV",
                "denergy_eV",
                "theta_deg",
                "phi_deg",
                "dtheta_deg",
                "dphi_deg",
                "gfactor",
                "valid",
            )
        }
        return xr.Dataset(
            {
                units: (("time", "energy_step", "bin"), self.to_units(units)),
                "grid_index": (("time",), self.grid_index),
                "end_time": (("time",), self.end_time),
                "integration_s": (("time",), self.integration_s),
                **grid_vars,
            },
            coords={
                "time": self.time,
                "energy_step": np.arange(32),
                "bin": np.arange(nbins),
                "grid": [g.ram for g in self.grids],
            },
            attrs=dict(
                mission="kaguya",
                instrument=self.sensor,
                record_type=f"0x{self.record_type:02x}",
                units=units,
                frame=self.frame,
                count_correction=self.count_correction,
                angles=self.angles,
                efficiency=self.efficiency,
                mass_eV_per_km2_s2=self.mass_eV,
                n_polar=self.n_polar,
                n_azimuth=self.n_azimuth,
                source_files=[str(p) for p in self.files],
                notes=list(self.notes),
                reference="SPEDAS kgy_ima_get3d / kgy_iea_get3d (sabin order)",
            ),
        )

    # ------------------------------------------------------------------

    def _records(self, records: Any) -> np.ndarray:
        if records is None:
            return np.arange(self.n_records)
        return np.asarray(np.arange(self.n_records)[np.asarray(records)])

    def _chunks(self, size: int) -> Iterable[np.ndarray]:
        for start in range(0, self.n_records, size):
            yield np.arange(start, min(start + size, self.n_records))

    def _unit_scale(self, grid: PaceIonGrid, units: str) -> np.ndarray:
        gf = np.where(grid.valid & (grid.gfactor > 0), grid.gfactor * self.efficiency, np.nan)
        energy = grid.energy_eV
        if units == "eflux":
            return gf
        if units == "flux":
            return np.asarray(gf * energy)
        if units == "df":
            return np.asarray(gf * energy**2 * 2.0 / self.mass_eV**2 * 1e5)
        raise ValueError(f"unknown units {units!r}")

    def _moment_weights(
        self, grid: PaceIonGrid, energy_range: tuple[float, float] | None
    ) -> tuple[np.ndarray, np.ndarray]:
        energy = grid.energy_eV
        theta = np.deg2rad(grid.theta_deg)
        phi = np.deg2rad(grid.phi_deg)
        solid = (
            2.0
            * np.cos(theta)
            * np.sin(0.5 * np.deg2rad(grid.dtheta_deg))
            * np.deg2rad(grid.dphi_deg)
        )
        use = grid.valid & np.isfinite(energy) & (energy > 0)
        if energy_range is not None:
            use &= (energy >= energy_range[0]) & (energy <= energy_range[1])
        density = np.where(
            use, self.mass_eV**-1.5 * np.sqrt(2.0) * grid.denergy_eV * np.sqrt(energy) * solid, 0.0
        )
        flux_scalar = np.where(
            use, 2.0 / self.mass_eV**2 * 1e5 * grid.denergy_eV * energy * solid, 0.0
        )
        direction = np.stack(
            (np.cos(theta) * np.cos(phi), np.cos(theta) * np.sin(phi), np.sin(theta)), axis=-1
        )
        return np.nan_to_num(density), np.nan_to_num(flux_scalar[..., None] * direction)

    def _rotate(
        self, vectors: np.ndarray, frame: str | None, context: FrameContext | None
    ) -> np.ndarray:
        if frame is None or normalize_frame(frame) == normalize_frame(self.frame):
            return vectors
        matrices = self.rotation_matrices(normalize_frame(frame), context=context)
        return np.asarray(np.einsum("nij,nj->ni", matrices, vectors))


def pace_ion_3d(
    pace: PaceData,
    calibration: PaceCalibration,
    *,
    count_correction: CountCorrection = "none",
    angles: AngleSource = "info",
    time: TimeRange | None = None,
    efficiency: float = 0.6,
    files: Sequence[Path] = (),
) -> dict[int, PaceIon3D]:
    """IMA/IEA records as :class:`PaceIon3D`, one per supported record type.

    ``count_correction`` follows SPEDAS ``/cntcorr``: trash then event
    correction; IMA type 0x40 has no trash telemetry and only the event step
    is applied. Unsupported record types are skipped and listed in ``notes``.
    """

    sensor = pace.sensor_name.replace("-", "").upper()
    if sensor not in ION_SENSORS:
        raise ValueError(f"pace_ion_3d needs IMA or IEA data, received {pace.sensor_name}")
    info = calibration.info.get(ION_SENSORS[sensor])
    fov = calibration.fov.get(ION_SENSORS[sensor])
    if angles == "info" and info is None:
        raise ValueError(
            f"{sensor} INFO calibration tables are required "
            f"(kg.{sensor.lower()}.load_calibration())"
        )
    if angles == "fov" and (fov is None or info is None):
        raise ValueError(f"{sensor} FOV and INFO tables are required for angles='fov'")
    if angles not in {"info", "fov"}:
        raise ValueError("angles must be 'info' or 'fov'")

    groups: dict[int, list[tuple[PaceRecord, dict[str, Any]]]] = {}
    skipped: dict[int, int] = {}
    for record in pace.record_order:
        header = pace.headers[record.index]
        if (sensor, record.type) not in ION_RECORD_LAYOUTS:
            skipped[record.type] = skipped.get(record.type, 0) + 1
            continue
        centre = header.get("time")
        if centre is None or not np.isfinite(float(centre)):
            continue
        if time is not None:
            instant = datetime.fromtimestamp(float(centre), tz=UTC)
            if not time.start <= instant < time.stop:
                continue
        groups.setdefault(record.type, []).append((record, header))

    notes = tuple(
        f"skipped {n} records of unsupported type 0x{t:02x}" for t, n in sorted(skipped.items())
    )
    out: dict[int, PaceIon3D] = {}
    for record_type, rows in sorted(groups.items()):
        out[record_type] = _build_type(
            sensor,
            record_type,
            rows,
            info,
            fov,
            count_correction,
            angles,
            efficiency,
            tuple(files),
            notes,
        )
    return out


# ----------------------------------------------------------------------------


def _build_type(
    sensor: str,
    record_type: int,
    rows: list[tuple[PaceRecord, dict[str, Any]]],
    info: dict[str, np.ndarray] | None,
    fov: dict[str, np.ndarray] | None,
    count_correction: CountCorrection,
    angles: str,
    efficiency: float,
    files: tuple[Path, ...],
    notes: tuple[str, ...],
) -> PaceIon3D:
    key, n_polar, n_azimuth = ION_RECORD_LAYOUTS[(sensor, record_type)]
    grids: dict[int, PaceIonGrid] = {}
    grid_index = np.empty(len(rows), dtype=np.int64)
    counts = np.empty((len(rows), 32, n_polar * n_azimuth))
    start = np.empty(len(rows), dtype="datetime64[ns]")
    stop = np.empty(len(rows), dtype="datetime64[ns]")
    integration = np.empty(len(rows))
    for i, (record, header) in enumerate(rows):
        ram = int(header.get("svs_tbl", 0))
        if ram not in grids:
            grids[ram] = _grid(sensor, record_type, ram, info, fov, angles)
        grid_index[i] = list(grids).index(ram)
        enesq, polsq, _ = _sequences(info, key, ram, n_polar)
        table = _table_counts(sensor, record_type, record, count_correction)
        counts[i] = _flatten(_remap(table, enesq, polsq, remap_polar=record_type != 0x40))
        resolution = float(header.get("time_resolution", 0.0)) * 1e-3
        centre = float(header["time"])
        start[i] = np.datetime64(int(round((centre - resolution / 2) * 1e9)), "ns")
        stop[i] = np.datetime64(int(round((centre + resolution / 2) * 1e9)), "ns")
        sampl = float(header.get("sampl_time", 0.0))
        integration[i] = 16.0 / sampl if sampl > 0 else np.nan
    order = np.argsort(start, kind="stable")
    extra = tuple(
        f"RAM {g.ram}: sequence numbers were not a permutation; identity order used"
        for g in grids.values()
        if g.sequence_fallback
    )
    return PaceIon3D(
        sensor=sensor,
        record_type=record_type,
        time=start[order],
        end_time=stop[order],
        integration_s=integration[order],
        counts=counts[order],
        grid_index=grid_index[order],
        grids=tuple(grids.values()),
        n_polar=n_polar,
        n_azimuth=n_azimuth,
        count_correction=count_correction,
        angles=angles,
        efficiency=efficiency,
        files=files,
        notes=notes + extra,
    )


def _sequences(
    info: dict[str, np.ndarray] | None, key: str, ram: int, n_polar: int
) -> tuple[np.ndarray, np.ndarray, bool]:
    if info is None or f"ene_sqno_{key}" not in info:
        return np.arange(32), np.arange(n_polar), True
    ram = min(ram, info[f"ene_sqno_{key}"].shape[0] - 1)
    enesq = np.asarray(info[f"ene_sqno_{key}"][ram, :, 0, 0], dtype=int)
    polsq = np.asarray(info[f"pol_sqno_{key}"][ram, 0, :, 0], dtype=int)
    ok = sorted(enesq.tolist()) == list(range(32)) and sorted(polsq.tolist()) == list(
        range(n_polar)
    )
    if not ok:
        return np.arange(32), np.arange(n_polar), True
    return enesq, polsq, False


def _grid(
    sensor: str,
    record_type: int,
    ram: int,
    info: dict[str, np.ndarray] | None,
    fov: dict[str, np.ndarray] | None,
    angles: str,
) -> PaceIonGrid:
    key, n_polar, n_azimuth = ION_RECORD_LAYOUTS[(sensor, record_type)]
    enesq, polsq, fallback = _sequences(info, key, ram, n_polar)
    assert info is not None
    ram_i = min(ram, info[f"gfactor_{key}"].shape[0] - 1)
    if record_type == 0x40:
        ch = TYPE40_GFACTOR_CHANNEL
        gfactor = _remap_type40_grid(info[f"gfactor_{key}"][ram_i][:, :, ch], enesq, polsq, 0.0)
        if angles == "info":
            energy = _remap_type40_grid(info[f"ene_{key}"][ram_i][:, :, ch] * 1000.0, enesq, polsq)
            theta = _remap_type40_grid(info[f"pol_{key}"][ram_i][:, :, ch], enesq, polsq)
        else:
            assert fov is not None
            ram_f = min(ram, fov["ene"].shape[0] - 1)
            energy = _remap_type40_grid(
                np.broadcast_to(fov["ene"][ram_f][:, None] * 1000.0, (32, n_polar)), enesq, polsq
            )
            theta = _remap_type40_grid(-fov["pol4"][ram_f], enesq, polsq)
        energy, theta, gfactor = energy[:, :, None], theta[:, :, None], gfactor[:, :, None]
        phi = np.zeros_like(energy)
    else:
        shape = (32, n_polar, n_azimuth)
        gfactor = _assign(shape, enesq, polsq, info[f"gfactor_{key}"][ram_i], 0.0)
        if angles == "info":
            energy = _assign(shape, enesq, polsq, info[f"ene_{key}"][ram_i] * 1000.0)
            theta = _assign(shape, enesq, polsq, info[f"pol_{key}"][ram_i])
            phi = _assign(shape, enesq, polsq, info[f"az_{key}"][ram_i])
        else:
            assert fov is not None
            ram_f = min(ram, fov["ene"].shape[0] - 1)
            pol = fov["pol16" if n_polar == 16 else "pol4"][ram_f]
            az = fov["az64" if n_azimuth == 64 else "az16"]
            energy = np.full(shape, np.nan)
            energy[enesq] = np.broadcast_to(fov["ene"][ram_f][:, None, None] * 1000.0, shape)
            theta = _assign(shape, enesq, polsq, np.broadcast_to(-pol[:, :, None], shape))
            phi = np.broadcast_to(az[None, None, :], shape).astype(float).copy()
    valid = np.isfinite(gfactor) & (gfactor != 0.0)
    if angles == "fov":
        valid = np.ones_like(valid)  # SPEDAS sets bins from the gfactor only with INFO angles
    denergy = _denergy(energy)
    dtheta = np.full(energy.shape, 90.0 / n_polar)
    dphi = np.full(energy.shape, 360.0 / n_azimuth)
    return PaceIonGrid(
        ram=ram,
        energy_eV=_flatten(energy),
        denergy_eV=_flatten(denergy),
        theta_deg=_flatten(theta),
        phi_deg=_flatten(phi),
        dtheta_deg=_flatten(dtheta),
        dphi_deg=_flatten(dphi),
        gfactor=_flatten(np.nan_to_num(gfactor)),
        valid=_flatten(valid),
        sequence_fallback=fallback,
    )


def _remap_type40_grid(
    table: np.ndarray, enesq: np.ndarray, polsq: np.ndarray, default: float = np.nan
) -> np.ndarray:
    """SPEDAS type 0x40: ``g[enesq,*] = table`` then ``g[*,polsq] = g``."""

    grid = np.full(table.shape, default, dtype=float)
    grid[enesq, :] = table
    out = grid.copy()
    out[:, polsq] = grid
    return out


def _assign(
    shape: tuple[int, int, int],
    enesq: np.ndarray,
    polsq: np.ndarray,
    values: Any,
    default: float = np.nan,
) -> np.ndarray:
    out = np.full(shape, default, dtype=float)
    out[np.ix_(enesq, polsq, np.arange(shape[2]))] = values
    return out


def _remap(
    table: np.ndarray, enesq: np.ndarray, polsq: np.ndarray, *, remap_polar: bool
) -> np.ndarray:
    """Place table-order counts at their energy (and polar) steps.

    Same as SPEDAS ``data[enesq, polsq, *] = ccnt``.
    """

    out = np.full(table.shape, np.nan)
    polar = polsq if remap_polar else np.arange(table.shape[1])
    out[np.ix_(enesq, polar, np.arange(table.shape[2]))] = table
    return out


def _flatten(values: np.ndarray) -> np.ndarray:
    """``(32, n_polar, n_azimuth)`` -> ``(32, nbins)`` with ``bin = polar + azimuth * n_polar``."""

    return np.ascontiguousarray(np.transpose(values, (0, 2, 1)).reshape(values.shape[0], -1))


def _denergy(energy: np.ndarray) -> np.ndarray:
    """SPEDAS step widths along the energy-step axis (central differences).

    The absolute value is taken so that a descending sweep gives positive widths
    (SPEDAS keeps the sign, which would make moments negative for such a sweep).
    """

    out = np.empty_like(energy)
    out[0] = energy[1] - energy[0]
    out[-1] = energy[-1] - energy[-2]
    out[1:-1] = (energy[2:] - energy[:-2]) / 2.0
    return np.asarray(np.abs(out))


def _telemetry(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values)
    out = array.astype(float, copy=True)
    if np.issubdtype(array.dtype, np.integer):
        out[array == np.iinfo(array.dtype).max] = np.nan
    return out


def _nansum_keep_missing(values: np.ndarray, axis: int) -> np.ndarray:
    total = np.nansum(values, axis=axis)
    total[np.all(np.isnan(values), axis=axis)] = np.nan
    return np.asarray(total)


def _table_counts(
    sensor: str, record_type: int, record: PaceRecord, correction: CountCorrection
) -> np.ndarray:
    """Counts in table order ``(32, n_polar, n_azimuth)`` with the SPEDAS correction applied."""

    arrays = record.arrays
    cnt = _telemetry(arrays["cnt"])
    trash = _telemetry(arrays["trash"]) if "trash" in arrays else None
    event = _telemetry(arrays["event"]) if "event" in arrays else None
    if record_type == 0x40:
        cnt = np.transpose(_nansum_keep_missing(cnt, axis=2))[
            :, :, None
        ]  # (pol, ene, mass) -> (ene, pol, 1)
    elif record_type == 0x43:
        cnt = _nansum_keep_missing(cnt, axis=0)
        trash = None if trash is None else np.nansum(trash, axis=0)
    if sensor == "IMA" and event is not None:
        event = event[1] + event[2] + event[3]  # TOF events; row 0 counts position events
    elif event is not None:
        event = np.squeeze(event)
    if correction == "none":
        return cnt
    if record_type == 0x40:  # no trash telemetry; SPEDAS applies the event step only
        correction = "event" if correction in {"event", "event_trash"} else "none"
        if correction == "none":
            return cnt
    factor = pace_count_correction_factor(cnt, trash=trash, event=event, correction=correction)
    return np.asarray(cnt * factor)
