"""Reader for per-cast sensor metadata written by seasenselib.

Parses the ``raw_metadata`` global attribute (a JSON blob) into a list of sensor
descriptors for the cast page.
"""

from __future__ import annotations

import datetime
import json

import xarray as xr


def _normalise_calibration_date(raw: str) -> str:
    """Return *raw* reformatted as ``YYYY-MMM-DD``, or *raw* unchanged on failure.

    SeaBird writes dates in ``DD-Mon-YY`` or ``DD-Mon-YYYY`` form
    (e.g. ``"17-Feb-26"`` or ``"17-Feb-2026"``).
    """
    for fmt in ("%d-%b-%y", "%d-%b-%Y"):
        try:
            return datetime.datetime.strptime(raw, fmt).date().strftime("%Y-%b-%d")
        except ValueError:
            continue
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
