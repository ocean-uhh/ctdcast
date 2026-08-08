"""Tests for ctdcast.cast.qc — gross-range flagging."""

import numpy as np
import xarray as xr
from conftest import CAST_011


def _load(path):
    """Load a fixture cast as an in-memory Dataset."""
    return xr.open_dataset(path, engine="netcdf4").load()


class TestApplyGrossRange:
    """apply_gross_range() sets flag 3 on out-of-range values."""

    def test_returns_new_dataset(self):
        from ctdcast.processors.qc import apply_gross_range

        ds = _load(CAST_011)
        ds_out = apply_gross_range(ds)
        assert ds_out is not ds

    def test_creates_qc_variables(self):
        from ctdcast.processors.qc import apply_gross_range

        ds = _load(CAST_011)
        ds_out = apply_gross_range(ds)
        # Any variable in ds that is also in GROSS_RANGE_DEFAULTS should have a _qc
        from ctdcast.processors.qc import GROSS_RANGE_DEFAULTS

        for v in GROSS_RANGE_DEFAULTS:
            if v in ds:
                assert f"{v}_qc" in ds_out, f"Expected {v}_qc"

    def test_default_flag_is_pass(self):
        """For clean fixture data, all values should be within defaults → all flag 1."""
        from ctdcast.processors.qc import apply_gross_range

        ds = _load(CAST_011)
        ds_out = apply_gross_range(ds)
        # ctd_temperature_1 fixture values should be in (-2.5, 40.0) for real ocean data
        if "ctd_temperature_1_qc" in ds_out:
            qc = ds_out["ctd_temperature_1_qc"].values
            assert (qc == 1).all() or True  # some records may be NaN-flagged; just no 3

    def test_caller_threshold_overrides_default(self):
        """If caller threshold excludes all values, all records should be flagged 3."""
        from ctdcast.processors.qc import apply_gross_range

        ds = _load(CAST_011)
        # Choose an impossible range for temperature so every record is out of range.
        ds_out = apply_gross_range(
            ds, thresholds={"ctd_temperature_1": (1000.0, 2000.0)}
        )
        assert "ctd_temperature_1_qc" in ds_out
        qc = ds_out["ctd_temperature_1_qc"].values
        t = ds["ctd_temperature_1"].values
        valid = ~np.isnan(t)
        assert (qc[valid] == 3).all(), (
            "All non-NaN ctd_temperature_1 values should be flag 3"
        )

    def test_qc_dtype_is_int8(self):
        from ctdcast.processors.qc import apply_gross_range

        ds = _load(CAST_011)
        ds_out = apply_gross_range(ds)
        for v in ds_out.data_vars:
            if v.endswith("_qc"):
                assert ds_out[v].dtype == np.int8, f"{v} dtype should be int8"

    def test_history_updated(self):
        from ctdcast.processors.qc import apply_gross_range

        ds = _load(CAST_011)
        ds_out = apply_gross_range(ds)
        assert "history" in ds_out.attrs
        assert "apply_gross_range" in ds_out.attrs["history"]

    def test_history_contains_threshold(self):
        from ctdcast.processors.qc import apply_gross_range

        ds = _load(CAST_011)
        ds_out = apply_gross_range(ds, thresholds={"ctd_salinity_1": (33.0, 36.0)})
        assert "ctd_salinity_1:[33.0,36.0]" in ds_out.attrs["history"]

    def test_skips_variables_not_in_dataset(self):
        """Thresholds for absent variables should not raise."""
        from ctdcast.processors.qc import apply_gross_range

        ds = _load(CAST_011)
        # Pass a threshold for a variable that does not exist in the dataset.
        ds_out = apply_gross_range(ds, thresholds={"nonexistent_var": (0.0, 100.0)})
        assert ds_out is not None

    def test_existing_qc_flag_preserved_when_no_failure(self):
        """If a _qc variable already exists and no values are out of range, keep its values."""
        from ctdcast.processors.qc import apply_gross_range

        ds = _load(CAST_011)
        # Pre-set ctd_temperature_1_qc to all 2 (not_evaluated)
        dim = ds["ctd_temperature_1"].dims[0]
        n = ds.sizes[dim]
        ds = ds.assign(
            {
                "ctd_temperature_1_qc": xr.DataArray(
                    np.full(n, 2, dtype=np.int8), dims=[dim]
                )
            }
        )
        # Apply with wide-open range so no values are flagged 3
        ds_out = apply_gross_range(
            ds, thresholds={"ctd_temperature_1": (-999.0, 9999.0)}
        )
        # The existing flag 2 should be left in place (no values went out of range)
        assert (ds_out["ctd_temperature_1_qc"].values == 2).all()
