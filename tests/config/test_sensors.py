"""Tests for the sensor-provenance registry and override resolution.

Cover the three-step resolution (SensorID default -> role override -> alias),
the never-guess fallback, and the serial hazards from the design note.
"""

from __future__ import annotations

import warnings

import pytest

from ctdcast.config.sensors import (
    SensorOverrides,
    SensorRegistry,
    catalog_var_name,
    resolve_sensor,
    sanitize_serial,
)


def _registry() -> SensorRegistry:
    """The real package registry (ships with ctdcast)."""
    return SensorRegistry.load()


def test_registry_loads_known_sensor_ids() -> None:
    """The package YAML resolves the SensorIDs the design note enumerates."""
    reg = _registry()
    known = (
        "55",
        "3",
        "45",
        "38",
        "0",
        "20",
        "67",
        "71",
        "43",
        "61",
        "11",
        "13",
        "42",
        "51",
        "46",
        "58",
    )
    for sid in known:
        assert reg.default_for(sid) is not None, f"SensorID {sid} missing"
    assert reg.default_for("999") is None


def test_registry_default_is_a_copy() -> None:
    """Mutating a returned default must not corrupt the shared table."""
    reg = _registry()
    d = reg.default_for("55")
    d["sensor_model"] = "TAMPERED"
    assert reg.default_for("55")["sensor_model"] == "SBE 3plus"


def test_known_sensor_resolves_from_registry_alone() -> None:
    """A confident SensorID needs no override and does not warn."""
    reg = _registry()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        attrs = resolve_sensor(
            sensor_id="55",
            serial="4823",
            role="temperature_1",
            calibration_date="2021-05-07",
            element="TemperatureSensor",
            registry=reg,
        )
    assert attrs["sensor_model"] == "SBE 3plus"
    assert attrs["sensor_serial_number"] == "4823"
    assert attrs["sensor_calibration_date"] == "2021-05-07"
    assert attrs["sbe_sensor_id"] == "55"
    assert attrs["sbe_sensor_element"] == "TemperatureSensor"
    assert attrs["model_source"] == "assumed"


def test_role_override_sharpens_generic_default() -> None:
    """A cruise override replaces present fields and inherits absent ones."""
    reg = _registry()
    ov = SensorOverrides.from_cruise_config(
        {
            "sensors": {
                "overrides": {
                    "fluorometer": {
                        "sensor_model": "WET Labs ECO FLNTU(RT)D",
                        "sensor_model_vocabulary": "https://vocab.nerc.ac.uk/collection/L22/current/TOOL1531/",
                        "model_source": "operator",
                    }
                }
            }
        }
    )
    attrs = resolve_sensor(
        sensor_id="20",
        serial="FLNTURTD-3219",
        role="fluorometer",
        registry=reg,
        overrides=ov,
    )
    assert attrs["sensor_model"] == "WET Labs ECO FLNTU(RT)D"
    assert attrs["model_source"] == "operator"
    # inherited from the SensorID 20 default, not set by the override:
    assert attrs["sensor_type"] == "fluorometers"
    assert attrs["sensor_maker"] == "WET Labs"


def test_altimeter_unresolved_warns_but_does_not_raise() -> None:
    """SensorID 0 with no override -> UNK + loud warning, build continues."""
    reg = _registry()
    with pytest.warns(UserWarning, match=r"sensors\.overrides\.altimeter"):
        attrs = resolve_sensor(
            sensor_id="0",
            serial="42299",
            role="altimeter",
            registry=reg,
        )
    assert attrs["sensor_model"] == "UNK"
    assert attrs["model_source"] == "UNK"


