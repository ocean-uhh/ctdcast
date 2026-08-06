"""Smoke tests for _converters: build_profiles."""

import pytest
from conftest import FIXTURES_NC

from ctdcast.converters import _select_cast_files, build_profiles


def test_build_profiles_writes_file(tmp_path):
    out = tmp_path / "profiles.nc"
    wrote = build_profiles(FIXTURES_NC, out, force=False)
    assert wrote is True
    assert out.exists()
    assert out.stat().st_size > 0


def test_build_profiles_writes_cast_suffix(tmp_path):
    import xarray as xr

    out = tmp_path / "profiles.nc"
    build_profiles(FIXTURES_NC, out, force=True)
    ds = xr.open_dataset(out, engine="netcdf4")
    assert "cast_suffix" in ds
    # The committed fixtures are all plain casts, so every suffix is empty.
    assert all(s == "" for s in ds["cast_suffix"].values.astype(str))
    ds.close()


def test_profile_cast_suffixes_reads_and_falls_back(tmp_path):
    import xarray as xr

    from ctdcast.reports._format import profile_cast_suffixes

    out = tmp_path / "profiles.nc"
    build_profiles(FIXTURES_NC, out, force=True)
    ds = xr.open_dataset(out, engine="netcdf4").load()
    # Present: reads the variable (all plain for these fixtures).
    suffixes = profile_cast_suffixes(ds)
    assert len(suffixes) == ds.sizes["N_PROF"]
    assert all(s == "" for s in suffixes)
    # Fallback: a profiles.nc without cast_suffix reads as all-plain.
    ds_old = ds.drop_vars("cast_suffix")
    fallback = profile_cast_suffixes(ds_old)
    assert len(fallback) == ds_old.sizes["N_PROF"]
    assert all(s == "" for s in fallback)
    ds.close()


def test_select_cast_files_keeps_plain_and_b_as_distinct(tmp_path):
    # A plain cast and its lettered sibling are separate events; both must survive
    # selection. _select_cast_files only parses filenames, so empty stand-in
    # files exercise the path without any instrument data.
    for name in (
        "mixsed2_010.nc",
        "mixsed2_010b.nc",
        "mixsed2_029.nc",
        "mixsed2_029_b.nc",
    ):
        (tmp_path / name).touch()
    selected = _select_cast_files(tmp_path)
    ids = [(num, suffix) for num, suffix, _path in selected]
    assert ids == [(10, ""), (10, "b"), (29, ""), (29, "b")]


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
