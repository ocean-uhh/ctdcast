"""Tests for ctdcast.cruise.profiles — build_profiles refactored from converters."""

import xarray as xr
from conftest import FIXTURES_NC


class TestBuildProfilesCruise:
    """Tests for cruise.profiles.build_profiles (replaces some test_converters tests)."""

    def test_cast_direction_variable_present(self, tmp_path):
        """profiles.nc must have cast_direction instead of the float N_PROF encoding."""
        from ctdcast.processors.profiles import build_profiles

        out = tmp_path / "profiles.nc"
        build_profiles(FIXTURES_NC, out, force=True)
        ds = xr.open_dataset(out, engine="netcdf4")
        assert "cast_direction" in ds, (
            "cast_direction variable missing from profiles.nc"
        )
        ds.close()

    def test_science_vars_get_cf_attrs(self, tmp_path):
        """Binned science variables carry units/standard_name/long_name/label_units."""
        from ctdcast.processors.profiles import build_profiles

        out = tmp_path / "profiles.nc"
        build_profiles(FIXTURES_NC, out, force=True)
        ds = xr.open_dataset(out, engine="netcdf4")
        for var in ("ctd_temperature_1", "ctd_salinity_1", "conductivity_1"):
            a = ds[var].attrs
            assert a.get("units"), f"{var} missing units"
            assert a.get("standard_name"), f"{var} missing standard_name"
            # long_name must be the descriptive name, not the placeholder var name
            assert a.get("long_name") and a["long_name"] != var
            assert a.get("label_units"), f"{var} missing label_units"
        ds.close()

    def test_coords_get_standard_name(self, tmp_path):
        """latitude/longitude/pressure coordinates carry standard_name."""
        from ctdcast.processors.profiles import build_profiles

        out = tmp_path / "profiles.nc"
        build_profiles(FIXTURES_NC, out, force=True)
        ds = xr.open_dataset(out, engine="netcdf4")
        assert ds["latitude"].attrs.get("standard_name") == "latitude"
        assert ds["longitude"].attrs.get("standard_name") == "longitude"
        assert ds["pressure"].attrs.get("standard_name") == "sea_water_pressure"
        ds.close()

    def test_cast_direction_values(self, tmp_path):
        """cast_direction must contain only 'down' and 'up'."""
        from ctdcast.processors.profiles import build_profiles

        out = tmp_path / "profiles.nc"
        build_profiles(FIXTURES_NC, out, force=True)
        ds = xr.open_dataset(out, engine="netcdf4")
        directions = set(ds["cast_direction"].values.astype(str))
        assert directions <= {"down", "up"}, f"Unexpected directions: {directions}"
        ds.close()

    def test_n_prof_is_integer_index(self, tmp_path):
        """N_PROF must be a sequential integer index, not the old cast+0.5 float encoding."""
        from ctdcast.processors.profiles import build_profiles

        out = tmp_path / "profiles.nc"
        build_profiles(FIXTURES_NC, out, force=True)
        ds = xr.open_dataset(out, engine="netcdf4")
        n_prof = ds["N_PROF"].values
        # Should be 0,1,2,...,n-1 (integer index)
        assert n_prof.dtype.kind in ("i", "u"), (
            f"N_PROF should be integer, got {n_prof.dtype}"
        )
        expected = list(range(len(n_prof)))
        assert list(n_prof) == expected, f"N_PROF should be 0..n-1, got {n_prof}"
        ds.close()

    def test_cast_type_backward_compat(self, tmp_path):
        """cast_type must still exist for backward compatibility."""
        from ctdcast.processors.profiles import build_profiles

        out = tmp_path / "profiles.nc"
        build_profiles(FIXTURES_NC, out, force=True)
        ds = xr.open_dataset(out, engine="netcdf4")
        assert "cast_type" in ds, "cast_type backward-compat alias is missing"
        ds.close()

    def test_cast_id_variable_present(self, tmp_path):
        """profiles.nc must have a cast_id string variable."""
        from ctdcast.processors.profiles import build_profiles

        out = tmp_path / "profiles.nc"
        build_profiles(FIXTURES_NC, out, force=True)
        ds = xr.open_dataset(out, engine="netcdf4")
        assert "cast_id" in ds, "cast_id variable missing from profiles.nc"
        ids = list(ds["cast_id"].values.astype(str))
        # Fixture casts are 011, 012, 128, 129 — each appears twice (down + up).
        assert ids == ["011", "011", "012", "012", "128", "128", "129", "129"]
        ds.close()

    def test_profiles_count_matches_casts_times_two(self, tmp_path):
        """Each cast contributes exactly 2 profiles (down + up)."""
        from ctdcast.processors.profiles import _select_cast_files, build_profiles

        out = tmp_path / "profiles.nc"
        build_profiles(FIXTURES_NC, out, force=True)
        n_casts = len(_select_cast_files(FIXTURES_NC))
        ds = xr.open_dataset(out, engine="netcdf4")
        assert ds.sizes["N_PROF"] == n_casts * 2
        ds.close()

    def test_max_pressure_variable_present(self, tmp_path):
        """profiles.nc must have max_pressure_dbar as a per-profile (N_PROF) variable."""
        from ctdcast.processors.profiles import build_profiles

        out = tmp_path / "profiles.nc"
        build_profiles(FIXTURES_NC, out, force=True)
        ds = xr.open_dataset(out, engine="netcdf4")
        assert "max_pressure_dbar" in ds, "max_pressure_dbar missing from profiles.nc"
        assert ds["max_pressure_dbar"].dims == ("N_PROF",)
        ds.close()

    def test_max_pressure_positive_and_repeated_for_cast(self, tmp_path):
        """max_pressure_dbar must be positive and identical for down+up of each cast."""
        from ctdcast.processors.profiles import _select_cast_files, build_profiles

        out = tmp_path / "profiles.nc"
        build_profiles(FIXTURES_NC, out, force=True)
        n_casts = len(_select_cast_files(FIXTURES_NC))
        ds = xr.open_dataset(out, engine="netcdf4")
        mp = ds["max_pressure_dbar"].values
        assert (mp > 0).all(), "max_pressure_dbar should be positive"
        for i in range(n_casts):
            assert mp[2 * i] == mp[2 * i + 1], (
                f"Cast {i}: down ({mp[2 * i]}) and up ({mp[2 * i + 1]}) max_pressure differ"
            )
        ds.close()

    def test_gebco_depth_variable_present(self, tmp_path):
        """profiles.nc must have gebco_depth_m even when no GEBCO file is given (NaN)."""
        from ctdcast.processors.profiles import build_profiles

        out = tmp_path / "profiles.nc"
        build_profiles(FIXTURES_NC, out, force=True)
        ds = xr.open_dataset(out, engine="netcdf4")
        assert "gebco_depth_m" in ds, "gebco_depth_m missing from profiles.nc"
        assert ds["gebco_depth_m"].dims == ("N_PROF",)
        ds.close()

    def test_gebco_depth_nan_without_gebco_file(self, tmp_path):
        """gebco_depth_m must be all-NaN when no GEBCO file is supplied."""
        import numpy as np

        from ctdcast.processors.profiles import build_profiles

        out = tmp_path / "profiles.nc"
        build_profiles(FIXTURES_NC, out, force=True, gebco_path=None)
        ds = xr.open_dataset(out, engine="netcdf4")
        assert np.all(np.isnan(ds["gebco_depth_m"].values)), (
            "gebco_depth_m should be all-NaN without a GEBCO file"
        )
        ds.close()

    def test_gebco_depth_repeated_for_cast(self, tmp_path):
        """gebco_depth_m must be identical for the down and up profiles of each cast."""
        from ctdcast.processors.profiles import _select_cast_files, build_profiles

        out = tmp_path / "profiles.nc"
        build_profiles(FIXTURES_NC, out, force=True)
        n_casts = len(_select_cast_files(FIXTURES_NC))
        ds = xr.open_dataset(out, engine="netcdf4")
        gd = ds["gebco_depth_m"].values
        for i in range(n_casts):
            # Both NaN or both equal
            import numpy as np

            d, u = gd[2 * i], gd[2 * i + 1]
            assert (np.isnan(d) and np.isnan(u)) or d == u, (
                f"Cast {i}: down/up gebco_depth_m differ ({d} vs {u})"
            )
        ds.close()

    def test_source_stage_flat_fixtures_are_unknown(self, tmp_path):
        """Flat fixtures are only assumed stage 1 by the shim → source_stage 0."""
        import numpy as np

        from ctdcast.processors.profiles import build_profiles

        out = tmp_path / "profiles.nc"
        build_profiles(FIXTURES_NC, out, force=True)
        ds = xr.open_dataset(out, engine="netcdf4")
        assert ds["source_stage"].dtype == np.int8
        assert (ds["source_stage"].values == 0).all()
        ds.close()

    def test_source_stage_records_nested_rung(self, tmp_path):
        """A nested stage-3 file compiles with source_stage == 3 (it states its stage)."""
        import shutil

        from ctdcast.processors.profiles import build_profiles
        from ctdcast.processors.stage_layout import stage_path

        root = tmp_path / "CTD"
        dst = stage_path(root, "mixsed2_011", 3)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES_NC / "mixsed2_011.nc", dst)
        out = tmp_path / "profiles.nc"
        build_profiles(root, out, force=True)
        ds = xr.open_dataset(out, engine="netcdf4")
        assert (ds["source_stage"].values == 3).all()
        ds.close()

    def test_source_stage_mixed_directory(self, tmp_path):
        """Casts at different rungs yield mixed source_stage (nested stage1 → 1, not 0)."""
        import shutil

        import numpy as np

        from ctdcast.processors.profiles import build_profiles
        from ctdcast.processors.stage_layout import stage_path

        root = tmp_path / "CTD"
        for stem, name, stage in [
            ("mixsed2_011", "mixsed2_011.nc", 1),
            ("mixsed2_012", "mixsed2_012.nc", 3),
        ]:
            dst = stage_path(root, stem, stage)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(FIXTURES_NC / name, dst)
        out = tmp_path / "profiles.nc"
        build_profiles(root, out, force=True)
        ds = xr.open_dataset(out, engine="netcdf4")
        assert set(np.unique(ds["source_stage"].values)) == {1, 3}
        ds.close()

    def test_qc_flags_excluded_from_profiles(self, tmp_path):
        """profiles.nc carries no _qc columns even when compiled from a flagged stage."""
        import shutil

        from ctdcast.processors.profiles import build_profiles
        from ctdcast.processors.stage2 import run as stage2_run
        from ctdcast.processors.stage_layout import stage_path

        root = tmp_path / "CTD"
        s1 = stage_path(root, "mixsed2_011", 1)
        s1.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES_NC / "mixsed2_011.nc", s1)
        stage2_run(root)  # writes a stage-2 file carrying QARTOD _qc flags
        out = tmp_path / "profiles.nc"
        build_profiles(root, out, force=True)
        ds = xr.open_dataset(out, engine="netcdf4")
        assert not any(v.endswith("_qc") for v in ds.data_vars)
        assert (ds["source_stage"].values == 2).all()
        ds.close()

    def test_source_file_records_each_cast_filename(self, tmp_path):
        """source_file records each cast's filename, distinguishing same-number casts."""
        import shutil

        from ctdcast.processors.profiles import build_profiles
        from ctdcast.processors.stage_layout import stage_path

        root = tmp_path / "CTD"
        # A plain cast and its lettered sibling: same number, distinct events.
        for stem in ("mixsed2_011", "mixsed2_011_b"):
            dst = stage_path(root, stem, 1)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(FIXTURES_NC / "mixsed2_011.nc", dst)
        out = tmp_path / "profiles.nc"
        build_profiles(root, out, force=True)
        ds = xr.open_dataset(out, engine="netcdf4")
        files = {str(f) for f in ds["source_file"].values}
        assert "mixsed2_011_stage1.nc" in files
        assert "mixsed2_011_b_stage1.nc" in files  # the sibling is not dropped
        # and the two casts stay distinct in identity, not collapsed to one
        assert {str(s) for s in ds["cast_suffix"].values} == {"", "b"}
        ds.close()
