"""The casts.html interactive-map payload and context builders (``cruise_map``)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ctdcast.reports import cruise_map


def _meta(cast_num: int, lat: float, lon: float) -> dict[str, Any]:
    """Return a minimal per-cast metadata dict for the map builders."""
    return {
        "cast_num": cast_num,
        "cast_num_str": f"{cast_num:03d}",
        "lat": lat,
        "lon": lon,
        "time_start": "2026-01-01T00:00:00",
        "max_depth": 1000.0,
    }


_SECTIONS = {
    "KO": {"cast_numbers": [[1, 2]], "color": "#123456", "description": "K line"}
}


def test_payload_one_point_per_cast_and_one_polyline_per_section() -> None:
    """Each located cast is a single-point track; a section of >= 2 casts is a polyline."""
    all_meta = [_meta(1, 60.0, -30.0), _meta(2, 60.5, -30.5)]
    payload = cruise_map.casts_map_payload(all_meta, _SECTIONS)

    by_id = {t["id"]: t for t in payload}
    assert set(by_id) == {"section_KO", "cast_001", "cast_002"}

    assert len(by_id["cast_001"]["track"]) == 1  # a point → circle marker
    assert by_id["cast_001"]["track"] == [[60.0, -30.0]]
    assert by_id["cast_001"]["href"] == "casts/cast_001.html"
    assert by_id["cast_001"]["link_label"] == "→ Station page"

    assert len(by_id["section_KO"]["track"]) == 2  # a polyline
    assert by_id["section_KO"]["href"] == "sections/section_KO.html"
    assert by_id["section_KO"]["link_label"] == "→ Section page"
    assert by_id["section_KO"]["color"] == "#123456"


def test_payload_info_is_facts_only_no_links() -> None:
    """The macro appends its own link, so payload ``info`` carries no anchor tag."""
    payload = cruise_map.casts_map_payload([_meta(1, 60.0, -30.0)], {})
    assert payload[0]["info"]  # facts present
    assert "<a " not in payload[0]["info"]


def test_payload_omits_casts_without_a_position() -> None:
    """A cast with a non-finite lat/lon is left off the map."""
    all_meta = [_meta(1, 60.0, -30.0), _meta(2, float("nan"), -30.5)]
    ids = {t["id"] for t in cruise_map.casts_map_payload(all_meta, {})}
    assert ids == {"cast_001"}  # cast_002 omitted; section needs 2, so none


def test_context_json_is_valid_and_bounds_span_the_casts() -> None:
    """The context values parse as JSON and the bounds enclose the cast positions."""
    all_meta = [_meta(1, 60.0, -30.0), _meta(2, 60.5, -30.5)]
    ctx = cruise_map.casts_map_context(all_meta, _SECTIONS)

    payload = json.loads(ctx["casts_map_payload_json"])
    assert len(payload) == 3
    bounds = json.loads(ctx["map_bounds_json"])
    assert bounds == [
        [60.0, -30.5],
        [60.5, -30.0],
    ]  # [[latMin, lonMin], [latMax, lonMax]]


def test_context_empty_when_no_located_cast() -> None:
    """With no finite position the payload is empty and coastline/bounds are null."""
    ctx = cruise_map.casts_map_context([_meta(1, float("nan"), float("nan"))], {})
    assert json.loads(ctx["casts_map_payload_json"]) == []
    assert ctx["coastline_json"] == "null"
    assert ctx["map_bounds_json"] == "null"


def test_context_warns_when_coastline_unavailable(monkeypatch) -> None:
    """A null coastline (cartopy absent) warns, so a land-less map is never silent."""
    monkeypatch.setattr(cruise_map, "coastline_geojson", lambda *a, **k: "null")
    with pytest.warns(RuntimeWarning, match="coastline unavailable"):
        ctx = cruise_map.casts_map_context([_meta(1, 60.0, -30.0)], {})
    assert ctx["coastline_json"] == "null"
