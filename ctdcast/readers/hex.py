"""Reader for Sea-Bird SBE 911plus ``.hex`` files, on seabirdscientific directly.

A ``.hex`` holds one line of hexadecimal per scan at the instrument's native rate (24 Hz on a
911plus), after a ``*``-prefixed header that ends at ``*END*``.  Reading it takes the matching
``.xmlcon`` (:mod:`ctdcast.readers.xmlcon`) for the channel layout and the calibration
coefficients.

What :func:`read_hex` returns, at the native rate and with nothing removed:

- ``pressure``, ``ctd_temperature_1/2``, ``conductivity_1/2`` in mS/cm, each with the
  ``.xmlcon`` Slope and Offset applied as Sea-Bird's DatCnv does;
- every voltage channel as raw volts (``volt<N>_raw``; an SBE 43 channel as ``oxygen_raw_<N>``),
  plus the engineering value for each sensor seabirdscientific converts (fluorescence,
  turbidity, altimeter, beam transmission) and a quick-look SBE 43 oxygen;
- the deck unit's per-scan status bits and data-integrity counter;
- ``time``, ``latitude``, ``longitude`` coordinates.

The time axis is built forward from the first scan: scan *k* is at ``T0 + k × interval``.
``T0`` is the header's ``NMEA UTC (Time)`` (GPS time when acquisition started) when present and
sane, else the header's ``System UpLoad Time`` (the PC clock at the first scan), uncorrected and
labelled as the System clock so the stage-2 clock correction can apply to it.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import gsw
import numpy as np
import xarray as xr
from seabirdscientific import conversion as cv
from seabirdscientific import instrument_data as idt

from ctdcast.config.cnv_header import parse_star_block
from ctdcast.readers.xmlcon import (
    XmlconInstrument,
    XmlconSensor,
    altimeter_coefficients,
    conductivity_coefficients,
    cstar_coefficients,
    eco_coefficients,
    oxygen43_coefficients,
    pressure_digiquartz_coefficients,
    read_xmlcon,
    temperature_coefficients,
)

#: The 911plus's native scan rate.
SBE911_SCAN_RATE_HZ = 24.0

#: Schema tag of the ``raw_metadata`` envelope a ``.hex`` cast carries.
RAW_METADATA_SCHEMA = "ctdcast-raw-metadata/1"

#: Default limit on how far the NMEA header time may sit from the PC upload time before it is
#: distrusted (a GPS receiver with no date set reports year 2000).
DEFAULT_NMEA_TOLERANCE_SECONDS = 3600.0

_INSTRUMENT_TYPE_911 = 8

_RE_BYTES_PER_SCAN = re.compile(r"^\*\s*Number of Bytes Per Scan\s*=\s*(\d+)\s*$")
_RE_VOLTAGE_WORDS = re.compile(r"^\*\s*Number of Voltage Words\s*=\s*(\d+)\s*$")
_RE_BOTTLE = re.compile(r"^\s*(\d+),\s*(\d+),\s*(.+?),\s*(\d+),\s*(\d+)\s*$")

# seabirdscientific's decoder keys for the raw words.
_K_T1, _K_C1, _K_P = "temperature", "conductivity", "digiquartz pressure"
_K_T2, _K_C2 = "secondary temperature", "secondary conductivity"
_K_TCOMP = "temperature compensation"

# Status words the deck unit adds to every scan -> stage-1 name and long_name.
_STATUS_VARS = {
    "SBE911 pump status": ("pump_status", "SBE 911plus pump status (1 = on)"),
    "SBE911 bottom contact status": (
        "bottom_contact_status",
        "SBE 911plus bottom contact status (1 = no contact)",
    ),
    "SBE911 confirm status": (
        "bottle_confirm_status",
        "SBE 911plus bottle-fire confirm status (1 = confirm detected)",
    ),
    "SBE911 modem status": (
        "modem_status",
        "SBE 911plus modem status (0 = carrier detected)",
    ),
    "data integrity": ("data_integrity", "SBE 911plus data-integrity counter"),
}


@dataclass(frozen=True)
class HexFile:
    """A ``.hex`` split into its header and scan lines."""

    #: The ``*`` header lines up to and including ``*END*``, Unix newlines.
    header: str
    #: One hexadecimal string per scan, stripped.
    lines: list[str]


def read_hex_lines(path: Path | str) -> HexFile:
    """Split a ``.hex`` into its header and its scan lines.

    The file is decoded as Latin-1, deliberately rather than UTF-8: Seasave writes the header in
    the Windows code page (``** Ship: Odón de Buen`` is the single byte 0xF3), and Latin-1
    decodes every byte without raising.  The scan lines are plain ASCII either way.

    Parameters
    ----------
    path : pathlib.Path or str
        The ``.hex`` file.

    Returns
    -------
    HexFile
        The header and the scan lines.

    Raises
    ------
    ValueError
        If the file has no ``*END*`` line.
    """
    text = (
        Path(path)
        .read_text(encoding="latin-1")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    head, sep, body = text.partition("*END*")
    if not sep:
        raise ValueError(f"{Path(path).name}: no *END* line, not a Sea-Bird .hex")
    return HexFile(
        header=head + "*END*",
        lines=[ln.strip() for ln in body.split("\n") if ln.strip()],
    )


def _header_int(header: str, pattern: re.Pattern[str]) -> int | None:
    for line in header.split("\n"):
        if (m := pattern.match(line)) is not None:
            return int(m.group(1))
    return None


def enabled_sensors(instrument: XmlconInstrument) -> list[idt.Sensors]:
    """Return the seabirdscientific ``Sensors`` list that decodes this instrument's scans.

    Every voltage channel present is enabled, used or not, so each scan's voltage words are
    all read and kept as raw volts.

    Parameters
    ----------
    instrument : XmlconInstrument
        The parsed ``.xmlcon``.

    Returns
    -------
    list of seabirdscientific.instrument_data.Sensors
        The sensors to pass to ``read_sbe911plus_data``.
    """
    s = idt.Sensors
    out: list[idt.Sensors] = []
    if instrument.n_frequency >= 4:
        out.append(s.SecondaryTemperature)
    if instrument.n_frequency >= 5:
        out.append(s.SecondaryConductivity)
    out.extend(getattr(s, f"ExtVolt{n}") for n in range(instrument.n_voltage))
    if instrument.surface_par_added:
        out.append(s.SPAR)
    if instrument.nmea_position_added:
        out.append(s.nmeaLocation)
    if instrument.nmea_depth_added:
        out.append(s.nmeaDepth)
    if instrument.nmea_time_added:
        out.append(s.nmeaTime)
    if instrument.scan_time_added:
        out.append(s.SystemTime)
    return out


def _check_layout(hexfile: HexFile, instrument: XmlconInstrument, name: str) -> None:
    """Refuse a ``.hex`` whose scan layout disagrees with its header or ``.xmlcon``.

    seabirdscientific already raises when a line's length does not match the enabled sensors;
    these checks name the cause, and catch a header/``.xmlcon`` mismatch before decoding.
    """
    if instrument.instrument_type != _INSTRUMENT_TYPE_911:
        raise ValueError(
            f"{name}: .xmlcon instrument type {instrument.instrument_type} "
            f"({instrument.name!r}); only the SBE 911plus (type 8) is supported"
        )
    if not hexfile.lines:
        raise ValueError(f"{name}: no scans after *END*")
    nbytes = _header_int(hexfile.header, _RE_BYTES_PER_SCAN)
    if nbytes is not None:
        bad = {len(ln) for ln in hexfile.lines} - {2 * nbytes}
        if bad:
            raise ValueError(
                f"{name}: header says {nbytes} bytes per scan ({2 * nbytes} hex characters), "
                f"but scan lines have lengths {sorted(bad)}"
            )
    nwords = _header_int(hexfile.header, _RE_VOLTAGE_WORDS)
    if nwords is not None and 2 * nwords != instrument.n_voltage:
        raise ValueError(
            f"{name}: header says {nwords} voltage words, the .xmlcon leaves "
            f"{instrument.n_voltage} voltage channels"
        )


def _decode(hexfile: HexFile, instrument: XmlconInstrument) -> dict[str, np.ndarray]:
    sensors = enabled_sensors(instrument)
    cols: dict[str, list] = {}
    for line in hexfile.lines:
        rec = idt.read_sbe911plus_data(
            line,
            sensors,
            instrument.frequency_channels_suppressed,
            instrument.voltage_words_suppressed,
        )
        if not cols:
            cols = {k: [] for k in rec}
        for k, v in rec.items():
            cols[k].append(v)
    return {k: np.asarray(v) for k, v in cols.items()}


def _slope_offset(
    values: np.ndarray, sensor: XmlconSensor
) -> tuple[np.ndarray, float, float]:
    slope = float(sensor.text("Slope") or 1.0)
    offset = float(sensor.text("Offset") or 0.0)
    return values * slope + offset, slope, offset


def _cal_attrs(sensor: XmlconSensor, method: str, **extra: object) -> dict:
    attrs: dict[str, object] = {
        "conversion_method": method,
        "sensor_serial_number": sensor.serial or "UNK",
        "sbe_xmlcon_index": sensor.index,
    }
    attrs.update(extra)
    return attrs


@dataclass(frozen=True)
class TimeAnchor:
    """The time of a cast's first scan and where it came from."""

    #: Time of the first scan (naive, UTC or PC clock as ``source`` says).
    t0: datetime
    #: The ``time_coordinate_source`` wording, in Sea-Bird's bracket vocabulary: ``"NMEA time,
    #: header"`` or ``"System UTC, first data scan"``.
    source: str
    #: Why this anchor was chosen, for ``history``.
    note: str


