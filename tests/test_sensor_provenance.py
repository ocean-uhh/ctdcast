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


def test_records_carry_slope_and_offset() -> None:
    """Each channel record carries its Slope/Offset, read from the same block as the role.

    This is what lets the stage-1 catalog stamp calibration without a second parse: the
    pressure sensor in this fixture has an applied span correction (slope 1.00004096), the
    temperature sensors are identity. The pH channel shows the raw parse keeps every
    channel's native Slope (0.3368) — the frequency-only drift filtering is the consumer's
    job (:func:`sensor_calibrations`), not this reader's.
    """
    by_role = {r["role"]: r for r in _fixture_records() if r["role"]}
    assert by_role["pressure"]["slope"] == "1.00004096"
    assert by_role["pressure"]["offset"] == "0.27440"
    assert by_role["temperature_1"]["slope"] == "1.00000000"
    assert by_role["ph"]["slope"] == "0.3368"  # native cal, carried verbatim


def _cast_catalog() -> xr.Dataset:
    """The mixsed2_011 fixture with its per-cast sensor catalog built (stage-1 step)."""
    from ctdcast.processors.stage1 import _build_cast_sensor_catalog

    ds = xr.open_dataset(FIXTURES_NC / "mixsed2_011.nc", engine="netcdf4")
    return _build_cast_sensor_catalog(ds, SensorOverrides())


def test_cast_catalog_links_variables_to_existing_sensors() -> None:
    """Each data variable's ``sensor`` names a SENSOR_* variable, which holds role and channel."""
    out = _cast_catalog()
    linked = {
        v: out[v].attrs["sensor"] for v in out.data_vars if "sensor" in out[v].attrs
    }
    assert linked, "no data variable was linked to a sensor"
    for var, sensor in linked.items():
        assert sensor in out.variables, f"{var}.sensor={sensor} is a dangling reference"
        # Role and channel live on the catalog entry, not the variable.
        assert out[sensor].attrs["sensor_role"]
        assert isinstance(out[sensor].attrs["sensor_channel"], int)


def test_linked_variable_carries_only_the_sensor_link() -> None:
    """One link out: a mapped data variable carries ``sensor`` and no other ``sensor*`` attr.

    Asserts the absence so the old placement — ``sensor_role``/``sensor_channel`` on the data
    variable — cannot creep back. Those facts belong on the SENSOR_* entry.
    """
    out = _cast_catalog()
    linked = [v for v in out.data_vars if "sensor" in out[v].attrs]
    assert linked, "no data variable was linked to a sensor"
    for var in linked:
        extra = [k for k in out[var].attrs if k.startswith("sensor") and k != "sensor"]
        assert not extra, f"{var} carries stray sensor attrs {extra}"


def test_cast_catalog_data_values_unchanged() -> None:
    """Building the catalog stamps attributes only; no data value changes."""
    import numpy as np

    before = xr.open_dataset(FIXTURES_NC / "mixsed2_011.nc", engine="netcdf4")
    after = _cast_catalog()
    for v in before.data_vars:
        assert np.array_equal(after[v].values, before[v].values, equal_nan=True)


def test_frequency_sensor_carries_slope_offset_voltage_does_not() -> None:
    """A T/C/P sensor carries its drift Slope/Offset; a voltage sensor does not."""
    out = _cast_catalog()
    pres = out["SENSOR_PRESSURE_0814"].attrs
    assert pres["sensor_calibration_slope"] == "1.00004096"
    assert pres["sensor_calibration_offset"] == "0.27440"
    # oxygen is a voltage sensor: its native Slope is not a datcnv drift knob, so absent
    assert "sensor_calibration_slope" not in out["SENSOR_OXYGEN_0707"].attrs


def test_single_sensor_role_survives_suffix_stripping() -> None:
    """A single-oxygen cast stores ``ctd_oxygen`` but the entry keeps ``sensor_role='oxygen_1'``.

    ``_normalise`` strips the ``_1`` from the variable name, so the role — which Phase-2
    aggregation rebuilds the linkage from — must be stored on the SENSOR_* entry, not
    re-derived from the (now suffix-stripped) variable name.
    """
    out = _cast_catalog()
    assert "ctd_oxygen" in out and "ctd_oxygen_1" not in out
    assert out["ctd_oxygen"].attrs["sensor"] == "SENSOR_OXYGEN_0707"
    assert out["SENSOR_OXYGEN_0707"].attrs["sensor_role"] == "oxygen_1"


