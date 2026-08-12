"""Enforcement tests for the shared report design system (spec §10).

These are cheap guards against the drift classes the design system exists to
prevent: broken slot maths, bbox-trimmed PNGs, external resources, and an
over-used ``optional=True`` escape hatch.  The typography test (§10.3) and the
caption-classification test (§10.6) land with the visual branch, where the
figure-font normalization and prose classes are done.
"""

from __future__ import annotations

import ast
import base64
import io
import re
from pathlib import Path

import pytest
import xarray as xr
from PIL import Image

import ctdcast.plotters.plots as P
from ctdcast.analysis.derive import derive_teos10
from ctdcast.config.report_tokens import FIG_DPI, SLOTS, W_FULL
from ctdcast.reports._encode import render_b64

_ROOT = Path(__file__).resolve().parent.parent
_PKG = _ROOT / "ctdcast"
_CAST_128 = _ROOT / "tests" / "fixtures" / "nc" / "mixsed2_128.nc"


# ---------------------------------------------------------------------------
# 10.1 Slot contract
# ---------------------------------------------------------------------------
def test_slot_contract() -> None:
    """Every slot's inches equals W_FULL × its fraction (the font-consistency identity)."""
    for name, (frac, inch) in SLOTS.items():
        assert abs(inch / W_FULL - frac) < 1e-9, (
            f"slot {name}: {inch}/{W_FULL} != {frac}"
        )


# ---------------------------------------------------------------------------
# 10.2 PNG geometry — fixed-slot figures render at exactly round(inches × dpi)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def ds_128() -> xr.Dataset:
    """Deep repeat-station cast with TEOS-10 fields added."""
    ds = derive_teos10(xr.open_dataset(_CAST_128, engine="netcdf4"))
    yield ds
    ds.close()


@pytest.mark.parametrize(
    ("draw", "slot"),
    [
        (P.draw_ct_sa_sigma0_fig, "full"),
        (P.draw_stability_fig, "twothirds"),
        (P.draw_ts_diagram_fig, "third"),
    ],
)
def test_png_geometry_fixed_slots(ds_128: xr.Dataset, draw, slot: str) -> None:
    """A fixed-slot figure's PNG is exactly round(slot inches × FIG_DPI) px wide.

    Exact — not within a tolerance — because the encoder saves the full canvas
    (no ``bbox_inches``).  A tolerance being needed would mean something is
    trimming the canvas again.  Aspect-locked figures (maps, sections) are
    excluded: their width is physical, not a slot width.
    """
    b64 = render_b64(draw, ds_128)
    assert b64 is not None
    width = Image.open(io.BytesIO(base64.b64decode(b64))).size[0]
    assert width == round(SLOTS[slot][1] * FIG_DPI)


def test_encoder_saves_full_canvas() -> None:
    """No ``savefig`` in the encoder passes ``bbox_inches`` — that trims the canvas (§10.2)."""
    tree = ast.parse((_PKG / "reports" / "_encode.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "savefig"
        ):
            kwargs = {kw.arg for kw in node.keywords}
            assert "bbox_inches" not in kwargs, (
                "encoder savefig must save the full canvas (no bbox_inches)"
            )


# ---------------------------------------------------------------------------
# 10.4 Self-containment — templates carry no external resources
# ---------------------------------------------------------------------------
def test_templates_self_contained() -> None:
    """No template loads an external resource at view time (src= / <link href=)."""
    for tpl in sorted((_PKG / "reports" / "templates").glob("*.html")):
        txt = tpl.read_text(encoding="utf-8")
        assert not re.search(r'\bsrc=["\']https?://', txt), f"{tpl.name}: external src="
        assert not re.search(r'<link\b[^>]+href=["\']https?://', txt), (
            f"{tpl.name}: external <link href="
        )


# ---------------------------------------------------------------------------
# 10.5 Guard integrity — optional=True on at most 40% of render_b64 call sites
# ---------------------------------------------------------------------------
def test_optional_guard_ratio() -> None:
    """``optional=True`` is a claim of legitimate absence, not a default to silence bugs."""
    src = (_PKG / "reports" / "_plots.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    total = 0
    optional_true = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "render_b64"
        ):
            total += 1
            for kw in node.keywords:
                if (
                    kw.arg == "optional"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                ):
                    optional_true += 1
    assert total > 0, "no render_b64 call sites found"
    ratio = optional_true / total
    assert ratio <= 0.40, (
        f"{optional_true}/{total} render_b64 calls use optional=True ({ratio:.0%} > 40%)"
    )
