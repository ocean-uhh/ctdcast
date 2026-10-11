"""Stage-3 preferred-sensor stamping and its flow into ``profiles.nc``.

Exercises the stamp (``stage3._stamp_preferred_sensors``) against a real per-cast catalog
— the ``mixsed2_011`` fixture, a dual-T/C, single-oxygen cast (``conductivity_1`` sits on
CNV channel 2, so these also guard the role-index-vs-channel distinction) — then the
per-profile aggregation and the compile-time validation.  The pure resolve/segment/validate
logic is covered in ``tests/config/test_preferred_sensors.py``; here we check the
dataset-facing behaviour: which attributes land, the single-sensor refuse, silent-absent,
the N_PROF variables, and the advisory warning.
"""

from __future__ import annotations

import warnings

import pytest
import xarray as xr
from conftest import FIXTURES_NC

from ctdcast.config.sensors import SensorOverrides
from ctdcast.processors.profiles import (
    build_profiles,
    validate_preferred_against_catalog,
)
from ctdcast.processors.stage1 import _build_cast_sensor_catalog
from ctdcast.processors.stage3 import (
    _build_preferred_composites,
    _stamp_preferred_sensors,
)

# The fixture's resolved catalog names (see _build_cast_sensor_catalog on mixsed2_011).
T1, T2 = "SENSOR_TEMPERATURE_6435", "SENSOR_TEMPERATURE_6000"
C1, C2 = "SENSOR_CONDUCTIVITY_4922", "SENSOR_CONDUCTIVITY_3120"
O1 = "SENSOR_OXYGEN_0707"
CAST = 11


def _catalog_ds() -> xr.Dataset:
    """The mixsed2_011 fixture with its per-cast SENSOR_* catalog built (stage-1 step)."""
    ds = xr.open_dataset(FIXTURES_NC / "mixsed2_011.nc", engine="netcdf4")
    return _build_cast_sensor_catalog(ds, SensorOverrides())


def test_pair_default_primary_stamps_primary_sensors() -> None:
    ds = _catalog_ds()
    _stamp_preferred_sensors(ds, {"preferred_pair": {"default": "primary"}}, CAST)
    assert ds.attrs["preferred_pair"] == "primary"
    assert ds.attrs["sensor_temperature_preferred"] == T1
    assert ds.attrs["sensor_conductivity_preferred"] == C1


def test_pair_default_secondary_stamps_secondary_sensors() -> None:
    ds = _catalog_ds()
    _stamp_preferred_sensors(ds, {"preferred_pair": {"default": "secondary"}}, CAST)
    assert ds.attrs["preferred_pair"] == "secondary"
    assert ds.attrs["sensor_temperature_preferred"] == T2
    assert ds.attrs["sensor_conductivity_preferred"] == C2


def test_pair_range_overrides_default() -> None:
    cfg = {
        "preferred_pair": {
            "default": "primary",
            "ranges": [{"casts": [[11, 11]], "use": "secondary"}],
        }
    }
    ds = _catalog_ds()
    _stamp_preferred_sensors(ds, cfg, CAST)
    assert ds.attrs["preferred_pair"] == "secondary"
    assert ds.attrs["sensor_temperature_preferred"] == T2


def test_single_oxygen_cast_gets_no_preferred_oxygen() -> None:
    # The fixture has one oxygen sensor (catalog role oxygen_1, data var the plain
    # ctd_oxygen). There is no primary-vs-secondary choice, so even a cruise-wide
    # default: primary must NOT stamp preferred_oxygen, and ctd_oxygen is left untouched.
    ds = _catalog_ds()
    oxy_before = ds["ctd_oxygen"].values.copy()
    _stamp_preferred_sensors(ds, {"preferred_oxygen": {"default": "primary"}}, CAST)
    assert "preferred_oxygen" not in ds.attrs
    assert "sensor_oxygen_preferred" not in ds.attrs
    assert (ds["ctd_oxygen"].values == oxy_before).all()


