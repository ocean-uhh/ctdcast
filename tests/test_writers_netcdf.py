"""Tests for ctdcast.writers.netcdf — CF-compliant netCDF writer."""

import numpy as np
import xarray as xr
from conftest import CAST_011


def _load(path):
    return xr.open_dataset(path, engine="netcdf4").load()


class TestWrite:
    """write() adds CF metadata and writes atomically."""

    def test_write_creates_file(self, tmp_path):
        from ctdcast.writers.netcdf import write

        ds = _load(CAST_011)
        out = tmp_path / "test.nc"
        write(ds, out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_no_tmp_file_left_behind(self, tmp_path):
        from ctdcast.writers.netcdf import write

        ds = _load(CAST_011)
        out = tmp_path / "test.nc"
        write(ds, out)
        assert not out.with_suffix(".nc.tmp").exists()

    def test_conventions_attr_set(self, tmp_path):
        from ctdcast.writers.netcdf import write

        ds = _load(CAST_011)
        out = tmp_path / "test.nc"
        write(ds, out)
        ds_back = xr.open_dataset(out, engine="netcdf4")
        assert ds_back.attrs.get("Conventions") == "CF-1.13"
        ds_back.close()

    def test_known_variable_gets_units(self, tmp_path):
        from ctdcast.writers.netcdf import write

        ds = _load(CAST_011)
        out = tmp_path / "test.nc"
        write(ds, out)
        ds_back = xr.open_dataset(out, engine="netcdf4")
        if "temperature_1" in ds_back:
            assert "units" in ds_back["temperature_1"].attrs
        ds_back.close()

    def test_known_variable_gets_label_units(self, tmp_path):
        from ctdcast.writers.netcdf import write

        ds = _load(CAST_011)
        out = tmp_path / "test.nc"
        write(ds, out)
        ds_back = xr.open_dataset(out, engine="netcdf4")
        assert ds_back["ctd_salinity_1"].attrs.get("label_units") == "PSU"
        ds_back.close()

    def test_latitude_coordinate_gets_standard_name(self, tmp_path):
        """Coordinate variables in VARIABLES receive CF attrs, not just data_vars."""
        from ctdcast.writers.netcdf import write

        ds = _load(CAST_011)
        # strip any existing standard_name so we prove write() supplies it
        ds["latitude"].attrs.pop("standard_name", None)
        out = tmp_path / "test.nc"
        write(ds, out)
        ds_back = xr.open_dataset(out, engine="netcdf4")
        assert ds_back["latitude"].attrs.get("standard_name") == "latitude"
        ds_back.close()

    def test_qc_variable_gets_flag_attrs(self, tmp_path):
        from ctdcast.processors.stage2 import apply_stage2
        from ctdcast.writers.netcdf import write

        ds = _load(CAST_011)
        ds = apply_stage2(ds)
        out = tmp_path / "flagged.nc"
        write(ds, out)
        ds_back = xr.open_dataset(out, engine="netcdf4")
        # temperature_1_qc should exist and have CF flag attrs
        if "temperature_1_qc" in ds_back:
            attrs = ds_back["temperature_1_qc"].attrs
            assert "flag_values" in attrs
            assert "flag_meanings" in attrs
        ds_back.close()

    def test_creates_parent_directory(self, tmp_path):
        from ctdcast.writers.netcdf import write

        ds = _load(CAST_011)
        out = tmp_path / "subdir" / "deep" / "test.nc"
        write(ds, out)
        assert out.exists()

    def test_roundtrip_preserves_data(self, tmp_path):
        from ctdcast.writers.netcdf import write

        ds = _load(CAST_011)
        out = tmp_path / "roundtrip.nc"
        write(ds, out)
        ds_back = xr.open_dataset(out, engine="netcdf4").load()
        for v in ds.data_vars:
            if v in ds_back:
                np.testing.assert_allclose(
                    ds[v].values, ds_back[v].values, rtol=1e-5, equal_nan=True
                )
        ds_back.close()