def time_anchor(
    header: str, *, nmea_tolerance_seconds: float = DEFAULT_NMEA_TOLERANCE_SECONDS
) -> TimeAnchor:
    """Choose the time of the first scan from a ``.hex`` header.

    Parameters
    ----------
    header : str
        The ``.hex`` header text.
    nmea_tolerance_seconds : float, optional
        The largest acceptable difference between the NMEA header time and the PC upload time;
        beyond it the NMEA time is distrusted (default 1 h).

    Returns
    -------
    TimeAnchor
        The NMEA header time when present and within tolerance, else the PC upload time.

    Raises
    ------
    ValueError
        If the header has neither a ``System UpLoad Time`` nor an ``NMEA UTC (Time)``.

    Warns
    -----
    UserWarning
        When the PC clock is used, so a cast without GPS time is never silent.
    """
    clocks = parse_star_block(header).clocks
    upload, nmea = clocks.system_upload_dt, clocks.nmea_dt
    if nmea is not None and (
        upload is None or abs((nmea - upload).total_seconds()) <= nmea_tolerance_seconds
    ):
        return TimeAnchor(
            nmea, "NMEA time, header", "T0 = NMEA UTC (Time) from the .hex header"
        )
    if upload is None:
        raise ValueError(
            ".hex header has neither System UpLoad Time nor NMEA UTC (Time)"
        )
    if nmea is None:
        why = "no NMEA UTC (Time) in the header"
    else:
        why = (
            f"NMEA UTC (Time) {nmea:%Y-%m-%d %H:%M:%S} is "
            f"{(nmea - upload).total_seconds():+.0f} s from the upload time, beyond "
            f"{nmea_tolerance_seconds:.0f} s"
        )
    warnings.warn(
        f"time from the PC clock (System UpLoad Time), uncorrected: {why}", stacklevel=2
    )
    return TimeAnchor(
        upload,
        "System UTC, first data scan",
        f"T0 = System UpLoad Time (PC clock, uncorrected): {why}",
    )


