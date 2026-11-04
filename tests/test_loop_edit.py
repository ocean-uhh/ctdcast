import numpy as np
import pytest
from seabirdscientific import processing as sp

from ctdcast.processors.editing import (
    SOAK_NOT_APPLIED,
    apply_loop_edit,
    loop_edit_mask,
    resolve_loop_edit,
    soak_window_reached,
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


def test_no_surface_soak_runs_and_marks_less(hex_stage2):
    p = hex_stage2.pressure.values.astype(float)
    lat = float(np.nanmean(hex_stage2.latitude.values))
    with_soak = loop_edit_mask(p, resolve_loop_edit({}), DT, lat)
    no_soak = loop_edit_mask(p, resolve_loop_edit({"surface_soak": False}), DT, lat)
    assert no_soak.any() and not no_soak.all()
    # Without the soak test the soak itself is no longer marked; nothing new is.
    assert no_soak.sum() < with_soak.sum()
    assert not (no_soak & ~with_soak).any()
    out, _ = apply_loop_edit(hex_stage2, {"surface_soak": False}, DT)
    assert "no surface soak" in out.loop_edit_flag.attrs["loop_edit"]


# --- A cast whose recording starts below the soak window (a yo-yo cut into casts at depth) ---


#: A soak window at fixed depth (as OdB configures it); with the default ``deck_pressure: true``
#: the window moves down to wherever the recording starts, so it is always reached.
FIXED = {"surface_soak": {"deck_pressure": 0}}


def _starts_at_depth(ds, dbar=40.0):
    """The real cast from its first scan deeper than *dbar*: logging that began at depth."""
    first = int(np.argmax(ds.pressure.values > dbar))
    return ds.isel(time=slice(first, None))


def test_soak_window_reached(hex_stage2):
    lat = float(np.nanmean(hex_stage2.latitude.values))
    p = resolve_loop_edit(FIXED)
    assert soak_window_reached(hex_stage2.pressure.values, p, lat)
    deep = _starts_at_depth(hex_stage2)
    assert not soak_window_reached(deep.pressure.values, p, lat)
    assert soak_window_reached(deep.pressure.values, resolve_loop_edit({}), lat)


def test_starts_below_resolves_and_is_described():
    assert resolve_loop_edit({}).starts_below == "skip"
    p = resolve_loop_edit({"surface_soak": {"starts_below": "fail"}})
    assert p.starts_below == "fail" and p.describe().endswith("starts_below=fail")
    with pytest.raises(ValueError, match="skip or fail"):
        resolve_loop_edit({"surface_soak": {"starts_below": "ignore"}})


def test_cast_starting_at_depth_runs_without_the_soak_test(hex_stage2):
    deep = _starts_at_depth(hex_stage2)
    out, mask = apply_loop_edit(deep, FIXED, DT, cast_label="011")
    lat = float(np.nanmean(deep.latitude.values))
    no_soak = loop_edit_mask(
        deep.pressure.values.astype(float),
        resolve_loop_edit({"surface_soak": False}),
        DT,
        lat,
    )
    np.testing.assert_array_equal(mask, no_soak)
    attrs = out.loop_edit_flag.attrs
    # The configured setting is recorded unchanged, so every cast of the cruise reads the same.
    assert attrs["loop_edit"] == resolve_loop_edit(FIXED).describe()
    assert attrs["loop_edit_soak_not_applied"].startswith(SOAK_NOT_APPLIED)
    assert SOAK_NOT_APPLIED in out.attrs["history"]
    # A cast that has a soak keeps the soak test, and records no note.
    full, _ = apply_loop_edit(hex_stage2, FIXED, DT, cast_label="011")
    assert "loop_edit_soak_not_applied" not in full.loop_edit_flag.attrs


def test_starts_below_fail_refuses_the_cast(hex_stage2):
    deep = _starts_at_depth(hex_stage2)
    strict = {"surface_soak": {"deck_pressure": 0, "starts_below": "fail"}}
    with pytest.raises(
        ValueError, match=r"cast 011: the recording starts below .*starts_below: fail"
    ):
        apply_loop_edit(deep, strict, DT, cast_label="011")
    apply_loop_edit(hex_stage2, strict, DT, cast_label="011")  # a cast with a soak runs


def test_shallow_cast_runs_without_the_soak_test_even_with_fail(hex_stage2):
    # The slice reaches 97 dbar: a window down to 120 m is never passed, so there is no soak
    # test to run, and the record says that rather than "starts below".
    shallow = {
        "surface_soak": {"max_depth": 120, "deck_pressure": 0, "starts_below": "fail"}
    }
    out, _ = apply_loop_edit(hex_stage2, shallow, DT, cast_label="011")
    note = out.loop_edit_flag.attrs["loop_edit_soak_not_applied"]
    assert "never goes deeper than the soak window" in note


def test_soak_search_leaves_out_scans_an_earlier_loop_edit_marked(hex_stage2):
    # An earlier Loop Edit marked every scan down to the first one below the window: the soak
    # search (which skips marked scans when exclude_flagged) finds nothing in the window first.
    p = hex_stage2.pressure.values.astype(float)
    lat = float(np.nanmean(hex_stage2.latitude.values))
    excluded = np.zeros(p.size, dtype=bool)
    excluded[: int(np.argmax(p > 25.0))] = True
    params = resolve_loop_edit(FIXED)
    assert soak_window_reached(p, params, lat)
    assert not soak_window_reached(p, params, lat, excluded)
    out, mask = apply_loop_edit(
        hex_stage2, FIXED, DT, excluded=excluded, cast_label="011"
    )
    assert mask[excluded].all()
    assert out.loop_edit_flag.attrs["loop_edit_soak_not_applied"].startswith(
        SOAK_NOT_APPLIED
    )
