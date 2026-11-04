"""Bin Average keeps a scan's good values when one variable's value is flagged (OdB .hex slice)."""

import warnings

import numpy as np
import pytest

from ctdcast.processors.products import make_product
from ctdcast.processors.stage3 import _stamp_product_divergence, stage3

PRODUCT = {
    "name": "1dbar_down",
    "steps": [{"split": "down"}, {"binavg": {"bin": "decibars", "size": 1}}],
}


def _binavg(**params):
    return {"name": "p", "steps": [{"binavg": params}]}


def _make(ds, product):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return make_product(ds, product, cast_number=11, cast_label="011")


@pytest.fixture
def marked(hex_stage2):
    """Stage 3 with Wild Edit on the oxygen voltage, after a +1 V spike at scan 2000."""
    ds = hex_stage2.copy(deep=True)
    v = ds["oxygen_raw_1"].values.copy()
    v[2000] += 1.0
    ds["oxygen_raw_1"] = ("time", v, ds["oxygen_raw_1"].attrs)
    steps = [{"wildedit": {"variables": ["oxygen_raw_1"], "mindelta": 0.05}}]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return stage3(ds, {"data_processing": {"steps": steps}}, cast_number=11)


@pytest.fixture
def clean(hex_stage2):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return stage3(hex_stage2, {}, cast_number=11)


def test_flagged_value_leaves_only_its_own_variable_and_is_recorded(marked):
    assert marked["oxygen_raw_1_qc"].values[2000] == 4
    with pytest.warns(UserWarning, match="would be dropped whole"):
        out = make_product(marked, PRODUCT, cast_number=11, cast_label="011")
    assert out.attrs["bin_average_partly_flagged_scans"] == 1
    assert "oxygen_raw_1 1" in out.attrs["bin_average_partly_flagged"]
    # The scan's temperature is still in its bin, and so are the other scans' oxygen values.
    p = float(marked["pressure"].values[2000])
    b = int(np.nanargmin(np.abs(out["pressure"].values - p)))
    assert np.isfinite(out["ctd_temperature_1"].values[b])
    assert np.isfinite(out["oxygen_raw_1"].values[b])


def test_no_flagged_values_is_said_plainly(clean):
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        out = make_product(clean, PRODUCT, cast_number=11, cast_label="011")
    assert out.attrs["bin_average_partly_flagged_scans"] == 0
    assert out.attrs["bin_average_partly_flagged"].startswith("none")


@pytest.mark.parametrize("kind", ["seconds", "scans"])
def test_stage2_soak_and_deck_flags_are_not_counted(clean, kind):
    """Scans flagged in every variable are whole-scan flags, not one sensor's."""
    out = _make(clean, _binavg(bin=kind, size=24 if kind == "scans" else 1))
    assert out.attrs["bin_average_partly_flagged_scans"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"bin": "scans", "size": 24, "skip_over": 2500},  # the spike is trimmed off
        {"bin": "decibars", "size": 1, "min_scans": 100000},  # no bins at all
    ],
)
def test_scans_in_no_bin_are_not_counted(marked, params):
    assert (
        _make(marked, _binavg(**params)).attrs["bin_average_partly_flagged_scans"] == 0
    )


def test_a_nan_in_a_whole_scan_flag_does_not_make_it_partial(clean):
    ds = clean.copy(deep=True)
    whole = int(np.flatnonzero(ds["ctd_temperature_1_qc"].values == 4)[0])
    fl = ds["ctd_fluor"].values.copy()
    fl[whole] = np.nan
    ds["ctd_fluor"] = ("time", fl, ds["ctd_fluor"].attrs)
    out = _make(ds, _binavg(bin="scans", size=24))
    assert out.attrs["bin_average_partly_flagged_scans"] == 0


def test_a_product_that_fails_to_write_names_only_itself(
    marked, tmp_path, monkeypatch, capsys
):
    from ctdcast.processors import stage3 as s3

    good = {"name": "good", "steps": [{"binavg": {"bin": "decibars", "size": 1}}]}
    bad = {"name": "bad", "steps": [{"binavg": {"bin": "decibars", "size": 1}}]}
    made = [(bad, _make(marked, bad)), (good, _make(marked, good))]
    real = s3._write_nc

    def flaky(ds, path):
        if "bad" in str(path):
            raise OSError("disk full")
        real(ds, path)

    monkeypatch.setattr(s3, "_write_nc", flaky)
    s3._write_products(made, tmp_path, "MIXSED2_011")
    err = capsys.readouterr().err
    assert "FAILED writing product bad" in err
    assert (tmp_path / "products" / "good" / "MIXSED2_011_good.nc").exists()


def test_cast_page_shows_the_divergence_amber_with_its_criterion(marked):
    from ctdcast.reports.cast import _ctdcast_corrections_html

    out = _make(marked, PRODUCT)
    page_ds = marked.copy()
    _stamp_product_divergence(page_ds, [(PRODUCT, out)])
    assert "1dbar_down:" in page_ds.attrs["products_bin_average_partly_flagged"]
    html = _ctdcast_corrections_html(page_ds, "")
    assert "binavg (1dbar_down)" in html
    assert "Amber binavg row" in html
    assert "a scan with any flagged value is dropped whole" in html
    at = html.index("binavg (1dbar_down)")
    assert "var(--warn-bg)" in html[at - 200 : at]  # the row itself is amber
