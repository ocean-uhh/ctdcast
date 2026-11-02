import shutil
import warnings
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ctdcast.processors.products import (
    bin_average,
    check_binavg,
    check_products,
    make_product,
    split_leg,
)

FIX = Path(__file__).parent / "fixtures"


def test_seconds_bins_average_each_second(hex_stage2):
    out = bin_average(
        hex_stage2, {"bin": "seconds", "size": 1, "exclude_flagged": False}
    )
    n = hex_stage2.sizes["time"]
    assert abs(out.sizes["bin"] - n / 24) <= 2
    assert set(out.nbin.values[1:-1]) <= {23, 24, 25}
    # A full bin is the plain mean of its scans (those not flagged 4 or 9).
    i = 5
    t0 = hex_stage2.time.values[0]
    secs = (hex_stage2.time.values - t0) / np.timedelta64(1, "s")
    p = hex_stage2.pressure.values.astype(float)
    in_bin = (secs >= i - 0.5) & (secs < i + 0.5)
    k = int(np.argmin(np.abs(out.time.values - (t0 + np.timedelta64(i, "s")))))
    assert out.pressure.values[k] == pytest.approx(p[in_bin].mean(), abs=1e-4)
    assert "ctd_salinity_1" in out and "re-derived" in out.attrs["history"]
    assert "processing.bin_average" in out.attrs["bin_average_method"]


def test_a_flagged_value_leaves_only_its_own_variable(hex_stage2):
    ds = hex_stage2.copy()
    qc = np.ones(ds.sizes["time"], dtype=np.int8)
    qc[:240] = 4  # the first ten seconds of temperature fail
    ds["ctd_temperature_1_qc"] = ("time", qc)
    out = bin_average(ds, {"bin": "seconds", "size": 1, "exclude_flagged": False})
    early = out.time.values < ds.time.values[0] + np.timedelta64(9, "s")
    assert np.isnan(out.ctd_temperature_1.values[early]).all()
    assert np.isfinite(out.pressure.values[early]).all()


def test_loop_edit_scans_leave_the_whole_bin(hex_stage2):
    ds = hex_stage2.copy()
    flag = np.zeros(ds.sizes["time"], dtype=np.int8)
    flag[:240] = 1
    ds["loop_edit_flag"] = ("time", flag)
    kept = bin_average(ds, {"bin": "seconds", "size": 1, "exclude_flagged": False})
    dropped = bin_average(ds, {"bin": "seconds", "size": 1, "exclude_flagged": True})
    assert dropped.sizes["bin"] < kept.sizes["bin"]
    assert dropped.time.values.min() >= ds.time.values[230]


def test_split_keeps_one_leg(hex_stage2):
    p = hex_stage2.pressure.values
    deepest = int(np.nanargmax(p))
    down = split_leg(hex_stage2, "down")
    up = split_leg(hex_stage2, "up")
    assert down.sizes["time"] == deepest + 1
    assert up.sizes["time"] == p.size - deepest
    binned = bin_average(down, {"bin": "decibars", "size": 1})
    assert np.all(np.diff(binned.pressure.values) > 0)
    assert "downcast" in binned.attrs["bin_average"]


@pytest.mark.parametrize(
    ("products", "match"),
    [
        (
            [{"name": "a b", "steps": [{"binavg": {"bin": "seconds", "size": 1}}]}],
            "letters",
        ),
        (
            [
                {
                    "name": "x",
                    "steps": [
                        {"binavg": {"bin": "seconds", "size": 1}},
                        {"split": "down"},
                    ],
                }
            ],
            "last step",
        ),
        ([{"name": "x", "steps": [{"split": "down"}, {"split": "up"}]}], "once"),
        (
            [{"name": "x", "steps": [{"binavg": {"bin": "seconds", "size": 1}}]}] * 2,
            "used twice",
        ),
        ([{"name": "x", "steps": [{"split": "sideways"}]}], "down or up"),
        ([{"name": "x", "steps": []}], "no steps"),
    ],
)
def test_products_are_checked(products, match):
    with pytest.raises(ValueError, match=match):
        check_products(products)