def test_explicit_range_naming_absent_secondary_oxygen_raises() -> None:
    # The cast has only oxygen_1; an explicit range asking for secondary is an error.
    cfg = {"preferred_oxygen": {"ranges": [{"casts": [[11, 11]], "use": "secondary"}]}}
    ds = _catalog_ds()
    with pytest.raises(ValueError, match="no secondary sensor"):
        _stamp_preferred_sensors(ds, cfg, CAST)


def test_cruise_wide_default_on_single_oxygen_is_silent_absent() -> None:
    # A cruise-wide default landing on a cast lacking that channel: no attribute, no raise.
    ds = _catalog_ds()
    _stamp_preferred_sensors(ds, {"preferred_oxygen": {"default": "secondary"}}, CAST)
    assert "preferred_oxygen" not in ds.attrs
    assert "sensor_oxygen_preferred" not in ds.attrs


def test_undeclared_leaves_no_preferred_attributes() -> None:
    ds = _catalog_ds()
    _stamp_preferred_sensors(ds, {}, CAST)
    assert not any(k.startswith("preferred_") for k in ds.attrs)
    assert not any(k.endswith("_preferred") for k in ds.attrs)


def test_out_of_set_value_raises() -> None:
    ds = _catalog_ds()
    with pytest.raises(ValueError, match="not one of"):
        _stamp_preferred_sensors(ds, {"preferred_pair": {"default": "secundary"}}, CAST)


# --- composites (per-cast selection) -----------------------------------------


def test_composites_copy_the_preferred_pair_channel() -> None:
    # Dual T/C fixture, preferred_pair=secondary -> plain composites equal the _2 channel.
    ds = _catalog_ds()
    cfg = {"preferred_pair": {"default": "secondary"}}
    _build_preferred_composites(ds, cfg, CAST)
    import numpy as np

    assert np.array_equal(ds["ctd_temperature"].values, ds["ctd_temperature_2"].values)
    assert np.array_equal(ds["ctd_salinity"].values, ds["ctd_salinity_2"].values)
    assert np.array_equal(ds["conductivity"].values, ds["conductivity_2"].values)
    # Provenance recorded on the composite.
    assert "secondary" in ds["ctd_temperature"].attrs["comment"]
    # The composite is a selection, not a renamed source column: it must NOT carry the
    # source channel's CNV-origin attrs (they key the rename table and would collide).
    assert "cnv_original_name" not in ds["conductivity"].attrs
    assert "source_variable" not in ds["conductivity"].attrs
    # but it stays self-describing (units survive).
    assert ds["conductivity"].attrs.get("units") == "mS cm-1"


def test_undeclared_dual_cast_gets_no_composite() -> None:
    # No declaration -> no plain composite built (never a silent _1 fallback).
    ds = _catalog_ds()
    assert "ctd_temperature" not in ds  # fixture is dual T/C, no native plain name
    _build_preferred_composites(ds, {}, CAST)
    assert "ctd_temperature" not in ds
    assert "ctd_salinity" not in ds


# --- flow into profiles.nc ---------------------------------------------------


def test_preferred_vars_land_per_profile_in_profiles_nc(tmp_path) -> None:
    """Stamped choices aggregate to N_PROF variables; a per-cast flip shows per profile."""
    cfg = {
        "preferred_pair": {
            "default": "primary",
            "ranges": [{"casts": [[12, 12]], "use": "secondary"}],
        }
    }
    for f in sorted(FIXTURES_NC.glob("mixsed2_01[12].nc")):
        ds = _build_cast_sensor_catalog(
            xr.open_dataset(f, engine="netcdf4"), SensorOverrides()
        )
        _stamp_preferred_sensors(ds, cfg, int(ds.attrs["cast_id"]))
        ds.to_netcdf(tmp_path / f.name)
    out = tmp_path / "profiles.nc"
    build_profiles(tmp_path, out, force=True, cruise_cfg=cfg)
    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        assert ds["preferred_pair"].dims == ("N_PROF",)
        words = [str(x) for x in ds["preferred_pair"].values]
        # cast 11 -> profiles 0,1 (primary); cast 12 -> profiles 2,3 (secondary).
        assert words[0] == "primary"
        assert words[2] == "secondary"
        temp_pref = [str(x) for x in ds["sensor_temperature_preferred"].values]
        assert temp_pref[0] == T1
        assert temp_pref[2] == T2
        # Oxygen was never declared -> no oxygen preferred variables at all.
        assert "preferred_oxygen" not in ds.variables
        assert "sensor_oxygen_preferred" not in ds.variables
    finally:
        ds.close()


