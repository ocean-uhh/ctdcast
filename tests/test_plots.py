"""Smoke tests for Tier-1 _make_*_b64 plot functions.

Each test asserts only that the function returns a str or None — not
that the image is pixel-perfect.  A returned str must start with the
PNG base64 magic bytes ("iVBOR").
"""

from conftest import FIXTURES_LADCP

from ctdcast.reports._plots import (
    _make_aux_profiles_b64,
    _make_ct_sa_sigma0_b64,
    _make_ladcp_bottomtrack_b64,
    _make_pressure_time_b64,
    _make_sensor_diff_b64,
    _make_stability_b64,
    _make_station_map_b64,
    _make_ts_density_b64,
    _make_ts_diagram_b64,
    _make_ts_updown_b64,
    _make_updown_diff_b64,
)

_LADCP_011 = FIXTURES_LADCP / "011.mat"
_LADCP_128 = FIXTURES_LADCP / "128.mat"


def _is_valid(result, *, may_be_none: bool = False) -> bool:
    """Return True if result is a PNG base64 string, or None when may_be_none is set."""
    if result is None:
        return may_be_none
    return isinstance(result, str) and result.startswith("iVBOR")


# --- station-page plot functions ---------------------------------------------


def test_ts_density_b64(ds_011):
    assert _is_valid(_make_ts_density_b64(ds_011))


def test_ts_diagram_b64(ds_011):
    assert _is_valid(_make_ts_diagram_b64(ds_011))


def test_stability_b64(ds_011):
    assert _is_valid(_make_stability_b64(ds_011))


def test_aux_profiles_b64(ds_011):
    assert _is_valid(_make_aux_profiles_b64(ds_011))


def test_ct_sa_sigma0_b64(ds_011):
    assert _is_valid(_make_ct_sa_sigma0_b64(ds_011))


def test_ts_updown_b64(ds_011):
    assert _is_valid(_make_ts_updown_b64(ds_011))


def test_pressure_time_b64(ds_011):
    assert _is_valid(_make_pressure_time_b64(ds_011))


def test_sensor_diff_b64(ds_011):
    assert _is_valid(_make_sensor_diff_b64(ds_011))


def test_updown_diff_b64(ds_011):
    assert _is_valid(_make_updown_diff_b64(ds_011))


# --- LADCP plot functions ----------------------------------------------------


def test_ts_density_ladcp_b64(ds_011):
    assert _is_valid(_make_ts_density_b64(ds_011, _LADCP_011))


def test_ts_density_ladcp_missing_file(ds_011):
    # ladcp_path=None → single-column layout, not raise
    result = _make_ts_density_b64(ds_011, None)
    assert _is_valid(result)


def test_ladcp_bottomtrack_b64():
    assert _is_valid(_make_ladcp_bottomtrack_b64(_LADCP_011))


def test_ladcp_bottomtrack_none():
    assert _make_ladcp_bottomtrack_b64(None) is None


# --- station map (no GEBCO) --------------------------------------------------


def test_station_map_no_gebco(ds_011):
    # The default ReportConfig has gebco_path=None, so the station map renders
    # without bathymetry.
    import numpy as np

    lat = float(np.nanmedian(ds_011["latitude"].values))
    lon = float(np.nanmedian(ds_011["longitude"].values))
    all_meta = [{"lat": lat, "lon": lon}]
    assert _is_valid(_make_station_map_b64(lat, lon, all_meta))


# --- deep cast (cast 128) ----------------------------------------------------


def test_ts_density_deep_cast(ds_128):
    assert _is_valid(_make_ts_density_b64(ds_128))


def test_ts_density_ladcp_deep(ds_128):
    assert _is_valid(_make_ts_density_b64(ds_128, _LADCP_128))


# --- section_figsize_and_slot: the width-matches-slot invariant ---------------


def test_section_figsize_width_equals_slot_canonical_width():
    """Every section figure is rendered at its slot's canonical inch width.

    A between-slots width is squeezed into the nearest slot box by the browser,
    shrinking the baked-in figure fonts; this guards the fix that snaps fig_w to a
    canonical SLOTS width across a spread of section geometries (shallow/wide to
    deep/short).
    """
    from ctdcast.config.report_tokens import (
        MAX_SECTION_H,
        MIN_SECTION_H,
        SLOTS,
    )
    from ctdcast.plotters.plots import section_figsize_and_slot

    canonical = {f"slot-{name}": inch for name, (_frac, inch) in SLOTS.items()}
    cases = [
        (416, 94),  # KTout — shallow/wide
        (2336, 103.6),  # FARDWO — deep/short
        (400, 300),  # very shallow/wide
        (1500, 200),  # mid
        (5000, 10),  # pathologically deep/short → narrowest slot
    ]
    for p_max, dist in cases:
        (fig_w, fig_h), slot = section_figsize_and_slot(p_max, dist)
        assert slot in canonical, f"{slot} is not a known slot"
        assert fig_w == canonical[slot], (
            f"p_max={p_max} dist={dist}: fig_w {fig_w} != slot {slot} width "
            f"{canonical[slot]}"
        )
        assert MIN_SECTION_H <= fig_h <= MAX_SECTION_H


def test_section_figsize_deep_short_is_narrower_than_shallow_wide():
    """A deep, short section lands on a narrower slot than a shallow, wide one."""
    from ctdcast.config.report_tokens import SLOTS
    from ctdcast.plotters.plots import section_figsize_and_slot

    (wide_w, _), _ = section_figsize_and_slot(400, 300)
    (deep_w, _), _ = section_figsize_and_slot(2336, 103.6)
    assert wide_w == SLOTS["full"][1]
    assert deep_w < wide_w
