"""Tests for the vendored masthead-nav contract (``reports._manifest.validate_nav``).

These cover the plain-mapping nav shape and its validator; the rendered-macro and
emitted-CSS checks arrive with the nav swap (plan steps 4-5).
"""

import pytest

from ctdcast.reports._manifest import validate_nav


def _pill(label, href, role, state="link"):
    return {"label": label, "href": href, "role": role, "state": state}


def _nav(**overrides):
    """Return a minimal well-formed nav: one current row pill, one strip pill."""
    nav = {
        "rows": [
            {
                "label": "Pages:",
                "pills": [
                    _pill("Summary", "index.html", "landing", "current"),
                    _pill("Casts", "casts.html", "collection"),
                ],
            }
        ],
        "back": None,
        "inventory": [_pill("profiles.nc", "dataset_profiles.html", "component")],
    }
    nav.update(overrides)
    return nav


def test_valid_nav_passes():
    validate_nav(_nav())


def test_zero_current_allowed():
    """An inventory page rendered without its strip highlights nothing — valid."""
    rows = [{"label": "Pages:", "pills": [_pill("Summary", "index.html", "landing")]}]
    validate_nav(_nav(rows=rows, inventory=[]))


def test_two_current_rejected():
    rows = [
        {
            "label": "Pages:",
            "pills": [
                _pill("Summary", "index.html", "landing", "current"),
                _pill("Casts", "casts.html", "collection", "current"),
            ],
        }
    ]
    with pytest.raises(ValueError, match="at most one 'current'"):
        validate_nav(_nav(rows=rows, inventory=[]))


def test_current_may_live_in_the_strip():
    """A file page's current pill is in the strip, with no current in the row."""
    rows = [{"label": "Pages:", "pills": [_pill("Summary", "index.html", "landing")]}]
    inventory = [_pill("SBE sensors", "sensors.html", "component", "current")]
    validate_nav(_nav(rows=rows, inventory=inventory))


def test_unknown_role_rejected():
    rows = [
        {
            "label": "Pages:",
            "pills": [_pill("Summary", "index.html", "nope", "current")],
        }
    ]
    with pytest.raises(ValueError, match="not a ROLE_ACCENT key"):
        validate_nav(_nav(rows=rows, inventory=[]))


def test_invalid_state_rejected():
    rows = [
        {
            "label": "Pages:",
            "pills": [_pill("Summary", "index.html", "landing", "active")],
        }
    ]
    with pytest.raises(ValueError, match="state"):
        validate_nav(_nav(rows=rows, inventory=[]))


def test_link_without_href_rejected():
    rows = [
        {
            "label": "Pages:",
            "pills": [
                _pill("Summary", "index.html", "landing", "current"),
                _pill("Casts", "", "collection"),
            ],
        }
    ]
    with pytest.raises(ValueError, match="no href"):
        validate_nav(_nav(rows=rows, inventory=[]))


def test_missing_state_needs_no_href():
    """A 'missing' pill (page not yet generated) is unclickable, so needs no href."""
    rows = [
        {
            "label": "Pages:",
            "pills": [
                _pill("Summary", "index.html", "landing", "current"),
                _pill("Grid", "", "aggregate-a", "missing"),
            ],
        }
    ]
    validate_nav(_nav(rows=rows, inventory=[]))


def test_back_pill_field_checked_but_not_counted():
    """The up-link is validated for role/state but is not the page's current pill."""
    validate_nav(_nav(back=_pill("All cruises", "../index.html", "up")))
    with pytest.raises(ValueError, match="not a ROLE_ACCENT key"):
        validate_nav(_nav(back=_pill("All cruises", "../index.html", "bogus")))
