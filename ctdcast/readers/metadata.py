"""Reader for per-cast sensor metadata written by seasenselib.

Parses the ``raw_metadata`` global attribute (a JSON blob) into a list of sensor
descriptors for the cast page.
"""

from __future__ import annotations

import datetime
import json
import re

import xarray as xr

from ctdcast.config.sensors import INDEXED_ROLES, ROLE_QUANTITY


# Calibration-date formats seen across real SBE config files (XMLCON, CON, CNV).
# Day-first is the SeaBird convention; month-first is deliberately NOT included,
# to avoid mis-reading an ambiguous "13/02/24".  A year-only string ("2013") has
# no format here, so it is left raw rather than invented into 2013-01-01.
_CAL_DATE_FORMATS: tuple[str, ...] = (
    "%d-%b-%y",
    "%d-%b-%Y",  # 11-Apr-17 / 30-sep-2004
    "%d %b %y",
    "%d %b %Y",  # 20 Nov 92 / 15 Jan 2016
    "%d/%m/%y",
    "%d/%m/%Y",  # 13/02/24 / 18/06/2013
    "%Y/%m/%d",  # 2016/04/12
    "%d.%m.%y",
    "%d.%m.%Y",  # 20.12.11 / 15.06.2010
    "%d-%m-%y",
    "%d-%m-%Y",  # 27-03-2009
)


def _normalise_calibration_date(raw: str) -> str:
    """Return *raw* reformatted as ``YYYY-Mon-DD``, or *raw* unchanged on failure.

    Tries the SeaBird calibration-date formats in :data:`_CAL_DATE_FORMATS`.  A
    parse is accepted only if the resulting year is plausible (1980–2035), which
    rejects a bad match such as ``%d/%m/%Y`` reading ``"13/02/24"`` as year 24.
    Anything unrecognised (e.g. a bare year, or ``"090726"``) is returned raw
    rather than guessed.
    """
    raw = (raw or "").strip()
    for fmt in _CAL_DATE_FORMATS:
        try:
            d = datetime.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        if 1980 <= d.year <= 2035:
            return d.strftime("%Y-%b-%d")
    return raw


# Human-readable display names for SBE sensor type strings.
_SENSOR_LABELS: dict[str, str] = {
    "TemperatureSensor": "Temperature",
    "ConductivitySensor": "Conductivity",
    "PressureSensor": "Pressure",
    "OxygenSensor": "Oxygen (SBE43)",
    "FluoroWetlabECO_AFL_FL_Sensor": "Fluorometer",
    "TurbidityMeter": "Turbidity",
    "pH_Sensor": "pH",
    "AltimeterSensor": "Altimeter",
    "UserPolynomialSensor": "Aux",
    "WET_LabsCStar": "Transmissometer",
}


