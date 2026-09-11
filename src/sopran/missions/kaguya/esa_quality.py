"""ESA look-distribution eligibility, not an ion-instrument calibration mask.

Sources: PACE ``paceql_outputdata_090805.h`` and SPEDAS
``kgy_esa{1,2}_get3d.pro``. See the ESA mode policy documentation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ESA_PITCH_RECORD_POLICY = "esa_look_quality_v2"
PACE_ION_CHECK_MODES = frozenset((0x11, 0x12))
PACE_STANDARD_COMMANDS = frozenset(
    (
        0x01,
        0x02,
        0x11,
        0x12,
        0x13,
        0x14,
        0x24,
        0x15,
        0x25,
        0x16,
        0x26,
        0x17,
        0x18,
        0x19,
        0x29,
        0x1A,
        0x2A,
        0x1B,
    )
)


def esa_pitch_rejection_reason(header: Mapping[str, Any], *, data_type: int) -> str | None:
    """Return the reason a header cannot enter detector-look pitch analysis.

    Missing optional mode metadata is allowed for manually constructed input.
    An unknown command is unvalidated, not evidence that its counts are bad.
    ``data_quality`` is retained but not decoded: its bit meanings have not
    been established from the public format description.
    """
    mode = header.get("mode")
    if mode is not None:
        mode = int(mode)
        if mode & 0x80:
            return "internal_count_mode"
        if mode not in PACE_STANDARD_COMMANDS:
            return "unvalidated_command"
    if data_type == 0x02:
        return "onboard_pitch_sorted_not_supported"
    if data_type not in (0x00, 0x01):
        return "unsupported_esa_look_type"
    # SPEDAS marks precisely this combination invalid for both ESA sensors.
    if mode == 0x29 and data_type == 0x01 and header.get("svs_tbl") == 0:
        return "spedas_mode29_type1_ram0_invalid"
    return None
