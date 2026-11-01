"""Reader for Sea-Bird ``.xmlcon`` instrument configuration files (SBE 911plus).

An ``.xmlcon`` is the configuration Seasave writes beside each ``.hex``: the instrument
settings (which channels are suppressed, what the deck unit appends to each scan) and one
``<Sensor index=…>`` element per channel, holding the sensor's serial number, calibration
date and coefficients.

This module turns it into three things:

- :class:`XmlconInstrument`, the parsed settings and sensors;
- seabirdscientific coefficient objects for the sensors ctdcast converts at stage 1
  (temperature, conductivity, Digiquartz pressure, SBE 43 oxygen, ECO, altimeter, C-Star);
- sensor records shaped exactly like
  :func:`ctdcast.config.cnv_header.parse_sensor_block`'s, so the per-cast sensor catalog is
  built by the same code for a ``.hex`` cast as for a ``.cnv`` one.

The ``<sensor>`` block a CNV header embeds is the same XML as the ``.xmlcon``'s ``<Sensor>``
element, wrapped differently and preceded by a comment naming the channel and its quantity
(``<!-- Frequency 3, Temperature, 2 -->``).  :func:`sensor_records` rebuilds that wrapping, so
``raw_block`` reads the same whichever file the sensor came from.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from seabirdscientific import cal_coefficients as cc

#: Frequency channels on a 911plus before suppression: T, C, P, T2, C2.
N_FREQUENCY_CHANNELS = 5
#: Voltage channels on a 911plus before suppression (4 words of 2 channels each).
N_VOLTAGE_CHANNELS = 8

# .xmlcon element -> the quantity text Seasave writes in the CNV sensor comment.  Taken from
# real CNV headers (MIXSED2 and MSM142 fixtures); the comment's first part is what
# readers.metadata resolves to a sensor role.  An element not listed here keeps its element
# name as the comment, which resolves to a role by the generic fallback.
_COMMENT_FOR_ELEMENT: dict[str, str] = {
    "TemperatureSensor": "Temperature",
    "ConductivitySensor": "Conductivity",
    "PressureSensor": "Pressure, Digiquartz with TC",
    "OxygenSensor": "Oxygen, SBE 43",
    "UserPolynomialSensor": "User Polynomial",
    "NotInUse": "Free",
    "pH_Sensor": "pH",
    "AltimeterSensor": "Altimeter",
    "WET_LabsCStar": "Transmissometer, WET Labs C-Star",
    "TurbidityMeter": "Turbidity Meter, WET Labs, ECO-NTU",
    "FluoroWetlabECO_AFL_FL_Sensor": "Fluorometer, WET Labs ECO-AFL/FL",
}

# Elements that can appear twice on a 911plus; the second gets ", 2" in its comment.
_INDEXED_ELEMENTS = frozenset(
    {"TemperatureSensor", "ConductivitySensor", "OxygenSensor"}
)

_RE_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>")
_RE_SENSOR_SPAN = re.compile(
    r'<Sensor index="(\d+)"[^>]*>\n(.*?)\n[ \t]*</Sensor>', re.DOTALL
)


@dataclass(frozen=True)
class XmlconSensor:
    """One ``<Sensor>`` of an ``.xmlcon``.

    Attributes
    ----------
    index : int
        The ``.xmlcon`` index, 0-based.
    element : str
        The sensor's element tag, e.g. ``"TemperatureSensor"``.
    sensor_id : str
        Sea-Bird's ``SensorID`` for the element.
    serial : str
        The serial number as written (may be empty).
    calibration_date : str
        The calibration date as written (may be empty).
    kind : str
        ``"frequency"`` or ``"voltage"``.
    number : int
        The channel number within its kind: frequency 0–4, voltage 0–7.
    comment : str
        The quantity text Seasave would write in the CNV sensor comment, e.g.
        ``"Temperature, 2"``.
    body : str
        The sensor element's XML, verbatim, with Unix newlines.
    node : xml.etree.ElementTree.Element
        The parsed sensor element (the child of ``<Sensor>``).
    """

    index: int
    element: str
    sensor_id: str
    serial: str
    calibration_date: str
    kind: str
    number: int
    comment: str
    body: str
    node: ET.Element = field(repr=False, compare=False)

    def value(self, tag: str) -> float:
        """Return the float value of a direct child *tag* of the sensor element.

        Parameters
        ----------
        tag : str
            The child element name, e.g. ``"Slope"``.

        Returns
        -------
        float
            The parsed value.

        Raises
        ------
        KeyError
            If the sensor element has no such child.
        """
        text = self.node.findtext(tag)
        if text is None:
            raise KeyError(f"{self.element} (index {self.index}) has no <{tag}>")
        return float(text)

    def text(self, tag: str) -> str | None:
        """Return the stripped text of a direct child *tag*, or ``None`` if absent.

        Parameters
        ----------
        tag : str
            The child element name.

        Returns
        -------
        str or None
            The text, or ``None`` when the element has no such child.
        """
        text = self.node.findtext(tag)
        return text.strip() if text is not None else None


@dataclass(frozen=True)
class XmlconInstrument:
    """The parsed ``<Instrument>`` of an ``.xmlcon``.

    Attributes
    ----------
    name : str
        The instrument name, e.g. ``"SBE 911plus/917plus CTD"``.
    instrument_type : int
        Sea-Bird's ``Instrument Type`` code (8 is the 911plus).
    frequency_channels_suppressed : int
        Number of frequency channels suppressed (0–2).
    voltage_words_suppressed : int
        Number of voltage words suppressed (0–4); each word is two channels.
    scans_to_average : int
        Scans averaged by the deck unit.
    nmea_position_added, nmea_time_added, nmea_depth_added : bool
        What the deck unit appends to each scan from the ship's NMEA feed.
    scan_time_added, surface_par_added : bool
        Whether the PC's scan time or a surface PAR voltage is appended to each scan.
    sensors : tuple of XmlconSensor
        The sensors, in index order.
    """

    name: str
    instrument_type: int
    frequency_channels_suppressed: int
    voltage_words_suppressed: int
    scans_to_average: int
    nmea_position_added: bool
    nmea_time_added: bool
    nmea_depth_added: bool
    scan_time_added: bool
    surface_par_added: bool
    sensors: tuple[XmlconSensor, ...]

    @property
    def n_frequency(self) -> int:
        """Number of frequency channels present (5 minus those suppressed)."""
        return N_FREQUENCY_CHANNELS - self.frequency_channels_suppressed

    @property
    def n_voltage(self) -> int:
        """Number of voltage channels present (8 minus two per suppressed word)."""
        return N_VOLTAGE_CHANNELS - 2 * self.voltage_words_suppressed

    def by_element(self, element: str) -> list[XmlconSensor]:
        """Return the sensors with element tag *element*, in index order.

        Parameters
        ----------
        element : str
            The element tag, e.g. ``"ConductivitySensor"``.

        Returns
        -------
        list of XmlconSensor
            Possibly empty.
        """
        return [s for s in self.sensors if s.element == element]


def _int(node: ET.Element, tag: str, default: int = 0) -> int:
    text = node.findtext(tag)
    return int(text) if text is not None and text.strip() else default


def parse_xmlcon(text: str) -> XmlconInstrument:
    """Parse the text of an SBE 911plus ``.xmlcon``.

    Parameters
    ----------
    text : str
        The whole file, already decoded.

    Returns
    -------
    XmlconInstrument
        The instrument settings and its sensors.

    Raises
    ------
    ValueError
        If the file has no ``<Instrument>`` or ``<SensorArray>``, or if the number of
        sensors does not match the channels the suppression settings leave: a layout ctdcast
        would otherwise read into the wrong channels.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    root = ET.fromstring(_RE_DECLARATION.sub("", text, count=1))
    inst = root.find("Instrument")
    if inst is None:
        raise ValueError(".xmlcon has no <Instrument> element")
    array = inst.find("SensorArray")
    if array is None:
        raise ValueError(".xmlcon has no <SensorArray> element")

    fsup = _int(inst, "FrequencyChannelsSuppressed")
    vsup = _int(inst, "VoltageWordsSuppressed")
    n_freq = N_FREQUENCY_CHANNELS - fsup
    n_expected = n_freq + N_VOLTAGE_CHANNELS - 2 * vsup
    size_attr = array.get("Size")
    nodes = list(array)
    if len(nodes) != n_expected or (
        size_attr is not None and int(size_attr) != n_expected
    ):
        raise ValueError(
            f".xmlcon lists {len(nodes)} sensors (Size={size_attr}), but "
            f"{fsup} suppressed frequency channel(s) and {vsup} suppressed voltage word(s) "
            f"leave {n_expected} channels"
        )

    bodies = {int(m.group(1)): m.group(2) for m in _RE_SENSOR_SPAN.finditer(text)}
    seen: dict[str, int] = {}
    sensors: list[XmlconSensor] = []
    for wrapper in nodes:
        index = int(wrapper.get("index", "-1"))
        if len(wrapper) != 1:
            raise ValueError(
                f".xmlcon <Sensor index={index}> must hold exactly one element"
            )
        node = wrapper[0]
        element = node.tag
        seen[element] = seen.get(element, 0) + 1
        comment = _COMMENT_FOR_ELEMENT.get(element, element)
        if element in _INDEXED_ELEMENTS and seen[element] > 1:
            comment = f"{comment}, {seen[element]}"
        kind, number = (
            ("frequency", index) if index < n_freq else ("voltage", index - n_freq)
        )
        sensors.append(
            XmlconSensor(
                index=index,
                element=element,
                sensor_id=node.get("SensorID", ""),
                serial=(node.findtext("SerialNumber") or "").strip(),
                calibration_date=(node.findtext("CalibrationDate") or "").strip(),
                kind=kind,
                number=number,
                comment=comment,
                body=bodies.get(index, ""),
                node=node,
            )
        )
    if [s.index for s in sensors] != list(range(n_expected)):
        raise ValueError(".xmlcon sensor indices are not 0..N-1 in order")

    return XmlconInstrument(
        name=(inst.findtext("Name") or "").strip(),
        instrument_type=int(inst.get("Type", "-1")),
        frequency_channels_suppressed=fsup,
        voltage_words_suppressed=vsup,
        scans_to_average=_int(inst, "ScansToAverage", 1),
        nmea_position_added=bool(_int(inst, "NmeaPositionDataAdded")),
        nmea_time_added=bool(_int(inst, "NmeaTimeAdded")),
        nmea_depth_added=bool(_int(inst, "NmeaDepthDataAdded")),
        scan_time_added=bool(_int(inst, "ScanTimeAdded")),
        surface_par_added=bool(_int(inst, "SurfaceParVoltageAdded")),
        sensors=tuple(sensors),
    )