@dataclass(frozen=True)
class BottleCheck:
    """Result of checking bottle-fire times against bottle-fire scan numbers."""

    #: Number of bottle lines read.
    n_bottles: int
    #: Largest ``|fire time − (upload time + scan × interval)|``, in seconds.
    max_deviation_seconds: float
    #: Whether every bottle is within the tolerance.
    passed: bool


def check_bottle_log(
    bl_path: Path | str,
    upload_time: datetime,
    interval_seconds: float,
    *,
    tolerance_seconds: float = 1.0,
) -> BottleCheck:
    """Check a ``.bl`` bottle log against the scan clock.

    Each ``.bl`` line holds a bottle's fire time (PC clock, whole seconds) and the scan range it
    covers.  If the upload time is the first scan and scans are evenly spaced, every fire time
    equals ``upload_time + first_scan × interval`` to within a second.  A wrong anchor or a file
    with dropped scans fails.

    Parameters
    ----------
    bl_path : pathlib.Path or str
        The ``.bl`` file.
    upload_time : datetime
        The header's ``System UpLoad Time`` (the same PC clock as the fire times).
    interval_seconds : float
        Time between scans.
    tolerance_seconds : float, optional
        Allowed deviation; the fire times have one-second resolution (default 1 s).

    Returns
    -------
    BottleCheck
        The comparison.
    """
    devs = []
    for line in Path(bl_path).read_text(encoding="latin-1").splitlines():
        m = _RE_BOTTLE.match(line)
        if m is None:
            continue
        fired = datetime.strptime(" ".join(m.group(3).split()), "%b %d %Y %H:%M:%S")
        expected = (fired - upload_time).total_seconds()
        devs.append(abs(expected - int(m.group(4)) * interval_seconds))
    worst = max(devs) if devs else 0.0
    return BottleCheck(len(devs), worst, worst <= tolerance_seconds)


