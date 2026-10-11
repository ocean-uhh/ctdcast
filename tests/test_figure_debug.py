"""Tests for the opt-in per-figure debug overlay (``CTDCAST_REPORT_DEBUG``).

Renders a real fixture cast page and checks that debug lines appear under each
figure when the environment variable is set and are absent when it is not.
"""

import re
from pathlib import Path

from ctdcast.reports import _figdebug
from ctdcast.reports.cast import generate_station_page
from ctdcast.reports.index import _read_cast_meta

_HERE = Path(__file__).resolve().parent
_CAST_011 = _HERE / "fixtures" / "nc" / "mixsed2_011.nc"

_DEBUG_DIV = re.compile(r'<div class="debug">([^<]+)</div>')


def _render_cast(tmp_path):
    """Render fixture cast 011 to an HTML string and return it."""
    meta = _read_cast_meta(_CAST_011)
    out = generate_station_page(
        _CAST_011, tmp_path, all_meta=[meta], force=True, ladcp_dir=None
    )
    assert out is not None and out.exists()
    return out.read_text(encoding="utf-8")


def test_debug_lines_present_when_enabled(tmp_path, monkeypatch):
    """With the env var set, every figure gets a debug line with figsize + png px."""
    monkeypatch.setenv("CTDCAST_REPORT_DEBUG", "1")
    _figdebug.clear()
    lines = _DEBUG_DIV.findall(_render_cast(tmp_path))
    assert lines, "no debug overlay lines rendered with CTDCAST_REPORT_DEBUG set"
    for line in lines:
        assert "figsize" in line and "in" in line, line
        assert "png" in line and "px" in line, line
        assert "×" in line, line


def test_no_debug_lines_when_disabled(tmp_path, monkeypatch):
    """With the env var unset, the page contains no debug overlay at all."""
    monkeypatch.delenv("CTDCAST_REPORT_DEBUG", raising=False)
    _figdebug.clear()
    assert 'class="debug"' not in _render_cast(tmp_path)


def test_figdbg_empty_for_unrecorded_key():
    """figdbg() returns an empty string for a b64 that was never recorded."""
    _figdebug.clear()
    assert _figdebug.figdbg("never-recorded-key") == ""
    assert _figdebug.figdbg(None) == ""


def _boom():
    """A draw function that raises, to exercise the error branch."""
    raise ValueError("no data")


def test_render_b64_returns_none_not_stub_when_draw_raises(monkeypatch):
    """_figdebug.render_b64 keeps the str|None contract — a raising draw yields None."""
    from ctdcast.reports._vendored import design_tokens as report_tokens

    monkeypatch.setattr(report_tokens, "RAISE_ON_PLOT_ERROR", False)
    monkeypatch.delenv("CTDCAST_REPORT_DEBUG", raising=False)
    assert _figdebug.render_b64(_boom) is None


def test_render_b64_returns_none_not_stub_when_draw_raises_debug_on(monkeypatch):
    """The str|None contract holds on the debug-enabled path too (no Stub leak)."""
    from ctdcast.reports._vendored import design_tokens as report_tokens

    monkeypatch.setattr(report_tokens, "RAISE_ON_PLOT_ERROR", False)
    monkeypatch.setenv("CTDCAST_REPORT_DEBUG", "1")
    _figdebug.clear()
    assert _figdebug.render_b64(_boom) is None
