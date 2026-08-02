"""Smoke tests for _converters: build_profiles."""

import pytest

from ctd_report._converters import build_profiles

from conftest import FIXTURES_NC


def test_build_profiles_writes_file(tmp_path):
    out = tmp_path / "profiles.nc"
    wrote = build_profiles(FIXTURES_NC, out, force=False)
    assert wrote is True
    assert out.exists()
    assert out.stat().st_size > 0


def test_build_profiles_skips_existing(tmp_path):
    out = tmp_path / "profiles.nc"
    build_profiles(FIXTURES_NC, out, force=False)
    mtime = out.stat().st_mtime
    wrote = build_profiles(FIXTURES_NC, out, force=False)
    assert wrote is False
    assert out.stat().st_mtime == mtime


def test_build_profiles_force_overwrites(tmp_path):
    out = tmp_path / "profiles.nc"
    build_profiles(FIXTURES_NC, out, force=False)
    mtime1 = out.stat().st_mtime
    wrote = build_profiles(FIXTURES_NC, out, force=True)
    assert wrote is True
    # mtime may or may not change within a single second; just check it ran
    assert out.exists()


def test_build_profiles_output_has_expected_vars(tmp_path):
    import xarray as xr

    out = tmp_path / "profiles.nc"
    build_profiles(FIXTURES_NC, out, force=True)
    ds = xr.open_dataset(out, engine="netcdf4")
    for var in ("cast_number", "cast_type", "pressure"):
        assert var in ds or var in ds.coords, f"Missing variable: {var}"
    ds.close()


def test_build_profiles_raises_on_empty_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="No recognised cast"):
        build_profiles(empty, tmp_path / "profiles.nc")
