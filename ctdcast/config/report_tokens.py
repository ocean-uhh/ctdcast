"""Shared report design tokens — the single source of every presentation value.

This module is **vendored byte-identical** across the packages that share the
report design system (currently ``ctdcast`` and ``oceanarray``); a test asserts
the copies match a reference hash.  Keep it package-neutral: it names no package
and holds only data (plus the mplstyle path, resolved relative to this file so
no package name appears in the text).  A value that belongs to one package (a
scientific variable registry) does **not** live here.

Layering: this is a leaf, and it lives in ``config/`` for that reason — its only
import is :mod:`pathlib`.  Both the plotters (which size figures from
:data:`SLOTS`) and the report/CSS layer read it; it reads nothing of theirs.
Placing it under ``reports/`` would form an import cycle
(``plotters.plots -> ctdcast.reports -> reports._index -> plotters.plots``).

Part II of ``2026-08-12-report-spec.md`` is the prose behind these numbers.
Templates and plotters read them; they never restate them.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Style file and error policy
# ---------------------------------------------------------------------------
# The report mplstyle sits next to this module under config/, with a
# package-neutral name so this line is byte-identical across packages.
MPLSTYLE_PATH: Path = Path(__file__).with_name("report.mplstyle")

# When True, a plotting failure (or a None from a required panel) re-raises
# instead of being swallowed.  Test infrastructure toggles this at runtime; the
# default False is identical across packages.  Read at call time by both the
# plotters and the encoder so a single flag governs both.
RAISE_ON_PLOT_ERROR: bool = False

# ---------------------------------------------------------------------------
# Geometry (spec §11)
# ---------------------------------------------------------------------------
CONTENT_MAX_PX: int = 1150  # body max-width
CONTENT_PAD_PX: int = 32  # body padding, each side
USABLE_PX: int = CONTENT_MAX_PX - 2 * CONTENT_PAD_PX  # 1086
W_FULL: float = 9.0  # full-slot figure width in inches (the basis of SLOTS)
FIG_DPI: int = 150  # savefig dpi; with W_FULL this fixes every PNG width
# Oversample (png_px / display_px) is DERIVED, not a free knob: W_FULL, FIG_DPI
# and USABLE_PX over-determine it, so declaring all three independently would
# guarantee a contradiction.  The true value is ≈1.243, not a round 1.25 — the
# difference is invisible, and keeping W_FULL and FIG_DPI clean (they are the two
# that appear in code, as figsize and savefig dpi) reproduces ctdcast's existing
# PNG widths exactly.  Nothing reads this; it is documentation.
OVERSAMPLE: float = W_FULL * FIG_DPI / USABLE_PX  # ≈ 1.2431
PNG_PALETTE_COLORS: int = 256  # 8-bit palette quantization in the encoder

# ---------------------------------------------------------------------------
# Slot table (spec §14)
# ---------------------------------------------------------------------------
# name -> (fraction of USABLE_PX, figure width in inches).
# Invariant asserted by the slot-contract test: inches == W_FULL * fraction, so
# display_px / fig_in is identical for every figure and one font size renders at
# one on-screen size everywhere.  Test 2 asserts each saved PNG is exactly
# round(inches * FIG_DPI) px wide (1350 / 900 / 810 / 675 / 540 / 450).
SLOTS: dict[str, tuple[float, float]] = {
    "full": (1.0, 9.0),
    "twothirds": (2 / 3, 6.0),
    "three-fifths": (0.6, 5.4),
    "half": (0.5, 4.5),
    "two-fifths": (0.4, 3.6),
    "third": (1 / 3, 3.0),
}

# Ergonomic width aliases (inches) for plotter call sites; derived from SLOTS.
W_TWOTHIRDS: float = SLOTS["twothirds"][1]
W_THREE_FIFTHS: float = SLOTS["three-fifths"][1]
W_HALF: float = SLOTS["half"][1]
W_TWO_FIFTHS: float = SLOTS["two-fifths"][1]
W_THIRD: float = SLOTS["third"][1]

# Aspect-locked figure constants (spec §14).
SECTION_STRETCH: float = (
    16.0  # calibrated: 416 dbar × 94 km → 2.5 in tall at full width
)
MAX_SECTION_H: float = 5.2  # height cap; tall/narrow sections get a narrower fig_w
MIN_SECTION_H: float = 3.0  # height floor

# ---------------------------------------------------------------------------
# Spacing and radii (spec §15)  [data; applied by emit_css() in rep/vis-system]
# ---------------------------------------------------------------------------
SPACE: dict[str, str] = {
    "1": "4px",
    "2": "8px",
    "3": "12px",
    "4": "16px",
    "5": "24px",
    "6": "32px",
    "7": "48px",
}
RADII: dict[str, str] = {"card": "8px", "btn": "4px", "pill": "999px"}

# ---------------------------------------------------------------------------
# Typography (spec §13.2)  [data; applied by emit_css() in rep/vis-system]
# ---------------------------------------------------------------------------
# THE single source of page font sizes.  Nothing else in the repository sets a
# page font size.  px against a 16px root; deliberately compact.  Provisional —
# tune here and only here.  Figure font sizes are a *separate* knob (the
# mplstyle, in matplotlib points); the two are not coupled.
TYPE: dict[str, dict[str, str]] = {
    "h1": {"size": "22px", "line": "1.2", "weight": "600"},  # masthead title
    "h2": {
        "size": "16px",
        "line": "1.25",
        "weight": "600",
    },  # numbered section headings
    "h3": {"size": "14px", "line": "1.3", "weight": "600"},  # sub-sections
    "base": {"size": "14px", "line": "1.5"},  # body
    "sm": {"size": "12.5px", "line": "1.45"},  # caption, explainer, table body
    "xs": {"size": "11px", "line": "1.4"},  # meta dt, footer, page-type label
    "mono": {"size": "12.5px", "line": "1.45"},  # serials, filenames, nc names
}

# Shared web-safe font stacks (spec §13.1) — the CSS and the mplstyle name the
# same families in the same order so page text and figure text agree.
FONT_SANS: str = (
    '"Helvetica Neue", Helvetica, Arial, "Liberation Sans", "DejaVu Sans", sans-serif'
)
FONT_MONO: str = (
    'ui-monospace, "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace'
)

# ---------------------------------------------------------------------------
# Colour — base tokens (spec §12.1)  [data; applied in rep/vis-system]
# ---------------------------------------------------------------------------
COLORS: dict[str, str] = {
    "ocean": "#1a3a5c",  # headings, structural dark
    "seafoam": "#e8f4f8",  # h2 underline, jump-nav background
    "muted": "#95a5a6",  # footer, breadcrumb separators, ↑ top
    "text": "#2c3e50",  # body text
    "rule": "#dfe6e9",  # table borders, hairlines
    "bg": "#ffffff",  # page background
    "bg-sunken": "#f7f9fa",  # table zebra, card interiors
    "warn": "#e67e22",  # .warn border and icon
    "warn-bg": "#fdf3e7",  # .warn background
    "error": "#c0392b",  # failed QC, sentinel values
}

# Role accent (spec §12.2): masthead background, nav pill, page-type label.
ROLE_ACCENT: dict[str, str] = {
    "landing": "#2980b9",
    "entity": "#1a3a5c",
    "collection": "#5d6d7e",
    "aggregate-a": "#8e44ad",
    "aggregate-b": "#27ae60",
    "component": "#b35c00",
    "map": "#ee3377",
}

# Package accent (spec §12.2): h2 underline, link colour, footer rule, wordmark.
PACKAGE_ACCENT: dict[str, str] = {
    "oceanarray": "#1a3a5c",
    "ctdcast": "#0e6e6e",
    "caldip": "#7a4b8a",  # reserved
    "amocatlas": "#8a5a2b",  # reserved
}
