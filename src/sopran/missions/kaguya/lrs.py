from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np

from sopran.core.data import (
    DEFAULT_MAX_POLARS_ROWS,
    PolarsLayout,
    SopranArray,
    _data_array_to_array_polars,
    _data_array_to_long_polars,
    ensure_polars_row_limit,
)
from sopran.core.pages import InfoPage
from sopran.core.store import DatasetRecord, Store
from sopran.core.time import TimeRange
from sopran.missions.kaguya.schema import KAGUYA_LRS_SCHEMA

LRS_KINDS = ("NPW", "WFC")
LRS_NPW_VARIABLES = ("npw_rx1", "npw_rx2", "npw_mode")
LRS_WFC_VARIABLES = (
    "wfc_ex_db",
    "wfc_ey_db",
    "wfc_gain",
    "wfc_ex_field",
    "wfc_ey_field",
    "wfc_ex_power_spectral_density",
    "wfc_ey_power_spectral_density",
    "wfc_xymode",
    "wfc_fband",
    "wfc_omode",
    "wfc_pdc_ti",
    "wfc_postgap",
)


@dataclass(frozen=True)
class KaguyaLrsData:
    arrays: dict[str, Any]
    time: TimeRange
    files: tuple[Path, ...] = ()
    instrument: str = "LRS"
    missing_reason: str | None = None

    def info(self) -> InfoPage:
        variables = ", ".join(self.arrays)
        lines = [
            f"time: {self.time.start_iso} to {self.time.stop_iso}",
            f"variables: {variables}",
            f"files: {len(self.files)}",
        ]
        if self.missing_reason is not None:
            lines.append(f"missing_reason: {self.missing_reason}")
        return InfoPage(title="KAGUYA.LRS", lines=tuple(lines))

    def __getattr__(self, name: str) -> SopranArray:
        if name.startswith("__"):
            raise AttributeError(name)
        try:
            return self.array(name)
        except KeyError as exc:
            raise AttributeError(name) from exc

    def array(self, name: str) -> SopranArray:
        schema = KAGUYA_LRS_SCHEMA.variable(name)
        if schema.name not in self.arrays:
            raise KeyError(schema.name)
        array = self.arrays[schema.name]
        attrs = _schema_attrs(schema)
        attrs.update(array.attrs)
        array = array.assign_attrs(attrs)
        return SopranArray(
            name=schema.name,
            time=self.time,
            schema=schema,
            files=self.files,
            xr=array,
        )

    @cached_property
    def npw_rx1(self) -> SopranArray:
        return self.array("npw_rx1")

    @cached_property
    def npw_rx2(self) -> SopranArray:
        return self.array("npw_rx2")

    @cached_property
    def npw_mode(self) -> SopranArray:
        return self.array("npw_mode")

    @cached_property
    def wfc_ex_db(self) -> SopranArray:
        return self.array("wfc_ex_db")

    @cached_property
    def wfc_ey_db(self) -> SopranArray:
        return self.array("wfc_ey_db")

    @cached_property
    def wfc_gain(self) -> SopranArray:
        return self.array("wfc_gain")

    @cached_property
    def wfc_ex_field(self) -> SopranArray:
        return self.array("wfc_ex_field")

    @cached_property
    def wfc_ey_field(self) -> SopranArray:
        return self.array("wfc_ey_field")

    @cached_property
    def wfc_ex_power_spectral_density(self) -> SopranArray:
        return self.array("wfc_ex_power_spectral_density")

    @cached_property
    def wfc_ey_power_spectral_density(self) -> SopranArray:
        return self.array("wfc_ey_power_spectral_density")

    @cached_property
    def wfc_xymode(self) -> SopranArray:
        return self.array("wfc_xymode")

    @cached_property
    def wfc_fband(self) -> SopranArray:
        return self.array("wfc_fband")

    @cached_property
    def wfc_omode(self) -> SopranArray:
        return self.array("wfc_omode")

    @cached_property
    def wfc_pdc_ti(self) -> SopranArray:
        return self.array("wfc_pdc_ti")

    @cached_property
    def wfc_postgap(self) -> SopranArray:
        return self.array("wfc_postgap")

    @property
    def wfc_ex_power(self) -> SopranArray:
        return self.wfc_ex_power_spectral_density

    @property
    def wfc_ey_power(self) -> SopranArray:
        return self.wfc_ey_power_spectral_density

    def to_xarray(self) -> Any:
        import xarray as xr

        if not self.arrays:
            return _empty_dataset(self.time)
        try:
            dataset = xr.merge(tuple(self.arrays.values()), join="exact")
        except ValueError as exc:
            raise ValueError(
                "KAGUYA LRS variables use different coordinates; "
                "load one kind or access variables as SopranArray objects."
            ) from exc
        dataset.attrs.update(
            {
                "mission": "kaguya",
                "instrument": self.instrument,
                "start": self.time.start_iso,
                "stop": self.time.stop_iso,
            }
        )
        if self.missing_reason is not None:
            dataset.attrs["missing_reason"] = self.missing_reason
        return dataset

    def to_polars(
        self,
        variable: str,
        *,
        layout: PolarsLayout = "auto",
        max_rows: int | None = DEFAULT_MAX_POLARS_ROWS,
        allow_large: bool = False,
    ) -> Any:
        try:
            import polars as pl  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("polars is required for KaguyaLrsData.to_polars()") from exc

        array = self.array(variable).to_xarray()
        values = np.asarray(array.values)
        resolved_layout = "array" if layout == "auto" and values.ndim >= 3 else layout
        if resolved_layout == "auto":
            resolved_layout = "long"
        if resolved_layout == "array":
            return _data_array_to_array_polars(array, variable, np, pl)
        if resolved_layout != "long":
            raise ValueError("layout must be 'auto', 'array', or 'long'")
        ensure_polars_row_limit(
            values.size,
            name=f"KAGUYA LRS {variable}",
            max_rows=max_rows,
            allow_large=allow_large,
        )
        return _data_array_to_long_polars(array, variable, np, pl)

    def write_parquet(
        self,
        store: Store,
        *,
        variable: str,
        dataset_id: str | None = None,
        layer: str = "normalized",
        shard_path: str = "shards/part-000.parquet",
        overwrite: bool = False,
        append: bool = False,
    ) -> DatasetRecord:
        return store.write_parquet_dataset(
            dataset_id=dataset_id or f"kaguya.lrs.{variable}",
            layer=layer,
            mission="kaguya",
            instrument="lrs",
            product=variable,
            schema=KAGUYA_LRS_SCHEMA,
            time_coverage=self.time,
            frame=self.to_polars(variable),
            source_files=tuple(str(path) for path in self.files),
            shard_path=shard_path,
            overwrite=overwrite,
            append=append,
        )


