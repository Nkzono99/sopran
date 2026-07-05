from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import Any, Literal, SupportsFloat

from sopran.core.data import (
    DEFAULT_MAX_POLARS_ROWS,
    PolarsLayout,
    SopranArray,
    _data_array_to_array_polars,
    ensure_polars_row_limit,
)
from sopran.core.pages import InfoPage
from sopran.core.store import DatasetRecord, Store
from sopran.core.time import TimeRange
from sopran.missions.kaguya.pace import (
    PaceCalibration,
    PaceData,
    pace_count_energy_look,
    read_pace_pbf,
)
from sopran.missions.kaguya.pitch import PitchAngleSpectrumOptions, build_pitch_angle_spectrum
from sopran.missions.kaguya.schema import kaguya_pace_schema


@dataclass(frozen=True)
class KaguyaPaceData:
    time: TimeRange
    files: tuple[Path, ...] = ()
    instrument: str = "ESA1"
    calibration: PaceCalibration | None = None
    missing_reason: str | None = None

    @cached_property
    def instrument_schema(self) -> Any:
        return kaguya_pace_schema(self.instrument)

    def info(self) -> InfoPage:
        lines = [
            f"time: {self.time.start_iso} to {self.time.stop_iso}",
            "variables: energy_flux, counts, energy, quality",
            f"files: {len(self.files)}",
            _calibration_info_line(self.calibration, self.instrument),
        ]
        if self.missing_reason is not None:
            lines.append(f"missing_reason: {self.missing_reason}")
        return InfoPage(
            title=f"KAGUYA.{self.instrument}",
            lines=tuple(lines),
        )

    @cached_property
    def energy_flux(self) -> SopranArray:
        return SopranArray(
            name="energy_flux",
            time=self.time,
            schema=self.instrument_schema.variable("energy_flux"),
            files=self.files,
            xr=self.to_xarray()["energy_flux"],
        )

    @property
    def eflux(self) -> SopranArray:
        return self.energy_flux

    @cached_property
    def counts(self) -> SopranArray:
        return SopranArray(
            name="counts",
            time=self.time,
            schema=self.instrument_schema.variable("counts"),
            files=self.files,
            xr=self.to_xarray()["counts"],
        )

    @cached_property
    def energy(self) -> SopranArray:
        return SopranArray(
            name="energy",
            time=self.time,
            schema=self.instrument_schema.variable("energy"),
            files=self.files,
            xr=self.to_xarray()["energy"],
        )

    @cached_property
    def quality(self) -> SopranArray:
        return SopranArray(
            name="quality",
            time=self.time,
            schema=self.instrument_schema.variable("quality"),
            files=self.files,
            xr=self.to_xarray()["quality"],
        )

    @cached_property
    def pace(self) -> PaceData | None:
        if not self.files:
            return None
        return read_pace_pbf(self.files)

    def to_xarray(self) -> Any:
        try:
            import numpy as np
            import xarray as xr
        except ImportError as exc:
            raise RuntimeError("xarray is required for to_xarray()") from exc

        if self.pace is not None:
            return self._pace_to_xarray(np, xr, self.pace)

        return self._empty_xarray(np, xr)

    def to_polars(
        self,
        variable: str = "counts",
        *,
        reduce_look: Literal["sum"] | None = None,
        layout: PolarsLayout = "auto",
        max_rows: int | None = DEFAULT_MAX_POLARS_ROWS,
        allow_large: bool = False,
    ) -> Any:
        try:
            import numpy as np
            import polars as pl
        except ImportError as exc:
            raise RuntimeError("polars is required for to_polars()") from exc

        if reduce_look not in (None, "sum"):
            raise ValueError("reduce_look must be None or 'sum'")
        if layout not in ("auto", "array", "long"):
            raise ValueError("layout must be 'auto', 'array', or 'long'")

        pace = self.pace
        if (
            reduce_look == "sum"
            and variable == "counts"
            and pace is not None
            and layout in ("auto", "long")
        ):
            return _pace_counts_sum_look_to_polars(
                pace,
                self.time,
                variable,
                np,
                pl,
                max_rows=max_rows,
                allow_large=allow_large,
            )
        if (
            reduce_look is None
            and variable == "counts"
            and pace is not None
            and layout == "long"
        ):
            ensure_polars_row_limit(
                _pace_counts_padded_row_count(pace, self.time),
                name=f"KAGUYA {self.instrument} {variable}",
                max_rows=max_rows,
                allow_large=allow_large,
            )

        dataset = self.to_xarray()
        if variable not in dataset:
            raise KeyError(f"Unknown variable for KAGUYA {self.instrument} data: {variable}")

        array = dataset[variable]
        if reduce_look == "sum":
            if "look" not in array.dims:
                raise ValueError(f"{variable} has no look dimension to reduce")
            array = array.sum("look")

        resolved_layout = _resolve_kaguya_polars_layout(array, layout, reduce_look=reduce_look)
        if resolved_layout == "array":
            return _data_array_to_array_polars(array, variable, np, pl)

        ensure_polars_row_limit(
            int(array.size),
            name=f"KAGUYA {self.instrument} {variable}",
            max_rows=max_rows,
            allow_large=allow_large,
        )
        return _data_array_to_polars(array, variable, np, pl)

    def to_pandas(
        self,
        variable: str = "counts",
        *,
        reduce_look: Literal["sum"] | None = None,
        layout: PolarsLayout = "auto",
        max_rows: int | None = DEFAULT_MAX_POLARS_ROWS,
        allow_large: bool = False,
    ) -> Any:
        return self.to_polars(
            variable,
            reduce_look=reduce_look,
            layout=layout,
            max_rows=max_rows,
            allow_large=allow_large,
        ).to_pandas()

    def pitch_angle_spectrum(
        self,
        magnetic_field: Any,
        *,
        value: str = "counts",
        pitch_bins: Any = "native",
        look_frame: str = "SELENE_M_SPACECRAFT",
        magnetic_frame: str | None = None,
        min_look_bins: int = 1,
        frame_context: Any | None = None,
    ) -> SopranArray:
        """Return PACE spectra binned by pitch angle.

        The result has dimensions ``time x energy x pitch_angle``. ``look`` is
        resolved through the PACE angle calibration tables, not treated as a
        physical direction by itself.
        """

        return build_pitch_angle_spectrum(
            pace=self.pace,
            time=self.time,
            calibration=self.calibration,
            magnetic_field=magnetic_field,
            files=self.files,
            options=PitchAngleSpectrumOptions(
                value=value,
                pitch_bins=pitch_bins,
                look_frame=look_frame,
                magnetic_frame=magnetic_frame,
                min_look_bins=min_look_bins,
            ),
            frame_context=frame_context,
        )

    def pas(self, magnetic_field: Any, **kwargs: Any) -> SopranArray:
        return self.pitch_angle_spectrum(magnetic_field, **kwargs)

    def to_energy_flux(self, *, efficiency: float = 0.6) -> SopranArray:
        try:
            import numpy as np
            import xarray as xr
        except ImportError as exc:
            raise RuntimeError("xarray is required for to_energy_flux()") from exc

        return SopranArray(
            name="energy_flux",
            time=self.time,
            schema=self.instrument_schema.variable("energy_flux"),
            files=self.files,
            xr=self._energy_flux_array(np, xr, efficiency=efficiency, require=True),
        )

    def write_parquet(
        self,
        store: Store,
        *,
        variable: str = "counts",
        reduce_look: Literal["sum"] | None = None,
        dataset_id: str | None = None,
        layer: str = "normalized",
        shard_path: str = "shards/part-000.parquet",
        overwrite: bool = False,
        append: bool = False,
        partitioning: tuple[str, ...] = (),
        provenance: dict[str, Any] | None = None,
    ) -> DatasetRecord:
        product = variable
        return store.write_parquet_dataset(
            dataset_id=dataset_id or f"kaguya.{self.instrument.lower()}.{product}",
            layer=layer,
            mission="kaguya",
            instrument=self.instrument.lower(),
            product=product,
            schema=self.instrument_schema,
            time_coverage=self.time,
            frame=self.to_polars(variable, reduce_look=reduce_look, layout="long"),
            source_files=tuple(str(path) for path in self.files),
            shard_path=shard_path,
            overwrite=overwrite,
            append=append,
            partitioning=partitioning,
            provenance=provenance,
        )

    def _empty_xarray(self, np: Any, xr: Any) -> Any:
        energy_flux_schema = self.instrument_schema.variable("energy_flux")
        counts_schema = self.instrument_schema.variable("counts")
        energy_schema = self.instrument_schema.variable("energy")
        quality_schema = self.instrument_schema.variable("quality")
        calibration = _calibration_metadata(self.calibration, self.instrument)
        attrs = {
            "mission": "kaguya",
            "instrument": self.instrument,
            "start": self.time.start_iso,
            "stop": self.time.stop_iso,
            "calibration": calibration,
        }
        if self.missing_reason is not None:
            attrs["missing_reason"] = self.missing_reason
        return xr.Dataset(
            data_vars={
                "energy_flux": (
                    energy_flux_schema.dims,
                    np.empty((0, 0, 0)),
                    _energy_flux_attrs(energy_flux_schema, calibration),
                ),
                "counts": (
                    counts_schema.dims,
                    np.empty((0, 0, 0)),
                    {"units": counts_schema.units, "description": counts_schema.description},
                ),
                "quality": (
                    quality_schema.dims,
                    np.empty((0,)),
                    {"description": quality_schema.description},
                ),
            },
            coords={
                "time": [],
                "energy": ("energy", [], _variable_attrs(energy_schema)),
                "look": [],
            },
            attrs=attrs,
        )

    def _pace_to_xarray(self, np: Any, xr: Any, pace: PaceData) -> Any:
        energy_flux_schema = self.instrument_schema.variable("energy_flux")
        counts_schema = self.instrument_schema.variable("counts")
        energy_schema = self.instrument_schema.variable("energy")
        quality_schema = self.instrument_schema.variable("quality")
        calibration = _calibration_metadata(self.calibration, self.instrument)
        count_rows = []
        headers = []

        for record in pace.record_order:
            counts = record.arrays.get("cnt")
            if counts is None:
                continue
            header = pace.headers[record.index]
            if not _header_in_time_range(header, self.time):
                continue
            count_rows.append(_counts_to_energy_look(counts))
            headers.append(header)

        if not count_rows:
            return self._empty_xarray(np, xr)

        counts = _stack_energy_look_rows(count_rows, np)
        energy_flux = _energy_flux_from_rows(
            pace,
            headers,
            count_rows,
            self.calibration,
            self.instrument,
            np,
            efficiency=0.6,
        )
        energy_flux_attrs = _energy_flux_attrs(
            energy_flux_schema,
            calibration,
            applied=not np.isnan(energy_flux).all(),
            efficiency=0.6,
        )
        quality = np.array(
            [int(header.get("data_quality", 0)) for header in headers],
            dtype=np.uint32,
        )
        time_values = np.array(
            [_header_time_to_datetime64(header.get("time"), np) for header in headers],
            dtype="datetime64[ns]",
        )

        return xr.Dataset(
            data_vars={
                "energy_flux": (
                    energy_flux_schema.dims,
                    energy_flux,
                    energy_flux_attrs,
                ),
                "counts": (
                    counts_schema.dims,
                    counts,
                    {"units": counts_schema.units, "description": counts_schema.description},
                ),
                "quality": (
                    quality_schema.dims,
                    quality,
                    {"description": quality_schema.description},
                ),
            },
            coords={
                "time": time_values,
                "energy": (
                    "energy",
                    np.arange(counts.shape[1]),
                    _variable_attrs(energy_schema),
                ),
                "look": np.arange(counts.shape[2]),
            },
            attrs={
                "mission": "kaguya",
                "instrument": self.instrument,
                "sensor": pace.sensor_name,
                "raw_format": "PACE PBF",
                "source_files": [str(path) for path in self.files],
                "start": self.time.start_iso,
                "stop": self.time.stop_iso,
                "calibration": calibration,
            },
        )

    def _energy_flux_array(
        self,
        np: Any,
        xr: Any,
        *,
        efficiency: float,
        require: bool,
    ) -> Any:
        energy_flux_schema = self.instrument_schema.variable("energy_flux")
        calibration = _calibration_metadata(self.calibration, self.instrument)
        if self.pace is None:
            if require:
                raise ValueError(_missing_energy_flux_calibration_message(self.instrument))
            return self._empty_xarray(np, xr)["energy_flux"]

        count_rows = []
        headers = []
        for record in self.pace.record_order:
            counts = record.arrays.get("cnt")
            if counts is None:
                continue
            header = self.pace.headers[record.index]
            if not _header_in_time_range(header, self.time):
                continue
            count_rows.append(_counts_to_energy_look(counts))
            headers.append(header)

        if not count_rows:
            return self._empty_xarray(np, xr)["energy_flux"]

        values = _energy_flux_from_rows(
            self.pace,
            headers,
            count_rows,
            self.calibration,
            self.instrument,
            np,
            efficiency=efficiency,
        )
        if require and np.isnan(values).all():
            raise ValueError(_missing_energy_flux_calibration_message(self.instrument))
        time_values = np.array(
            [_header_time_to_datetime64(header.get("time"), np) for header in headers],
            dtype="datetime64[ns]",
        )
        return xr.DataArray(
            values,
            dims=energy_flux_schema.dims,
            coords={
                "time": time_values,
                "energy": np.arange(values.shape[1]),
                "look": np.arange(values.shape[2]),
            },
            attrs=_energy_flux_attrs(
                energy_flux_schema,
                calibration,
                applied=not np.isnan(values).all(),
                efficiency=efficiency,
            ),
        )