def test_altimeter_resolved_by_override() -> None:
    """The cruise override turns the UNK altimeter into a real model."""
    reg = _registry()
    ov = SensorOverrides.from_cruise_config(
        {
            "sensors": {
                "overrides": {
                    "altimeter": {
                        "sensor_model": "Benthos PSA-916T",
                        "sensor_model_vocabulary": "https://vocab.nerc.ac.uk/collection/L22/current/TOOL0134/",
                        "sensor_maker": "Teledyne Benthos",
                        "model_source": "operator",
                    }
                }
            }
        }
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        attrs = resolve_sensor(
            sensor_id="0",
            serial="42299",
            role="altimeter",
            registry=reg,
            overrides=ov,
        )
    assert attrs["sensor_model"] == "Benthos PSA-916T"
    assert attrs["sensor_maker"] == "Teledyne Benthos"


def test_cruise_override_fills_unknown_sensor_id_silently() -> None:
    """A role override resolves a SensorID the package table lacks, with no warning.

    SensorID 999 is not in the shipped registry; a cruise
    ``sensors.overrides.temperature_1`` fills it, and because the gap is filled
    the resolver must not warn.
    """
    reg = _registry()
    assert reg.default_for("999") is None  # genuinely absent from the package table
    ov = SensorOverrides.from_cruise_config(
        {
            "sensors": {
                "overrides": {
                    "temperature_1": {
                        "sensor_model": "SBE 3F",
                        "sensor_model_vocabulary": "https://vocab.nerc.ac.uk/collection/L22/current/TOOL0418/",
                        "sensor_maker": "Sea-Bird Scientific",
                        "sensor_type": "water temperature sensor",
                        "model_source": "operator",
                    }
                }
            }
        }
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning fails the test
        attrs = resolve_sensor(
            sensor_id="999",
            serial="7321",
            role="temperature_1",
            registry=reg,
            overrides=ov,
        )
    assert attrs["sensor_model"] == "SBE 3F"
    assert attrs["model_source"] == "operator"


def test_unknown_sensor_id_without_override_still_warns() -> None:
    """An unknown SensorID with no override falls back to UNK and warns."""
    reg = _registry()
    with pytest.warns(UserWarning, match="Unknown SeaBird SensorID"):
        attrs = resolve_sensor(
            sensor_id="999", serial="7321", role="temperature_1", registry=reg
        )
    assert attrs["sensor_model"] == "UNK"


def test_strict_raises_on_unresolved() -> None:
    """strict=True turns the UNK fallback into a hard failure."""
    reg = _registry()
    with pytest.raises(ValueError, match="not resolved"):
        resolve_sensor(
            sensor_id="0", serial="42299", role="altimeter", registry=reg, strict=True
        )


def test_unknown_sensor_id_warns_and_returns_unk() -> None:
    """An unregistered SensorID warns and falls back to UNK, never guesses."""
    reg = _registry()
    with pytest.warns(UserWarning, match="Unknown SeaBird SensorID"):
        attrs = resolve_sensor(
            sensor_id="999", serial="1", role="mystery", registry=reg
        )
    assert attrs["sensor_model"] == "UNK"


def test_non_string_serial_rejected() -> None:
    """A leading-zero serial read as an int must be refused, not coerced."""
    reg = _registry()
    with pytest.raises(TypeError, match="serial must be a str"):
        resolve_sensor(sensor_id="45", serial=410, role="pressure", registry=reg)  # type: ignore[arg-type]


def test_role_serial_override_beats_bare_role() -> None:
    """A role:serial key is more specific than the bare role key."""
    ov = SensorOverrides.from_cruise_config(
        {
            "sensors": {
                "overrides": {
                    "altimeter": {"sensor_model": "Generic"},
                    "altimeter:42299": {"sensor_model": "Specific"},
                }
            }
        }
    )
    assert ov.for_role("altimeter", "42299")["sensor_model"] == "Specific"
    assert ov.for_role("altimeter", "99999")["sensor_model"] == "Generic"


def test_alias_resolves_role_serial_key() -> None:
    """A serial alias lets a role:serial override match either spelling."""
    ov = SensorOverrides.from_cruise_config(
        {
            "sensors": {
                "overrides": {"turbidity:FLNTURTD-3508": {"sensor_model": "Combined"}},
                "aliases": {"3508": "FLNTURTD-3508"},
            }
        }
    )
    assert ov.canonical_serial("3508") == "FLNTURTD-3508"
    assert ov.for_role("turbidity", "3508")["sensor_model"] == "Combined"


def test_catalog_var_name_and_sanitize() -> None:
    """Catalog names follow SENSOR_<TYPE>_<INDEX>_<SERIAL> with OG1-style sanitizing."""
    assert catalog_var_name("temperature_1", "5806") == "SENSOR_TEMPERATURE_1_5806"
    assert catalog_var_name("conductivity_2", "4062") == "SENSOR_CONDUCTIVITY_2_4062"
    assert (
        catalog_var_name("fluorometer", "FLNTURTD-3219")
        == "SENSOR_FLUOROMETER_1_FLNTURTD_3219"
    )
    assert sanitize_serial("FLNTURTD-3219") == "FLNTURTD_3219"


def test_element_mismatch_warns() -> None:
    """A CNV element disagreeing with the registry element warns."""
    reg = _registry()
    with pytest.warns(UserWarning, match="disagrees with registry element"):
        resolve_sensor(
            sensor_id="55",
            serial="1",
            role="temperature_1",
            element="TurbidityMeter",
            registry=reg,
        )
