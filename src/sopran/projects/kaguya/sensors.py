from __future__ import annotations

SENSOR_ALIASES = {
    0: "ESA1",
    1: "ESA2",
    2: "IMA",
    3: "IEA",
    4: "LMAG",
    "0": "ESA1",
    "1": "ESA2",
    "2": "IMA",
    "3": "IEA",
    "4": "LMAG",
    "ESA1": "ESA1",
    "ESA-S1": "ESA1",
    "ESAS1": "ESA1",
    "ESA2": "ESA2",
    "ESA-S2": "ESA2",
    "ESAS2": "ESA2",
    "IMA": "IMA",
    "IEA": "IEA",
    "LMAG": "LMAG",
    "MAG": "LMAG",
}


def normalize_sensor(sensor: object) -> str:
    key = sensor if isinstance(sensor, int) else str(sensor).upper().replace("_", "-")
    try:
        return SENSOR_ALIASES[key]
    except KeyError as exc:
        raise ValueError(f"Unknown KAGUYA sensor: {sensor!r}") from exc


def normalize_sensors(sensors: object | None) -> list[str]:
    if sensors is None:
        sensors = ["ESA1", "ESA2", "IMA", "IEA", "LMAG"]
    if isinstance(sensors, str | int):
        sensors = [sensors]
    normalized: list[str] = []
    for sensor in sensors:
        name = normalize_sensor(sensor)
        if name not in normalized:
            normalized.append(name)
    return normalized