def _counts_to_energy_look(counts: Any) -> Any:
    out = pace_count_energy_look(counts).astype(float, copy=True)
    out[out == 65535] = float("nan")
    return out


def _stack_energy_look_rows(rows: list[Any], np: Any) -> Any:
    look_count = max(row.shape[1] for row in rows)
    if all(row.shape[1] == look_count for row in rows):
        return np.stack(rows)
    output = np.full((len(rows), 32, look_count), np.nan, dtype=float)
    for index, row in enumerate(rows):
        output[index, :, : row.shape[1]] = row
    return output


def _pace_counts_sum_look_to_polars(
    pace: PaceData,
    time: TimeRange,
    variable: str,
    np: Any,
    pl: Any,
    *,
    max_rows: int | None,
    allow_large: bool,
) -> Any:
    rows = []
    time_values = []
    for record in pace.record_order:
        counts = record.arrays.get("cnt")
        if counts is None:
            continue
        header = pace.headers[record.index]
        if not _header_in_time_range(header, time):
            continue
        energy_look = _counts_to_energy_look(counts)
        finite = np.isfinite(energy_look)
        row = np.nansum(energy_look, axis=1)
        row[~finite.any(axis=1)] = np.nan
        rows.append(row)
        time_values.append(_header_time_to_datetime64(header.get("time"), np))

    ensure_polars_row_limit(
        len(rows) * 32,
        name=f"KAGUYA PACE {variable}",
        max_rows=max_rows,
        allow_large=allow_large,
    )

    if not rows:
        return pl.DataFrame(
            {
                "time": np.array([], dtype="datetime64[ns]"),
                "energy": np.array([], dtype=np.int64),
                variable: np.array([], dtype=np.uint64),
            }
        )

    values = np.stack(rows)
    times = np.array(time_values, dtype="datetime64[ns]")
    energy = np.arange(values.shape[1])
    return pl.DataFrame(
        {
            "time": np.repeat(times, len(energy)),
            "energy": np.tile(energy, len(times)),
            variable: values.reshape(-1),
        }
    )


