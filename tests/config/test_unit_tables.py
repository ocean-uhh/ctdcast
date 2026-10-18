"""Tests for ctdcast.config.unit_tables — ctdcast's view of the vendored units tables.

The registry pin keeps every ``VARIABLES["units"]`` equal to the canonical the shared tables
record for its quantity (so a non-canonical spelling cannot enter the registry unnoticed); the
remaining tests fix the no-standard-name entries explicitly, keep every display unit routed
through the one call site, and keep the package's alias additions evidenced.
"""

from __future__ import annotations

from pathlib import Path

from ctdcast.config import unit_tables as cu
from ctdcast.config.parameters import VARIABLES

_PKG = Path(__file__).resolve().parents[2] / "ctdcast"

#: Registry entries that carry no CF ``standard_name`` — raw voltages, SBE engineering
#: channels, timing, and the derived diagnostics CF has no name for.  Listed so that adding
#: one (which drops it out of the ``TABLES.canonical`` pin below) is a deliberate change, not a
#: silent gap in the units guard.
_NO_STANDARD_NAME = {
    "AOU",
    "Turner",
    "oxygen_raw_1",
    "oxygen_raw_2",
    "oxygen_saturation",
    "par",
    "sbe_density",
    "sbe_depth",
    "sbe_flag",
    "sbe_oxygen_saturation_1",
    "sbe_oxygen_saturation_2",
    "sbe_scan",
    "sbe_speed_of_sound",
    "sbe_timeJ",
    "sbe_timeS",
    "spar",
    "transmissometer",
    *{f"volt{n}_raw" for n in range(8)},
}

#: Golden display label per registry variable.  The vendored-table move must be label-neutral,
#: so this pins every rendered unit to what ctdcast showed before it; a change here is a real
#: change to an axis or table caption and must be intended.
_LABEL_GOLDEN = {
    "pressure": "dbar",
    "latitude": "°N",
    "longitude": "°E",
    "ctd_temperature_1": "°C",
    "ctd_temperature_2": "°C",
    "ctd_temperature": "°C",
    "conductivity": "mS/cm",
    "conductivity_1": "mS/cm",
    "conductivity_2": "mS/cm",
    "ctd_salinity_1": "PSU",
    "ctd_salinity_2": "PSU",
    "ctd_salinity": "PSU",
    "ctd_oxygen_1": "µmol/kg",
    "ctd_oxygen_2": "µmol/kg",
    "ctd_oxygen": "µmol/kg",
    "oxygen_saturation": "%",
    "ctd_fluor": "mg/m³",
    "ctd_turbidity": "NTU",
    "ctd_altimeter": "m",
    "sbe_density": "kg/m³",
    "sbe_speed_of_sound": "m/s",
    "sbe_depth": "m",
    "sbe_timeJ": "day",
    "sbe_timeS": "s",
    "sbe_flag": "1",
    "sbe_scan": "1",
    "sbe_oxygen_saturation_1": "%",
    "sbe_oxygen_saturation_2": "%",
    "oxygen_raw_1": "V",
    "oxygen_raw_2": "V",
    "transmissometer": "%",
    "par": "µmol m⁻² s⁻¹",
    "spar": "µmol m⁻² s⁻¹",
    **{f"volt{n}_raw": "V" for n in range(8)},
    "conservative_temperature": "°C",
    "absolute_salinity": "g/kg",
    "sigma0": "kg/m³",
    "AOU": "µmol/kg",
    "U": "m/s",
    "V": "m/s",
    "N2": "rad²/s²",
    "Turner": "°",
}


def test_registry_units_pinned_to_tables_canonical():
    """Every registry entry with a standard_name stores the canonical the tables record."""
    offenders = {}
    for name, entry in VARIABLES.items():
        sn = entry.get("standard_name")
        if not sn:
            continue
        expected = cu.TABLES.canonical.get(sn)
        if entry.get("units") != expected:
            offenders[name] = (entry.get("units"), expected)
    assert offenders == {}, (
        f"registry units disagree with TABLES.canonical: {offenders}"
    )


def test_no_standard_name_entries_are_the_listed_set():
    """The entries without a standard_name are exactly the explicit list (adding one is loud)."""
    actual = {name for name, e in VARIABLES.items() if not e.get("standard_name")}
    assert actual == _NO_STANDARD_NAME


def test_every_standard_name_has_a_canonical():
    """Each registry standard_name is known to the tables, so the pin above is total."""
    missing = sorted(
        sn
        for e in VARIABLES.values()
        if (sn := e.get("standard_name")) and sn not in cu.TABLES.canonical
    )
    assert missing == [], f"standard_names with no canonical in TABLES: {missing}"


def test_unit_label_is_label_neutral_over_the_registry():
    """Every rendered display unit equals its golden — the vendored move changed no label."""
    actual = {
        name: cu.unit_label(e.get("units", ""), e.get("standard_name"))
        for name, e in VARIABLES.items()
    }
    assert actual == _LABEL_GOLDEN


def test_registry_standard_names_maps_every_named_entry():
    """registry_standard_names() carries exactly the entries that declare a standard_name."""
    mapping = cu.registry_standard_names()
    expected = {
        name: e["standard_name"]
        for name, e in VARIABLES.items()
        if e.get("standard_name")
    }
    assert mapping == expected


def test_unit_alias_extras_entries_are_evidenced():
    """Each UNIT_ALIAS_EXTRAS canonical key carries an evidence comment directly above it."""
    lines = (
        (_PKG / "config" / "unit_tables.py").read_text(encoding="utf-8").splitlines()
    )
    start = next(i for i, ln in enumerate(lines) if ln.startswith("UNIT_ALIAS_EXTRAS"))
    unevidenced = []
    for canonical in cu.UNIT_ALIAS_EXTRAS:
        key_line = next(
            i
            for i, ln in enumerate(lines[start:], start)
            if ln.strip().startswith(f'"{canonical}":')
        )
        if not lines[key_line - 1].strip().startswith("#"):
            unevidenced.append(canonical)
    assert unevidenced == [], (
        f"UNIT_ALIAS_EXTRAS entries with no evidence comment: {unevidenced}"
    )


def test_format_units_is_called_only_from_config_units():
    """Outside the vendored layer, ``format_units(`` is called only in ``config/unit_tables.py``.

    Every display unit routes through ``config.unit_tables.unit_label`` (which the plot path and
    ``reports.design`` both use), so a package override reaches every axis and table; a direct
    ``format_units(`` elsewhere would bypass ctdcast's ``TABLES``.
    """
    callers = sorted(
        p.relative_to(_PKG).as_posix()
        for p in _PKG.rglob("*.py")
        if "_vendored" not in p.parts
        and "format_units(" in p.read_text(encoding="utf-8")
    )
    assert callers == ["config/unit_tables.py"], (
        f"format_units() called outside config/units: {callers}"
    )
