"""Tests for the vendored masthead-nav contract (``reports._vendored.page_model.validate_nav``).

These cover the plain-mapping nav shape and its validator; the rendered-macro and
emitted-CSS checks arrive with the nav swap (plan steps 4-5).
"""

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

from ctdcast.reports._vendored.page_model import validate_nav

_VENDORED_TEMPLATES = (
    Path(__file__).resolve().parent.parent
    / "ctdcast"
    / "reports"
    / "_vendored"
    / "templates"
)


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


def test_missing_state_rejected():
    """A pill with no ``state`` is rejected, not silently treated as a link."""
    rows = [
        {
            "label": "Pages:",
            "pills": [{"label": "Summary", "href": "index.html", "role": "landing"}],
        }
    ]
    with pytest.raises(ValueError, match="has no 'state'"):
        validate_nav(_nav(rows=rows, inventory=[]))


def test_back_pill_renders_without_rows():
    """A page with a back pill and no rows still renders the back pill."""
    env = Environment(
        loader=FileSystemLoader(str(_VENDORED_TEMPLATES)), autoescape=True
    )
    tmpl = env.from_string('{% import "_nav.html" as nav_m %}{{ nav_m.page_nav(nav) }}')
    out = tmpl.render(
        nav={"rows": [], "back": _pill("All cruises", "../index.html", "up")}
    )
    assert out.count("nav-pill") == 1
    assert "All cruises" in out


def test_non_link_pills_carry_a_title_hint():
    """A missing pill and a current pill get a hover ``title``; a link pill does not."""
    env = Environment(
        loader=FileSystemLoader(str(_VENDORED_TEMPLATES)), autoescape=True
    )
    tmpl = env.from_string('{% import "_nav.html" as nav_m %}{{ nav_m.page_nav(nav) }}')
    rows = [
        {
            "label": "Pages:",
            "pills": [
                _pill("Summary", "index.html", "landing", "current"),
                _pill("Grid", "", "aggregate-a", "missing"),
                _pill("Casts", "casts.html", "collection"),
            ],
        }
    ]
    out = tmpl.render(nav={"rows": rows, "back": None})
    assert 'title="current page"' in out
    assert 'title="not yet generated"' in out
    # the plain link pill carries no title
    assert out.count("title=") == 2


def test_css_carries_the_vendored_sync_rules():
    """emit_css renders the h3 rule, the pill contrast edge and multi-row spacing."""
    from ctdcast.reports._vendored.css import emit_css

    css = emit_css("#123456")
    assert "h3 {" in css and "var(--fs-h3)" in css
    assert "box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.55)" in css
    assert ".page-nav + .page-nav" in css


def test_css_qc_variables_mirror_the_qc_colour_dicts():
    """Every ``--qc-<flag>`` in the CSS equals the vendored QC colour dict — one source."""
    import re

    from ctdcast.reports._vendored.css import emit_css
    from ctdcast.reports._vendored.design_tokens import QC_COLORS, QC_TEXT_COLORS

    css = emit_css("#123456")
    emitted = {
        int(f): c for f, c in re.findall(r"--qc-(\d+):\s*(#[0-9A-Fa-f]{6});", css)
    }
    emitted_text = {
        int(f): c for f, c in re.findall(r"--qc-(\d+)-text:\s*(#[0-9A-Fa-f]{6});", css)
    }
    assert emitted == QC_COLORS
    assert emitted_text == QC_TEXT_COLORS


def test_every_masthead_role_is_a_role_accent_key():
    """Every page's ``masthead_role`` is a ``ROLE_ACCENT`` key.

    ``base.html`` renders ``class="masthead role-{{ masthead_role }}"``; a page that passed an
    unknown (or missing) role would render an unstyled masthead with no error. This pins every
    builder's and index template's role to the generated ``.masthead.role-<key>`` rule set.
    """
    import re

    from ctdcast.reports._vendored.design_tokens import ROLE_ACCENT

    reports = Path(__file__).resolve().parent.parent / "ctdcast" / "reports"
    sources = list(reports.glob("*.py")) + list((reports / "templates").glob("*.html"))
    roles: set[str] = set()
    for path in sources:
        roles |= set(
            re.findall(
                r'masthead_role\s*=\s*"([^"]+)"',
                path.read_text(encoding="utf-8"),
            )
        )
    assert roles, "no masthead_role assignments found — did the attribute move?"
    unknown = roles - set(ROLE_ACCENT)
    assert not unknown, f"masthead_role values not in ROLE_ACCENT: {sorted(unknown)}"