def _pace_counts_padded_row_count(pace: PaceData, time: TimeRange) -> int:
    records = []
    for record in pace.record_order:
        counts = record.arrays.get("cnt")
        if counts is None:
            continue
        header = pace.headers[record.index]
        if _header_in_time_range(header, time):
            records.append(counts)
    if not records:
        return 0
    look_count = max(int(_counts_to_energy_look(counts).shape[1]) for counts in records)
    return len(records) * 32 * look_count


def _resolve_kaguya_polars_layout(
    array: Any,
    layout: PolarsLayout,
    *,
    reduce_look: Literal["sum"] | None,
) -> Literal["array", "long"]:
    if layout == "auto":
        if reduce_look is None and len(tuple(array.dims)) >= 3:
            return "array"
        return "long"
    return layout


def _header_time_to_datetime64(value: object, np: Any) -> Any:
    if value is None:
        return np.datetime64("NaT", "ns")
    if not isinstance(value, (str, bytes, SupportsFloat)):
        raise TypeError(f"header time must be numeric, got {value!r}")
    text = datetime.fromtimestamp(float(value), tz=UTC).replace(tzinfo=None).isoformat()
    return np.datetime64(text, "ns")


def _header_in_time_range(header: dict[str, Any], time: TimeRange) -> bool:
    value = header.get("time")
    if value is None:
        return False
    instant = datetime.fromtimestamp(float(value), tz=UTC)
    return time.start <= instant < time.stop


