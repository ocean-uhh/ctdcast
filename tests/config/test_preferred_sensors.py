"""Tests for the preferred-sensor resolver (``config/preferred_sensors.py``).

Pure-function tests with synthetic catalog records (the shape
``processors.sensor_catalog.read_cast_sensor_catalog`` returns: ``name``/``role``/``channel``/
``attrs``).  Primary/secondary is the role index (``temperature_1``/``_2``), not the
``sensor_channel`` field, so the synthetic records mirror that.
"""

import pytest

from ctdcast.config.preferred_sensors import (
    PREFERRED_OXYGEN,
    PREFERRED_PAIR,
    derive_segments,
    has_choice,
    has_use,
    index_of,
    preferred_sensor_names,
    resolve_preferred,
    validate_preferred,
)


def _rec(role: str, name: str, channel: int = 0) -> dict:
    return {"role": role, "name": name, "channel": channel, "attrs": {}}


def _dual(
    t1="SENSOR_TEMPERATURE_A",
    c1="SENSOR_CONDUCTIVITY_A",
    t2="SENSOR_TEMPERATURE_B",
    c2="SENSOR_CONDUCTIVITY_B",
    o1="SENSOR_OXYGEN_A",
    o2=None,
) -> list[dict]:
    """A dual T/C (and single or dual O₂) cast's catalog records."""
    recs = [
        _rec("temperature_1", t1, 1),
        _rec("conductivity_1", c1, 2),
        _rec("temperature_2", t2, 4),
        _rec("conductivity_2", c2, 5),
        _rec("oxygen_1", o1, 8),
    ]
    if o2 is not None:
        recs.append(_rec("oxygen_2", o2, 9))
    return recs


def _single() -> list[dict]:
    """A single-sensor cast: only the primary T/C and one oxygen."""
    return [
        _rec("temperature_1", "SENSOR_TEMPERATURE_A", 1),
        _rec("conductivity_1", "SENSOR_CONDUCTIVITY_A", 2),
        _rec("oxygen_1", "SENSOR_OXYGEN_A", 8),
    ]


# --- resolve_preferred -------------------------------------------------------


def test_default_only_applies_everywhere():
    cfg = {"preferred_pair": {"default": "primary"}}
    assert resolve_preferred(PREFERRED_PAIR, cfg, 5) == ("primary", "default")


def test_range_wins_over_default():
    cfg = {
        "preferred_pair": {
            "default": "primary",
            "ranges": [{"casts": [[31, 60]], "use": "secondary"}],
        }
    }
    assert resolve_preferred(PREFERRED_PAIR, cfg, 45) == ("secondary", "range")
    assert resolve_preferred(PREFERRED_PAIR, cfg, 10) == ("primary", "default")


def test_single_cast_range():
    cfg = {
        "preferred_oxygen": {
            "default": "primary",
            "ranges": [{"casts": [[15, 15]], "use": "secondary"}],
        }
    }
    assert resolve_preferred(PREFERRED_OXYGEN, cfg, 15) == ("secondary", "range")
    assert resolve_preferred(PREFERRED_OXYGEN, cfg, 16) == ("primary", "default")


def test_undeclared_group_returns_none():
    assert resolve_preferred(PREFERRED_PAIR, {}, 5) == (None, None)
    assert resolve_preferred(
        PREFERRED_PAIR, {"preferred_oxygen": {"default": "primary"}}, 5
    ) == (None, None)


def test_ranges_only_cast_outside_all_is_undeclared():
    # A ranges-only declaration (no default): a cast outside every range is undeclared.
    cfg = {"preferred_pair": {"ranges": [{"casts": [[31, 60]], "use": "secondary"}]}}
    assert resolve_preferred(PREFERRED_PAIR, cfg, 5) == (None, None)


def test_lettered_cast_resolves_by_number():
    """010b resolves by its cast number 10 — the caller passes the int."""
    cfg = {"preferred_pair": {"ranges": [{"casts": [[10, 10]], "use": "secondary"}]}}
    assert resolve_preferred(PREFERRED_PAIR, cfg, 10) == ("secondary", "range")


def test_out_of_set_value_refused():
    cfg = {"preferred_pair": {"default": "secundary"}}
    with pytest.raises(ValueError, match="not one of"):
        resolve_preferred(PREFERRED_PAIR, cfg, 1)
    cfg_digit = {"preferred_pair": {"default": 1}}
    with pytest.raises(ValueError, match="not one of"):
        resolve_preferred(PREFERRED_PAIR, cfg_digit, 1)


