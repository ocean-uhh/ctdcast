"""Every slotted figure in a full fixture report is drawn at exactly the width it is shown at.

A figure's displayed width is ``W_FULL`` times the product of the slot fractions of the
elements around it (a ``slot-full`` figure inside a ``slot-two-fifths`` column is two-fifths
wide).  If the PNG is drawn at a different width the browser rescales it and its text no
longer matches its neighbours, so the PNG width must equal that displayed width in pixels.
"""

from __future__ import annotations

import base64
import io
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from PIL import Image

from ctdcast.processors.profiles import build_profiles
from ctdcast.reports._vendored.design_tokens import FIG_DPI, SLOTS, W_FULL
from ctdcast.reports.index import report

_FIX = Path(__file__).resolve().parent / "fixtures"
_SLOT = re.compile(r"\bslot-([a-z-]+)\b")
_SECTIONS = """\
sections:
  KO:
    description: Kangerlussuaq Outer (fixture)
    cast_numbers: [[11, 12]]
    color: "#1f77b4"
timeseries:
  Triangle:
    description: Triangle repeat station (fixture)
    cast_numbers: [[128, 129]]
    color: "#d62728"
"""


class _SlottedImages(HTMLParser):
    """Collect ``(displayed_fraction, png_b64)`` for every embedded PNG inside a slot."""

    _VOID = {"img", "br", "hr", "meta", "link", "input", "source", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[
            float | None
        ] = []  # slot fraction per open element, None = no slot
        self.found: list[tuple[float, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        m = _SLOT.search(a.get("class") or "")
        frac = SLOTS[m.group(1)][0] if m and m.group(1) in SLOTS else None
        if tag == "img":
            fracs = [f for f in (*self.stack, frac) if f is not None]
            src = a.get("src") or ""
            if fracs and src.startswith("data:image/png;base64,"):
                shown = 1.0
                for f in fracs:
                    shown *= f
                self.found.append((shown, src.split(",", 1)[1]))
            return
        if tag not in self._VOID:
            self.stack.append(frac)

    def handle_endtag(self, tag: str) -> None:
        if tag not in self._VOID and self.stack:
            self.stack.pop()


@pytest.fixture(scope="module")
def report_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("report")
    (out / "ctd_sections.yaml").write_text(_SECTIONS, encoding="utf-8")
    build_profiles(_FIX / "nc", out / "profiles.nc", force=True)
    report(
        _FIX / "nc",
        out,
        profiles_path=out / "profiles.nc",
        section_yaml=out / "ctd_sections.yaml",
        ladcp_dir=_FIX / "ladcp",
        force=True,
    )
    return out


def _slotted(page: Path) -> list[tuple[float, str]]:
    p = _SlottedImages()
    p.feed(page.read_text(encoding="utf-8"))
    return p.found


@pytest.mark.parametrize(
    "page",
    [
        "index.html",
        "sections.html",
        "timeseries.html",
        "casts/cast_011.html",
        "casts/cast_128.html",
        "sections/section_KO.html",
        "timeseries/timeseries_Triangle.html",
    ],
)
def test_png_width_equals_displayed_width(report_dir: Path, page: str) -> None:
    found = _slotted(report_dir / page)
    assert found, f"{page}: no slotted figures found"
    for shown, b64 in found:
        width = Image.open(io.BytesIO(base64.b64decode(b64))).size[0]
        assert width == round(W_FULL * shown * FIG_DPI), (
            f"{page}: PNG {width} px shown at {round(W_FULL * shown * FIG_DPI)} px"
        )


def test_overview_panel_takes_the_slot_width_at_the_configured_aspect(report_dir: Path):
    """A CLI-style ``overview_figsize`` of 12 x 4 in still yields a full-slot-wide panel."""
    import xarray as xr

    from ctdcast.config.report_config import ReportConfig
    from ctdcast.plotters.sections import draw_overview_panel_fig, overview_figsize

    assert overview_figsize((12.0, 4.0), W_FULL) == (W_FULL, W_FULL / 3.0)
    assert overview_figsize((12.0, 4.0), None) == (12.0, 4.0)
    with xr.open_dataset(
        report_dir / "profiles.nc", engine="netcdf4", decode_timedelta=False
    ) as ds:
        down = ds.isel(N_PROF=ds["cast_type"].values == "down").load()
    fig = draw_overview_panel_fig(
        down,
        "ctd_temperature_1",
        "T",
        cfg=ReportConfig(overview_figsize=(12.0, 4.0)),
        width_in=W_FULL,
    )
    assert tuple(fig.get_size_inches()) == pytest.approx((W_FULL, W_FULL / 3.0))


@pytest.mark.slow
def test_cli_report_overview_panels_fill_their_slot(tmp_path: Path) -> None:
    """``ctdcast report`` on the demo config draws the overview panels at the slot width."""
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    cfg = (root / "config_demo.yaml").read_text(encoding="utf-8")
    cfg = cfg.replace("tests/fixtures", str(root / "tests" / "fixtures"))
    cfg = cfg.replace("  dir: demo_report", f"  dir: {tmp_path / 'out'}")
    (tmp_path / "config.yaml").write_text(cfg, encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "ctdcast", "report", str(tmp_path / "config.yaml")],
        check=True,
        capture_output=True,
    )
    index = tmp_path / "out" / "index.html"
    found = _slotted(index)
    full = [b64 for shown, b64 in found if shown == 1.0]
    assert full, "no full-width figures on index.html"
    for b64 in full:
        width = Image.open(io.BytesIO(base64.b64decode(b64))).size[0]
        assert width == round(W_FULL * FIG_DPI)
