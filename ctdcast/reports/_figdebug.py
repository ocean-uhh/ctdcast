"""Package-local wrapper around the vendored encoder: debug overlay and panel capture.

Two owned concerns layered on :mod:`ctdcast.reports._vendored.figure_png` without editing it:

- **Debug overlay** (``CTDCAST_REPORT_DEBUG=1``): every embedded figure gets a ``.debug``
  line showing **slot | draw-func · figsize · png_px**, so a figsize-vs-display-slot
  mismatch (the class of bug that shrinks fonts when a wide PNG lands in a narrow slot) is
  visible. Zero cost when off: :func:`record` no-ops and the template macro emits nothing.
- **Panel-failure capture**: :func:`render_b64` keeps the vendored ``str | None`` contract,
  but inside an :func:`as_panel` scope it records *why* a draw failed into a context
  variable, so ``as_panel`` can turn a swallowed failure into a :class:`Stub` that says why.
  Direct figure embeds call :func:`render_b64` outside any such scope and keep getting
  ``None`` on failure.

The ``.debug`` CSS lives in ``base.html``'s local style block, not the vendored ``emit_css``.
"""

from __future__ import annotations

import contextlib
import contextvars
import os
from typing import TYPE_CHECKING, Any

from ctdcast.reports._vendored import figure_png as _encode
from ctdcast.reports._vendored.design_tokens import FIG_DPI
from ctdcast.reports._vendored.page_model import Stub

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from matplotlib.figure import Figure

#: b64 PNG string -> {"func": str, "figsize_in": (w, h), "png_px": (w, h)}.
_COLLECTED: dict[str, dict[str, Any]] = {}

#: Active panel-capture sink, or None outside an :func:`as_panel` scope.  When set,
#: :func:`render_b64` (given no explicit ``on_error``) records a failed draw's cause here.
_panel_capture: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "panel_capture", default=None
)


def enabled() -> bool:
    """Return True when the ``CTDCAST_REPORT_DEBUG`` env var is set to a truthy value."""
    return os.environ.get("CTDCAST_REPORT_DEBUG", "").strip().lower() not in (
        "",
        "0",
        "false",
        "no",
    )


def clear() -> None:
    """Reset the collected registry — call once at the start of each report build.

    Without this the ``b64 -> debug`` map accumulates across builds and could hand back
    a stale entry for a byte-identical PNG produced by a later run.
    """
    _COLLECTED.clear()
    _encode.clear_sources()


def _draw_name(draw: Callable[..., object]) -> str:
    """Return a readable name for *draw* — the name half of the vendored source string.

    Reuses :func:`ctdcast.reports._vendored.figure_png.source_for` (which collapses a
    ``.<locals>.`` closure to its enclosing ``_make_*`` / ``draw_*`` scope) and keeps
    the part after the ``:`` — so the debug overlay and the ``source:`` caption agree.
    """
    return _encode.source_for(draw).rsplit(":", 1)[-1]


def record(b64: str | None, func: str, fig: Figure | None) -> None:
    """Store the figsize/png geometry for *b64* under label *func* (no-op when disabled)."""
    if not enabled() or not b64 or fig is None:
        return
    w_in, h_in = (float(v) for v in fig.get_size_inches())
    _COLLECTED[b64] = {
        "func": func,
        "figsize_in": (round(w_in, 2), round(h_in, 2)),
        "png_px": (round(w_in * FIG_DPI), round(h_in * FIG_DPI)),
    }


def figdbg(b64: str | None) -> str:
    """Return the one-line debug string for a recorded *b64*, or ``""`` if none.

    Registered as a Jinja global; the template macro emits nothing when this is empty,
    so the whole feature is a no-op when debug is off (no debug flag needs threading).
    """
    d = _COLLECTED.get(b64 or "")
    if not d:
        return ""
    fw, fh = d["figsize_in"]
    pw, ph = d["png_px"]
    return f"{d['func']} · figsize {fw}×{fh} in · png {pw}×{ph} px"