def _calibration_info_line(calibration: PaceCalibration | None, instrument: str) -> str:
    metadata = _calibration_metadata(calibration, instrument)
    return (
        "calibration: "
        f"fov={metadata['fov']}, "
        f"info={metadata['info']}, "
        f"status={metadata['status']}"
    )


def _calibration_metadata(
    calibration: PaceCalibration | None,
    instrument: str,
) -> dict[str, object]:
    if calibration is None:
        return {"fov": False, "info": False, "status": "not_loaded"}
    coverage = calibration.coverage(instrument)
    has_any_table = bool(coverage["fov"] or coverage["info"])
    return {
        "fov": coverage["fov"],
        "info": coverage["info"],
        "status": "tables_loaded" if has_any_table else "not_loaded",
    }


def _variable_attrs(schema: Any) -> dict[str, object]:
    attrs: dict[str, object] = {"description": schema.description}
    if schema.units is not None:
        attrs["units"] = schema.units
    if schema.frame is not None:
        attrs["frame"] = schema.frame
    return attrs


def _energy_flux_attrs(
    schema: Any,
    calibration: dict[str, object],
    *,
    applied: bool = False,
    efficiency: float | None = None,
) -> dict[str, object]:
    status = "applied" if applied else calibration["status"]
    attrs = {
        **_variable_attrs(schema),
        "calibration": status,
        "calibration_status": status,
        "physical_validity": "calibrated" if applied else "placeholder",
    }
    if efficiency is not None:
        attrs["efficiency"] = efficiency
        attrs["formula"] = "counts / (integ_t * gfactor * efficiency)"
    return attrs


