"""Tests for ``ctdcast fit``: the cost functions, the cruise fit and the command (real data)."""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr

from ctdcast.analysis import fits as F
from ctdcast.processors.fit import (
    FitSettings,
    cast_arrays,
    fit_cruise,
    suggested_yaml,
    summarise,
)
from ctdcast.processors.stage1 import stage1
from ctdcast.processors.stage2 import run as stage2_run

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def root(tmp_path_factory) -> Path:
    """A CTD root holding cast 011's .hex slice (7-98 dbar, 3600 scans) through stage 2."""
    tmp = tmp_path_factory.mktemp("fit")
    raw = tmp / "raw"
    raw.mkdir()
    for name in ("MIXSED2_011.hex", "MIXSED2_011.XMLCON"):
        shutil.copy(FIX / "hex_slice" / name, raw / name)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stage1(raw, tmp / "ctd", backend="hex", pattern="*.[hH][eE][xX]")
        stage2_run(tmp / "ctd")
    return tmp / "ctd"


@pytest.fixture(scope="module")
def cast(root) -> F.Cast:
    path = next((root / "stage2").glob("*.nc"))
    with xr.open_dataset(path, engine="netcdf4") as ds:
        return cast_arrays(ds.load(), 1, 1 / 24)


def test_despike_pressure_removes_a_single_scan_spike(cast):
    p = np.nan_to_num(cast.pressure, nan=50.0).copy()
    p[1000] = 30778.0
    out = F.despike_pressure(p)
    assert np.isnan(out[1000]) and np.isfinite(out[999]) and np.isfinite(out[1001])


def test_alignment_cost_has_a_minimum_inside_the_search(cast):
    cost = F.alignment_cost(cast)
    assert cost.shape == (2, F.DEFAULT_RESIDUALS.size)
    total = np.nansum(cost, axis=0)
    best = F.DEFAULT_RESIDUALS[np.nanargmin(total)]
    # The data carry the deck unit's 0.073 s; the residual minimum is near zero, not at an edge,
    # and too much advance costs more than the minimum (the spikes reverse).
    assert -0.05 <= best <= 0.03
    assert total[-1] > total.min() * 1.5


def test_ctm_cost_needs_both_legs_below_the_window(cast):
    # The slice is a downcast from 7 to 98 dbar: nothing below 200 dbar, and no upcast at all.
    assert F.ctm_cost(cast) is None
    assert F.ctm_cost(cast, pmin=20.0) is None
    assert F.window_delta_t(cast) == (pytest.approx(np.nan, nan_ok=True),) * 2


FULL = FIX / "hex"


@pytest.fixture(scope="module")
def full011(tmp_path_factory) -> F.Cast:
    """OdB cast 011 in full (318 dbar), local only: tests/fixtures/hex/ is git-ignored."""
    if not (FULL / "MIXSED2_011.hex").exists():
        pytest.skip(
            "full-length hex fixture MIXSED2_011.hex not present (git-ignored, local only)"
        )
    tmp = tmp_path_factory.mktemp("full")
    (tmp / "raw").mkdir()
    for name in ("MIXSED2_011.hex", "MIXSED2_011.XMLCON"):
        shutil.copy(FULL / name, tmp / "raw" / name)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stage1(tmp / "raw", tmp / "ctd", backend="hex", pattern="*.[hH][eE][xX]")
        stage2_run(tmp / "ctd")
    with xr.open_dataset(
        next((tmp / "ctd" / "stage2").glob("*.nc")), engine="netcdf4"
    ) as ds:
        return cast_arrays(ds.load(), 1, 1 / 24)


def test_ctm_cost_on_a_full_cast(full011):
    cost = F.ctm_cost(full011)
    assert cost.shape == (F.DEFAULT_ALPHA.size, F.DEFAULT_TAU.size)
    assert np.all(cost[0] == cost[0, 0])  # alpha = 0 is no correction for every tau
    norm = F.normalise(cost, (0, 0))
    assert norm[0, 0] == 1.0
    # Sea-Bird's (0.03, 7) improves on no correction for this cast, and the one-parameter
    # fits land near it (prototype on all 143 OdB casts: alpha 0.018-0.030, tau 3.5-6.5 s).
    ia = int(np.argmin(np.abs(F.DEFAULT_ALPHA - 0.03)))
    jt = int(np.argmin(np.abs(F.DEFAULT_TAU - 7.0)))
    assert norm[ia, jt] < 1.0
    a, t = F.one_parameter_fits(norm)
    assert 0.005 <= a <= 0.05 and 2.0 <= t <= 12.0
    dn, up = F.window_delta_t(full011)
    assert dn > 1.0 and up > 1.0