def render_b64(
    draw: Callable[..., object],
    /,
    *args: Any,  # noqa: ANN401  # forwarded verbatim to *draw*
    optional: bool = False,
    on_error: Callable[[BaseException], None] | None = None,
    **kwargs: Any,  # noqa: ANN401  # forwarded verbatim to *draw*
) -> str | None:
    """Encode *draw* via the vendored encoder; when debug is on, record its geometry.

    Drop-in for :func:`ctdcast.reports._vendored.figure_png.render_b64` and keeps its ``str | None``
    contract: a failed or empty draw returns ``None`` (the informative warning still fires
    in the encoder); this wrapper never returns a :class:`Stub`.  With no explicit
    ``on_error`` and inside an :func:`as_panel` scope, a draw failure's cause is recorded in
    the capture sink so ``as_panel`` can build the ``Stub``.  When debug is on, wraps *draw*
    to capture the Figure and records the figsize/png_px under the base64 PNG.
    """
    if on_error is None:
        _sink = _panel_capture.get()
        if _sink is not None:

            def on_error(exc: BaseException) -> None:
                _sink["reason"] = f"{type(exc).__name__}: {exc}"

    if not enabled():
        return _encode.render_b64(
            draw, *args, optional=optional, on_error=on_error, **kwargs
        )

    captured: dict[str, Any] = {}

    def _wrapped(
        *a: Any,  # noqa: ANN401  # forwarded verbatim to *draw*
        **k: Any,  # noqa: ANN401  # forwarded verbatim to *draw*
    ) -> Any:  # noqa: ANN401  # returns whatever *draw* returns (Figure or None)
        fig = draw(*a, **k)
        captured["fig"] = fig
        return fig

    b64 = _encode.render_b64(
        _wrapped,
        *args,
        optional=optional,
        on_error=on_error,
        source=_encode.source_for(draw),
        **kwargs,
    )
    record(b64, _draw_name(draw), captured.get("fig"))
    return b64


@contextlib.contextmanager
def _capture_scope() -> Iterator[dict[str, str]]:
    """Activate a panel-capture sink for the duration of the block, then restore."""
    sink: dict[str, str] = {}
    token = _panel_capture.set(sink)
    try:
        yield sink
    finally:
        _panel_capture.reset(token)


def as_panel(make: Callable[[], str | None]) -> str | Stub | None:
    """Run a ``Panel.render`` figure adapter, naming *why* a swallowed draw failed.

    Wraps a ``_make_*_b64(...)`` call (passed as a zero-argument *make* thunk) in a capture
    scope that :func:`render_b64` consults.  If the draw raised — and
    ``RAISE_ON_PLOT_ERROR`` is unset, so the encoder swallowed it to ``None`` — returns
    ``Stub("<ExcType>: <message>")`` so the resolver renders a stub that says why; a draw
    that merely returns ``None`` (an absent variable) stays ``None``.  This is the one place
    a ``Stub`` is produced, and only ``Panel.render`` adapters call it; the direct figure
    embeds call :func:`render_b64` outside any scope and keep their ``str | None`` result.

    The capture sink is per scope, not per encode: *make* must issue **at most one**
    :func:`render_b64`, and the scope must not nest (no wrapped draw may itself call
    :func:`render_b64` or :func:`as_panel`).  Both hold for every current adapter — each wraps
    a single ``_make_*_b64`` and no ``draw_*`` re-enters the encoder.  A composed adapter that
    broke either would mis-attribute a reason; wrap each draw in its own ``as_panel`` instead.

    Parameters
    ----------
    make : callable
        Zero-argument thunk that performs the panel's single ``render_b64`` call and returns
        its ``str | None`` result (typically ``lambda: _make_x_b64(...)``).

    Returns
    -------
    str or Stub or None
        The base64 PNG on success, ``Stub(reason)`` when the draw raised and was swallowed,
        or ``None`` when the draw produced nothing without raising.
    """
    with _capture_scope() as sink:
        result = make()
    if result is None and sink.get("reason"):
        return Stub(sink["reason"])
    return result