def read_xmlcon(path: Path | str) -> tuple[XmlconInstrument, str]:
    """Read and parse an ``.xmlcon`` file.

    The file is decoded as Latin-1, deliberately rather than UTF-8: Seasave writes text in the
    Windows code page, and Latin-1 decodes every byte without raising.

    Parameters
    ----------
    path : pathlib.Path or str
        The ``.xmlcon`` file.

    Returns
    -------
    tuple of (XmlconInstrument, str)
        The parsed instrument and the file's text, verbatim (for ``raw_metadata``).

    Raises
    ------
    ValueError
        See :func:`parse_xmlcon`.
    """
    text = Path(path).read_text(encoding="latin-1")
    return parse_xmlcon(text), text


def _cnv_block(sensor: XmlconSensor) -> str:
    """Rebuild the ``<sensor Channel=…>`` block a CNV header embeds for *sensor*.

    The CNV block indents the sensor element two spaces deeper than ``<sensor>``, which sits
    two in from ``<Sensors>``; the ``.xmlcon`` element sits eight in.  Dedenting by four and
    adding the channel comment reproduces the CNV text.  An unused (``NotInUse``) slot is
    written as the comment alone, as DatCnv writes it.
    """
    if sensor.element == "NotInUse":
        lines: list[str] = []
    else:
        lines = [
            ln[4:] if ln.startswith("    ") else ln for ln in sensor.body.split("\n")
        ]
    label = "Frequency" if sensor.kind == "frequency" else "A/D voltage"
    return "\n".join(
        [
            f'<sensor Channel="{sensor.index + 1}" >',
            f"    <!-- {label} {sensor.number}, {sensor.comment} -->",
            *lines,
            "  </sensor>",
        ]
    )


