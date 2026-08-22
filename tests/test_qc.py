"""Tests for ctdcast.processors.qc — two-tier gross-range and spike flagging."""

import numpy as np
import xarray as xr
from conftest import CAST_011

from ctdcast.processors.qc import (
    GROSS_RANGE_FAIL,
    GROSS_RANGE_SUSPECT,
    apply_gross_range,
    apply_spike_test,
)


def _load(path):
    """Load a fixture cast as an in-memory Dataset."""
    with xr.open_dataset(path, engine="netcdf4") as ds:
        return ds.load()


class TestApplyGrossRange:
    """apply_gross_range sets flag 3 outside suspect bounds, flag 4 outside fail."""

    def test_returns_new_dataset(self):
        ds = _load(CAST_011)
        assert apply_gross_range(ds) is not ds

    def test_creates_qc_variables(self):
        ds = _load(CAST_011)
        ds_out = apply_gross_range(ds)
        for v in set(GROSS_RANGE_SUSPECT) | set(GROSS_RANGE_FAIL):
            if v in ds:
                assert f"{v}_qc" in ds_out, f"expected {v}_qc"

    def test_qc_dtype_is_int8(self):
        ds_out = apply_gross_range(_load(CAST_011))
        for v in ds_out.data_vars:
            if v.endswith("_qc"):
                assert ds_out[v].dtype == np.int8

    def test_suspect_override_flags_3(self):
        """A suspect range excluding every value flags them suspect (3)."""
        ds = _load(CAST_011)
        ds_out = apply_gross_range(
            ds, thresholds={"suspect": {"ctd_temperature_1": (1000.0, 2000.0)}}
        )
        qc = ds_out["ctd_temperature_1_qc"].values
        valid = np.isfinite(ds["ctd_temperature_1"].values)
        assert (qc[valid] == 3).all()

    def test_fail_override_flags_4_over_suspect(self):
        """Outside the fail range flags 4, which wins over suspect."""
        ds = _load(CAST_011)
        ds_out = apply_gross_range(
            ds,
            thresholds={
                "suspect": {"ctd_temperature_1": (1000.0, 2000.0)},
                "fail": {"ctd_temperature_1": (1000.0, 2000.0)},
            },
        )
        qc = ds_out["ctd_temperature_1_qc"].values
        valid = np.isfinite(ds["ctd_temperature_1"].values)
        assert (qc[valid] == 4).all()

    def test_records_both_tiers_on_qc_var(self):
        ds = _load(CAST_011)
        ds_out = apply_gross_range(
            ds,
            thresholds={
                "suspect": {"ctd_salinity_1": (33.0, 36.0)},
                "fail": {"ctd_salinity_1": (30.0, 40.0)},
            },
        )
        a = ds_out["ctd_salinity_1_qc"].attrs
        assert a["qc_gross_range_suspect_min"] == 33.0
        assert a["qc_gross_range_fail_max"] == 40.0

    def test_history_updated(self):
        ds_out = apply_gross_range(_load(CAST_011))
        assert "stage3: gross_range" in ds_out.attrs["history"]

    def test_skips_variables_not_in_dataset(self):
        ds_out = apply_gross_range(
            _load(CAST_011), thresholds={"suspect": {"nope": (0.0, 1.0)}}
        )
        assert ds_out is not None

    def test_worst_flag_not_downgraded(self):
        """An existing fail (4) is not lowered to suspect (3) by gross-range."""
        ds = _load(CAST_011)
        dim = ds["ctd_temperature_1"].dims[0]
        ds = ds.assign(
            {
                "ctd_temperature_1_qc": xr.DataArray(
                    np.full(ds.sizes[dim], 4, dtype=np.int8), dims=[dim]
                )
            }
        )
        ds_out = apply_gross_range(
            ds, thresholds={"suspect": {"ctd_temperature_1": (1000.0, 2000.0)}}
        )
        assert (ds_out["ctd_temperature_1_qc"].values == 4).all()

    def test_missing_data_flagged_9_not_pass(self):
        """A NaN sample is missing (9), not pass (1)."""
        ds = _load(CAST_011)
        vals = ds["ctd_temperature_1"].values.copy()
        vals[5] = np.nan  # mark one real sample missing
        ds["ctd_temperature_1"] = ds["ctd_temperature_1"].copy(data=vals)
        ds_out = apply_gross_range(ds)
        assert ds_out["ctd_temperature_1_qc"].values[5] == 9


class TestApplySpikeTest:
    """apply_spike_test sets flag 3/4 on the QARTOD spike metric."""

    def test_flags_spikes_and_records_threshold(self):
        """A tiny suspect threshold makes natural variability exceed it → flag 3."""
        ds = _load(CAST_011)
        ds_out = apply_spike_test(
            ds, thresholds={"suspect": {"ctd_temperature_1": 1e-4}}
        )
        qc = ds_out["ctd_temperature_1_qc"].values
        assert (qc == 3).any(), "a near-zero spike threshold should flag some records"
        assert (
            ds_out["ctd_temperature_1_qc"].attrs["qc_spike_suspect_threshold"] == 1e-4
        )

    def test_endpoints_not_evaluated(self):
        """First and last samples have no spike metric, so they are never flagged."""
        ds = _load(CAST_011)
        ds_out = apply_spike_test(
            ds, thresholds={"suspect": {"ctd_temperature_1": 1e-4}}
        )
        qc = ds_out["ctd_temperature_1_qc"].values
        assert qc[0] != 3 and qc[-1] != 3

    def test_history_updated(self):
        ds_out = apply_spike_test(_load(CAST_011))
        assert "stage3: spike" in ds_out.attrs["history"]