def read_lrs_public(
    files: str | Path | Iterable[str | Path],
    *,
    time: TimeRange | None = None,
    missing_reason: str | None = None,
) -> KaguyaLrsData:
    paths = _as_paths(files)
    if time is None:
        time = _time_from_files(paths)
    arrays: dict[str, list[Any]] = {}
    for path in paths:
        for name, array in _read_file_arrays(path).items():
            arrays.setdefault(name, []).append(_filter_time(array, time))
    merged = _merge_arrays(arrays, time=time)
    return KaguyaLrsData(
        arrays=merged,
        files=tuple(paths),
        time=time,
        missing_reason=missing_reason,
    )


def empty_lrs_data(
    time: TimeRange,
    *,
    kind: str = "all",
    files: tuple[Path, ...] = (),
    missing_reason: str | None = None,
) -> KaguyaLrsData:
    return KaguyaLrsData(
        arrays={
            name: _empty_array(name, time)
            for name in lrs_variables_for_kind(kind)
        },
        time=time,
        files=files,
        missing_reason=missing_reason,
    )


def lrs_array_from_polars(
    frame: Any,
    *,
    schema: Any,
    time_range: TimeRange,
    files: tuple[Path, ...] = (),
    coordinates: dict[str, Any] | None = None,
    attrs: dict[str, Any] | None = None,
) -> SopranArray:
    import xarray as xr

    pandas = frame.to_pandas().sort_values("time")
    array_attrs = _schema_attrs(schema)
    array_attrs.update(attrs or {})
    if pandas.empty:
        array = _empty_cached_array(
            schema,
            time_range,
            coordinates=coordinates or {},
        ).assign_attrs(array_attrs)
        return SopranArray(
            name=schema.name,
            time=time_range,
            schema=schema,
            files=files,
            xr=array,
        )

    if schema.dims == ("time",):
        array = xr.DataArray(
            pandas[schema.name].to_numpy(),
            dims=("time",),
            coords={"time": pandas["time"].to_numpy(dtype="datetime64[ns]")},
            name=schema.name,
            attrs=array_attrs,
        )
    elif schema.dims == ("time", "frequency"):
        array = _spectral_array_from_polars(
            pandas,
            name=schema.name,
            attrs=array_attrs,
            coordinates=coordinates or {},
        )
    else:
        raise ValueError(f"Unsupported cached KAGUYA LRS dims: {schema.dims}")
    return SopranArray(
        name=schema.name,
        time=time_range,
        schema=schema,
        files=files,
        xr=array,
    )


