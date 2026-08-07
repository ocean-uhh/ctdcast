"""Tests for ctdcast.analysis.derive.derive_salinity."""

import numpy as np
import xarray as xr
from conftest import CAST_011


def _load(path):
    return xr.open_dataset(path, engine="netcdf4").load()


class TestDeriveSalinity:
    """derive_salinity() re-derives practical salinity from C/T/P."""

    def test_returns_new_dataset(self):
        from ctdcast.analysis.derive import derive_salinity

        ds = _load(CAST_011)
        ds_out = derive_salinity(ds)
        assert ds_out is not ds

    def test_salinity_1_present_in_output(self):
        from ctdcast.analysis.derive import derive_salinity

        ds = _load(CAST_011)
        ds_out = derive_salinity(ds)
        assert "salinity_1" in ds_out

    def test_derived_matches_existing_to_milliunit(self):
        """gsw.SP_from_C applied to the fixture conductivity must agree with the
        SeaBird-derived salinity_1 to within 0.001 PSU (numerical precision)."""
        from ctdcast.analysis.derive import derive_salinity

        ds = _load(CAST_011)
        original = ds["salinity_1"].values.copy()
        ds_out = derive_salinity(ds)
        derived = ds_out["salinity_1"].values
        diff = np.abs(original - derived)
        valid = ~np.isnan(diff)
        assert valid.sum() > 0, "All salinity_1 values are NaN — cannot verify"
        assert diff[valid].max() < 0.001, (
            f"Max difference {diff[valid].max():.6f} PSU exceeds 0.001 PSU tolerance"
        )

    def test_derived_from_attr_set(self):
        from ctdcast.analysis.derive import derive_salinity

        ds = _load(CAST_011)
        ds_out = derive_salinity(ds)
        attrs = ds_out["salinity_1"].attrs
        assert "derived_from" in attrs
        assert "gsw.SP_from_C" in attrs["derived_from"]

    def test_noop_when_conductivity_missing(self):
        """If conductivity_1 is absent, dataset is returned unchanged."""
        from ctdcast.analysis.derive import derive_salinity

        ds = _load(CAST_011).drop_vars("conductivity_1")
        ds_out = derive_salinity(ds)
        # salinity_1 should be unchanged (no derived_from attr)
        if "salinity_1" in ds_out:
            assert "derived_from" not in ds_out["salinity_1"].attrs