def _raw_metadata(
    hex_name: str, header: str, xmlcon_name: str, xmlcon_text: str
) -> str:
    return json.dumps(
        {
            "schema": RAW_METADATA_SCHEMA,
            "raw_format": "sbe-hex",
            "source_files": [hex_name, xmlcon_name],
            "blocks": {"header": header, "xmlcon": xmlcon_text},
        }
    )


def read_hex(
    hex_path: Path | str,
    xmlcon_path: Path | str,
    *,
    nmea_tolerance_seconds: float = DEFAULT_NMEA_TOLERANCE_SECONDS,
) -> xr.Dataset:
    """Read an SBE 911plus ``.hex`` with its ``.xmlcon`` into a native-rate Dataset.

    Parameters
    ----------
    hex_path : pathlib.Path or str
        The ``.hex`` file.
    xmlcon_path : pathlib.Path or str
        The ``.xmlcon`` holding the calibration coefficients to convert with.
    nmea_tolerance_seconds : float, optional
        See :func:`time_anchor`.

    Returns
    -------
    xarray.Dataset
        Dimension ``time`` (one entry per scan); variables and coordinates as described in
        the module docstring.  Global attributes include ``raw_metadata`` (the header and the
        ``.xmlcon`` verbatim), ``input_format = "hex"``, ``sample_interval_seconds``,
        ``time_coordinate_source`` and ``seabirdscientific_version``.

    Raises
    ------
    ValueError
        If the layout checks fail, the instrument is not a 911plus, or the header carries no
        usable time.
    """
    hex_path, xmlcon_path = Path(hex_path), Path(xmlcon_path)
    hexfile = read_hex_lines(hex_path)
    instrument, xmlcon_text = read_xmlcon(xmlcon_path)
    _check_layout(hexfile, instrument, hex_path.name)

    acq = parse_star_block(hexfile.header)
    averaged = acq.deck_unit.scans_averaged or instrument.scans_to_average or 1
    if (
        acq.deck_unit.scans_averaged
        and acq.deck_unit.scans_averaged != instrument.scans_to_average
    ):
        raise ValueError(
            f"{hex_path.name}: header says {acq.deck_unit.scans_averaged} scans averaged, "
            f"the .xmlcon {instrument.scans_to_average}"
        )
    interval = averaged / SBE911_SCAN_RATE_HZ

    cols = _decode(hexfile, instrument)
    sensors = instrument.sensors
    freq = [s for s in sensors if s.kind == "frequency"]
    data: dict[str, tuple[np.ndarray, dict]] = {}

    p_sensor = freq[2]
    p = cv.convert_pressure_digiquartz(
        cols[_K_P],
        cols[_K_TCOMP],
        pressure_digiquartz_coefficients(p_sensor),
        "dbar",
        interval,
    )
    data["pressure"] = (
        p,
        _cal_attrs(
            p_sensor,
            "seabirdscientific convert_pressure_digiquartz",
            units="dbar",
            xmlcon_slope=float(p_sensor.text("Slope") or 1.0),
            xmlcon_offset=float(p_sensor.text("Offset") or 0.0),
            comment="xmlcon Slope and Offset (dbar) applied inside convert_pressure_digiquartz",
        ),
    )

    temps: dict[int, np.ndarray] = {}
    for line_no, t_sensor, key in (
        (1, freq[0], _K_T1),
        (2, freq[3] if len(freq) > 3 else None, _K_T2),
    ):
        if t_sensor is None:
            continue
        t_raw = cv.convert_temperature_frequency(
            cols[key], temperature_coefficients(t_sensor)
        )
        t, slope, offset = _slope_offset(t_raw, t_sensor)
        temps[line_no] = t
        data[f"ctd_temperature_{line_no}"] = (
            t,
            _cal_attrs(
                t_sensor,
                "seabirdscientific convert_temperature_frequency",
                units="degree_Celsius",
                xmlcon_slope=slope,
                xmlcon_offset=offset,
                comment="xmlcon Slope and Offset (degC, ITS-90) applied after conversion",
            ),
        )

    for line_no, c_sensor, key in (
        (1, freq[1], _K_C1),
        (2, freq[4] if len(freq) > 4 else None, _K_C2),
    ):
        if c_sensor is None:
            continue
        offset = float(c_sensor.text("Offset") or 0.0)
        if offset != 0.0:
            # Sea-Bird's conductivity offset is taken to be in S/m; not yet checked against
            # Sea-Bird's documentation, so a nonzero one is refused rather than guessed.
            raise ValueError(
                f"{hex_path.name}: conductivity sensor {c_sensor.serial} has a nonzero .xmlcon "
                f"Offset ({offset}); its unit is not yet confirmed, so it is not applied"
            )
        c_si = cv.convert_conductivity(
            cols[key],
            temps[line_no],
            p,
            conductivity_coefficients(c_sensor),
            idt.InstrumentType.SBE911Plus,
            units="S/m",
        )
        c_si, slope, offset = _slope_offset(c_si, c_sensor)  # in S/m, before the x10
        c = cv.convert_conductivity_units(c_si, "S/m", "mS/cm")
        data[f"conductivity_{line_no}"] = (
            c,
            _cal_attrs(
                c_sensor,
                "seabirdscientific convert_conductivity",
                units="mS cm-1",
                xmlcon_slope=slope,
                xmlcon_offset=offset,
                comment="xmlcon Slope and Offset applied in S m-1, then converted to mS cm-1",
            ),
        )

    # Voltage channels: every one kept as raw volts; SBE 43 channels under the oxygen name.
    n_oxygen = 0
    for s in (s for s in sensors if s.kind == "voltage"):
        volts = cols[f"volt {s.number}"]
        if s.element == "OxygenSensor":
            n_oxygen += 1
            name = f"oxygen_raw_{n_oxygen}"
        else:
            name = f"volt{s.number}_raw"
        data[name] = (
            volts,
            {
                "units": "V",
                "sbe_xmlcon_index": s.index,
                "sbe_sensor_element": s.element or "NotInUse",
            },
        )
        conv = _convert_voltage(s, volts)
        if conv is not None:
            cname, values, attrs = conv
            if cname in data:
                warnings.warn(
                    f"{hex_path.name}: a second {s.element} kept only as {name}",
                    stacklevel=2,
                )
                continue
            data[cname] = (values, attrs)

    # Quick-look oxygen: SBE 43 voltage converted with the uncorrected T/S of its line, no tau
    # or hysteresis correction.  The real ctd_oxygen is derived at stage 3, after alignment and CTM.
    for k, ox in enumerate(instrument.by_element("OxygenSensor"), start=1):
        line_no = k if k in temps and f"conductivity_{k}" in data else 1
        sp = gsw.SP_from_C(data[f"conductivity_{line_no}"][0], temps[line_no], p)
        o2 = cv.convert_sbe43_oxygen(
            data[f"oxygen_raw_{k}"][0],
            temps[line_no],
            p,
            sp,
            oxygen43_coefficients(ox),
            units="umol/kg",
        )
        data[f"sbe_oxygen_{k}"] = (
            o2,
            _cal_attrs(
                ox,
                "seabirdscientific convert_sbe43_oxygen (no tau or hysteresis correction)",
                units="umol kg-1",
                long_name=f"SBE 43 oxygen, quick-look, sensor {k}",
                comment=(
                    f"Converted at read time by ctdcast, with Sea-Bird's seabirdscientific toolkit "
                    f"(not SBE Data Processing), from oxygen_raw_{k} and the uncorrected "
                    f"temperature and practical salinity of line {line_no} (no alignment, no cell "
                    "thermal mass, tau or hysteresis correction). Not the stage-3 ctd_oxygen."
                ),
            ),
        )

    for key, (name, long_name) in _STATUS_VARS.items():
        if key in cols:
            # int16: the integrity counter runs 0-255, beyond int8.
            data[name] = (
                cols[key].astype(np.int16),
                {"units": "1", "long_name": long_name},
            )

    anchor = time_anchor(hexfile.header, nmea_tolerance_seconds=nmea_tolerance_seconds)
    n = len(hexfile.lines)
    offsets_ns = np.round(np.arange(n) * interval * 1e9).astype("int64")
    time = np.datetime64(anchor.t0, "ns") + offsets_ns.astype("timedelta64[ns]")

    coords: dict[str, tuple] = {
        "time": ("time", time, {"standard_name": "time", "axis": "T"})
    }
    if "NMEA Latitude" in cols:
        coords["latitude"] = (
            "time",
            cols["NMEA Latitude"].astype(float),
            {
                "units": "degrees_north",
                "standard_name": "latitude",
                "source": "NMEA position appended to each scan",
            },
        )
        coords["longitude"] = (
            "time",
            cols["NMEA Longitude"].astype(float),
            {
                "units": "degrees_east",
                "standard_name": "longitude",
                "source": "NMEA position appended to each scan",
            },
        )

    ds = xr.Dataset(
        {
            name: ("time", np.asarray(values), attrs)
            for name, (values, attrs) in data.items()
        },
        coords=coords,
    )
    stat = hex_path.stat()
    ds.attrs.update(
        {
            "raw_metadata": _raw_metadata(
                hex_path.name, hexfile.header, xmlcon_path.name, xmlcon_text
            ),
            "raw_filename": hex_path.name,
            "raw_filesize_bytes": int(stat.st_size),
            "raw_mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "input_format": "hex",
            "source_xmlcon": xmlcon_path.name,
            "sample_interval_seconds": interval,
            "time_coordinate_source": anchor.source,
            "time_anchor_note": anchor.note,
            "seabirdscientific_version": importlib.metadata.version(
                "seabirdscientific"
            ),
            "sbe_n_scans": n,
        }
    )
    return ds


