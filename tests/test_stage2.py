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
            # SENSOR_* catalog scalars and any dimensionless var get no _qc companion.
            if v in _SKIP_STAGE2_QC or v.startswith("SENSOR_") or ds[v].ndim == 0:
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
        assert "stage2: soak/deck" in ds_out.attrs["history"]
        # The note names the variables it flagged, so the record says what was touched.
        assert "flag 4 on" in ds_out.attrs["history"]
        assert "ctd_temperature_1" in ds_out.attrs["history"]

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


class TestCuratedDrop:
    """apply_curated_drop removes the SBE-derived channels stage 1 keeps, and records it."""

    def test_default_drops_sbe_and_records(self):
        from ctdcast.processors.stage2 import apply_curated_drop

        ds = xr.Dataset(
            {
                "ctd_temperature_1": ("time", np.arange(3.0)),
                "sbe_density": ("time", np.arange(3.0)),
                "sbe_flag": ("time", np.arange(3.0)),
            },
            coords={"time": np.arange(3)},
        )
        out = apply_curated_drop(ds)
        assert "sbe_density" not in out and "sbe_flag" not in out
        assert "ctd_temperature_1" in out  # a real measurement is untouched
        assert "sbe_density" in out.attrs["dropped_channels"]
        assert "stage2 curated drop" in out.attrs["history"]

    def test_explicit_list_is_a_subset_not_the_full_default(self):
        """A drop_sbe list drops exactly those sbe_ names — a subset — not the full sbe_ default."""
        from ctdcast.processors.stage2 import apply_curated_drop

        ds = xr.Dataset(
            {
                "sbe_density": ("time", np.arange(3.0)),
                "sbe_flag": ("time", np.arange(3.0)),
            },
            coords={"time": np.arange(3)},
        )
        out = apply_curated_drop(ds, drop_names=["sbe_density"])
        assert "sbe_density" not in out  # the one listed
        assert (
            "sbe_flag" in out
        )  # NOT dropped — the list overrides the drop-all-sbe_ default

    def test_explicit_list_refuses_non_sbe_name(self):
        """A non-sbe_ name in drop_sbe is an operator error and must raise, not silently drop
        a science/provenance channel."""
        import pytest

        from ctdcast.processors.stage2 import apply_curated_drop

        ds = xr.Dataset(
            {"ctd_temperature_2": ("time", np.arange(3.0))},
            coords={"time": np.arange(3)},
        )
        with pytest.raises(ValueError, match="only sbe_"):
            apply_curated_drop(ds, drop_names=["ctd_temperature_2"])

    def test_stage1_keeps_sbe_channels(self):
        """Stage 1 is a faithful translation: the regenerated fixture carries the sbe_* set."""
        ds = _load(CAST_011)
        try:
            sbe = sorted(v for v in ds.data_vars if str(v).startswith("sbe_"))
            assert "sbe_density" in sbe and "sbe_timeJ" in sbe
        finally:
            ds.close()