def test_conflicting_overlap_refused():
    cfg = {
        "preferred_pair": {
            "ranges": [
                {"casts": [[1, 20]], "use": "primary"},
                {"casts": [[10, 30]], "use": "secondary"},
            ]
        }
    }
    with pytest.raises(ValueError, match="different pairs"):
        resolve_preferred(PREFERRED_PAIR, cfg, 15)


def test_scalar_shorthand_declaration_refused():
    # `preferred_pair: primary` (a scalar) instead of `{default: primary}` → clear error,
    # not an opaque AttributeError.
    cfg = {"preferred_pair": "primary"}
    with pytest.raises(ValueError, match="must be a mapping"):
        resolve_preferred(PREFERRED_PAIR, cfg, 1)


def test_range_missing_casts_key_refused():
    cfg = {"preferred_pair": {"ranges": [{"use": "secondary"}]}}
    with pytest.raises(ValueError, match="needs a 'casts' key"):
        resolve_preferred(PREFERRED_PAIR, cfg, 1)


def test_falsey_declaration_refused_not_silently_absent():
    # `preferred_pair: 0` / `false` is malformed, not "absent" — refuse it (a dual cast must
    # not be silently left unstamped). A missing key or empty mapping is undeclared (None).
    for bad in (0, False):
        with pytest.raises(ValueError, match="must be a mapping"):
            resolve_preferred(PREFERRED_PAIR, {"preferred_pair": bad}, 1)
    assert resolve_preferred(PREFERRED_PAIR, {}, 1) == (None, None)
    assert resolve_preferred(PREFERRED_PAIR, {"preferred_pair": {}}, 1) == (None, None)


# --- preferred_sensor_names / has_use (single-sensor reconciliation) ---------


def test_preferred_names_select_the_indexed_role():
    recs = _dual()
    assert preferred_sensor_names(PREFERRED_PAIR, recs, "primary") == {
        "temperature": "SENSOR_TEMPERATURE_A",
        "conductivity": "SENSOR_CONDUCTIVITY_A",
    }
    assert preferred_sensor_names(PREFERRED_PAIR, recs, "secondary") == {
        "temperature": "SENSOR_TEMPERATURE_B",
        "conductivity": "SENSOR_CONDUCTIVITY_B",
    }


def test_has_use_false_for_missing_secondary_on_single_sensor_cast():
    assert has_use(PREFERRED_PAIR, _dual(), "secondary") is True
    assert has_use(PREFERRED_PAIR, _single(), "secondary") is False
    assert has_use(PREFERRED_PAIR, _single(), "primary") is True
    # oxygen: single cast has only oxygen_1
    assert has_use(PREFERRED_OXYGEN, _single(), "secondary") is False
    assert has_use(PREFERRED_OXYGEN, _dual(o2="SENSOR_OXYGEN_B"), "secondary") is True


def test_has_choice_true_only_for_dual_casts():
    # A genuine primary-vs-secondary choice needs both channels present.
    assert has_choice(PREFERRED_PAIR, _dual()) is True
    assert has_choice(PREFERRED_PAIR, _single()) is False
    # oxygen: single cast has only oxygen_1 -> no choice; add oxygen_2 -> choice.
    assert has_choice(PREFERRED_OXYGEN, _single()) is False
    assert has_choice(PREFERRED_OXYGEN, _dual(o2="SENSOR_OXYGEN_B")) is True


def test_index_of():
    assert index_of("primary") == 1
    assert index_of("secondary") == 2


# --- derive_segments ---------------------------------------------------------


def test_unchanged_hardware_is_one_segment():
    cats = {1: _dual(), 2: _dual(), 3: _dual()}
    segs = derive_segments(PREFERRED_PAIR, cats)
    assert len(segs) == 1
    assert segs[0][:2] == (1, 3)


def test_any_of_four_serials_changing_starts_a_segment():
    # swap the SECONDARY conductivity serial at cast 3 — not the preferred channel, but
    # still a new hardware configuration (decision H).
    cats = {
        1: _dual(),
        2: _dual(),
        3: _dual(c2="SENSOR_CONDUCTIVITY_B2"),
        4: _dual(c2="SENSOR_CONDUCTIVITY_B2"),
    }
    segs = derive_segments(PREFERRED_PAIR, cats)
    assert [s[:2] for s in segs] == [(1, 2), (3, 4)]


