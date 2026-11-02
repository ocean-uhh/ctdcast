import warnings

import numpy as np
import pytest
from seabirdscientific import processing as sp

from ctdcast.processors.filtering import (
    apply_filter,
    apply_window_filter,
    check_filter,
    check_window_filter,
)
from ctdcast.processors.stage3 import stage3

DT = 1 / 24


def test_filter_is_seabirdscientific_low_pass(hex_stage2):
    out, done = apply_filter(
        hex_stage2, {"time_constant": 0.15, "variables": ["pressure", "absent"]}
    )
    assert done == ["pressure"]
    expected = sp.low_pass_filter(hex_stage2.pressure.values.astype(float), 0.15, DT)
    np.testing.assert_allclose(out.pressure.values, expected, rtol=0, atol=1e-4)
    assert out.pressure.attrs["filters"] == "low-pass 0.15 s"
    assert "not in this cast: absent" in out.attrs["history"]
    out2, _ = apply_filter(out, {"time_constant": 0.03, "variables": ["pressure"]})
    assert out2.pressure.attrs["filters"] == "low-pass 0.15 s; low-pass 0.03 s"


def test_filter_steps_over_marked_values_and_keeps_them(hex_stage2):
    x = hex_stage2.oxygen_raw_1.values.astype(float)
    marked = np.zeros(x.size, dtype=bool)
    marked[[100, 101, 500]] = True
    out, _ = apply_filter(
        hex_stage2,
        {"time_constant": 0.03, "variables": ["oxygen_raw_1"]},
        marked={"oxygen_raw_1": marked},
    )
    y = out.oxygen_raw_1.values
    np.testing.assert_array_equal(y[marked], x[marked].astype(y.dtype))
    bridged = x.copy()
    idx = np.arange(x.size)
    bridged[marked] = np.interp(idx[marked], idx[~marked], x[~marked])
    expected = sp.low_pass_filter(bridged, 0.03, DT)
    np.testing.assert_allclose(y[~marked], expected[~marked], atol=1e-5)


def test_window_filter_median_matches_seabirdscientific(hex_stage2):
    sub = hex_stage2.isel(time=slice(0, 600))
    out, done = apply_window_filter(
        sub, {"type": "median", "width": 9, "variables": ["ctd_fluor"]}
    )
    x = sub.ctd_fluor.values.astype(float)
    expected = sp.window_filter(x, np.zeros_like(x), "median", 9, DT)
    np.testing.assert_allclose(out.ctd_fluor.values, expected, atol=1e-5)
    assert out.ctd_fluor.attrs["filters"] == "window median 9 scans"


@pytest.mark.parametrize(
    ("check", "params", "match"),
    [
        (check_filter, {"variables": ["pressure"]}, "needs time_constant"),
        (
            check_filter,
            {"time_constant": -1, "variables": ["pressure"]},
            "must be positive",
        ),
        (check_filter, {"time_constant": 0.1}, "list of variable names"),
        (
            check_filter,
            {"time_constant": 0.1, "variables": ["p"], "a": 1},
            "unknown key",
        ),
        (
            check_window_filter,
            {"type": "hann", "width": 5, "variables": ["p"]},
            "expected one of",
        ),
        (
            check_window_filter,
            {"type": "median", "width": 1, "variables": ["p"]},
            "at least 2",
        ),
        (
            check_window_filter,
            {"type": "median", "width": 5.0, "variables": ["p"]},
            "whole number",
        ),
    ],
)
def test_parameters_are_checked(check, params, match):
    with pytest.raises(ValueError, match=match):
        check(params)


def test_stage3_filters_then_rederives_salinity(hex_stage2):
    cfg = {
        "data_processing": {
            "steps": [
                {"filter": {"time_constant": 0.5, "variables": ["ctd_temperature_1"]}}
            ]
        }
    }
    out = stage3(hex_stage2, cfg, cast_number=11)
    assert out.attrs["data_processing_steps"] == "filter"
    assert "salinity re-derived from corrected" in out.attrs["history"]
    assert not np.allclose(
        out.ctd_salinity_1.values, hex_stage2.ctd_salinity_1.values, equal_nan=True
    )


def test_filter_skipped_on_a_cast_sea_bird_already_filtered():
    from pathlib import Path

    from ctdcast.readers.cnv import read

    pytest.importorskip("seasenselib")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = read(Path(__file__).parent / "fixtures" / "cnv" / "mixsed2_004.cnv")
    cfg = {
        "data_processing": {
            "steps": [{"filter": {"time_constant": 0.15, "variables": ["pressure"]}}]
        }
    }
    with pytest.warns(UserWarning, match="filter skipped"):
        out = stage3(ds, cfg, cast_number=4)
    np.testing.assert_array_equal(out.pressure.values, ds.pressure.values)
