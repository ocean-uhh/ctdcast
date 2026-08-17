"""Tests for the legacy-anchor transition shim (``reports/_anchors.py``)."""

from __future__ import annotations

from ctdcast.reports._anchors import LEGACY_ANCHORS, legacy_anchor_spans


def test_hydrography_collapses_three_legacy_anchors() -> None:
    """The three old Hydrography anchors all map to the one new section id."""
    hydro = {old for old, new in LEGACY_ANCHORS.items() if new == "hydrography"}
    assert hydro == {"s-profiles", "s-physics", "s-hydro"}


def test_biogeochemistry_collapses_two_legacy_anchors() -> None:
    """Both old Biogeochemistry anchors map to the one new section id."""
    biogeo = {old for old, new in LEGACY_ANCHORS.items() if new == "biogeochemistry"}
    assert biogeo == {"s-aux", "s-biogeo"}


def test_every_legacy_key_is_an_s_anchor() -> None:
    """Keys are the old hand-authored ``s-*`` anchors."""
    assert all(k.startswith("s-") for k in LEGACY_ANCHORS)


def test_spans_emitted_only_for_rendered_sections() -> None:
    """A legacy span appears iff its target section is in the rendered set."""
    out = legacy_anchor_spans({"hydrography", "ts_diagram"})
    for present in ('id="s-profiles"', 'id="s-physics"', 'id="s-hydro"', 'id="s-ts"'):
        assert present in out
    for absent in ('id="s-map"', 'id="s-overview"', 'id="s-aux"'):
        assert absent not in out


def test_no_spans_when_nothing_rendered() -> None:
    """An empty rendered set produces no aliases."""
    assert legacy_anchor_spans(set()) == ""


def test_spans_are_empty_and_well_formed() -> None:
    """Each emitted alias is an empty span carrying only the old id."""
    out = legacy_anchor_spans({"overview"})
    assert out == '<span id="s-overview"></span>'