def _energy_flux_from_rows(
    pace: PaceData,
    headers: list[dict[str, Any]],
    count_rows: list[Any],
    calibration: PaceCalibration | None,
    instrument: str,
    np: Any,
    *,
    efficiency: float,
) -> Any:
    counts = _stack_energy_look_rows(count_rows, np)
    flux = np.full(counts.shape, np.nan, dtype=float)
    info = None
    if calibration is not None:
        sensor_id = _pace_sensor_id(instrument)
        info = calibration.info.get(sensor_id)
    if info is None:
        return flux

    for index, header in enumerate(headers):
        gfactor = _gfactor_energy_look(info, count_rows[index], header, np)
        if gfactor is None:
            continue
        sampl_time = float(header.get("sampl_time", 0.0))
        if sampl_time == 0:
            continue
        integ_t = 16.0 / sampl_time
        with np.errstate(divide="ignore", invalid="ignore"):
            value = count_rows[index] / (integ_t * gfactor * efficiency)
        valid = np.isfinite(gfactor) & (gfactor > 0)
        value[~valid] = np.nan
        flux[index, :, : value.shape[1]] = value
    return flux


def _gfactor_energy_look(
    info: dict[str, Any],
    counts: Any,
    header: dict[str, Any],
    np: Any,
) -> Any | None:
    look_count = int(counts.shape[1])
    if look_count == 64 and "gfactor_4x16" in info:
        key = "gfactor_4x16"
    elif look_count == 1024 and "gfactor_16x64" in info:
        key = "gfactor_16x64"
    else:
        return None
    table = info[key]
    ram = min(int(header.get("svs_tbl", 0)), int(table.shape[0]) - 1)
    return pace_count_energy_look(np.asarray(table[ram], dtype=float))


def _pace_sensor_id(instrument: str) -> int:
    return {"ESA1": 0, "ESA2": 1, "IMA": 2, "IEA": 3}[instrument.upper()]


def _missing_energy_flux_calibration_message(instrument: str) -> str:
    return (
        f"KAGUYA {instrument} energy_flux requires PACE INFO calibration tables. "
        "Load counts instead with kg.esa1.counts.load(time), or provide calibration "
        "with kg.esa1.energy_flux.load(time, calibration='auto')."
    )


def _data_array_to_polars(array: Any, variable: str, np: Any, pl: Any) -> Any:
    dims = tuple(array.dims)
    values = np.asarray(array.values)
    if dims == ("time", "energy"):
        times = np.asarray(array.coords["time"].values)
        energy = np.asarray(array.coords["energy"].values)
        return pl.DataFrame(
            {
                "time": np.repeat(times, len(energy)),
                "energy": np.tile(energy, len(times)),
                variable: values.reshape(-1),
            }
        )
    if dims == ("time", "energy", "look"):
        times = np.asarray(array.coords["time"].values)
        energy = np.asarray(array.coords["energy"].values)
        look = np.asarray(array.coords["look"].values)
        return pl.DataFrame(
            {
                "time": np.repeat(times, len(energy) * len(look)),
                "energy": np.tile(np.repeat(energy, len(look)), len(times)),
                "look": np.tile(look, len(times) * len(energy)),
                variable: values.reshape(-1),
            }
        )
    if dims == ("time",):
        return pl.DataFrame(
            {
                "time": np.asarray(array.coords["time"].values),
                variable: values.reshape(-1),
            }
        )
    raise NotImplementedError(f"Cannot convert {variable} with dims {dims} to Polars")


KaguyaESA1Data = KaguyaPaceData
