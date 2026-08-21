"""Tests for sensor-provenance parsing and the sensor catalog in profiles.nc.

Exercised against the committed mixsed2 fixtures, which cover pH, a
transmissometer, a UVP6 user-polynomial channel, an empty-serial altimeter, a
Free channel, and the FLNTU recorded under two serial spellings (``3508`` on the
turbidity channel, ``FLNTURTD-3508`` on the fluorometer channel).
"""

from __future__ import annotations

import xarray as xr
from conftest import FIXTURES_NC

from ctdcast.config.sensors import SensorOverrides
from ctdcast.processors.profiles import build_profiles
from ctdcast.readers.metadata import parse_sensor_channels
from ctdcast.reports._sensors import read_sensor_tables


def _fixture_records() -> list[dict[str, str]]:
    ds = xr.open_dataset(FIXTURES_NC / "mixsed2_011.nc", engine="netcdf4")
    try:
        return parse_sensor_channels(ds)
    finally:
        ds.close()


def test_roles_derived_from_header_comments() -> None:
    """Each populated channel gets its canonical role from the CNV comment."""
    by_role = {r["role"]: r for r in _fixture_records() if r["role"]}
    assert by_role["temperature_1"]["element"] == "TemperatureSensor"
    assert by_role["temperature_2"]["sensor_id"] == "55"
    assert by_role["conductivity_2"]["role"] == "conductivity_2"
    assert by_role["ph"]["element"] == "pH_Sensor"
    assert by_role["transmissometer"]["element"] == "WET_LabsCStar"


def test_free_channel_has_no_role() -> None:
    """A ``Free`` channel is parsed with role None and an empty serial."""
    free = [r for r in _fixture_records() if r["role"] is None]
    assert free, "expected at least one Free channel in the fixture"
    assert all(r["serial"] == "" for r in free)


def test_turbidity_serial_recovered_from_header() -> None:
    """The turbidity channel's serial comes from the header, not the lossy dicts."""
    turb = next(r for r in _fixture_records() if r["role"] == "turbidity")
    assert turb["serial"] == "3508"
    assert turb["sensor_id"] == "67"


def test_profiles_carry_sensor_catalog(tmp_path) -> None:
    """build_profiles emits SENSOR_* catalog vars and sensor_<role> linkage."""
    out = tmp_path / "profiles.nc"
    build_profiles(FIXTURES_NC, out, force=True)
    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        catalog = [v for v in ds.variables if str(v).startswith("SENSOR_")]
        assert catalog, "no SENSOR_* catalog variables written"
        # pH sensor 339 resolves to SBE 18 from the package registry
        assert "SENSOR_PH_339" in ds.variables
        assert ds["SENSOR_PH_339"].attrs["sensor_model"] == "SBE 18"
        # linkage exists for a role present in the fixture
        assert "sensor_ph" in ds.variables
        assert "sensor_channel_ph" in ds.variables
        # the catalog variable is dimensionless
        assert ds["SENSOR_PH_339"].dims == ()
    finally:
        ds.close()


def test_serial_alias_collapses_shared_flntu(tmp_path) -> None:
    """With an alias, the FLNTU's two spellings resolve to one shared device.

    The fixture records the FLNTU as ``FLNTURTD-3508`` (fluorometer) and ``3508``
    (turbidity).  A cruise alias makes both roles cross-link via
    ``sensor_shared_with``.
    """
    ov = SensorOverrides.from_cruise_config(
        {"sensors": {"aliases": {"3508": "FLNTURTD-3508"}}}
    )
    out = tmp_path / "profiles.nc"
    build_profiles(FIXTURES_NC, out, force=True, sensor_overrides=ov)
    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        fl = "SENSOR_FLUOROMETER_FLNTURTD_3508"
        tu = "SENSOR_TURBIDITY_FLNTURTD_3508"
        assert fl in ds.variables and tu in ds.variables
        assert ds[fl].attrs.get("sensor_shared_with") == tu
        assert ds[tu].attrs.get("sensor_shared_with") == fl
    finally:
        ds.close()


def test_read_sensor_tables_builds_catalog_and_blocks(tmp_path) -> None:
    """read_sensor_tables assembles the catalog, config blocks and role columns.

    The four mixsed2 fixtures share one sensor configuration, so the change and
    rewiring logs are empty and the configuration collapses to a single block
    spanning casts 011–129.
    """
    out = tmp_path / "profiles.nc"
    build_profiles(FIXTURES_NC, out, force=True)
    m = read_sensor_tables(out)
    assert m["has_catalog"] is True
    assert m["n_casts"] == 4
    # roles the fixture exercises show up as configuration columns
    keys = {c["key"] for c in m["role_cols"]}
    assert {"temperature_1", "conductivity_2", "ph", "transmissometer"} <= keys
    # one shared configuration across the four fixture casts
    assert len(m["blocks"]) == 1
    assert m["blocks"][0]["cast_start"] == 11
    assert m["blocks"][0]["cast_end"] == 129
    assert m["changes"] == [] and m["rewiring"] == []
    # the pH sensor (serial 339) resolves to SBE 18 in the catalog
    ph = next(d for d in m["catalog"] if d["serial"] == "339")
    assert ph["model"] == "SBE 18"
    assert ph["roles"] == ["Ph"]


def test_read_sensor_tables_reports_read_error() -> None:
    """A missing/unreadable file returns an error rather than raising."""
    m = read_sensor_tables(FIXTURES_NC / "does_not_exist.nc")
    assert "error" in m
