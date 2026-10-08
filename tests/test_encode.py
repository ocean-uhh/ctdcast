"""Tests for the vendored encoder's error policy (``reports/_encode.render_b64``).

When a draw function raises and ``RAISE_ON_PLOT_ERROR`` is unset, the panel is
omitted: the warning now names the cause, and an ``on_error`` callback (used by
the package adapter to turn a bare stub into one that says why) receives the
exception. When ``RAISE_ON_PLOT_ERROR`` is set, the exception propagates and
``on_error`` is not called.
"""

import warnings

import pytest

from ctdcast.config import report_tokens
from ctdcast.reports._encode import render_b64


def _boom():
    """A draw function that always raises, to exercise the error branch."""
    raise TypeError("boom")


def test_draw_raising_warns_with_cause_and_calls_on_error(monkeypatch):
    """The warning carries the exception type and message; on_error gets the exception."""
    # The suite sets RAISE_ON_PLOT_ERROR True (conftest); this test is the swallow path.
    monkeypatch.setattr(report_tokens, "RAISE_ON_PLOT_ERROR", False)
    seen: list[BaseException] = []
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        out = render_b64(_boom, on_error=seen.append)
    assert out is None
    assert len(seen) == 1
    assert isinstance(seen[0], TypeError)
    assert any("TypeError: boom" in str(r.message) for r in records)


def test_raise_on_plot_error_propagates_and_skips_on_error(monkeypatch):
    """With RAISE_ON_PLOT_ERROR set the exception propagates and on_error is not called."""
    monkeypatch.setattr(report_tokens, "RAISE_ON_PLOT_ERROR", True)
    seen: list[BaseException] = []
    with pytest.raises(TypeError, match="boom"):
        render_b64(_boom, on_error=seen.append)
    assert seen == []
