"""Smoke tests for generate_leaflet_map."""

import re

from conftest import CAST_011, CAST_012, CAST_128, CAST_129

from ctdreport.index import _read_cast_meta
from ctdreport.map_leaflet import generate_leaflet_map


def _all_meta():
    """Return metadata for all four fixture casts."""
    metas = [_read_cast_meta(p) for p in (CAST_011, CAST_012, CAST_128, CAST_129)]
    return [m for m in metas if m is not None]


def test_leaflet_map_generates(tmp_path):
    out = generate_leaflet_map(_all_meta(), sections_cfg={}, out_dir=tmp_path)
    assert out is not None
    assert out.exists()
    assert out.stat().st_size > 5_000


def test_leaflet_output_path(tmp_path):
    out = generate_leaflet_map(_all_meta(), sections_cfg={}, out_dir=tmp_path)
    assert out == tmp_path / "leaflet.html"


def test_leaflet_is_self_contained(tmp_path):
    out = generate_leaflet_map(_all_meta(), sections_cfg={}, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")
    # Only flag resources loaded at view time: src= and <link> href=
    # Anchor <a href="https://..."> navigation links are intentionally excluded
    external = re.findall(r'\bsrc=["\']https?://', html)
    external += re.findall(r'<link\b[^>]+\bhref=["\']https?://', html)
    assert external == [], f"External resource links in leaflet.html: {external}"


def test_leaflet_has_js(tmp_path):
    out = generate_leaflet_map(_all_meta(), sections_cfg={}, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")
    assert "L.map" in html


def test_leaflet_returns_none_for_empty_meta(tmp_path):
    out = generate_leaflet_map([], sections_cfg={}, out_dir=tmp_path)
    assert out is None