def test_sensor_page_does_not_treat_preferred_vars_as_roles(tmp_path) -> None:
    """The sensor catalog page must not read `sensor_<role>_preferred` as a role."""
    from ctdcast.reports._sensors import read_sensor_tables

    cfg = {"preferred_pair": {"default": "secondary"}}
    for f in sorted(FIXTURES_NC.glob("mixsed2_01[12].nc")):
        ds = _build_cast_sensor_catalog(
            xr.open_dataset(f, engine="netcdf4"), SensorOverrides()
        )
        _stamp_preferred_sensors(ds, cfg, int(ds.attrs["cast_id"]))
        ds.to_netcdf(tmp_path / f.name)
    out = tmp_path / "profiles.nc"
    build_profiles(tmp_path, out, force=True, cruise_cfg=cfg)
    tables = read_sensor_tables(out)
    assert not [c for c in tables["role_cols"] if c["key"].endswith("_preferred")]
    # The genuine roles are still present.
    assert any(c["key"] == "temperature_1" for c in tables["role_cols"])


def test_undeclared_cruise_adds_no_preferred_variables(tmp_path) -> None:
    """With no declaration, profiles.nc gains no preferred variables (undeclared = absent)."""
    for f in sorted(FIXTURES_NC.glob("mixsed2_01[12].nc")):
        ds = _build_cast_sensor_catalog(
            xr.open_dataset(f, engine="netcdf4"), SensorOverrides()
        )
        ds.to_netcdf(tmp_path / f.name)
    out = tmp_path / "profiles.nc"
    build_profiles(tmp_path, out, force=True, cruise_cfg={})
    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        assert not [v for v in ds.variables if str(v).startswith("preferred_")]
        assert not [v for v in ds.variables if str(v).endswith("_preferred")]
    finally:
        ds.close()


def _rec(role: str, name: str) -> dict:
    return {"role": role, "name": name, "channel": 0, "attrs": {}}


def test_read_catalog_by_cast_reads_each_cast_via_best_available(tmp_path) -> None:
    """ctdcast validate's catalog reader returns one record set per cast, keyed by number."""
    from ctdcast.cli.validate import _read_catalog_by_cast

    for f in sorted(FIXTURES_NC.glob("mixsed2_01[12].nc")):
        _build_cast_sensor_catalog(
            xr.open_dataset(f, engine="netcdf4"), SensorOverrides()
        ).to_netcdf(tmp_path / f.name)
    warns: list[str] = []
    got = _read_catalog_by_cast(tmp_path, warns)
    assert set(got) == {11, 12}
    assert warns == []
    assert any(r["role"] == "temperature_1" for r in got[11])


def test_validate_against_catalog_returns_range_crossing_message() -> None:
    """The shared validator RETURNS the message when a range crosses a swap (pure; no warn)."""
    # Hardware swaps at cast 3 (primary temperature serial), but the range is 1-4.
    seg_a = [
        _rec("temperature_1", "SENSOR_TEMPERATURE_A"),
        _rec("conductivity_1", "C_A"),
        _rec("temperature_2", "T_B"),
        _rec("conductivity_2", "C_B"),
    ]
    seg_b = [
        _rec("temperature_1", "SENSOR_TEMPERATURE_A2"),
        _rec("conductivity_1", "C_A"),
        _rec("temperature_2", "T_B"),
        _rec("conductivity_2", "C_B"),
    ]
    catalog_by_cast = {1: seg_a, 2: seg_a, 3: seg_b, 4: seg_b}
    cfg = {"preferred_pair": {"ranges": [{"casts": [[1, 4]], "use": "secondary"}]}}
    # The wrapper is pure: it returns messages and emits nothing (callers choose emission).
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        msgs = validate_preferred_against_catalog(cfg, catalog_by_cast)
    assert any("crosses the hardware segment" in m for m in msgs)
