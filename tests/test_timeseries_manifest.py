"""Integrity tests for the timeseries section-manifest (``reports/_timeseries.py``).

Mirrors ``test_section_manifest``: static checks on ``TIMESERIES_DEFAULT`` plus a
rendered-HTML check driving ``generate_timeseries_page`` over a demo group.  The
timeseries page shares the section page's ids/anchors, so the same legacy ``#s-*``
aliases resolve on both.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from ctdcast.config.report_tokens import SLOTS
from ctdcast.reports._anchors import LEGACY_ANCHORS
from ctdcast.reports._section import SECTION_DEFAULT
from ctdcast.reports._timeseries import (
    TIMESERIES_DEFAULT,
    TIMESERIES_PANELS,
    _ts_field_panel,
    _ts_slot,
    generate_timeseries_page,
)

_FIX = Path(__file__).resolve().parent / "fixtures"
_PROFILES = _FIX / "profiles_demo.nc"
_LADCP = _FIX / "ladcp"
_TS_CFG = {"description": "demo yoyo", "cast_numbers": [[128, 129]]}


# ---------------------------------------------------------------------------
# Static checks
# ---------------------------------------------------------------------------


def test_registry_ids_match_profile_references() -> None:
    """Every string panel id referenced by the profile exists in the registry."""
    referenced = {
        p
        for sec in TIMESERIES_DEFAULT.entries
        for p in sec.panels
        if isinstance(p, str)
    }
    assert referenced <= set(TIMESERIES_PANELS)


def test_section_ids_have_a_legacy_anchor_alias() -> None:
    """D3: each section id is a LEGACY_ANCHORS target, so old #s-* links resolve."""
    ids = {sec.id for sec in TIMESERIES_DEFAULT.entries}
    assert ids <= set(LEGACY_ANCHORS.values())


def test_shares_section_ids_with_section_page() -> None:
    """Timeseries and section pages use the same section ids (shared anchors)."""
    assert [s.id for s in TIMESERIES_DEFAULT.entries] == [
        s.id for s in SECTION_DEFAULT.entries
    ]


def test_computed_slot_returns_a_slots_key() -> None:
    """The cast-count-driven field slot is a bare ``SLOTS`` key."""
    assert callable(_ts_field_panel("absolute_salinity").slot)
    for key in ("full", "half", "third"):
        assert _ts_slot(SimpleNamespace(ts_slot_key=key)) in SLOTS


# ---------------------------------------------------------------------------
# Rendered-HTML checks
# ---------------------------------------------------------------------------


def _render(tmp_path: Path) -> str:
    """Render a demo timeseries group and return its HTML."""
    out = generate_timeseries_page(
        "Demo", _TS_CFG, _PROFILES, tmp_path, force=True, ladcp_dir=_LADCP
    )
    assert out is not None
    return out.read_text(encoding="utf-8")


def test_headings_are_numbered_contiguously(tmp_path: Path) -> None:
    """Rendered section headings number (1)..(N) with no gaps."""
    html = _render(tmp_path)
    numbers = re.findall(r'<h2 id="[a-z_]+">\((\d+)\)', html)
    assert numbers == [str(i) for i in range(1, len(numbers) + 1)]
    assert len(numbers) >= 2


def test_no_unavailable_stub_on_complete_group(tmp_path: Path) -> None:
    """A complete demo group renders every panel — no applies_to/render drift."""
    assert "applicable but unavailable" not in _render(tmp_path)


def test_intro_prose_rendered(tmp_path: Path) -> None:
    """Each section carries its intro caption under the heading."""
    html = _render(tmp_path)
    assert "Time series of conservative temperature" in html
    assert "isopycnals" in html