def sensor_records(instrument: XmlconInstrument) -> list[dict]:
    """Return one raw record per sensor, shaped like ``parse_sensor_block``'s.

    Parameters
    ----------
    instrument : XmlconInstrument
        A parsed ``.xmlcon``.

    Returns
    -------
    list of dict
        Keys ``channel`` (1-based), ``element``, ``sensor_id``, ``serial``,
        ``calibration_date``, ``slope``, ``offset`` (``"1.0"`` / ``"0.0"`` when absent),
        ``comment`` and ``raw_block``, as
        :func:`ctdcast.config.cnv_header.parse_sensor_block` returns them for a CNV header.
    """
    records = []
    for s in instrument.sensors:
        slope, offset = s.text("Slope"), s.text("Offset")
        unused = s.element == "NotInUse"  # DatCnv writes an unused slot with no element
        records.append(
            {
                "channel": s.index + 1,
                "element": "" if unused else s.element,
                "sensor_id": "" if unused else s.sensor_id,
                "serial": s.serial,
                "calibration_date": s.calibration_date,
                "slope": slope if slope else "1.0",
                "offset": offset if offset else "0.0",
                "comment": s.comment,
                "raw_block": _cnv_block(s),
            }
        )
    return records


# --- seabirdscientific coefficient objects -------------------------------------------------