def lrs_variables_for_kind(kind: str) -> tuple[str, ...]:
    normalized = _normalize_kind(kind)
    if normalized == "NPW":
        return LRS_NPW_VARIABLES
    if normalized == "WFC":
        return LRS_WFC_VARIABLES
    return (*LRS_NPW_VARIABLES, *LRS_WFC_VARIABLES)


def lrs_kind_for_variable(variable: str) -> str:
    name = KAGUYA_LRS_SCHEMA.variable(variable).name
    if name.startswith("npw_"):
        return "NPW"
    if name.startswith("wfc_"):
        return "WFC"
    raise KeyError(variable)


def _read_file_arrays(path: Path) -> dict[str, Any]:
    try:
        import cdflib
    except ImportError as exc:
        raise RuntimeError("cdflib is required to read KAGUYA LRS CDF files") from exc

    cdf = cdflib.CDF(str(path))
    try:
        name = path.name.upper()
        if "NPW" in name:
            return _read_npw(cdf)
        if "WFC" in name:
            return _read_wfc(cdf)
        raise ValueError(f"Cannot determine KAGUYA LRS file type from {path}")
    finally:
        close = getattr(cdf, "close", None)
        if callable(close):
            close()


def _read_npw(cdf: Any) -> dict[str, Any]:
    import xarray as xr

    times = _times(cdf)
    frequency = np.asarray(cdf.varget("Frequency"), dtype=float)
    frequency_units = _frequency_units(cdf)
    arrays = {}
    for source, name in (("RX1", "npw_rx1"), ("RX2", "npw_rx2")):
        data = _var(cdf, source)
        if data is None:
            continue
        values = _time_first(_fill_to_nan(data, _attrs(cdf, source)), len(times))
        arrays[name] = xr.DataArray(
            values,
            dims=("time", "frequency"),
            coords={
                "time": _times_for_data(times, values),
                "frequency": ("frequency", frequency, {"units": frequency_units}),
            },
            name=name,
            attrs={
                **_schema_attrs(KAGUYA_LRS_SCHEMA.variable(name)),
                "source_variable": source,
            },
        )
    mode = _var(cdf, "Mode")
    if mode is not None:
        values = _fill_to_nan(mode, _attrs(cdf, "Mode"))
        arrays["npw_mode"] = xr.DataArray(
            values,
            dims=("time",),
            coords={"time": _times_for_data(times, values)},
            name="npw_mode",
            attrs={
                **_schema_attrs(KAGUYA_LRS_SCHEMA.variable("npw_mode")),
                "source_variable": "Mode",
            },
        )
    return arrays


