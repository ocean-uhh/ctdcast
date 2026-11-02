import numpy as np
import pytest
from seabirdscientific import processing as sp

from ctdcast.processors.editing import (
    apply_loop_edit,
    loop_edit_mask,
    resolve_loop_edit,
)
from ctdcast.processors.stage3 import stage3

DT = 1 / 24


def test_resolve_defaults_and_errors():
    p = resolve_loop_edit({})
    assert (p.min_velocity, p.min_depth, p.max_depth, p.deck_pressure) == (
        0.25,
        5.0,
        20.0,
        True,
    )
    assert resolve_loop_edit({"surface_soak": False}).surface_soak is False
    assert (
        resolve_loop_edit({"surface_soak": {"deck_pressure": 0}}).deck_pressure == 0.0
    )
    for bad, match in (
        ({"minVelocity": 0.25}, "unknown key"),
        ({"surface_soak": {"min_depth": 20, "max_depth": 5}}, "shallower"),
        ({"mean_speed_percent": 0}, r"\(0, 100\]"),
        ({"exclude_flagged": "yes"}, "true or false"),
        ({"surface_soak": "yes"}, "mapping or false"),
    ):
        with pytest.raises(ValueError, match=match):
            resolve_loop_edit(bad)


def test_mask_is_seabirdscientific_loop_edit(hex_stage2):
    p = hex_stage2.pressure.values.astype(float)
    lat = float(np.nanmean(hex_stage2.latitude.values))
    ours = loop_edit_mask(p, resolve_loop_edit({}), DT, lat)
    ref = (
        sp.loop_edit(p, np.zeros_like(p), DT, latitude=lat, units="pressure")
        == sp.FLAG_VALUE
    )
    np.testing.assert_array_equal(ours, ref)
    # An explicit deck pressure of 0 is no offset.
    np.testing.assert_array_equal(
        loop_edit_mask(
            p, resolve_loop_edit({"surface_soak": {"deck_pressure": 0}}), DT, lat
        ),
        sp.loop_edit(
            p,
            np.zeros_like(p),
            DT,
            use_deck_pressure_offset=False,
            latitude=lat,
            units="pressure",
        )
        == sp.FLAG_VALUE,
    )


def test_apply_keeps_values_and_records_marks(hex_stage2):
    out, mask = apply_loop_edit(hex_stage2, {}, DT)
    assert mask.any()
    np.testing.assert_array_equal(out.pressure.values, hex_stage2.pressure.values)
    np.testing.assert_array_equal(out.loop_edit_flag.values.astype(bool), mask)
    assert (out.conductivity_1_qc.values[mask] == 4).all()
    assert "min_velocity=0.25" in out.loop_edit_flag.attrs["loop_edit"]
    assert "processing.loop_edit" in out.loop_edit_flag.attrs["loop_edit_method"]
    assert f"marked {int(mask.sum())} of" in out.attrs["history"]


def test_later_wild_edit_leaves_loop_edit_scans_out(hex_stage2):
    cfg = {
        "data_processing": {
            "steps": [
                {"loopedit": {}},
                {"wildedit": {"variables": ["pressure"], "exclude_flagged": True}},
            ]
        }
    }
    out = stage3(hex_stage2, cfg, cast_number=11)
    n = int(out.loop_edit_flag.values.sum())
    assert out.pressure.attrs["wild_edit_excluded"].startswith(
        f"{n} scan(s) marked by an earlier Loop Edit"
    )
    assert out.attrs["data_processing_steps"] == "loopedit; wildedit"
