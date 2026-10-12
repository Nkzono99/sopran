"""Model-dependent magnetic connection of spacecraft records to the lunar surface.

Each record is traced through ``B_SVM3D`` plus a spatially uniform residual that
reproduces the measured field at the spacecraft (``svm3d_native_connection_v1``
of the Halekas mission runner). The inward branch follows the field toward the
Moon and must reach the lower shell; the reverse branch must not. A failed
reverse trace is not evidence of an open field line, and reaching the shell is
not proof of a surface connection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike

from sopran.experimental.moon.svm3d import SVM3DShellGrid, SVM3DTraceSettings

CONNECTION_STATUSES = (
    "trace_input_invalid",
    "inward_not_reached",
    "both_branches_connected",
    "side_changed",
    "model_connected",
    "no_usable_geometry",
)


@dataclass(frozen=True)
class ConnectionPolicy:
    """Tracing settings; the defaults are those of the 2026-09 mission run."""

    name: str = "svm3d_native_connection_v1"
    step_km: float = 0.5
    stop_altitude_km: float = 6.1
    maximum_path_km: float = 1000.0

    def trace_settings(self) -> SVM3DTraceSettings:
        return SVM3DTraceSettings(
            step_km=self.step_km,
            max_steps=round(self.maximum_path_km / self.step_km),
            stop_altitude_km=self.stop_altitude_km,
        )

    def metadata(self) -> dict[str, Any]:
        return dict(
            name=self.name,
            field="SVM3D plus spatially uniform residual matched to native LMAG",
            step_km=self.step_km,
            stop_altitude_km=self.stop_altitude_km,
            maximum_path_km=self.maximum_path_km,
            selection=(
                "All usable native records: inward reaches lower shell, reverse does not; "
                "stable sign"
            ),
            surface_connection_proven=False,
            reverse_failure_proves_open_field=False,
        )


def trace_connection(
    shell: SVM3DShellGrid,
    positions_km: ArrayLike,
    magnetic_field_nT: ArrayLike,
    *,
    policy: ConnectionPolicy | None = None,
) -> pd.DataFrame:
    """Trace both branches for every record (MOON_ME km and nT, one row each).

    Returns ``trace_input_valid``, the ``inward_*`` and ``reverse_*`` columns of
    :meth:`SVM3DShellGrid.trace` (NaN where the input was invalid) and
    ``record_connected`` (inward reached, reverse not, input valid).
    """

    selected = policy or ConnectionPolicy()
    positions = np.asarray(positions_km, dtype=float).reshape(-1, 3)
    magnetic = np.asarray(magnetic_field_nT, dtype=float).reshape(-1, 3)
    if positions.shape != magnetic.shape:
        raise ValueError("positions_km and magnetic_field_nT must have the same shape")
    external = shell.residual_external_field(positions, magnetic)
    # Inward follows -sign(r.B) along B, i.e. toward the Moon.
    signs = -np.sign(np.sum(positions * magnetic, axis=1))
    good = (
        np.isfinite(positions).all(axis=1)
        & np.isfinite(external).all(axis=1)
        & (np.abs(signs) == 1)
    )
    rows = range(len(positions))
    parts = []
    for name, direction in (("inward", 1), ("reverse", -1)):
        result = shell.trace(
            positions[good],
            external[good],
            signs[good] * direction,
            settings=selected.trace_settings(),
        )
        part = result.to_pandas(prefix=name)
        part.index = np.flatnonzero(good)
        parts.append(part.reindex(rows))
    out = pd.concat(parts, axis=1)
    out["trace_input_valid"] = good
    out["record_connected"] = (
        out.inward_valid.fillna(False).astype(bool)
        & ~out.reverse_valid.fillna(False).astype(bool)
        & good
    )
    return out


def classify_connection(
    traces: pd.DataFrame,
    window_ids: ArrayLike,
    *,
    policy: ConnectionPolicy | None = None,
) -> dict[int, dict[str, Any]]:
    """Connection status per window from the traces of its records.

    Order of checks: any invalid trace input, any inward branch that does not
    reach the shell, any reverse branch that does, an inward sign that changes
    within the window; otherwise ``model_connected``.
    """

    selected = policy or ConnectionPolicy()
    ids = np.asarray(window_ids)
    if ids.shape != (len(traces),):
        raise ValueError("window_ids must give one window per trace row")
    result: dict[int, dict[str, Any]] = {}
    frame = traces.assign(window_id=ids)
    for window_id, group in frame.groupby("window_id", sort=False):
        inward = group.inward_valid.fillna(False).astype(bool)
        reverse = group.reverse_valid.fillna(False).astype(bool)
        stable = bool(group.inward_connection_sign.nunique() == 1)
        if not group.trace_input_valid.all():
            status = "trace_input_invalid"
        elif not inward.all():
            status = "inward_not_reached"
        elif reverse.any():
            status = "both_branches_connected"
        elif not stable:
            status = "side_changed"
        else:
            status = "model_connected"
        result[int(cast(int, window_id))] = dict(
            field_connection_status=status,
            connection_eligible=status == "model_connected",
            connection_records=len(group),
            inward_connected_records=int(inward.sum()),
            reverse_connected_records=int(reverse.sum()),
            connection_side_stable=stable,
            connection_stop_altitude_km=selected.stop_altitude_km,
        )
    return result


def unconnected_window(status: str = "no_usable_geometry") -> Mapping[str, Any]:
    """Connection fields for a window without traced records."""

    return dict(field_connection_status=status, connection_eligible=False, connection_records=0)


__all__ = [
    "CONNECTION_STATUSES",
    "ConnectionPolicy",
    "classify_connection",
    "trace_connection",
    "unconnected_window",
]
