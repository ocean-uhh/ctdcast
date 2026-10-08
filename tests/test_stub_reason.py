"""End-to-end tests for the panel stub-reason path.

The vendored encoder and the ``_figdebug.render_b64`` wrapper keep their ``str | None``
contract (tested in test_encode and test_figure_debug); ``_figdebug.as_panel`` is the one
place a ``Stub`` is produced, and only ``Panel.render`` adapters call it. These tests run
with ``RAISE_ON_PLOT_ERROR`` False (the production default; the suite otherwise forces it
True), and the last one renders a real cast page with a plotter patched to raise and asserts
the page says *why*.
"""

from pathlib import Path

import pytest

from ctdcast.config import report_tokens
from ctdcast.reports._figdebug import as_panel, render_b64
from ctdcast.reports._manifest import Panel, Profile, Section, Stub, resolve

_HERE = Path(__file__).resolve().parent
_CAST_011 = _HERE / "fixtures" / "nc" / "mixsed2_011.nc"


@pytest.fixture(autouse=True)
def _swallow_plot_errors(monkeypatch):
    """Force the production error policy (swallow + stub) for these tests."""
    monkeypatch.setattr(report_tokens, "RAISE_ON_PLOT_ERROR", False)


def _boom():
    """A draw function that raises, standing in for a figure that cannot be produced."""
    raise ValueError("no data")


def _ok():
    """A draw that returns None (an absent-variable panel), not a raise."""


def test_as_panel_returns_stub_with_cause_on_raise():
    """as_panel turns a swallowed draw failure into Stub('<ExcType>: <message>')."""
    out = as_panel(lambda: render_b64(_boom))
    assert isinstance(out, Stub)
    assert out.reason == "ValueError: no data"


def test_as_panel_returns_none_when_draw_returns_none():
    """A draw that merely returns None stays None — only a raise makes a Stub."""
    assert as_panel(lambda: render_b64(_ok)) is None


def test_render_b64_outside_as_panel_scope_never_captures():
    """Direct embeds call render_b64 with no active scope and keep getting None."""
    assert render_b64(_boom) is None


def test_resolved_page_shows_the_reason():
    """as_panel -> Stub -> Panel.render -> resolve surfaces the cause text."""
    panel = Panel(id="p", render=lambda _c: as_panel(lambda: render_b64(_boom)))
    report = resolve(
        Profile(entries=(Section("s", "S", ("p",)),)), ctx=None, panels={"p": panel}
    )
    rp = report.sections[0].panels[0]
    assert rp.is_stub
    assert rp.payload is None
    assert rp.stub_reason == "applicable but unavailable: ValueError: no data"


def test_real_cast_page_shows_reason_when_a_plotter_raises(tmp_path, monkeypatch):
    """A patched draw on a real cast page renders a stub that names the cause."""
    from ctdcast.reports._cast import generate_station_page
    from ctdcast.reports._index import _read_cast_meta

    def _raise(*_a, **_k):
        raise RuntimeError("patched boom")

    # Patch the name as _plots imported it, so _make_stability_b64 sees the raising draw.
    monkeypatch.setattr("ctdcast.reports._plots.draw_stability_fig", _raise)

    meta = _read_cast_meta(_CAST_011)
    out = generate_station_page(
        _CAST_011, tmp_path, all_meta=[meta], force=True, ladcp_dir=None
    )
    assert out is not None and out.exists()
    html = out.read_text(encoding="utf-8")
    assert "applicable but unavailable: RuntimeError: patched boom" in html
