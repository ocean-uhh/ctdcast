from pathlib import Path

import matplotlib
import numpy as np
import pytest
import xarray as xr

from ctdcast.analysis.sbe_compare import compare, comparison_table, read_reference

matplotlib.use("Agg")

FIX = Path(__file__).parent / "fixtures"
BAD = -9.990e-29


def _pair(n=50):
    p = np.linspace(0, 100, n)
    t = 10 - 0.05 * p
    ours = xr.Dataset(
        {
            "pressure": ("time", p, {"units": "dbar"}),
            "ctd_temperature_1": ("time", t + 0.001, {"units": "degree_Celsius"}),
            "ctd_temperature_1_qc": ("time", np.ones(n, dtype="int8")),
        }
    )
    ref = xr.Dataset(
        {"pressure": ("time", p.copy()), "ctd_temperature_1": ("time", t.copy())}
    )
    return ours, ref


def test_difference_statistics():
    ours, ref = _pair()
    row = {r.name: r for r in compare(ours, ref)}["ctd_temperature_1"]
    assert row.n_compared == 50
    assert row.median == pytest.approx(0.001)
    assert row.rms == pytest.approx(0.001)


def test_flags_on_either_side_are_left_out_and_counted():
    ours, ref = _pair()
    ref["ctd_temperature_1"][3] = np.nan
    ref["ctd_temperature_1_sbe_flagged"] = ("time", np.arange(50) == 3)
    ours["ctd_temperature_1_qc"][[3, 7]] = 4
    ours["ctd_temperature_1"][7] = 99.0
    row = compare(ours, ref, ["ctd_temperature_1"])[0]
    assert row.n_compared == 48
    assert (row.flagged_ref, row.flagged_ours, row.flagged_both) == (1, 2, 1)
    assert row.max_abs == pytest.approx(0.001)
    assert "ctd_temperature_1" in comparison_table([row])


def test_scan_count_mismatch_raises():
    ours, ref = _pair()
    with pytest.raises(ValueError, match="scan counts differ"):
        compare(ours, ref.isel(time=slice(0, 40)))


def test_reference_bad_flag_becomes_nan():
    pytest.importorskip("seasenselib")
    ref = read_reference(FIX / "cnv" / "mixsed2_004.cnv")
    flagged = [v for v in ref.data_vars if v.endswith("_sbe_flagged")]
    assert flagged
    for f in flagged:
        name = f.removesuffix("_sbe_flagged")
        vals = ref[name].values[ref[f].values]
        assert np.isnan(vals).all()
    assert not any(
        np.any((ref[v].values < 0) & (np.abs(ref[v].values) < 1e-20))
        for v in ref.data_vars
        if ref[v].dtype.kind == "f"
    )


def test_cnv_oxygen_voltage_named_by_sensor():
    # sbeox0V is the primary SBE 43 whatever column order seasenselib numbers it in.
    pytest.importorskip("seasenselib")
    ref = read_reference(FIX / "cnv" / "mixsed2_004.cnv")
    assert "oxygen_raw_1" in ref and "oxygen_raw_2" not in ref


def test_figure_draws_and_declines():
    from ctdcast.plotters.sbe_compare import draw_sbe_compare_fig

    ours, ref = _pair()
    fig = draw_sbe_compare_fig(ours, ref, ["pressure", "ctd_temperature_1"])
    assert fig is not None and len(fig.axes) == 2
    assert draw_sbe_compare_fig(ours, ref.isel(time=slice(0, 10)), ["pressure"]) is None
    assert draw_sbe_compare_fig(ours, ref, ["not_there"]) is None