def _convert_voltage(
    sensor: XmlconSensor, volts: np.ndarray
) -> tuple[str, np.ndarray, dict] | None:
    """Engineering value for a voltage sensor seabirdscientific converts, or None."""
    e = sensor.element
    if e == "FluoroWetlabECO_AFL_FL_Sensor":
        values = cv.convert_eco(volts, eco_coefficients(sensor))
        return (
            "ctd_fluor",
            values,
            _cal_attrs(sensor, "seabirdscientific convert_eco", units="mg m-3"),
        )
    if e == "TurbidityMeter":
        values = cv.convert_eco(volts, eco_coefficients(sensor))
        return (
            "ctd_turbidity",
            values,
            _cal_attrs(sensor, "seabirdscientific convert_eco", units="1"),
        )
    if e == "AltimeterSensor":
        values = cv.convert_altimeter(volts, altimeter_coefficients(sensor))
        return (
            "ctd_altimeter",
            values,
            _cal_attrs(sensor, "seabirdscientific convert_altimeter", units="m"),
        )
    if e == "WET_LabsCStar":
        values = cv.convert_cstar_transmittance(volts, cstar_coefficients(sensor))
        return (
            "transmissometer",
            values,
            _cal_attrs(
                sensor, "seabirdscientific convert_cstar_transmittance", units="percent"
            ),
        )
    return None
