"""One sensor-catalog predicate, the sensors-page role selection, and override lookup."""

from ctdcast.config.parameters import color_limit_override
from ctdcast.config.sensors import is_sensor_catalog_var
from ctdcast.reports._sensors import _linkage_roles
from ctdcast.reports.design import is_sensor


def test_catalog_predicate_excludes_qc_and_linkage():
    assert is_sensor_catalog_var("SENSOR_TEMPERATURE_6435")
    assert not is_sensor_catalog_var("SENSOR_TEMPERATURE_6435_qc")
    assert not is_sensor_catalog_var("sensor_temperature_1")
    assert not is_sensor_catalog_var("sensor_channel_temperature_1")
    assert is_sensor("SENSOR_PH_339") and not is_sensor("SENSOR_PH_339_qc")


def test_linkage_roles_are_selected_by_inclusion():
    names = [
        "sensor_temperature_1",
        "sensor_channel_temperature_1",
        "sensor_temperature_preferred",
        "sensor_conductivity_preferred",
        "sensor_oxygen_1",
        "sensor_newthing",  # unlisted role, but it has a channel twin
        "sensor_channel_newthing",
        "sensor_mystery",  # unlisted, no channel twin: not a role
    ]
    assert _linkage_roles(names) == ["temperature_1", "oxygen_1", "newthing"]


def test_color_limit_override_accepts_either_sensor_form():
    assert (
        color_limit_override({"ctd_oxygen_1": 50.0}, "ctd_oxygen", "ctd_oxygen") == 50.0
    )
    assert (
        color_limit_override({"ctd_oxygen": 40.0}, "ctd_oxygen", "ctd_oxygen_1") == 40.0
    )
    both = {"ctd_oxygen": 40.0, "ctd_oxygen_1": 50.0}
    assert color_limit_override(both, "ctd_oxygen", "ctd_oxygen_1") == 50.0
    assert color_limit_override({}, "ctd_oxygen", "ctd_oxygen") is None
