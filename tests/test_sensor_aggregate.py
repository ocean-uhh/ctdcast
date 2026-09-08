"""Compile-time behaviour of the sensor-catalog aggregation in build_profiles.

Distinct from ``test_sensor_provenance.py`` (which covers header parsing and the
per-cast catalog): this module exercises the *merge* build_profiles performs over
per-cast catalogs — the two-provenance conflict warnings, and the catalog-less
split (the library warns and stamps; the pipeline driver refuses).

The behaviour tests run off the committed ``.nc`` fixtures and are not gated. The
final end-to-end contract test drives the real stage-1 → compile path and so is
gated on ``seasenselib`` inline, leaving the rest of the module runnable without it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import xarray as xr
from conftest import FIXTURES_CNV, FIXTURES_NC

from ctdcast.processors import process
from ctdcast.processors.profiles import build_profiles
from ctdcast.reports._sensors import read_sensor_tables

#: The variable set build_profiles must emit over the four mixsed2 fixtures.  Phase 2
#: is a re-plumbing: any variable added or (silently) dropped here — a missing
#: ``sensor_channel_*`` linkage most of all — is a defect, so this list is frozen.
_EXPECTED_PROFILE_VARS: frozenset[str] = frozenset(
    {
        "N_PROF",
        "SENSOR_CONDUCTIVITY_3120",
        "SENSOR_CONDUCTIVITY_4922",
        "SENSOR_FLUOROMETER_FLNTURTD_3508",
        "SENSOR_OXYGEN_0707",
        "SENSOR_PH_339",
        "SENSOR_PRESSURE_0814",
        "SENSOR_TEMPERATURE_6000",
        "SENSOR_TEMPERATURE_6435",
        "SENSOR_TRANSMISSOMETER_2033",
        "SENSOR_TURBIDITY_3508",
        "SENSOR_USER_POLYNOMIAL_UVP6",
        "cast_direction",
        "cast_id",
        "cast_number",
        "cast_suffix",
        "cast_type",
        "conductivity_1",
        "conductivity_2",
        "ctd_altimeter",
        "ctd_fluor",
        "ctd_oxygen",
        "ctd_salinity_1",
        "ctd_salinity_2",
        "ctd_temperature_1",
        "ctd_temperature_2",
        "ctd_turbidity",
        "gebco_depth_m",
        "latitude",
        "longitude",
        "max_pressure_dbar",
        "pressure",
        "sensor_channel_conductivity_1",
        "sensor_channel_conductivity_2",
        "sensor_channel_fluorometer",
        "sensor_channel_oxygen_1",
        "sensor_channel_ph",
        "sensor_channel_pressure",
        "sensor_channel_temperature_1",
        "sensor_channel_temperature_2",
        "sensor_channel_transmissometer",
        "sensor_channel_turbidity",
        "sensor_channel_user_polynomial",
        "sensor_conductivity_1",
        "sensor_conductivity_2",
        "sensor_fluorometer",
        "sensor_oxygen_1",
        "sensor_ph",
        "sensor_pressure",
        "sensor_temperature_1",
        "sensor_temperature_2",
        "sensor_transmissometer",
        "sensor_turbidity",
        "sensor_user_polynomial",
        "source_data_mode",
        "source_file",
        "source_stage",
        "source_tracking_id",
        "time_end",
        "time_start",
    }
)


def _copy_fixtures(
    dst: Path, *, edit: dict | None = None, strip_catalog: bool = False
) -> None:
    """Copy the mixsed2 ``.nc`` fixtures into *dst*, optionally mutating one cast.

    *edit*, when given, is ``{"file": name, "var": SENSOR_var, "attr": key,
    "value": str}`` and changes a single catalog entry attribute on that one cast —
    used to synthesise a cross-cast disagreement from otherwise identical fixtures.
    *strip_catalog* drops every ``SENSOR_*`` variable, producing files that predate
    the catalog.
    """
    for f in sorted(FIXTURES_NC.glob("mixsed2_*.nc")):
        ds = xr.open_dataset(f, engine="netcdf4").load()
        if strip_catalog:
            ds = ds.drop_vars([v for v in ds.variables if str(v).startswith("SENSOR_")])
        if edit and f.name == edit["file"]:
            ds[edit["var"]].attrs[edit["attr"]] = edit["value"]
        ds.to_netcdf(dst / f.name)
        ds.close()


def _write_cast(dst_path: Path, src_name: str, transform=None) -> None:
    """Copy one fixture cast to *dst_path*, applying *transform* to the dataset first.

    *transform*, when given, takes and returns an ``xr.Dataset`` — the seam for
    synthesising a single-temperature cast, a mid-cruise swap, or an added aux sensor
    from a real fixture, so the per-sample data stays genuine and only the catalog
    shape is hand-built (which is what the plan sanctions for the behaviour tests).
    """
    ds = xr.open_dataset(FIXTURES_NC / src_name, engine="netcdf4").load()
    if transform is not None:
        ds = transform(ds)
    ds.to_netcdf(dst_path)
    ds.close()


def test_sensor_config_xml_survives_aggregation(tmp_path) -> None:
    """The verbatim per-sensor config block reaches profiles.nc unchanged, so the compiled
    archive records the raw→physical calibration on its own — not only the stage-1 files."""
    src = tmp_path / "casts"
    src.mkdir()
    _copy_fixtures(src)
    out = tmp_path / "profiles.nc"
    build_profiles(src, out, force=True)

    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        entries = [v for v in ds.data_vars if str(v).startswith("SENSOR_")]
        assert entries
        for name in entries:
            xml = str(ds[name].attrs.get("sensor_config_xml", "")).strip()
            assert xml.startswith("<sensor Channel=") and xml.endswith("</sensor>"), (
                name
            )
    finally:
        ds.close()


def test_var_names_union_across_casts_warns_on_partial(tmp_path) -> None:
    """A channel present in only some casts is still compiled (union of channels, not just the
    first cast), all-NaN where absent, with one warning naming the casts that lack it."""
    import numpy as np

    src = tmp_path / "casts"
    src.mkdir()
    _write_cast(src / "mixsed2_011.nc", "mixsed2_011.nc")  # carries ctd_turbidity

    def _drop_turbidity(ds: xr.Dataset) -> xr.Dataset:
        return ds.drop_vars([v for v in ("ctd_turbidity",) if v in ds])

    _write_cast(src / "mixsed2_012.nc", "mixsed2_012.nc", transform=_drop_turbidity)
    out = tmp_path / "profiles.nc"

    with pytest.warns(UserWarning, match=r"ctd_turbidity.*absent"):
        build_profiles(src, out, force=True)

    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        assert "ctd_turbidity" in ds  # union kept it despite 012 lacking it
        vals = ds["ctd_turbidity"].values
        assert np.isfinite(vals).any()  # 011's profiles carry data
        assert np.isnan(vals).any()  # 012's profiles are all-NaN
    finally:
        ds.close()


def test_warns_and_stamps_catalog_less(tmp_path, recwarn) -> None:
    """A catalog-less directory compiles (library default) with a warning and a stamp."""
    src = tmp_path / "casts"
    src.mkdir()
    _copy_fixtures(src, strip_catalog=True)
    out = tmp_path / "profiles.nc"

    assert build_profiles(src, out, force=True) is True
    assert out.exists()
    assert any("carry no sensor catalog" in str(w.message) for w in recwarn.list)

    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        assert "absent" in ds.attrs.get("sensor_catalog", "")
    finally:
        ds.close()


def test_refuses_catalog_less_when_flag_set(tmp_path) -> None:
    """With refuse_catalog_less=True, a catalog-less cast raises and writes nothing."""
    src = tmp_path / "casts"
    src.mkdir()
    _copy_fixtures(src, strip_catalog=True)
    out = tmp_path / "profiles.nc"

    with pytest.raises(ValueError, match="no sensor catalog"):
        build_profiles(src, out, force=True, refuse_catalog_less=True)
    assert not out.exists()


def test_process_profiles_refuses_catalog_less(tmp_path) -> None:
    """The pipeline driver (process --stage profiles / run) refuses a catalog-less cast.

    ``process`` wires ``refuse_catalog_less=True`` into ``build_profiles``, so a
    directory that predates the catalog raises rather than shipping a product with a
    provenance gap.
    """
    src = tmp_path / "casts"
    src.mkdir()
    _copy_fixtures(src, strip_catalog=True)
    out = tmp_path / "profiles.nc"

    with pytest.raises(ValueError, match="no sensor catalog"):
        process(stage="profiles", nc_dir=src, profiles_path=out, force=True)
    assert not out.exists()


def test_header_native_conflict_warns(tmp_path) -> None:
    """A cross-cast disagreement on a calibration value warns as a data error.

    Calibration date/slope/offset are physically fixed for a serial, so a mismatch
    points at CNV parsing, not a config version.
    """
    src = tmp_path / "casts"
    src.mkdir()
    _copy_fixtures(
        src,
        edit={
            "file": "mixsed2_012.nc",
            "var": "SENSOR_PRESSURE_0814",
            "attr": "sensor_calibration_slope",
            "value": "1.11111111",
        },
    )
    out = tmp_path / "profiles.nc"
    with pytest.warns(UserWarning, match="calibration cannot change at sea"):
        build_profiles(src, out, force=True)


def test_config_resolved_conflict_warns(tmp_path) -> None:
    """A cross-cast disagreement on a config-resolved field warns as a re-stamp, not an error.

    Model/maker/vocabulary come from the registry + overrides at stage 1, so a
    mismatch means casts were stamped under different config versions.
    """
    src = tmp_path / "casts"
    src.mkdir()
    _copy_fixtures(
        src,
        edit={
            "file": "mixsed2_012.nc",
            "var": "SENSOR_PH_339",
            "attr": "sensor_model",
            "value": "SBE 99",
        },
    )
    out = tmp_path / "profiles.nc"
    # The warning must point at the fix (re-run stage 1 / enrich), not read as a data error.
    with pytest.warns(UserWarning, match="different config versions"):
        build_profiles(src, out, force=True)
    with pytest.warns(UserWarning, match="enrich"):
        build_profiles(src, out, force=True)


def test_profiles_variable_set_is_stable(tmp_path) -> None:
    """The compiled variable set is exactly the frozen list — a re-plumb defect guard.

    Asserts the full set (not just a spot check) so a silently dropped or renamed
    ``sensor_channel_*`` / ``sensor_<role>`` linkage variable fails here.
    """
    out = tmp_path / "profiles.nc"
    build_profiles(FIXTURES_NC, out, force=True)
    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        got = {str(v) for v in ds.variables}
    finally:
        ds.close()
    assert got == set(_EXPECTED_PROFILE_VARS), {
        "missing": sorted(set(_EXPECTED_PROFILE_VARS) - got),
        "unexpected": sorted(got - set(_EXPECTED_PROFILE_VARS)),
    }


def _make_single_temperature(ds: xr.Dataset) -> xr.Dataset:
    """Turn a dual-temperature fixture into a single-temperature cast.

    Mirrors what stage-1 ``_normalise`` does to a genuinely single-sensor cast: the
    variable loses its ``_1`` suffix (``ctd_temperature``), but the catalog entry
    keeps ``sensor_role='temperature_1'``. Drops the second temperature channel and
    its entry.
    """
    ds = ds.rename({"ctd_temperature_1": "ctd_temperature"})
    ds = ds.drop_vars(["ctd_temperature_2", "SENSOR_TEMPERATURE_6000"])
    ds["ctd_temperature"].attrs["sensor"] = "SENSOR_TEMPERATURE_6435"
    return ds


def test_mixed_single_and_dual_temperature_yields_one_linkage(tmp_path) -> None:
    """A cruise mixing a single- and a dual-temperature cast emits one temperature_1 linkage.

    This is the regression the Phase-1 amendment exists to prevent: the role is read
    off the catalog entry (``temperature_1``), not re-derived from the suffix-stripped
    variable name (``ctd_temperature``), so the single-T cast joins the *same*
    ``sensor_temperature_1`` linkage instead of spawning a stray ``sensor_temperature``.
    """
    src = tmp_path / "casts"
    src.mkdir()
    _write_cast(src / "mixsed2_011.nc", "mixsed2_011.nc")  # dual-T, first cast
    _write_cast(src / "mixsed2_012.nc", "mixsed2_012.nc", _make_single_temperature)
    out = tmp_path / "profiles.nc"
    build_profiles(src, out, force=True)
    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        assert "sensor_temperature" not in ds.variables  # no stray suffix-less spelling
        assert "sensor_temperature_1" in ds.variables
        assert "sensor_temperature_2" in ds.variables
        # temperature_1 is present on both casts, so every profile's linkage is filled.
        assert all(str(v) for v in ds["sensor_temperature_1"].values)
    finally:
        ds.close()


def _drop_transmissometer(ds: xr.Dataset) -> xr.Dataset:
    """Remove the transmissometer catalog entry (a cast fitted without that aux sensor)."""
    return ds.drop_vars(["SENSOR_TRANSMISSOMETER_2033"])


def test_aux_sensor_fitted_midcruise(tmp_path) -> None:
    """A sensor absent from the first cast still gets a catalog entry, with empty early linkage.

    ``_build_sensor_catalog`` iterates every cast, so an aux sensor first fitted on a
    later cast is catalogued; its ``sensor_<role>`` linkage is empty for the profiles
    that predate it and named for the ones that carry it.
    """
    src = tmp_path / "casts"
    src.mkdir()
    _write_cast(src / "mixsed2_011.nc", "mixsed2_011.nc", _drop_transmissometer)
    _write_cast(src / "mixsed2_012.nc", "mixsed2_012.nc")  # aux present here
    out = tmp_path / "profiles.nc"
    build_profiles(src, out, force=True)
    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        assert "SENSOR_TRANSMISSOMETER_2033" in ds.variables  # entry survives
        link = ds["sensor_transmissometer"].values.astype(str)
        assert link[0] == "" and link[1] == ""  # cast 011 down/up: no aux
        assert link[2] == "SENSOR_TRANSMISSOMETER_2033"  # cast 012 down
        assert link[3] == "SENSOR_TRANSMISSOMETER_2033"  # cast 012 up
    finally:
        ds.close()


def _swap_temperature_1(ds: xr.Dataset) -> xr.Dataset:
    """Swap the temperature_1 device for a different serial (a mid-cruise hardware swap)."""
    ds = ds.rename({"SENSOR_TEMPERATURE_6435": "SENSOR_TEMPERATURE_9999"})
    ds["SENSOR_TEMPERATURE_9999"].attrs["sensor_serial_number"] = "9999"
    ds["ctd_temperature_1"].attrs["sensor"] = "SENSOR_TEMPERATURE_9999"
    return ds


def test_midcruise_swap_logged_as_change_and_two_blocks(tmp_path) -> None:
    """A temperature_1 swap between casts shows as a change log entry and two config blocks."""
    src = tmp_path / "casts"
    src.mkdir()
    _write_cast(src / "mixsed2_011.nc", "mixsed2_011.nc")  # temperature_1 = SN 6435
    _write_cast(src / "mixsed2_012.nc", "mixsed2_012.nc", _swap_temperature_1)  # → 9999
    out = tmp_path / "profiles.nc"
    build_profiles(src, out, force=True)

    m = read_sensor_tables(out)
    assert m["has_catalog"] is True
    # The change log labels the role for display ("Temperature 1"), so match loosely.
    changed_roles = {c["role"].lower() for c in m["changes"]}
    assert any("temperature" in r for r in changed_roles), m["changes"]
    assert len(m["blocks"]) == 2  # the swap starts a new configuration block


def test_stage1_to_profiles_contract(tmp_path) -> None:
    """End-to-end: stage 1 over raw CNV then compile yields a populated catalog.

    The contract the two branches must keep: stage 1 builds the per-cast catalog and
    build_profiles aggregates it into ``SENSOR_*`` entries plus ``sensor_<role>``
    linkage, with no catalog-less warning. Gated on seasenselib, the stage-1 reader.
    """
    pytest.importorskip("seasenselib")
    from ctdcast.processors.stage1 import stage1

    nc_dir = tmp_path / "stage1"
    # One cruise only: the fixture CNV dir also holds an MSM cast, and mixing
    # cruises in one compile is a deliberate identity error in build_profiles.
    n = stage1(FIXTURES_CNV, nc_dir, pattern="mixsed2_*.cnv")
    assert n >= 1

    out = tmp_path / "profiles.nc"
    assert build_profiles(nc_dir, out, force=True, refuse_catalog_less=True) is True

    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        catalog = [v for v in ds.variables if str(v).startswith("SENSOR_")]
        assert catalog, "stage-1 catalog did not survive into the compiled file"
        assert any(str(v).startswith("sensor_") for v in ds.variables), "no linkage"
        assert "sensor_catalog" not in ds.attrs  # no catalog-less admission stamped
    finally:
        ds.close()


def test_stage1_conversion_level_measured_yes_computed_no(tmp_path) -> None:
    """Fresh stage 1 stamps the conversion value on every measured channel (frequency and
    voltage) and on no computed channel — salinity is read from the CNV, never instrument
    data, so claiming conversion for it would be false.  Gated on seasenselib."""
    pytest.importorskip("seasenselib")
    from ctdcast.processors.stage1 import stage1

    converted = "converted to geophysical values"
    nc_dir = tmp_path / "stage1"
    assert stage1(FIXTURES_CNV, nc_dir, pattern="mixsed2_*.cnv") >= 1

    stage1_file = sorted(nc_dir.glob("stage1/*.nc"))[0]
    ds = xr.open_dataset(stage1_file, engine="netcdf4")
    try:
        # Every variable that maps to a <Sensors> sensor carries the conversion value...
        measured = [v for v in ds.data_vars if "sensor" in ds[v].attrs]
        assert measured, "no measured channel linked to a sensor"
        for v in measured:
            assert converted in ds[v].attrs.get("processing_level", ""), v
        # ...and no computed channel does (salinity is read, datcnv-derived from T/C/P).
        for v in ds.data_vars:
            if str(v).startswith("ctd_salinity"):
                assert converted not in ds[v].attrs.get("processing_level", ""), v
        # The SENSOR_* catalog scalars are not measurements: no processing_level.
        for v in ds.data_vars:
            if str(v).startswith("SENSOR_"):
                assert "processing_level" not in ds[v].attrs, v
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# data_mode aggregation — stage is not data mode; "M" only for genuine P/D mix
# ---------------------------------------------------------------------------


def test_uniform_provisional_casts_stay_P_not_M(tmp_path) -> None:
    """Every fixture is provisional, so the compiled file is 'P' — never 'M'."""
    src = tmp_path / "casts"
    src.mkdir()
    _copy_fixtures(src)
    out = tmp_path / "profiles.nc"
    build_profiles(src, out, force=True)

    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        assert ds.attrs["data_mode"] == "P"
        assert {str(x) for x in ds["source_data_mode"].values} == {"P"}
    finally:
        ds.close()


def test_mixed_data_modes_label_the_file_M_with_per_profile_modes(tmp_path) -> None:
    """A genuine P/D mix compiles to a global 'M'; the per-profile data_mode variable
    resolves which profile is in which mode (the OceanSITES <PARAM>_DM obligation)."""
    src = tmp_path / "casts"
    src.mkdir()
    _write_cast(src / "mixsed2_011.nc", "mixsed2_011.nc")  # no attr -> provisional

    def _delayed(ds: xr.Dataset) -> xr.Dataset:
        ds.attrs["data_mode"] = "D"
        return ds

    _write_cast(src / "mixsed2_012.nc", "mixsed2_012.nc", transform=_delayed)
    out = tmp_path / "profiles.nc"
    build_profiles(src, out, force=True)

    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        assert ds.attrs["data_mode"] == "M"
        assert "mix" in ds.attrs["data_mode_meaning"].lower()
        assert {str(x) for x in ds["source_data_mode"].values} == {"P", "D"}
    finally:
        ds.close()


def test_mixed_mode_identifier_token_matches_data_mode(tmp_path) -> None:
    """The data_mode embedded in the OceanSITES ``id`` / ``internal_mission_identifier``
    must equal the ``data_mode`` attribute — both are built from one mode, so a mixed-mode
    file cannot ship ``id='..._P_...'`` while it declares itself ``M``."""
    src = tmp_path / "casts"
    src.mkdir()
    _write_cast(src / "mixsed2_011.nc", "mixsed2_011.nc")

    def _delayed(ds: xr.Dataset) -> xr.Dataset:
        ds.attrs["data_mode"] = "D"
        return ds

    _write_cast(src / "mixsed2_012.nc", "mixsed2_012.nc", transform=_delayed)
    out = tmp_path / "profiles.nc"
    build_profiles(
        src,
        out,
        force=True,
        cruise_info={
            "platform": "odb",
            "start_date": "2026-07-09",
            "internal_id": "mixsed2",
        },
    )

    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        assert ds.attrs["data_mode"] == "M"
        assert "id" in ds.attrs, "id should build from platform + start_date"
        # id is <expocode>_<mode>_<product>_<grid>; the mode token must be the attr value.
        assert ds.attrs["id"].split("_")[1] == "M"
        assert ds.attrs["internal_mission_identifier"].split("_")[2] == "M"
    finally:
        ds.close()


def test_declared_D_with_provisional_casts_warns_and_records(tmp_path) -> None:
    """Declaring data_mode 'D' but compiling casts below it downgrades to 'P' (honest), yet
    warns naming each cast and its stage and records the reason in the file's history — the
    explicit declaration was overridden, so the file must say why it is not D."""
    src = tmp_path / "casts"
    src.mkdir()
    _copy_fixtures(src)  # flat fixtures read as stage 1 → provisional
    out = tmp_path / "profiles.nc"

    with pytest.warns(UserWarning, match="declares data_mode 'D'"):
        build_profiles(src, out, force=True, cruise_info={"data_mode": "D"})

    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        assert ds.attrs["data_mode"] == "P"
        assert "declares data_mode 'D'" in ds.attrs["history"]
        assert "011=stage" in ds.attrs["history"]  # each cast named with its stage
    finally:
        ds.close()


def test_mixed_stages_warn_but_do_not_force_M(tmp_path) -> None:
    """Casts compiled from different stages warn and are recorded in source_stage, but
    stages are all provisional, so the file stays 'P' — stage is not data mode."""
    from ctdcast.processors.stage_layout import stage_path

    root = tmp_path / "CTD"
    s1 = stage_path(root, "mixsed2_011", 1)
    s3 = stage_path(root, "mixsed2_012", 3)
    s1.parent.mkdir(parents=True, exist_ok=True)
    s3.parent.mkdir(parents=True, exist_ok=True)
    _write_cast(s1, "mixsed2_011.nc")
    _write_cast(s3, "mixsed2_012.nc")
    out = tmp_path / "profiles.nc"

    with pytest.warns(UserWarning, match="mixed processing stages"):
        build_profiles(root, out, force=True)

    ds = xr.open_dataset(out, engine="netcdf4")
    try:
        assert ds.attrs["data_mode"] == "P"  # provisional despite mixed stages
        assert {int(x) for x in ds["source_stage"].values} == {1, 3}
    finally:
        ds.close()