def test_role_without_a_variable_is_catalogued_with_role_and_channel() -> None:
    """A pH/transmissometer sensor gets a full catalog entry, but no variable links to it.

    These have no stored ctdcast variable, so nothing carries ``sensor=`` to them. Because role
    and channel live on the entry — not on a data variable that here does not exist — the entry
    still records both; this is the regression that motivated moving them off the variable. No
    "dropped a channel" warning fires (that warning is only for a role whose variable ctdcast
    *does* define but the reader dropped).
    """
    import warnings

    ds = xr.open_dataset(FIXTURES_NC / "mixsed2_011.nc", engine="netcdf4")
    from ctdcast.processors.stage1 import _build_cast_sensor_catalog

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = _build_cast_sensor_catalog(ds, SensorOverrides())
    assert "SENSOR_PH_339" in out.variables  # catalogued
    assert out["SENSOR_PH_339"].attrs["sensor_role"] == "ph"
    assert isinstance(out["SENSOR_PH_339"].attrs["sensor_channel"], int)
    assert not [
        v
        for v in out.data_vars
        if "sensor" in out[v].attrs and out[v].attrs["sensor"] == "SENSOR_PH_339"
    ]
    assert not [
        w for w in caught if "ph" in str(w.message) and "dropped" in str(w.message)
    ]


def test_build_profiles_compiles_catalog_bearing_casts(tmp_path) -> None:
    """build_profiles handles per-cast files that carry the stage-1 sensor catalog.

    The ``SENSOR_*`` scalars are not griddable columns: build_profiles must skip them (a
    regression guard — they previously crashed ``_bin_to_grid``) and must not leak the
    per-cast ``sensor=`` link onto the compiled variables (that is a per-profile fact, held
    by the linkage variables, never a file-level attribute).
    """
    from ctdcast.processors.stage1 import _build_cast_sensor_catalog

    for f in sorted(FIXTURES_NC.glob("mixsed2_*.nc")):
        ds = xr.open_dataset(f, engine="netcdf4")
        _build_cast_sensor_catalog(ds, SensorOverrides()).to_netcdf(tmp_path / f.name)
    out = tmp_path / "profiles.nc"
    build_profiles(tmp_path, out, force=True)
    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        assert ds["ctd_temperature_1"].dims == (
            "N_PROF",
            "pressure",
        )  # binned, not scalar
        assert "sensor" not in ds["ctd_temperature_1"].attrs  # no per-cast link leaked
        # Every catalog entry in profiles.nc is a dimensionless scalar; a >0-d SENSOR_*
        # would be a leaked all-NaN column (a per-cast scalar that reached the binning grid).
        for v in ds.variables:
            if str(v).startswith("SENSOR_"):
                assert ds[v].ndim == 0, f"{v} leaked into the profile grid"
    finally:
        ds.close()


def test_build_profiles_does_not_leak_alias_mismatched_catalog(tmp_path) -> None:
    """A SENSOR_* whose stage-1 name the compile path does not reproduce is not written.

    When stage 1 resolves a serial alias that ``build_profiles`` is not given, the per-cast
    ``SENSOR_<aliased>`` name differs from the compile-time ``SENSOR_<raw>``. The stage-1
    scalar must still be excluded by shape, not silently written as a bogus gridded variable.
    """
    from ctdcast.processors.stage1 import _build_cast_sensor_catalog

    # Build the per-cast catalogs with an alias so their SENSOR_ names differ from the
    # names build_profiles (given no alias) will re-derive from the headers.
    aliased = SensorOverrides(aliases={"3508": "ZZZ9999"})
    for f in sorted(FIXTURES_NC.glob("mixsed2_*.nc")):
        ds = xr.open_dataset(f, engine="netcdf4")
        _build_cast_sensor_catalog(ds, aliased).to_netcdf(tmp_path / f.name)
    out = tmp_path / "profiles.nc"
    build_profiles(tmp_path, out, force=True)  # no aliases here → names diverge
    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        for v in ds.variables:
            if str(v).startswith("SENSOR_"):
                assert ds[v].ndim == 0, f"{v} leaked as a gridded variable"
    finally:
        ds.close()


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
