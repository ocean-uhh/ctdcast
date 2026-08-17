"""Integrity tests for the index section-manifest (``reports/_index.py``).

The index panels are pre-rendered, so these resolve ``INDEX_DEFAULT`` against a
hand-built ``IndexPageCtx`` (payloads are opaque base64 placeholders — the test
exercises numbering, gating and anchors, not figure content) plus static checks.
The rendered index HTML is covered end-to-end by the golden/integration suite.
"""

from __future__ import annotations

from ctdcast.reports._anchors import LEGACY_ANCHORS
from ctdcast.reports._plots import RenderedPanel
from ctdcast.reports._section import SECTION_DEFAULT
from ctdcast.reports._index import (
    INDEX_DEFAULT,
    INDEX_PANELS,
    IndexPageCtx,
    resolve_index,
)


def _ctx(*, map_b64="MAP", physics=("CT", "SA"), biogeo=("O2",), ts=True) -> IndexPageCtx:
    """Build an IndexPageCtx with placeholder payloads for the requested panels."""
    return IndexPageCtx(
        map_b64=map_b64,
        physics_panels=tuple(RenderedPanel(b64="x", title=t, short=t) for t in physics),
        biogeo_panels=tuple(RenderedPanel(b64="x", title=t, short=t) for t in biogeo),
        ts_panels=(RenderedPanel(b64="x", title="hist"),) if ts else (),
    )


def test_registry_ids_match_profile_references() -> None:
    """Every string panel id referenced by the profile exists in the registry."""
    referenced = {
        p for sec in INDEX_DEFAULT.entries for p in sec.panels if isinstance(p, str)
    }
    assert referenced <= set(INDEX_PANELS)


def test_section_ids_have_a_legacy_anchor_alias() -> None:
    """D3: each section id is a LEGACY_ANCHORS target, so old #s-* links resolve."""
    ids = {sec.id for sec in INDEX_DEFAULT.entries}
    assert ids <= set(LEGACY_ANCHORS.values())


def test_ids_are_subset_of_section_page_ids() -> None:
    """The index reuses the section page's slugs (it has no Velocity section)."""
    index_ids = {sec.id for sec in INDEX_DEFAULT.entries}
    section_ids = {sec.id for sec in SECTION_DEFAULT.entries}
    assert index_ids < section_ids
    assert "velocity" not in index_ids


def test_numbering_contiguous_full_page() -> None:
    """A complete cruise numbers Map..T–S as 1..4 with no stubs."""
    report = resolve_index(_ctx())
    assert [s.number for s in report.sections] == ["1", "2", "3", "4"]
    assert not any(p.is_stub for s in report.sections for p in s.panels)


def test_map_dropped_and_renumbered_when_absent() -> None:
    """No map → Hydrography leads and the survivors renumber over it."""
    report = resolve_index(_ctx(map_b64=None))
    ids = [s.id for s in report.sections]
    assert "map" not in ids
    assert ids[0] == "hydrography"
    assert report.sections[0].number == "1"


def test_empty_ts_omits_the_section() -> None:
    """An empty T–S group drops the section rather than stubbing it."""
    report = resolve_index(_ctx(ts=False))
    assert "ts_diagram" not in {s.id for s in report.sections}
