"""Regression tests: the code review of the stage-3 steps and products, on the OdB .hex slice."""

import warnings

import numpy as np
import pytest

from ctdcast.processors.products import check_binavg, make_product, split_leg
from ctdcast.processors.stage3 import stage3


def _run(ds, steps, **kw):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return stage3(ds, {"data_processing": {"steps": steps, **kw}}, cast_number=11)


def _with(ds, var, i, delta):
    out = ds.copy(deep=True)
    x = out[var].values.copy()
    x[i] += delta
    out[var] = ("time", x, out[var].attrs)
    return out


def test_failed_pressure_does_not_set_the_bottom_or_the_bins(hex_stage2):
    """A pressure spike Wild Edit marks is left out of split and bin average."""
    p = hex_stage2.pressure.values
    i = 1000
    spiked = _with(hex_stage2, "pressure", i, 500.0 - p[i])
    steps = [{"wildedit": {"variables": ["pressure"], "mindelta": 0.1}}]
    clean, s3 = _run(hex_stage2.copy(deep=True), steps), _run(spiked, steps)
    assert s3.pressure_qc.values[i] == 4
    product = {
        "name": "1dbar_down",
        "steps": [{"split": "down"}, {"binavg": {"bin": "decibars", "size": 1}}],
    }
    a = make_product(clean, product, cast_number=11, cast_label="011")
    b = make_product(s3, product, cast_number=11, cast_label="011")
    assert split_leg(s3, "down").sizes["time"] == split_leg(clean, "down").sizes["time"]
    assert b.sizes["bin"] == a.sizes["bin"]
    assert np.nanmax(b.pressure.values) < 200


def test_failed_pressure_is_left_out_of_profiles(hex_stage2, tmp_path):
    from ctdcast.processors.profiles import build_profiles

    p = hex_stage2.pressure.values
    s3 = _run(
        _with(hex_stage2, "pressure", 1000, 500.0 - p[1000]),
        [{"wildedit": {"variables": ["pressure"], "mindelta": 0.1}}],
    )
    src = tmp_path / "stage3"
    src.mkdir()
    s3.to_netcdf(src / "MIXSED2_011_stage3.nc")
    out = tmp_path / "profiles.nc"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        build_profiles(tmp_path, out, force=True)
    import xarray as xr

    with xr.open_dataset(out, engine="netcdf4") as prof:
        assert float(prof.pressure.max()) < 200
        assert float(prof.max_pressure.max()) < 200 if "max_pressure" in prof else True


def test_marked_oxygen_voltage_does_not_spread(hex_stage2):
    """A voltage spike Wild Edit marks changes the oxygen only at its own (flagged) scan."""
    steps = [{"wildedit": {"variables": ["oxygen_raw_1"], "mindelta": 0.05}}]
    clean = _run(hex_stage2.copy(deep=True), steps)
    s3 = _run(_with(hex_stage2, "oxygen_raw_1", 2000, 1.0), steps)
    assert s3.oxygen_raw_1_qc.values[2000] == 4
    name = next(
        v for v in s3.data_vars if v.startswith("ctd_oxygen") and "_qc" not in v
    )
    diff = np.abs(s3[name].values - clean[name].values)
    good = s3[f"{name}_qc"].values != 4
    assert np.nanmax(diff[good]) < 0.01
    assert s3[f"{name}_qc"].values[2000] == 4
    assert s3[name].attrs["oxygen_marked_inputs_bridged"] >= 1


def test_product_without_binavg_re_derives_salinity(hex_stage2):
    s3 = _run(hex_stage2.copy(deep=True), [])
    product = {
        "name": "filtered",
        "steps": [{"filter": {"time_constant": 2.0, "variables": ["conductivity_1"]}}],
    }
    out = make_product(s3, product, cast_number=11, cast_label="011")
    assert (
        np.nanmax(np.abs(out.conductivity_1.values - s3.conductivity_1.values)) > 0.01
    )
    from ctdcast.analysis.derive import derive_salinity

    expected = derive_salinity(out.drop_vars("ctd_salinity_1")).ctd_salinity_1.values
    np.testing.assert_allclose(out.ctd_salinity_1.values, expected, equal_nan=True)


def test_product_filters_step_over_stage3_marks(hex_stage2):
    """A filter in a product bridges the values Wild Edit marked, as it does at stage 3."""
    from ctdcast.processors.steps import StepContext

    mark = {"wildedit": {"variables": ["conductivity_1"], "mindelta": 0.1}}
    filt = {"filter": {"time_constant": 0.5, "variables": ["conductivity_1"]}}
    spiked = _with(hex_stage2, "conductivity_1", 2000, 5.0)
    at_stage3 = _run(spiked.copy(deep=True), [mark, filt])
    ctx = StepContext()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s3 = stage3(
            spiked,
            {"data_processing": {"steps": [mark]}},
            cast_number=11,
            context=ctx,
        )
    assert s3.conductivity_1_qc.values[2000] == 4 and ctx.marked["conductivity_1"][2000]
    product = make_product(
        s3,
        {"name": "f", "steps": [filt]},
        cast_number=11,
        cast_label="011",
        marked=ctx.marked,
    )
    np.testing.assert_allclose(
        product.conductivity_1.values, at_stage3.conductivity_1.values, atol=1e-9
    )
    # From the file alone, the spike's neighbours are still clear of it.
    alone = make_product(
        s3, {"name": "f", "steps": [filt]}, cast_number=11, cast_label="011"
    )
    near = slice(1990, 2011)
    np.testing.assert_allclose(
        alone.conductivity_1.values[near],
        at_stage3.conductivity_1.values[near],
        atol=1e-6,
    )


def test_split_after_a_filter_keeps_the_marks_aligned(hex_stage2):
    from ctdcast.processors.steps import StepContext

    mark = {"wildedit": {"variables": ["conductivity_1"], "mindelta": 0.1}}
    filt = {"filter": {"time_constant": 0.5, "variables": ["conductivity_1"]}}
    ctx = StepContext()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s3 = stage3(
            _with(hex_stage2, "conductivity_1", 2000, 5.0),
            {"data_processing": {"steps": [mark]}},
            cast_number=11,
            context=ctx,
        )
    product = {"name": "d", "steps": [{"split": "down"}, filt]}
    out = make_product(s3, product, cast_number=11, cast_label="011", marked=ctx.marked)
    assert out.sizes["time"] == split_leg(s3, "down").sizes["time"]


def test_binavg_exclude_flagged_false_is_refused():
    with pytest.raises(ValueError, match="exclude_flagged: false"):
        check_binavg({"bin": "decibars", "size": 1, "exclude_flagged": False})
    assert check_binavg({"bin": "decibars", "size": 1})["exclude_flagged"] is True


def test_wild_edit_after_loop_edit_counts_only_its_own_marks(hex_stage2):
    we = {"wildedit": {"variables": ["ctd_temperature_1"]}}
    alone = _run(hex_stage2.copy(deep=True), [we])
    after = _run(hex_stage2.copy(deep=True), [{"loopedit": {"min_velocity": 0.5}}, we])
    loop = after.loop_edit_flag.values.astype(bool)
    n_alone = alone.ctd_temperature_1.attrs["wild_edit_marked"]
    n_after = after.ctd_temperature_1.attrs["wild_edit_marked"]
    assert n_after <= n_alone
    assert loop.any()
