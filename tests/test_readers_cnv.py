"""Tests for ctdcast.readers.cnv.read()."""

import pytest
import xarray as xr
from conftest import FIXTURES_CNV, FIXTURES_OXY

pytest.importorskip("seasenselib")

CNV_MIXSED_004 = FIXTURES_CNV / "mixsed2_004.cnv"
CNV_MIXSED_004B = FIXTURES_CNV / "mixsed2_004_b.cnv"
CNV_MSM_017 = FIXTURES_CNV / "msm_142_1_017_1sec.cnv"
CNV_MSM_056_OXY = FIXTURES_OXY / "msm_142_1_056_1sec.cnv"


class TestRead:
    """ctdcast.readers.cnv.read() parses CNV files into xr.Datasets."""

    def test_returns_dataset(self):
        """read() must return an xr.Dataset, not a path or array."""
        from ctdcast.readers.cnv import read

        ds = read(CNV_MIXSED_004)
        assert isinstance(ds, xr.Dataset)

    def test_dataset_loaded_in_memory(self):
        """Returned Dataset must not hold an open file handle (tempfile is gone)."""
        from ctdcast.readers.cnv import read

        ds = read(CNV_MIXSED_004)
        # DataArray.values works without FileNotFoundError only if data is in memory.
        _ = ds["pressure"].values

    def test_essential_variables_present(self):
        """pressure, ctd_temperature_1, conductivity_1, latitude, longitude must exist."""
        from ctdcast.readers.cnv import read

        ds = read(CNV_MIXSED_004)
        for var in (
            "pressure",
            "ctd_temperature_1",
            "conductivity_1",
            "latitude",
            "longitude",
        ):
            assert var in ds or var in ds.coords, f"{var!r} missing from dataset"

    def test_time_dimension_exists(self):
        """Dataset must have a 'time' dimension."""
        from ctdcast.readers.cnv import read

        ds = read(CNV_MIXSED_004)
        assert "time" in ds.sizes

    def test_nonzero_scans(self):
        """Dataset must contain at least one scan (time > 0)."""
        from ctdcast.readers.cnv import read

        ds = read(CNV_MIXSED_004)
        assert ds.sizes["time"] > 0

    def test_file_not_found_raises(self):
        """FileNotFoundError must be raised for a non-existent path."""
        from ctdcast.readers.cnv import read

        with pytest.raises(FileNotFoundError):
            read(FIXTURES_CNV / "does_not_exist.cnv")

    def test_lettered_sibling_cast(self):
        """mixsed2_004_b.cnv (a lettered sibling) must load without error."""
        from ctdcast.readers.cnv import read

        ds = read(CNV_MIXSED_004B)
        assert isinstance(ds, xr.Dataset)
        assert ds.sizes["time"] > 0

    def test_msm_cruise_loads_without_error(self):
        """msm_142 CNV uses mS/cm conductivity — reader must not crash."""
        from ctdcast.readers.cnv import read

        ds = read(CNV_MSM_017)
        assert isinstance(ds, xr.Dataset)
        assert ds.sizes["time"] > 0

    def test_oxy_fixture_oxygen_present(self):
        """msm_142_1_056 fixture must produce a dataset with ctd_oxygen or ctd_oxygen_1."""
        from ctdcast.readers.cnv import read

        ds = read(CNV_MSM_056_OXY)
        assert "ctd_oxygen" in ds or "ctd_oxygen_1" in ds

    def test_salinity_units_are_pss78(self):
        """ctd_salinity_1 units must indicate PSS-78 (units='1' or 'PSU')."""
        from ctdcast.readers.cnv import read

        ds = read(CNV_MIXSED_004)
        sal_var = next((v for v in ("ctd_salinity", "ctd_salinity_1") if v in ds), None)
        if sal_var is None:
            pytest.skip("ctd_salinity not produced by backend for this fixture")
        units = ds[sal_var].attrs.get("units", "")
        assert units in ("1", "PSU", "psu"), f"Unexpected salinity units: {units!r}"

    def test_pressure_units_are_dbar(self):
        """pressure units must be dbar or db (synonyms accepted)."""
        from ctdcast.readers.cnv import read

        ds = read(CNV_MIXSED_004)
        units = ds["pressure"].attrs.get("units", "")
        assert units.lower() in ("db", "dbar", "decibar"), (
            f"Unexpected pressure units: {units!r}"
        )