def test_segment_tracks_actual_casts_not_the_contiguous_span():
    # Casts 1,2,5,6 share one hardware config (gap at 3,4). The segment must carry the
    # real casts {1,2,5,6}, not range(1,7) — so reconciliation stays correct over gaps.
    cats = {1: _dual(), 2: _dual(), 5: _dual(), 6: _dual()}
    segs = derive_segments(PREFERRED_PAIR, cats)
    assert len(segs) == 1
    first, last, _key, casts = segs[0]
    assert (first, last) == (1, 6)
    assert casts == frozenset({1, 2, 5, 6})


def test_range_in_gap_does_not_falsely_cover_segment():
    # A ranges-only declaration naming only gap casts {3,4} (not in the segment) must leave
    # the segment uncovered — the contiguous-range bug would have marked it covered.
    cfg = {"preferred_pair": {"ranges": [{"casts": [[3, 4]], "use": "primary"}]}}
    cats = {1: _dual(), 2: _dual(), 5: _dual(), 6: _dual()}
    warns = validate_preferred(PREFERRED_PAIR, cfg, cats)
    assert any("has no declaration" in w for w in warns)


def test_oxygen_segment_breaks_on_its_line_tc_swap():
    # a primary-temperature swap is a boundary for the oxygen group too (R.3), because
    # O₂ saturation uses its line's T/S.
    cats = {1: _dual(), 2: _dual(t1="SENSOR_TEMPERATURE_A2")}
    segs = derive_segments(PREFERRED_OXYGEN, cats)
    assert [s[:2] for s in segs] == [(1, 1), (2, 2)]


# --- validate_preferred ------------------------------------------------------


def test_full_default_no_warnings():
    cfg = {"preferred_pair": {"default": "primary"}}
    cats = {1: _dual(), 2: _dual()}
    assert validate_preferred(PREFERRED_PAIR, cfg, cats) == []


def test_range_crossing_boundary_warns():
    # hardware swaps at cast 3, but the declared range is 1-4 → crosses the boundary.
    cfg = {"preferred_pair": {"ranges": [{"casts": [[1, 4]], "use": "secondary"}]}}
    cats = {
        1: _dual(),
        2: _dual(),
        3: _dual(t1="SENSOR_TEMPERATURE_A2"),
        4: _dual(t1="SENSOR_TEMPERATURE_A2"),
    }
    warns = validate_preferred(PREFERRED_PAIR, cfg, cats)
    assert any("crosses the hardware segment" in w for w in warns)


def test_uncovered_segment_warns_when_no_default():
    cfg = {"preferred_pair": {"ranges": [{"casts": [[1, 2]], "use": "primary"}]}}
    cats = {1: _dual(), 2: _dual(), 3: _dual(t1="SENSOR_TEMPERATURE_A2")}
    warns = validate_preferred(PREFERRED_PAIR, cfg, cats)
    assert any("segment casts 3-3 has no declaration" in w for w in warns)


def test_default_covers_all_segments():
    cfg = {"preferred_pair": {"default": "primary"}}
    cats = {1: _dual(), 2: _dual(t1="SENSOR_TEMPERATURE_A2")}
    assert validate_preferred(PREFERRED_PAIR, cfg, cats) == []


def test_validate_never_raises_on_malformed_config():
    # Reconciliation is advisory and must never raise/block a compile; the stamp
    # (resolve_preferred) is what refuses malformed config loudly. A scalar shorthand is
    # skipped silently; a range missing 'casts' covers nothing (so segments read as
    # undeclared) — neither re-raises.
    cats = {1: _dual(), 2: _dual()}
    assert validate_preferred(PREFERRED_PAIR, {"preferred_pair": "primary"}, cats) == []
    cfg = {"preferred_pair": {"ranges": [{"use": "secondary"}]}}
    result = validate_preferred(PREFERRED_PAIR, cfg, cats)  # must not raise
    assert isinstance(result, list)
    # A malformed (not merely missing) casts spec must also not raise out of validate —
    # the stamp (resolve_preferred) is what refuses it loudly.
    for bad in ("oops", [[1]], [1, 2], None):
        cfg_bad = {"preferred_pair": {"ranges": [{"casts": bad, "use": "secondary"}]}}
        assert isinstance(validate_preferred(PREFERRED_PAIR, cfg_bad, cats), list)


def test_entirely_undeclared_group_is_silent():
    # A cruise that declares preferred_pair but not preferred_oxygen must not warn about
    # the undeclared oxygen group — declaring one, both, or neither is valid.
    cfg = {"preferred_pair": {"default": "primary"}}
    cats = {1: _dual(), 2: _dual(t1="SENSOR_TEMPERATURE_A2")}
    assert validate_preferred(PREFERRED_OXYGEN, cfg, cats) == []
    assert validate_preferred(PREFERRED_PAIR, {}, cats) == []
