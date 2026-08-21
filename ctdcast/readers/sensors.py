"""Reader for the SBE sensor configuration embedded in a CNV header.

SeaBird ``.cnv`` files carry a ``<Sensors count="N">`` XML block (the applied
``.xmlcon``) in their ``#``-prefixed header, one entry per acquisition channel
with the sensor type and its serial number.  The conversion backend
(seasenselib) drops this block, so :func:`read_cnv_sensors` parses it straight
from the raw CNV.  :func:`sensor_attrs` / :func:`sensors_from_attrs` round-trip
the per-channel serials through flat netCDF global attributes so stage 1 can
store them and the report can read them back; :func:`detect_sensor_changes`
diffs the per-cast configurations by raw channel.
"""

from __future__ import annotations

import re
from pathlib import Path

#: One channel's identity: ``(sensor_type, serial_number)``.  Serial is ``""``
#: when the sensor element carries no ``<SerialNumber>``.
SensorMap = dict[int, tuple[str, str]]

_SENSORS_BLOCK_RE = re.compile(r"<Sensors count.*?</Sensors>", re.DOTALL)
_SENSOR_RE = re.compile(r'<sensor Channel="(\d+)"\s*>(.*?)</sensor>', re.DOTALL)
# Match the element carrying a ``SensorID=`` attribute, not one ending in
# "Sensor" — the latter misses ``<TurbidityMeter>`` (SensorID 67) and
# ``<WET_LabsCStar>`` (SensorID 71).  The captured name is the CNV element,
# matching the ``element`` field in config/sbe_sensors.yaml.
_TYPE_RE = re.compile(r"<([A-Za-z_]\w*)\s+SensorID=")
_SERIAL_RE = re.compile(r"<SerialNumber>\s*([^<\s]*)\s*</SerialNumber>")


def read_cnv_sensors(cnv_path: Path | str) -> SensorMap:
    """Return ``{channel: (sensor_type, serial)}`` from a CNV header sensor block.

    Strips the leading ``#`` comment prefixes, isolates the ``<Sensors>`` block,
    and reads each ``<sensor Channel="N">`` entry's sensor-type element and
    ``<SerialNumber>``.  Returns an empty dict when no sensor block is present.
    """
    text = Path(cnv_path).read_text(encoding="latin-1")
    text = re.sub(r"(?m)^#\s?", "", text)  # drop CNV comment prefixes
    block = _SENSORS_BLOCK_RE.search(text)
    if block is None:
        return {}
    sensors: SensorMap = {}
    for m in _SENSOR_RE.finditer(block.group(0)):
        channel = int(m.group(1))
        body = m.group(2)
        type_m = _TYPE_RE.search(body)
        serial_m = _SERIAL_RE.search(body)
        # Every populated sensor carries SensorID=; a channel with none is a
        # "Free"/unused A/D slot, not an unrecognised element.
        sensor_type = type_m.group(1) if type_m else "Free"
        serial = serial_m.group(1) if serial_m and serial_m.group(1) else ""
        sensors[channel] = (sensor_type, serial)
    return sensors


def sensor_attrs(sensors: SensorMap) -> dict[str, str]:
    """Flatten a :data:`SensorMap` to netCDF global attrs (self-describing, greppable).

    Produces ``sensor_channel_NN_type`` and ``sensor_channel_NN_serial`` pairs
    (channel zero-padded to two digits) that :func:`sensors_from_attrs` inverts.
    """
    attrs: dict[str, str] = {}
    for channel, (sensor_type, serial) in sorted(sensors.items()):
        attrs[f"sensor_channel_{channel:02d}_type"] = sensor_type
        attrs[f"sensor_channel_{channel:02d}_serial"] = serial
    return attrs


def sensors_from_attrs(attrs: dict[str, object]) -> SensorMap:
    """Reconstruct a :data:`SensorMap` from the flat attrs written by :func:`sensor_attrs`."""
    sensors: SensorMap = {}
    for key, value in attrs.items():
        m = re.fullmatch(r"sensor_channel_(\d+)_type", key)
        if m is None:
            continue
        channel = int(m.group(1))
        serial = attrs.get(f"sensor_channel_{channel:02d}_serial", "")
        sensors[channel] = (str(value), str(serial))
    return sensors


def detect_sensor_changes(
    per_cast: list[tuple[int, SensorMap]],
) -> list[dict[str, object]]:
    """Diff per-cast sensor configurations by raw channel, in cast order.

    *per_cast* is ``[(cast_number, sensor_map), ...]``; it is sorted by cast
    number here.  A change is recorded whenever a channel's serial differs from
    the most recent earlier cast that carried that channel.  All changes are
    reported (channel reassignments and setup casts included) — the caller
    decides how to annotate them.

    Returns a list of ``{cast, channel, sensor_type, old_serial, new_serial}``
    dicts in cast then channel order.
    """
    changes: list[dict[str, object]] = []
    previous: dict[int, str] = {}
    for cast, sensors in sorted(per_cast, key=lambda x: x[0]):
        for channel in sorted(sensors):
            sensor_type, serial = sensors[channel]
            if channel in previous and previous[channel] != serial:
                changes.append(
                    {
                        "cast": cast,
                        "channel": channel,
                        "sensor_type": sensor_type,
                        "old_serial": previous[channel],
                        "new_serial": serial,
                    }
                )
            previous[channel] = serial
    return changes
