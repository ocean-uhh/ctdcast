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
        # The writer preserves the input Conventions; stage 1 now declares ACDD
        # alongside CF, so assert CF is present rather than pinning the exact list.
        assert "CF-1.13" in ds_back.attrs.get("Conventions", "")
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

    def test_per_cast_file_defaults_to_provisional_data_mode(self, tmp_path):
        """A per-cast file with no data_mode gets 'P' at the writer, so a consumer
        reading a stage file (e.g. caldip via select_best_available) sees a mode."""
        from ctdcast.writers.netcdf import write

        ds = _load(CAST_011)
        ds.attrs.pop("data_mode", None)
        out = tmp_path / "test.nc"
        write(ds, out)
        ds_back = xr.open_dataset(out, engine="netcdf4")
        assert ds_back.attrs["data_mode"] == "P"
        assert ds_back.attrs["data_mode_meaning"] == "provisional"
        ds_back.close()

    def test_explicit_data_mode_kept_and_meaning_recomputed(self, tmp_path):
        """An upstream data_mode survives the writer, and data_mode_meaning is refreshed
        from it so a stale meaning can never travel with a changed mode."""
        from ctdcast.writers.netcdf import write

        ds = _load(CAST_011)
        ds.attrs["data_mode"] = "D"
        ds.attrs["data_mode_meaning"] = "stale"
        out = tmp_path / "test.nc"
        write(ds, out)
        ds_back = xr.open_dataset(out, engine="netcdf4")
        assert ds_back.attrs["data_mode"] == "D"
        assert ds_back.attrs["data_mode_meaning"] == "delayed-mode"
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


class TestCompression:
    """write() applies lossless zlib, with shuffle off for float64."""

    def test_every_dimensioned_numeric_var_compressed(self, tmp_path):
        """Numeric variables with a dimension (coordinates included) get zlib 4;
        0-d variables, which netCDF4 cannot chunk, are left uncompressed."""
        from ctdcast.writers.netcdf import write

        ds = _load(CAST_011)
        out = tmp_path / "c.nc"
        write(ds, out)
        back = _load(out)
        numeric = 0
        for name, var in back.variables.items():
            is_numeric = np.issubdtype(var.dtype, np.number) or np.issubdtype(
                var.dtype, np.datetime64
            )
            if is_numeric and var.ndim >= 1:
                numeric += 1
                assert back[name].encoding.get("zlib") is True, name
                assert back[name].encoding.get("complevel") == 4, name
            elif var.ndim == 0:
                assert not back[name].encoding.get("zlib"), name
        assert numeric > 0
        back.close()

    def test_shuffle_off_for_float64_on_for_integers(self, tmp_path):
        """shuffle roughly doubles ctdcast's float64 science columns, so it is off
        for float64 and on for integer variables (the QARTOD flag arrays)."""
        from ctdcast.processors.stage2 import apply_stage2
        from ctdcast.writers.netcdf import write

        ds = apply_stage2(_load(CAST_011))
        out = tmp_path / "c.nc"
        write(ds, out)
        back = _load(out)
        assert back["ctd_temperature_1"].dtype == np.float64
        assert not back["ctd_temperature_1"].encoding.get("shuffle")
        qc = [n for n in back.variables if n.endswith("_qc")]
        assert qc, "stage2 should have produced _qc flag variables"
        for n in qc:
            assert back[n].dtype == np.int8
            assert back[n].encoding.get("shuffle") is True, n
        back.close()

    def test_datetime_encoding_survives_compression(self, tmp_path):
        """The CF time encoding (epoch, float64, calendar, NaT fill) is merged with
        the compression settings, not replaced by them."""
        from ctdcast.writers.netcdf import write

        ds = _load(CAST_011)
        out = tmp_path / "c.nc"
        write(ds, out)
        back = _load(out)
        enc = back["time"].encoding
        assert "seconds since 1970-01-01" in enc["units"]
        assert np.dtype(enc["dtype"]) == np.float64
        assert enc["calendar"] == "proleptic_gregorian"
        assert np.isnan(enc.get("_FillValue"))
        assert enc.get("zlib") is True
        np.testing.assert_array_equal(ds["time"].values, back["time"].values)
        back.close()

    def test_compression_is_lossless(self, tmp_path):
        """Compressed float values equal the source exactly (zlib is lossless),
        NaN-aware, across every floating variable."""
        from ctdcast.writers.netcdf import write

        ds = _load(CAST_011)
        out = tmp_path / "compressed.nc"
        write(ds, out)
        back = _load(out)
        floats = [v for v in ds.variables if np.issubdtype(ds[v].dtype, np.floating)]
        assert floats
        for v in floats:
            np.testing.assert_array_equal(ds[v].values, back[v].values)
        assert back["ctd_temperature_1"].encoding.get("zlib") is True
        back.close()
