"""The encoder — the single place a matplotlib Figure becomes base64 PNG bytes.

This module is **vendored byte-identical** across the packages that share the
report design system; a test asserts the copies match a reference hash.  Keep it
package-neutral: it references shared values only through
``..config.report_tokens`` (textually identical in each package) and names no
package.

One choke point (:func:`render_b64`) is where the report mplstyle is applied,
the layout guard runs, dpi and palette quantization are chosen, memory is
bounded, and error policy is decided.  Layer 3 in the spec's layer model.
"""

from __future__ import annotations

import base64
import io
import warnings
from collections.abc import Callable
from typing import Any

import matplotlib.pyplot as plt
from PIL import Image

from ..config import report_tokens as _tok
from ..config.report_tokens import FIG_DPI, MPLSTYLE_PATH, PNG_PALETTE_COLORS


def _manages_own_layout(fig: Any) -> bool:
    """Return True when ``tight_layout()`` must be skipped for *fig*.

    Two cases, both mutually exclusive with ``tight_layout``:

    - a ``constrained_layout`` figure (matplotlib warns and mis-renders),
    - a figure containing a polar axis (bounding box is mis-computed).

    With ``layout="constrained"`` set on every figure (see the sizing invariant),
    the first case covers nearly everything and ``tight_layout`` is effectively
    never called; the guard remains as a safety net.  The former outside-legend
    branch is withdrawn: growing the image to fit a legend is exactly what breaks
    the displayed-type invariant, so the fix is a fixed canvas with
    ``constrained_layout`` shrinking the axes instead.
    """
    engine = getattr(fig.get_layout_engine(), "__class__", None)
    if engine is not None and "Constrained" in engine.__name__:
        return True
    return any(ax.name == "polar" for ax in fig.axes)


def _fig_to_base64(fig: Any) -> str:
    """Render *fig* to a quantized PNG and return its base64 string.

    Saves the **full canvas** at :data:`FIG_DPI` — no ``bbox_inches="tight"``, so
    ``png_px == round(fig_in × dpi)`` exactly for every figure and the
    displayed-type invariant holds by construction (figures use
    ``layout="constrained"`` to fit decorations inside the fixed figsize).
    Composites onto white to drop the alpha channel (report backgrounds are
    white), quantizes to :data:`PNG_PALETTE_COLORS` (these figures are few-colour
    by construction — line art plus discrete colorbars — so an 8-bit palette is
    visually lossless and ~3.6× smaller), and encodes the result.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=FIG_DPI)
    buf.seek(0)
    im = Image.open(buf).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    rgb = Image.alpha_composite(bg, im).convert(
        "RGB"
    )  # alpha must go before quantizing
    pal = rgb.quantize(colors=PNG_PALETTE_COLORS, method=Image.FASTOCTREE)
    out = io.BytesIO()
    pal.save(out, "PNG", optimize=True)
    return base64.b64encode(out.getvalue()).decode("ascii")


def render_b64(
    draw: Callable[..., Any],
    /,
    *args: Any,
    optional: bool = False,
    **kwargs: Any,
) -> str | None:
    """Run *draw* under the report mplstyle and return a base64 PNG, or None.

    Parameters
    ----------
    draw:
        A ``draw_*`` function returning a :class:`matplotlib.figure.Figure`, or
        ``None`` when the dataset lacks the required variables.
    *args, **kwargs:
        Forwarded to *draw*.
    optional:
        ``True`` when this panel is legitimately absent for some inputs (no
        secondary sensor fitted, a biogeochemical variable not measured).  When
        ``False`` (default) and :data:`report_tokens.RAISE_ON_PLOT_ERROR` is set,
        a ``None`` return raises so tests catch silently dropped required panels.

    Returns
    -------
    str or None
        Base64-encoded PNG bytes, or ``None`` when *draw* returned ``None`` or
        raised (unless ``RAISE_ON_PLOT_ERROR`` is set).
    """
    fig = None
    try:
        with plt.style.context(str(MPLSTYLE_PATH)):
            fig = draw(*args, **kwargs)
            if fig is None:
                if _tok.RAISE_ON_PLOT_ERROR and not optional:
                    raise RuntimeError(
                        f"{draw.__name__} returned None for a required panel; "
                        "check that all required variables are present in the dataset."
                    )
                return None
            if not _manages_own_layout(fig):
                fig.tight_layout()
            return _fig_to_base64(fig)
    except Exception:  # noqa: BLE001
        if _tok.RAISE_ON_PLOT_ERROR:
            raise
        warnings.warn(
            f"{draw.__name__} failed; panel omitted",
            RuntimeWarning,
            stacklevel=2,
        )
        return None
    finally:
        if fig is not None:
            plt.close(fig)
