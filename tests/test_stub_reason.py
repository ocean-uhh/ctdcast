"""End-to-end tests for the panel stub-reason path.

The vendored encoder keeps its ``str | None`` contract (tested in test_encode and
test_figure_debug); the owned ``render_panel_b64`` is the one place a ``Stub`` is
produced, and only ``Panel.render`` adapters call it. These tests run with
``RAISE_ON_PLOT_ERROR`` False (the production default; the suite otherwise forces
it True) and assert the panel path yields a ``Stub`` carrying the cause, and that a
resolved page shows ``"applicable but unavailable: <ExcType>: <msg>"``.
"""

import pytest

from ctdcast.config import report_tokens
from ctdcast.reports._manifest import Panel, Profile, Section, Stub, resolve
from ctdcast.reports._plots import render_panel_b64


@pytest.fixture(autouse=True)
def _swallow_plot_errors(monkeypatch):
    """Force the production error policy (swallow + stub) for these tests."""
    monkeypatch.setattr(report_tokens, "RAISE_ON_PLOT_ERROR", False)


def _boom():
    """A draw function that raises, standing in for a figure that cannot be produced."""
    raise ValueError("no data")


def _ok():
    """A draw that returns None (an absent-variable panel), not a raise."""


def test_render_panel_b64_returns_stub_with_cause_on_raise():
    """A raising draw yields Stub('<ExcType>: <message>'), not None."""
    out = render_panel_b64(_boom)
    assert isinstance(out, Stub)
    assert out.reason == "ValueError: no data"


def test_render_panel_b64_returns_none_when_draw_returns_none():
    """A draw that merely returns None stays None — only a raise makes a Stub."""
    assert render_panel_b64(_ok) is None


def test_resolved_page_shows_the_reason():
    """render_panel_b64 -> Stub -> Panel.render -> resolve surfaces the cause text."""
    panel = Panel(id="p", render=lambda _c: render_panel_b64(_boom))
    report = resolve(
        Profile(entries=(Section("s", "S", ("p",)),)), ctx=None, panels={"p": panel}
    )
    rp = report.sections[0].panels[0]
    assert rp.is_stub
    assert rp.payload is None
    assert rp.stub_reason == "applicable but unavailable: ValueError: no data"