def temperature_coefficients(
    sensor: XmlconSensor,
) -> cc.TemperatureFrequencyCoefficients:
    """Return the frequency-temperature coefficients (G, H, I, J, F0) of *sensor*.

    Parameters
    ----------
    sensor : XmlconSensor
        A ``TemperatureSensor`` with ``UseG_J = 1``.

    Returns
    -------
    seabirdscientific.cal_coefficients.TemperatureFrequencyCoefficients
        Slope and Offset are not part of it; the reader applies them.

    Raises
    ------
    ValueError
        If the sensor uses the older A–D equation (``UseG_J = 0``), which ctdcast does not
        convert.
    """
    if sensor.text("UseG_J") not in (None, "1"):
        raise ValueError(
            f"temperature sensor {sensor.serial}: only the G-J equation is supported"
        )
    return cc.TemperatureFrequencyCoefficients(
        g=sensor.value("G"),
        h=sensor.value("H"),
        i=sensor.value("I"),
        j=sensor.value("J"),
        f0=sensor.value("F0"),
    )


def conductivity_coefficients(sensor: XmlconSensor) -> cc.ConductivityCoefficients:
    """Return the conductivity coefficients (equation 1: G, H, I, J, CPcor, CTcor, WBOTC).

    Parameters
    ----------
    sensor : XmlconSensor
        A ``ConductivitySensor`` with ``UseG_J = 1``.

    Returns
    -------
    seabirdscientific.cal_coefficients.ConductivityCoefficients
        Slope and Offset are not part of it; the reader applies them.

    Raises
    ------
    ValueError
        If the sensor uses the older equation or has no equation-1 coefficients.
    """
    if sensor.text("UseG_J") not in (None, "1"):
        raise ValueError(
            f"conductivity sensor {sensor.serial}: only the G-J equation is supported"
        )
    eq = sensor.node.find("Coefficients[@equation='1']")
    if eq is None:
        raise ValueError(
            f"conductivity sensor {sensor.serial}: no equation-1 coefficients"
        )

    def v(tag: str) -> float:
        return float(eq.findtext(tag) or "nan")

    return cc.ConductivityCoefficients(
        g=v("G"),
        h=v("H"),
        i=v("I"),
        j=v("J"),
        cpcor=v("CPcor"),
        ctcor=v("CTcor"),
        wbotc=v("WBOTC"),
    )


