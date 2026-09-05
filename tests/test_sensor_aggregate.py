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
    with pytest.warns(UserWarning, match="different config versions"):
        build_profiles(src, out, force=True)


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
