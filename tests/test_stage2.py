"""Tests for ctdcast.cast.stage2 — apply_stage2 and flag-based refactor."""

import numpy as np
import xarray as xr
from conftest import CAST_011, CAST_128


def _load(path):
    """Load a fixture cast as an in-memory Dataset."""
    return xr.open_dataset(path, engine="netcdf4").load()


class TestApplyStage2:
    """apply_stage2() adds _qc variables and sets flag 4 on soak/deck records."""

    def test_returns_new_dataset(self):
        from ctdcast.processors.stage2 import apply_stage2

        ds = _load(CAST_011)
        ds_out = apply_stage2(ds)
        assert ds_out is not ds

    def test_adds_qc_variables(self):
        from ctdcast.processors.stage2 import _SKIP_STAGE2_QC, apply_stage2

        ds = _load(CAST_011)
        ds_out = apply_stage2(ds)
        phys_vars = [v for v in ds.data_vars if not v.endswith("_qc")]
        for v in phys_vars:
            if v in _SKIP_STAGE2_QC:
                continue
            assert f"{v}_qc" in ds_out, f"Expected {v}_qc in output"

    def test_qc_dtype_is_int8(self):
        from ctdcast.processors.stage2 import apply_stage2

        ds = _load(CAST_011)
        ds_out = apply_stage2(ds)
        for v in ds_out.data_vars:
            if v.endswith("_qc"):
                assert ds_out[v].dtype == np.int8, f"{v} dtype should be int8"

    def test_flag4_count_is_positive_for_real_casts(self):
        """Real casts should have at least some soak/deck records flagged."""
        from ctdcast.processors.stage2 import apply_stage2

        ds = _load(CAST_011)
        ds_out = apply_stage2(ds)
        # At least one _qc variable should have some flag-4 values.
        qc_vars = [v for v in ds_out.data_vars if v.endswith("_qc")]
        assert qc_vars, "No _qc variables in output"
        has_fail = any((ds_out[v].values == 4).any() for v in qc_vars)
        assert has_fail, "Expected at least some flag-4 records for a real cast"

    def test_pass_count_dominates(self):
        """Most records should pass (flag 1); fail records are a small fraction."""
        from ctdcast.processors.stage2 import apply_stage2

        ds = _load(CAST_128)
        ds_out = apply_stage2(ds)
        qc_vars = [v for v in ds_out.data_vars if v.endswith("_qc")]
        qc = ds_out[qc_vars[0]].values
        n = len(qc)
        n_pass = (qc == 1).sum()
        assert n_pass > n * 0.5, "Expected majority of records to be flag 1 (pass)"

    def test_history_attribute_updated(self):
        from ctdcast.processors.stage2 import apply_stage2

        ds = _load(CAST_011)
        ds_out = apply_stage2(ds)
        assert "history" in ds_out.attrs
        assert "apply_stage2" in ds_out.attrs["history"]

    def test_history_contains_parameters(self):
        from ctdcast.processors.stage2 import apply_stage2

        ds = _load(CAST_011)
        ds_out = apply_stage2(ds, near_surface_dbar=5.0)
        assert "near_surface_dbar=5.0" in ds_out.attrs["history"]

    def test_does_not_flag_pressure_qc(self):
        from ctdcast.processors.stage2 import apply_stage2

        ds = _load(CAST_011)
        ds_out = apply_stage2(ds)
        assert "pressure_qc" not in ds_out.data_vars

    def test_preserves_original_variables(self):
        from ctdcast.processors.stage2 import apply_stage2

        ds = _load(CAST_011)
        ds_out = apply_stage2(ds)
        for v in ds.data_vars:
            assert v in ds_out.data_vars, f"Original variable {v} missing from output"

    def test_idempotent_on_re_apply(self):
        """Applying stage2 twice should produce the same flags (second call re-creates qc arrays)."""
        from ctdcast.processors.stage2 import apply_stage2

        ds = _load(CAST_011)
        ds1 = apply_stage2(ds)
        ds2 = apply_stage2(ds1)
        qc_vars = [v for v in ds1.data_vars if v.endswith("_qc")]
        for v in qc_vars:
            np.testing.assert_array_equal(ds1[v].values, ds2[v].values)


class TestQcAttrs:
    """_qc_attrs() returns valid CF flag attribute dicts."""

    def test_qc_attrs_without_standard_name(self):
        from ctdcast.processors.qc import _qc_attrs

        attrs = _qc_attrs("fluorescence", None)
        assert "flag_values" in attrs
        assert "flag_meanings" in attrs
        assert "standard_name" not in attrs

    def test_qc_attrs_with_standard_name(self):
        from ctdcast.processors.qc import _qc_attrs

        attrs = _qc_attrs("temperature_1", "sea_water_temperature")
        assert attrs["standard_name"] == "sea_water_temperature status_flag"