def test_binavg_parameters_are_checked():
    with pytest.raises(ValueError, match="expected one of"):
        check_binavg({"bin": "metres", "size": 1})
    with pytest.raises(ValueError, match="whole number"):
        check_binavg({"bin": "seconds", "size": 1, "min_scans": 1.5})
    assert check_binavg({"bin": "seconds", "size": 1, "surface_bin": {"max": 3}})[
        "surface_bin"
    ] == {
        "min": 0.0,
        "max": 3.0,
        "value": 2.5,
    }


def test_product_runs_its_own_loop_edit(hex_stage2):
    prod = make_product(
        hex_stage2,
        {
            "name": "x",
            "steps": [{"loopedit": {}}, {"binavg": {"bin": "seconds", "size": 1}}],
        },
        cast_number=11,
        cast_label="011",
    )
    assert prod.attrs["product_steps"] == "loopedit; binavg"
    assert prod.attrs["product_name"] == "x"


def test_stage3_run_writes_products_beside_the_stage3_file(tmp_path):
    from ctdcast.processors.stage1 import stage1
    from ctdcast.processors.stage2 import run as stage2_run
    from ctdcast.processors.stage3 import run as stage3_run

    raw = tmp_path / "raw"
    raw.mkdir()
    for name in ("MIXSED2_011.hex", "MIXSED2_011.XMLCON"):
        shutil.copy(FIX / "hex_slice" / name, raw / name)
    cfg = {
        "data_processing": {
            "steps": [{"wildedit": {}}],
            "products": [
                {"name": "1sec", "steps": [{"binavg": {"bin": "seconds", "size": 1}}]},
                {
                    "name": "1dbar_down",
                    "steps": [
                        {"split": "down"},
                        {"binavg": {"bin": "decibars", "size": 1}},
                    ],
                },
            ],
        }
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stage1(raw, tmp_path / "ctd", backend="hex", pattern="*.[hH][eE][xX]")
        stage2_run(tmp_path / "ctd")
        stage3_run(tmp_path / "ctd", cruise_cfg=cfg)
    stage3_file = next((tmp_path / "ctd" / "stage3").glob("*.nc"))
    for name in ("1sec", "1dbar_down"):
        (path,) = (tmp_path / "ctd" / "products" / name).glob("*.nc")
        assert path.name.endswith(f"_{name}.nc")
        with xr.open_dataset(path, engine="netcdf4") as prod:
            assert prod.attrs["product_name"] == name
            assert "bin" in prod.dims
    with xr.open_dataset(stage3_file, engine="netcdf4") as ds:
        assert "time" in ds.dims and "bin" not in ds.dims


def test_split_leaves_its_input_alone(hex_stage2):
    before = dict(hex_stage2.attrs)
    split_leg(hex_stage2, "up")
    assert hex_stage2.attrs == before


def test_cast_page_lists_filters_and_loop_edit_in_order(hex_stage2):
    from ctdcast.processors.stage3 import stage3
    from ctdcast.reports.cast import _ctdcast_correction_rows, _ctdcast_corrections_html

    cfg = {
        "data_processing": {
            "steps": [
                {"filter": {"time_constant": 0.03, "variables": ["ctd_fluor"]}},
                {"filter": {"time_constant": 0.15, "variables": ["pressure"]}},
                {"loopedit": {}},
            ]
        }
    }
    out = stage3(hex_stage2, cfg, cast_number=11)
    rows = _ctdcast_correction_rows(out)
    assert [(r.label, r.parameters) for r, _ in rows][:2] == [
        ("filter", "low-pass 0.03 s"),
        ("filter", "low-pass 0.15 s"),
    ]
    assert [t.state for _, t in rows][:2] == ["no_reference", "match"]
    assert rows[2][0].label == "loopedit" and "scans marked" in rows[2][0].parameters
    assert "deck_pressure: true" in _ctdcast_corrections_html(out, "")
