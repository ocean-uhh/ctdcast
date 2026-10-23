"""The vendored Leaflet ``track_map`` macro renders the graticule and scale-bar fixes."""

from __future__ import annotations

from ctdcast.reports._env import get_template_raw

_PAYLOAD = (
    '[{"id": "001", "track": [[0.0, 0.0]], "color": "#123456", "href": "x.html"}]'
)


def _render_track_map() -> str:
    """Render ``track_map`` with a minimal one-point payload and return the HTML."""
    tmpl = get_template_raw("_map.html")
    return tmpl.module.track_map(
        _PAYLOAD, "null", "[[-1, -1], [1, 1]]", "", "// leaflet"
    )


def test_scale_bar_is_bottomright() -> None:
    """The scale bar sits bottom-right, clear of the bottom-left ``#track-info`` panel."""
    html = _render_track_map()
    assert "position: 'bottomright'" in html
    assert "position: 'bottomleft'" not in html


def test_graticule_edge_labels_sit_inside_the_frame() -> None:
    """Latitude labels offset right of the west edge, longitude labels above the south edge."""
    html = _render_track_map()
    assert "'right', [6, 0]" in html
    assert "'top', [0, -6]" in html


def test_graticule_unwraps_the_antimeridian() -> None:
    """The east edge unwraps to ``e + 360`` so meridians and parallels still draw across 180°."""
    assert "eastEdge" in _render_track_map()
