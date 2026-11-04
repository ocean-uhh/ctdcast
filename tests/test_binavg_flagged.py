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


def test_flagged_value_leaves_only_its_own_variable_and_is_recorded(marked):
    assert marked["oxygen_raw_1_qc"].values[2000] == 4
    with pytest.warns(
        UserWarning, match="seabirdscientific's bin_average drops the whole scan"
    ):
        out = make_product(marked, PRODUCT, cast_number=11, cast_label="011")
    n = out.attrs["bin_average_partly_flagged_scans"]
    assert n >= 1
    assert "oxygen_raw_1" in out.attrs["bin_average_partly_flagged"]
    # The scan's temperature is still in its bin: the bin holding scan 2000 has its full count.
    p = float(marked["pressure"].values[2000])
    b = int(np.nanargmin(np.abs(out["pressure"].values - p)))
    assert np.isfinite(out["ctd_temperature_1"].values[b])
    assert np.isfinite(
        out["oxygen_raw_1"].values[b]
    )  # the other scans' oxygen still binned


def test_no_flagged_values_is_said_plainly(hex_stage2):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s3 = stage3(hex_stage2, {}, cast_number=11)
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        out = make_product(s3, PRODUCT, cast_number=11, cast_label="011")
    assert out.attrs["bin_average_partly_flagged_scans"] == 0
    assert out.attrs["bin_average_partly_flagged"].startswith("none")


def test_cast_page_shows_the_divergence_amber_with_its_criterion(marked):
    from ctdcast.reports.cast import _ctdcast_corrections_html

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = make_product(marked, PRODUCT, cast_number=11, cast_label="011")
    page_ds = marked.copy()
    _stamp_product_divergence(page_ds, [(PRODUCT, out)])
    assert "1dbar_down:" in page_ds.attrs["products_bin_average_partly_flagged"]
    html = _ctdcast_corrections_html(page_ds, "")
    assert "binavg (1dbar_down)" in html
    assert "Amber binavg row" in html
    assert "a scan with any flagged value is dropped whole" in html
    row = html[
        html.index("binavg (1dbar_down)") - 200 : html.index("binavg (1dbar_down)")
    ]
    assert "var(--warn-bg)" in row  # the row itself is amber