def test_cruise_surface_weights_and_valley():
    a = np.array([[1.0, 0.8], [0.5, 0.9]])
    b = np.array([[1.0, 0.4], [0.9, 0.9]])
    equal = F.cruise_surface([a, b])  # mean [[1, 0.6], [0.7, 0.9]]
    assert equal.index == (0, 1) and equal.n_casts == 2
    only_a = F.cruise_surface([a, b], weights=[1.0, 0.0])
    assert only_a.index == (1, 0) and only_a.n_casts == 1
    assert only_a.valley.sum() == 1
    assert F.cruise_surface([]) is None


def test_one_parameter_fits_hold_the_other_at_the_default():
    alpha = np.array([0.0, 0.02, 0.03, 0.04])
    tau = np.array([5.0, 7.0, 9.0])
    s = np.ones((4, 3))
    s[1, 1] = 0.5  # alpha 0.02 at tau 7
    s[2, 0] = 0.6  # tau 5 at alpha 0.03
    assert F.one_parameter_fits(s, alpha, tau) == (0.02, 5.0)


@pytest.mark.parametrize(
    ("block", "match"),
    [
        ({"fit": {"ctm_pmin": -1}}, "positive number"),
        ({"fit": {"window": 2}}, "unknown key"),
        ({"fit": {"block": True}}, "positive number"),
    ],
)
def test_fit_settings_reject_bad_config(block, match):
    with pytest.raises(ValueError, match=match):
        FitSettings.from_config(block)


def test_fit_cruise_writes_costs_and_summary(root):
    fits = fit_cruise(root, FitSettings(), progress=False)
    assert list(fits["cast_id"].values) == ["011"]
    assert fits["alignment_cost"].shape == (1, 2, 2, F.DEFAULT_RESIDUALS.size)
    assert not np.isfinite(fits["ctm_cost"].values).any()  # the slice has no upcast
    assert fits.attrs["ctm_pmin_dbar"] == 200.0
    (s1, s2) = summarise(fits)
    assert (s1.line, s2.line) == (1, 2)
    assert np.isfinite(s1.residual) and np.isnan(s1.alpha)
    text = suggested_yaml([s1, s2], 0.073)
    assert "conductivity_1: {default:" in text and "deck unit's 0.073" in text
    assert "celltm" not in text  # nothing to suggest without an upcast


def test_binned_cast_is_skipped_with_the_reason(tmp_path):
    (tmp_path / "stage2").mkdir()
    shutil.copy(
        FIX / "nc" / "mixsed2_011.nc", tmp_path / "stage2" / "mixsed2_011_stage2.nc"
    )
    fits = fit_cruise(tmp_path, FitSettings(), progress=False)
    assert "decibars" in str(fits["skipped"].values[0])
    assert summarise(fits) == []


def test_cli_writes_fits_nc_and_prints_yaml(root, tmp_path, capsys):
    from ctdcast.cli.fit import run

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"data:\n  ctd_root: {root}\nprocessing:\n  fit:\n    ctm_pmin: 20\n"
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert run(SimpleNamespace(config=cfg, only=None, dry_run=False)) == 0
    out = capsys.readouterr().out
    assert "Suggested" in out and "alignctd:" in out
    with xr.open_dataset(root / "fits.nc", engine="netcdf4") as ds:
        assert ds.sizes["cast"] == 1
    assert run(SimpleNamespace(config=cfg, only=[999], dry_run=True)) == 0
    assert "would fit 0" in capsys.readouterr().out


def test_corrections_row_only_when_fits_exist(root, tmp_path):
    from ctdcast.reports._navs import inventory_pills, nav_for

    assert inventory_pills(None, None, tmp_path / "fits.nc") == []
    (tmp_path / "fits.nc").write_bytes(b"")
    pills = inventory_pills(None, None, tmp_path / "fits.nc")
    assert pills == [
        {"label": "T/S", "href": "corrections_ts.html", "row": "corrections"}
    ]
    nav = nav_for(None, inventory=pills, inventory_current="corrections_ts.html")
    assert [r["label"] for r in nav["rows"]] == ["Pages:", "Corrections:"]
    assert nav["rows"][1]["pills"][0]["state"] == "current" and nav["inventory"] == []


def test_corrections_page_renders(root, tmp_path):
    from ctdcast.processors.fit import FITS_FILENAME
    from ctdcast.reports.corrections import generate_corrections_page
    from ctdcast.writers.netcdf import write

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fits = fit_cruise(root, FitSettings(), progress=False)
    write(fits, tmp_path / FITS_FILENAME)
    out = generate_corrections_page(
        tmp_path / FITS_FILENAME,
        tmp_path / "corrections_ts.html",
        cruise="odb26",
        inventory_pills=[
            {"label": "T/S", "href": "corrections_ts.html", "row": "corrections"}
        ],
    )
    html = out.read_text(encoding="utf-8")
    assert "T/S corrections" in html and "Corrections:" in html
    assert "Conductivity alignment" in html and "data:image/png;base64," in html
    assert "conductivity_1: {default:" in html  # the suggested YAML
    assert "Nothing to show" in html  # the slice has no upcast, so no CTM figures
