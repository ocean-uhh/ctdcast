import warnings
from pathlib import Path

import numpy as np
import pytest
from seabirdscientific import processing as sp

from ctdcast.processors.editing import (
    apply_wild_edit,
    resolve_wild_edit,
    wild_edit_mask,
)
from ctdcast.processors.stage3 import stage3

FIX = Path(__file__).parent / "fixtures"


def test_resolve_defaults_and_errors():
    p = resolve_wild_edit({"wildedit": None})
    assert (p.pass1_nstd, p.pass2_nstd, p.scans_per_block, p.exclude_flagged) == (
        2.0,
        20.0,
        100,
        True,
    )
    assert "pressure" in p.variables
    assert resolve_wild_edit({}) is None
    with pytest.raises(ValueError, match="scans_per_block"):
        resolve_wild_edit({"wildedit": {"scans_per_block": 1}})
    with pytest.raises(ValueError, match="list of names"):
        resolve_wild_edit({"wildedit": {"variables": "pressure"}})


def test_marks_match_seabirdscientific_on_real_data(hex_stage2):
    p = resolve_wild_edit({"wildedit": {"pass2_nstd": 3.0, "scans_per_block": 50}})
    for var in ("pressure", "ctd_temperature_1", "conductivity_1", "oxygen_raw_1"):
        x = hex_stage2[var].values.astype(float)
        ref = (
            sp.wild_edit(x, np.zeros_like(x), 2.0, 3.0, 50, 0.0, True) == sp.FLAG_VALUE
        )
        np.testing.assert_array_equal(wild_edit_mask(x, p), ref)
    assert any(
        wild_edit_mask(hex_stage2[v].values, p).any()
        for v in ("pressure", "oxygen_raw_1")
    )


def test_excluded_scans_leave_the_statistics():
    x = np.r_[np.zeros(99), 1000.0, np.zeros(100)] + np.linspace(0, 1e-3, 200)
    p = resolve_wild_edit(
        {"wildedit": {"pass1_nstd": 2.0, "pass2_nstd": 3.0, "scans_per_block": 100}}
    )
    assert wild_edit_mask(x, p)[99]
    excluded = np.zeros(200, dtype=bool)
    excluded[99] = True
    # Out of the statistics, still judged: an excluded outlier is still marked.
    assert wild_edit_mask(x, p, excluded)[99]


def test_short_cast_is_one_block():
    p = resolve_wild_edit({"wildedit": {"pass2_nstd": 2.0, "scans_per_block": 100}})
    x = np.r_[np.zeros(20), 50.0] + np.arange(21) * 1e-4
    assert wild_edit_mask(x, p)[-1]


def test_apply_flags_and_keeps_values(hex_stage2):
    cfg = {
        "wildedit": {
            "pass2_nstd": 3.0,
            "scans_per_block": 50,
            "variables": ["oxygen_raw_1", "not_here"],
        }
    }
    out, marks = apply_wild_edit(hex_stage2, cfg, cast_label="011")
    mask = marks["oxygen_raw_1"]
    assert mask.any()
    np.testing.assert_array_equal(
        out.oxygen_raw_1.values, hex_stage2.oxygen_raw_1.values
    )
    assert (out.oxygen_raw_1_qc.values[mask] == 4).all()
    assert out.oxygen_raw_1.attrs["wild_edit_marked"] == int(mask.sum())
    assert "processing.wild_edit" in out.oxygen_raw_1.attrs["wild_edit_method"]
    history = out.attrs["history"]
    assert (
        "wildedit: pass1_nstd=2 pass2_nstd=3" in history
        and "not in this cast: not_here" in history
    )
    assert "wild_edit" not in hex_stage2.oxygen_raw_1.attrs  # input untouched


def test_skipped_when_sea_bird_already_wild_edited():
    from ctdcast.readers.cnv import read

    pytest.importorskip("seasenselib")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = read(FIX / "cnv" / "mixsed2_004.cnv")
    with pytest.warns(UserWarning, match="Sea-Bird wildedit already ran"):
        out, marks = apply_wild_edit(ds, {"wildedit": {}})
    assert marks == {}


def test_stage3_runs_steps_in_order_and_skips_what_it_cannot_apply_yet(
    hex_stage2, monkeypatch
):
    from ctdcast.processors import steps as S

    # Every step is applied today; stand one in as not yet applied to exercise the skip.
    monkeypatch.setitem(
        S.STEPS, "loopedit", S.Step("loopedit", None, lambda p, c: None)
    )
    cfg = {
        "data_processing": {
            "steps": [
                {"wildedit": {"pass2_nstd": 3.0, "scans_per_block": 50}},
                {"filter": {"time_constant": 0.15, "variables": ["pressure"]}},
                {"loopedit": {}},
                {"celltm": {"conductivity": {"alpha": 0.03, "tau": 7.0}}},
            ]
        }
    }
    with pytest.warns(
        UserWarning, match="not yet applied by ctdcast, skipped: loopedit"
    ):
        out = stage3(hex_stage2, cfg, cast_number=11, cast_label="011")
    h = out.attrs["history"]
    assert (
        h.index("wildedit:")
        < h.index("filter: low-pass")
        < h.index("loopedit: not yet applied")
        < h.index("celltm: conductivity_1")
    )
    assert "cell_thermal_mass_alpha" in out.conductivity_1.attrs
    assert "wild_edit" in out.pressure.attrs


def test_stage3_slope_offset_per_sensor(hex_stage2):
    cfg = {
        "data_processing": {
            "slope_offset": {"conductivity_2": {"slope": 1.001, "offset": 0.01}}
        }
    }
    out = stage3(hex_stage2, cfg, cast_number=11)
    c2 = hex_stage2.conductivity_2.values.astype(float)
    np.testing.assert_allclose(out.conductivity_2.values, c2 * 1.001 + 0.01, rtol=1e-6)
    np.testing.assert_array_equal(
        out.conductivity_1.values, hex_stage2.conductivity_1.values
    )
    assert out.conductivity_2.attrs["calibration_offset"] == 0.01
    assert (
        "slope_offset.conductivity_2 default"
        in out.conductivity_2.attrs["calibration_config"]
    )
    assert "calibrated and corrected" in out.attrs["history"]


def test_cast_page_lists_wild_edit_in_applied_order_with_the_note(hex_stage2):
    from ctdcast.reports.cast import _ctdcast_correction_rows, _ctdcast_corrections_html

    cfg = {
        "data_processing": {
            "slope_offset": {"conductivity_1": {"slope": 1.0001}},
            "steps": [
                {"celltm": {"conductivity": {"alpha": 0.03, "tau": 7.0}}},
                {"wildedit": {"pass2_nstd": 3.0, "scans_per_block": 50}},
            ],
        }
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = stage3(hex_stage2, cfg, cast_number=11)
    labels = [r.label for r, _ in _ctdcast_correction_rows(out)]
    assert labels[:4] == ["slope_offset", "celltm", "celltm", "wildedit"]
    html = _ctdcast_corrections_html(out, "")
    assert "appears to differ from SBE Data Processing" in html
    assert "values marked (QARTOD 4, kept)" in html


def test_file_records_the_order_and_what_exclusion_happened(hex_stage2):
    cfg = {
        "data_processing": {
            "steps": [
                {"filter": {"time_constant": 0.15, "variables": ["pressure"]}},
                {"wildedit": {"variables": ["pressure"]}},
            ]
        }
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = stage3(hex_stage2, cfg, cast_number=11)
    assert out.attrs["data_processing_steps"] == "filter; wildedit"
    assert out.pressure.attrs["wild_edit_excluded"].startswith("no earlier Loop Edit")
