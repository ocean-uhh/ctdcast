"""Integrity tests for the section section-manifest (``reports/_section.py``).

Two layers: static checks on ``SECTION_DEFAULT``/``SECTION_PANELS`` that need no
data, and a rendered-HTML check that drives ``generate_section_page`` against the
demo fixtures and asserts the numbering, anchors and gating the manifest exists to
guarantee (the template's old hand-typed ``namespace(n=0)`` counter is gone).
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import yaml

from ctdcast.config.report_tokens import SLOTS
from ctdcast.reports._anchors import LEGACY_ANCHORS
from ctdcast.reports._section import (
    SECTION_DEFAULT,
    SECTION_PANELS,
    _field_panel,
    _section_slot,
    generate_section_page,
)

_FIX = Path(__file__).resolve().parent / "fixtures"
_PROFILES = _FIX / "profiles_demo.nc"
_SECTIONS = _FIX / "ctd_sections_demo.yaml"
_LADCP = _FIX / "ladcp"


# ---------------------------------------------------------------------------
# Static checks — no data needed
# ---------------------------------------------------------------------------


def test_registry_ids_match_profile_references() -> None:
    """Every string panel id referenced by the profile exists in the registry."""
    referenced = {
        p for sec in SECTION_DEFAULT.entries for p in sec.panels if isinstance(p, str)
    }
    assert referenced <= set(SECTION_PANELS)


def test_section_ids_have_a_legacy_anchor_alias() -> None:
    """D3: each section id is a LEGACY_ANCHORS target, so old #s-* links resolve."""
    ids = {sec.id for sec in SECTION_DEFAULT.entries}
    assert ids <= set(LEGACY_ANCHORS.values())


def test_section_ids_and_titles_are_unique() -> None:
    """No duplicate section id or title in the profile."""
    ids = [sec.id for sec in SECTION_DEFAULT.entries]
    titles = [sec.title for sec in SECTION_DEFAULT.entries]
    assert len(ids) == len(set(ids))
    assert len(titles) == len(set(titles))


def test_computed_slot_returns_a_slots_key() -> None:
    """The computed section slot is a bare ``SLOTS`` key the panel macro can use."""
    assert callable(_field_panel("absolute_salinity").slot)
    for key in ("full", "twothirds", "half", "third"):
        assert _section_slot(SimpleNamespace(section_slot_key=key)) in SLOTS


# ---------------------------------------------------------------------------
# Rendered-HTML checks — drive the real page from the demo fixtures
# ---------------------------------------------------------------------------


def _render(tmp_path: Path) -> str:
    """Render the first demo section and return its HTML."""
    secs = yaml.safe_load(_SECTIONS.read_text())
    secs = secs.get("sections", secs)
    name, cfg = next(iter(secs.items()))
    out = generate_section_page(
        name, cfg, _PROFILES, tmp_path, force=True, ladcp_dir=_LADCP
    )
    assert out is not None
    return out.read_text(encoding="utf-8")


def test_headings_are_numbered_contiguously(tmp_path: Path) -> None:
    """Rendered section headings number (1)..(N) with no gaps."""
    html = _render(tmp_path)
    numbers = re.findall(r'<h2 id="[a-z_]+">\((\d+)\)', html)
    assert numbers == [str(i) for i in range(1, len(numbers) + 1)]
    assert len(numbers) >= 2


def test_map_leads_and_ts_trails(tmp_path: Path) -> None:
    """Section order is preserved: Map first, T–S diagrams last."""
    html = _render(tmp_path)
    ids = re.findall(r'<h2 id="([a-z_]+)">', html)
    assert ids[0] == "map"
    assert ids[-1] == "ts_diagram"


def test_no_unavailable_stub_on_complete_fixture(tmp_path: Path) -> None:
    """A complete demo section renders every panel — no applies_to/render drift."""
    html = _render(tmp_path)
    assert "applicable but unavailable" not in html


def test_legacy_anchor_spans_emitted_for_rendered_sections(tmp_path: Path) -> None:
    """Old #s-* anchors alias every rendered section (map/physics/biogeo/ladcp/ts)."""
    html = _render(tmp_path)
    for old in ("s-map", "s-physics", "s-biogeo", "s-ladcp", "s-ts"):
        assert f'id="{old}"' in html