def _read_wfc(cdf: Any) -> dict[str, Any]:
    import xarray as xr

    times = _times(cdf)
    frequency = np.asarray(cdf.varget("Frequency"), dtype=float)
    frequency_units = _frequency_units(cdf)
    frequency_coord = ("frequency", frequency, {"units": frequency_units})
    arrays = {}

    gain_raw = _var(cdf, "Gain")
    gain = None
    if gain_raw is not None:
        gain = _wfc_gain(gain_raw, fill=_fill_value(_attrs(cdf, "Gain")))
        arrays["wfc_gain"] = xr.DataArray(
            gain,
            dims=("time",),
            coords={"time": _times_for_data(times, gain)},
            name="wfc_gain",
            attrs={
                **_schema_attrs(KAGUYA_LRS_SCHEMA.variable("wfc_gain")),
                "source_variable": "Gain",
            },
        )

    dfreq = _wfc_dfreq(frequency)
    for source, db_name, field_name, power_name in (
        (
            "Ex",
            "wfc_ex_db",
            "wfc_ex_field",
            "wfc_ex_power_spectral_density",
        ),
        (
            "Ey",
            "wfc_ey_db",
            "wfc_ey_field",
            "wfc_ey_power_spectral_density",
        ),
    ):
        data = _var(cdf, source)
        if data is None:
            continue
        raw_db = _time_first(_fill_to_nan(data, _attrs(cdf, source)), len(times))
        var_times = _times_for_data(times, raw_db)
        arrays[db_name] = xr.DataArray(
            raw_db,
            dims=("time", "frequency"),
            coords={"time": var_times, "frequency": frequency_coord},
            name=db_name,
            attrs={
                **_schema_attrs(KAGUYA_LRS_SCHEMA.variable(db_name)),
                "source_variable": source,
            },
        )

        if gain is None or gain.shape[0] < raw_db.shape[0]:
            continue
        var_gain = gain[: raw_db.shape[0]]
        field = raw_db - var_gain.reshape(-1, 1) - 15.5
        field[:, : min(128, field.shape[1])] += 20.0
        if field.shape[1] > 128:
            field[:, 128:] += 10.0
        arrays[field_name] = xr.DataArray(
            field,
            dims=("time", "frequency"),
            coords={"time": var_times, "frequency": frequency_coord},
            name=field_name,
            attrs={
                **_schema_attrs(KAGUYA_LRS_SCHEMA.variable(field_name)),
                "source_variable": source,
            },
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            power = 10.0 ** (field / 10.0 - 12.0) / dfreq.reshape(1, -1)
        arrays[power_name] = xr.DataArray(
            power,
            dims=("time", "frequency"),
            coords={"time": var_times, "frequency": frequency_coord},
            name=power_name,
            attrs={
                **_schema_attrs(KAGUYA_LRS_SCHEMA.variable(power_name)),
                "source_variable": source,
                "dfreq_hz": dfreq.astype(float).tolist(),
            },
        )

    mode = _var(cdf, "Mode")
    if mode is not None:
        mode_values = np.asarray(mode)
        fill = _fill_value(_attrs(cdf, "Mode"))
        fill_mask = (
            mode_values == fill
            if fill is not None
            else np.zeros(mode_values.shape, dtype=bool)
        )
        mode_int = mode_values.astype(np.int64, copy=False)
        for name, values in {
            "wfc_xymode": (mode_int & 3).astype(float),
            "wfc_fband": ((mode_int & 12) >> 2).astype(float),
            "wfc_omode": ((mode_int & 48) >> 4).astype(float),
        }.items():
            values[fill_mask] = np.nan
            arrays[name] = xr.DataArray(
                values,
                dims=("time",),
                coords={"time": _times_for_data(times, values)},
                name=name,
                attrs=_schema_attrs(KAGUYA_LRS_SCHEMA.variable(name)),
            )

    for source, name in (("PDC-TI", "wfc_pdc_ti"), ("PostGap", "wfc_postgap")):
        data = _var(cdf, source)
        if data is None:
            continue
        values = _fill_to_nan(data, _attrs(cdf, source))
        arrays[name] = xr.DataArray(
            values,
            dims=("time",),
            coords={"time": _times_for_data(times, values)},
            name=name,
            attrs={
                **_schema_attrs(KAGUYA_LRS_SCHEMA.variable(name)),
                "source_variable": source,
            },
        )
    return arrays


def _as_paths(files: str | Path | Iterable[str | Path]) -> list[Path]:
    if isinstance(files, str | Path):
        return [Path(files)]
    return [Path(file) for file in files]


def _time_from_files(paths: list[Path]) -> TimeRange:
    if not paths:
        raise ValueError("time is required when no LRS files are provided")
    arrays: list[np.ndarray] = []
    for path in paths:
        try:
            import cdflib
        except ImportError as exc:
            raise RuntimeError("cdflib is required to read KAGUYA LRS CDF files") from exc
        cdf = cdflib.CDF(str(path))
        try:
            arrays.append(_times(cdf))
        finally:
            close = getattr(cdf, "close", None)
            if callable(close):
                close()
    if not arrays:
        raise ValueError("time is required when no LRS epoch values are available")
    all_times = np.concatenate(arrays)
    if all_times.size == 0:
        raise ValueError("time is required when no LRS epoch values are available")
    start = _datetime_from_datetime64(all_times.min())
    stop = _datetime_from_datetime64(all_times.max() + np.timedelta64(1, "ns"))
    return TimeRange(start, stop)


def _var(cdf: Any, name: str) -> Any | None:
    try:
        return cdf.varget(name)
    except Exception:
        return None


def _attrs(cdf: Any, name: str) -> dict[str, Any]:
    try:
        return dict(cdf.varattsget(name))
    except Exception:
        return {}


def _times(cdf: Any) -> np.ndarray:
    from cdflib import cdfepoch

    epoch = cdf.varget("Epoch")
    return np.asarray(cdfepoch.to_datetime(epoch), dtype="datetime64[ns]")


def _time_first(data: Any, nt: int) -> np.ndarray:
    array = np.asarray(data)
    if array.ndim >= 2 and array.shape[0] != nt and array.shape[-1] == nt:
        array = np.moveaxis(array, -1, 0)
    return array


def _times_for_data(times: np.ndarray, data: np.ndarray) -> np.ndarray:
    values = np.asarray(data)
    if values.ndim > 0 and values.shape[0] != times.shape[0]:
        return times[: values.shape[0]]
    return times


def _fill_to_nan(data: Any, attrs: dict[str, Any]) -> np.ndarray:
    array = np.asarray(data)
    if not np.issubdtype(array.dtype, np.number):
        return array
    output = array.astype(float, copy=True)
    fill = _fill_value(attrs)
    if fill is not None:
        output[array == fill] = np.nan
    return output


def _fill_value(attrs: dict[str, Any]) -> object | None:
    return attrs.get("FILLVAL", attrs.get("fillval"))


def _frequency_units(cdf: Any) -> str:
    attrs = _attrs(cdf, "Frequency")
    return str(attrs.get("UNITS", attrs.get("units", "")))


def _wfc_gain(raw: Any, *, fill: object | None = None) -> np.ndarray:
    raw_values = np.asarray(raw)
    gain_code = ((raw_values.astype(np.int64) & 12) >> 2).astype(float)
    gain = np.full(gain_code.shape, np.nan, dtype=float)
    gain[gain_code == 0] = 40.0
    gain[(gain_code == 1) | (gain_code == 2)] = 20.0
    gain[gain_code == 3] = 0.0
    if fill is not None:
        gain[raw_values == fill] = np.nan
    return gain


def _wfc_dfreq(frequency: Any) -> np.ndarray:
    freq = np.asarray(frequency, dtype=float)
    dfreq = np.zeros_like(freq)
    if freq.size > 1:
        dfreq[: min(128, freq.size)] = freq[1] - freq[0]
    for low, high in (
        (9.77, 78.13),
        (78.13, 117.19),
        (117.19, 156.25),
        (156.27, np.inf),
    ):
        mask = (freq > low) & (freq <= high)
        if np.any(mask):
            selected = freq[mask]
            if selected.size > 1:
                dfreq[mask] = np.median(np.diff(selected))
    return dfreq * 1e3


def _merge_arrays(arrays: dict[str, list[Any]], *, time: TimeRange) -> dict[str, Any]:
    import xarray as xr

    if not arrays:
        return {}
    data_vars = {}
    for name, items in arrays.items():
        filtered = [item for item in items if item.size > 0]
        if not filtered:
            data_vars[name] = items[0] if items else _empty_array(name, time)
            continue
        data_vars[name] = xr.concat(filtered, dim="time").sortby("time")
    return data_vars


def _filter_time(array: Any, time: TimeRange) -> Any:
    if "time" not in getattr(array, "dims", ()):
        return array
    values = np.asarray(array.coords["time"].values, dtype="datetime64[ns]")
    start = _datetime64(time.start)
    stop = _datetime64(time.stop)
    return array.isel(time=(values >= start) & (values < stop))


def _empty_dataset(time: TimeRange) -> Any:
    import xarray as xr

    return xr.Dataset(
        {
            variable.name: _empty_array(variable.name, time)
            for variable in KAGUYA_LRS_SCHEMA.variables
        },
        attrs={
            "mission": "kaguya",
            "instrument": "LRS",
            "start": time.start_iso,
            "stop": time.stop_iso,
        },
    )


def _empty_array(name: str, time: TimeRange) -> Any:
    import xarray as xr

    schema = KAGUYA_LRS_SCHEMA.variable(name)
    shape = tuple(0 for _ in schema.dims)
    coords: dict[str, Any] = {}
    if "time" in schema.dims:
        coords["time"] = np.asarray([], dtype="datetime64[ns]")
    if "frequency" in schema.dims:
        coords["frequency"] = ("frequency", np.asarray([], dtype=float), {"units": ""})
    return xr.DataArray(
        np.empty(shape, dtype=float),
        dims=schema.dims,
        coords=coords,
        name=schema.name,
        attrs=_schema_attrs(schema),
    )


def _empty_cached_array(
    schema: Any,
    time: TimeRange,
    *,
    coordinates: dict[str, Any],
) -> Any:
    import xarray as xr

    if schema.dims != ("time", "frequency"):
        return _empty_array(schema.name, time)
    frequency = np.asarray(coordinates.get("frequency", ()), dtype=float)
    frequency_attrs = {}
    frequency_units = coordinates.get("frequency_units")
    if frequency_units is not None:
        frequency_attrs["units"] = str(frequency_units)
    return xr.DataArray(
        np.empty((0, frequency.size), dtype=float),
        dims=("time", "frequency"),
        coords={
            "time": np.asarray([], dtype="datetime64[ns]"),
            "frequency": ("frequency", frequency, frequency_attrs),
        },
        name=schema.name,
        attrs=_schema_attrs(schema),
    )


def _spectral_array_from_polars(
    pandas: Any,
    *,
    name: str,
    attrs: dict[str, Any],
    coordinates: dict[str, Any],
) -> Any:
    import xarray as xr

    frequency_attrs = {}
    frequency_units = coordinates.get("frequency_units")
    if frequency_units is not None:
        frequency_attrs["units"] = str(frequency_units)

    if "frequency" in pandas.columns:
        pivoted = pandas.pivot(index="time", columns="frequency", values=name)
        pivoted = pivoted.sort_index(axis=0).sort_index(axis=1)
        frequency = pivoted.columns.to_numpy(dtype=float)
        values = pivoted.to_numpy()
        time_values = pivoted.index.to_numpy(dtype="datetime64[ns]")
    else:
        rows = [np.asarray(item, dtype=float).reshape(-1) for item in pandas[name]]
        values = np.vstack(rows) if rows else np.empty((0, 0), dtype=float)
        time_values = pandas["time"].to_numpy(dtype="datetime64[ns]")
        frequency = np.asarray(coordinates.get("frequency", ()), dtype=float)
        if frequency.size != values.shape[1]:
            frequency = np.arange(values.shape[1], dtype=float)

    return xr.DataArray(
        values,
        dims=("time", "frequency"),
        coords={
            "time": time_values,
            "frequency": ("frequency", frequency, frequency_attrs),
        },
        name=name,
        attrs=attrs,
    )


def _schema_attrs(schema: Any) -> dict[str, object]:
    attrs: dict[str, object] = {"description": schema.description}
    if schema.units is not None:
        attrs["units"] = schema.units
    if schema.frame is not None:
        attrs["frame"] = schema.frame
    return attrs


def _normalize_kind(kind: str) -> str:
    normalized = kind.upper()
    if normalized not in {"NPW", "WFC", "ALL"}:
        raise ValueError("kind must be 'NPW', 'WFC', or 'all'")
    return normalized


def _datetime64(value: Any) -> np.datetime64:
    return np.datetime64(value.replace(tzinfo=None), "ns")


def _datetime_from_datetime64(value: np.datetime64) -> Any:
    import pandas as pd

    return pd.Timestamp(value).tz_localize("UTC").to_pydatetime()