def pressure_digiquartz_coefficients(
    sensor: XmlconSensor,
) -> cc.PressureDigiquartzCoefficients:
    """Return the Digiquartz pressure coefficients, including Slope, Offset and AD590M/B.

    seabirdscientific's Digiquartz converter applies the Slope and Offset itself (in dbar),
    so they belong in the coefficient object, and the reader must not apply them again.

    Parameters
    ----------
    sensor : XmlconSensor
        A ``PressureSensor`` (Digiquartz with temperature compensation).

    Returns
    -------
    seabirdscientific.cal_coefficients.PressureDigiquartzCoefficients
        The coefficients.
    """
    v = sensor.value
    return cc.PressureDigiquartzCoefficients(
        c1=v("C1"), c2=v("C2"), c3=v("C3"), d1=v("D1"), d2=v("D2"),
        t1=v("T1"), t2=v("T2"), t3=v("T3"), t4=v("T4"), t5=v("T5"),
        ad590m=v("AD590M"), ad590b=v("AD590B"),
        slope=v("Slope"), offset=v("Offset"),
    )  # fmt: skip


def oxygen43_coefficients(sensor: XmlconSensor) -> cc.Oxygen43Coefficients:
    """Return the SBE 43 coefficients of the Sea-Bird (2007 and later) equation.

    Parameters
    ----------
    sensor : XmlconSensor
        An ``OxygenSensor`` with ``Use2007Equation = 1``.

    Returns
    -------
    seabirdscientific.cal_coefficients.Oxygen43Coefficients
        The coefficients.

    Raises
    ------
    ValueError
        If the sensor uses the Owens-Millard equation, which ctdcast does not convert.
    """
    if sensor.text("Use2007Equation") != "1":
        raise ValueError(
            f"oxygen sensor {sensor.serial}: only the 2007 Sea-Bird equation is supported"
        )
    eq = sensor.node.find("CalibrationCoefficients[@equation='1']")
    if eq is None:
        raise ValueError(f"oxygen sensor {sensor.serial}: no equation-1 coefficients")

    def v(tag: str) -> float:
        return float((eq.findtext(tag) or "nan").strip())

    return cc.Oxygen43Coefficients(
        soc=v("Soc"), v_offset=v("offset"), tau_20=v("Tau20"),
        a=v("A"), b=v("B"), c=v("C"), e=v("E"),
        d0=v("D0"), d1=v("D1"), d2=v("D2"),
        h1=v("H1"), h2=v("H2"), h3=v("H3"),
    )  # fmt: skip


def eco_coefficients(sensor: XmlconSensor) -> cc.ECOCoefficients:
    """Return ECO coefficients (scale factor and dark output) for a fluorometer or turbidity meter.

    Parameters
    ----------
    sensor : XmlconSensor
        A ``FluoroWetlabECO_AFL_FL_Sensor`` (dark output ``Vblank``) or ``TurbidityMeter``
        (dark output ``DarkVoltage``).

    Returns
    -------
    seabirdscientific.cal_coefficients.ECOCoefficients
        ``slope`` = ScaleFactor and ``offset`` = the dark voltage, as
        ``convert_eco`` computes ``slope * (V - offset)``.
    """
    dark = sensor.text("Vblank")
    if dark is None:
        dark = sensor.text("DarkVoltage")
    if dark is None:
        raise KeyError(
            f"{sensor.element} {sensor.serial}: no dark output (Vblank/DarkVoltage)"
        )
    return cc.ECOCoefficients(slope=sensor.value("ScaleFactor"), offset=float(dark))


def altimeter_coefficients(sensor: XmlconSensor) -> cc.AltimeterCoefficients:
    """Return altimeter coefficients (ScaleFactor as ``slope``, Offset).

    Parameters
    ----------
    sensor : XmlconSensor
        An ``AltimeterSensor``.

    Returns
    -------
    seabirdscientific.cal_coefficients.AltimeterCoefficients
        The coefficients.
    """
    return cc.AltimeterCoefficients(
        slope=sensor.value("ScaleFactor"), offset=sensor.value("Offset")
    )


def cstar_coefficients(sensor: XmlconSensor) -> cc.CstarCoefficients:
    """Return WET Labs C-Star coefficients (M, B, path length in m).

    Parameters
    ----------
    sensor : XmlconSensor
        A ``WET_LabsCStar``.

    Returns
    -------
    seabirdscientific.cal_coefficients.CstarCoefficients
        The coefficients.
    """
    return cc.CstarCoefficients(
        m=sensor.value("M"), b=sensor.value("B"), path_length=sensor.value("PathLength")
    )