def parse_sensor_info(ds: xr.Dataset) -> list[dict[str, str]]:
    """Extract sensor serial numbers and calibration dates from *ds*.

    Parses the ``raw_metadata`` global attribute (a JSON string written by
    seasenselib) and returns one entry per sensor channel that has both a
    ``sensor_type`` and a ``serial_number``.

    Parameters
    ----------
    ds:
        Per-cast Dataset as opened from a netCDF file.

    Returns
    -------
    list[dict[str, str]]
        Each dict has keys ``sensor_type`` (human-readable label),
        ``serial_number``, and ``calibration_date``.  Returns ``[]`` if
        ``raw_metadata`` is absent, unparseable, or contains no usable sensors.

    """
    raw = ds.attrs.get("raw_metadata", "")
    if not raw:
        return []
    try:
        meta = json.loads(raw)
        ga = meta["blocks"]["other"]["global_attributes"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []

    results: list[dict[str, str]] = []
    for key in sorted(
        ga,
        key=lambda k: (
            int(k.split("_")[-1])
            if k.startswith("cnv_sensor_") and k.split("_")[-1].isdigit()
            else 9999
        ),
    ):
        if not key.startswith("cnv_sensor_"):
            continue
        entry = ga[key]
        if not isinstance(entry, dict):
            continue
        sensor_type_raw = entry.get("sensor_type", "")
        serial = entry.get("serial_number", "")
        if not sensor_type_raw or not serial:
            continue
        label = _SENSOR_LABELS.get(sensor_type_raw, sensor_type_raw)
        results.append(
            {
                "sensor_type": label,
                "serial_number": serial,
                "calibration_date": _normalise_calibration_date(
                    entry.get("calibration_date", "")
                ),
            }
        )
    return results


_COMMENT_RE = re.compile(
    r"<!--\s*(?:Frequency|A/D voltage)\s+\d+,\s*(?P<rest>.*?)\s*-->"
)

# Parse the raw CNV <Sensors> block directly: seasenselib's per-channel
# cnv_sensor_N dicts are lossy (e.g. MSM142's turbidity channel keeps only the
# channel number), whereas the header block carries every field.
_SENSORS_BLOCK_RE = re.compile(r"<Sensors count.*?</Sensors>", re.DOTALL)
_SENSOR_ENTRY_RE = re.compile(r'<sensor Channel="(\d+)"\s*>(.*?)</sensor>', re.DOTALL)
_ELEM_RE = re.compile(r'<([A-Za-z_]\w*)\s+SensorID="(\d+)"')
_SERIAL_RE = re.compile(r"<SerialNumber>\s*([^<\s]*)\s*</SerialNumber>")
_CAL_RE = re.compile(r"<CalibrationDate>\s*([^<]*?)\s*</CalibrationDate>")


def _role_from_comment(rest: str) -> str | None:
    """Return the canonical role for a CNV sensor-block comment body, or None.

    *rest* is the text after the ``Frequency N,`` / ``A/D voltage N,`` prefix,
    e.g. ``"Temperature, 2"``, ``"Oxygen, SBE 43, 2"``,
    ``"Turbidity Meter, WET Labs, ECO-NTU"`` or ``"Free"``.  The first
    comma-part is the measured quantity; a trailing bare integer is the
    secondary index.  Returns None for a ``Free`` (unused) channel.
    """
    parts = [p.strip() for p in rest.split(",")]
    quantity = parts[0]
    if quantity == "Free" or not quantity:
        return None
    index = int(parts[-1]) if len(parts) > 1 and parts[-1].isdigit() else 1
    base = ROLE_QUANTITY.get(quantity)
    if base is None:
        base = re.sub(r"[^a-z0-9]+", "_", quantity.lower()).strip("_")
    return f"{base}_{index}" if base in INDEXED_ROLES else base


def parse_sensor_channels(ds: xr.Dataset) -> list[dict[str, str]]:
    """Return one full descriptor per sensor channel in *ds*, from the raw header.

    Parses the CNV ``<Sensors>`` block embedded in ``raw_metadata``'s
    ``blocks.header`` — the authoritative source, since seasenselib's per-channel
    ``cnv_sensor_N`` dicts are lossy for some channels.  For each
    ``<sensor Channel="N">`` entry it reads the block comment (role), the type
    element and its ``SensorID``, the ``SerialNumber`` and the
    ``CalibrationDate``.  ``Free`` (unused) channels get ``role = None`` and an
    empty serial.

    Returns ``[]`` if ``raw_metadata`` or the header sensor block is absent.
    Each dict has keys ``channel``, ``element``, ``sensor_id``, ``serial``,
    ``calibration_date`` (normalised) and ``role`` (canonical role or ``None``).
    """
    raw = ds.attrs.get("raw_metadata", "")
    if not raw:
        return []
    try:
        header = json.loads(raw)["blocks"].get("header", "")
    except (json.JSONDecodeError, KeyError, TypeError):
        return []

    text = re.sub(r"(?m)^#\s?", "", header)  # drop CNV comment prefixes
    block = _SENSORS_BLOCK_RE.search(text)
    if block is None:
        return []

    records: list[dict[str, str]] = []
    for m in _SENSOR_ENTRY_RE.finditer(block.group(0)):
        channel = int(m.group(1))
        body = m.group(2)
        comment = _COMMENT_RE.search(body)
        elem = _ELEM_RE.search(body)
        serial = _SERIAL_RE.search(body)
        cal = _CAL_RE.search(body)
        records.append(
            {
                "channel": channel,
                "element": elem.group(1) if elem else "",
                "sensor_id": elem.group(2) if elem else "",
                "serial": serial.group(1) if serial and serial.group(1) else "",
                "calibration_date": (
                    _normalise_calibration_date(cal.group(1)) if cal else ""
                ),
                "role": _role_from_comment(comment.group("rest")) if comment else None,
            }
        )
    records.sort(key=lambda r: r["channel"])
    return records
