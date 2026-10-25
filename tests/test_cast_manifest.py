"""Integrity tests for the cast section-manifest (``reports/_cast.py``).

These resolve ``CAST_DEFAULT`` against a real fixture cast and assert the
numbering and inclusion the manifest exists to guarantee — notably D1: the
rendered sections number 1..N with no gaps (the current cast page renders
1,3,4,5,6,7,9,10).  The template is not involved; this is the model layer.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ctdcast.analysis.derive import derive_teos10 as add_teos10
from ctdcast.config.report_config import DEFAULT_REPORT_CONFIG
from ctdcast.readers.ladcp import find_ladcp_file
from ctdcast.readers.metadata import parse_sensor_info
from ctdcast.reports.cast import CAST_DEFAULT, CAST_PANELS, PageCtx, resolve_cast

_FIX = Path(__file__).resolve().parent / "fixtures"
_CAST_011 = _FIX / "nc" / "mixsed2_011.nc"
_LADCP = _FIX / "ladcp"


def _ctx(nc: Path, ladcp_dir: Path | None = None) -> PageCtx:
    """Build a PageCtx from a fixture cast, mirroring generate_station_page."""
    ds = xr.open_dataset(nc, decode_timedelta=False, engine="netcdf4").load()
    sensor_info = parse_sensor_info(ds)
    ds = add_teos10(ds)
    lat = float(np.nanmedian(ds["latitude"].values))
    lon = float(np.nanmedian(ds["longitude"].values))
    ladcp_path = None
    ladcp_exists = False
    if ladcp_dir is not None:
        ladcp_path = find_ladcp_file(ladcp_dir, 11, "", None) or ladcp_dir / "011.mat"
        ladcp_exists = ladcp_path.exists()
    return PageCtx(
        ds=ds,
        cfg=DEFAULT_REPORT_CONFIG,
        lat=lat,
        lon=lon,
        all_meta=[{"lat": lat, "lon": lon}],
        ladcp_path=ladcp_path,
        ladcp_configured=ladcp_dir is not None,
        ladcp_exists=ladcp_exists,
        sensor_info=sensor_info,
        nc_path=nc,
    )


def test_registry_ids_match_profile_references() -> None:
    """Every panel id referenced by the profile exists in the registry."""
    referenced = {
        p for sec in CAST_DEFAULT.entries for p in sec.panels if isinstance(p, str)
    }
    assert referenced <= set(CAST_PANELS)


def test_content_numbers_are_contiguous_no_gaps() -> None:
    """D1: rendered content sections number 1..N with no gaps."""
    report = resolve_cast(_ctx(_CAST_011))
    content = [s.number for s in report.sections if s.role == "content"]
    assert content == [str(i) for i in range(1, len(content) + 1)]


def test_sensors_section_is_appendix_a() -> None:
    """The Sensors section is lettered (appendix), not padding the content run."""
    report = resolve_cast(_ctx(_CAST_011))
    sensors = [s for s in report.sections if s.id == "sensors"]
    if sensors:  # fixture has sensor metadata
        assert sensors[0].number == "A"
        assert sensors[0].role == "appendix"


def test_velocity_dropped_without_ladcp_and_present_with() -> None:
    """The Velocity section is gated on an existing LADCP file."""
    no_ladcp = resolve_cast(_ctx(_CAST_011))
    assert "velocity" not in {s.id for s in no_ladcp.sections}
    assert "Velocity (bottom track)" in no_ladcp.not_applicable

    with_ladcp = resolve_cast(_ctx(_CAST_011, ladcp_dir=_LADCP))
    assert "velocity" in {s.id for s in with_ladcp.sections}


def test_biogeochemistry_present_for_fixture() -> None:
    """Fixture 011 carries O2/fluor/turbidity, so Biogeochemistry is included."""
    report = resolve_cast(_ctx(_CAST_011))
    assert "biogeochemistry" in {s.id for s in report.sections}


def test_overview_is_first_and_number_one() -> None:
    """Overview leads the page and is section 1 (never a hand-typed 2)."""
    report = resolve_cast(_ctx(_CAST_011))
    assert report.sections[0].id == "overview"
    assert report.sections[0].number == "1"


def test_no_stubs_on_a_complete_fixture() -> None:
    """applies_to must agree with render: a complete cast produces zero stubs.

    Fixture 011 has T/S, dual sensors, biogeo variables and a LADCP file, so every
    section applies and every panel should render.  A stub here means a predicate
    said "applicable" while the figure came back None — the drift this guards.
    """
    report = resolve_cast(_ctx(_CAST_011, ladcp_dir=_LADCP))
    stubs = [(s.id, p.id) for s in report.sections for p in s.panels if p.is_stub]
    assert stubs == [], f"applies_to/render drift — unexpected stubs: {stubs}"


def _png_width(b64: str) -> int:
    import base64
    import io

    from PIL import Image

    return Image.open(io.BytesIO(base64.b64decode(b64))).size[0]


def test_every_fixed_slot_figure_is_drawn_at_its_slot_width() -> None:
    """A cast-page figure's PNG is exactly its slot's width, so its text matches its neighbours.

    Covers every figure panel with a fixed slot that renders for cast 011 with LADCP
    (the no-LADCP T–S profile is the known exception, tested below).
    """
    from ctdcast.reports._vendored.design_tokens import FIG_DPI, SLOTS

    ctx = _ctx(_CAST_011, ladcp_dir=_LADCP)
    checked = []
    for pid, panel in CAST_PANELS.items():
        if panel.kind != "figure" or not isinstance(panel.slot, str):
            continue
        b64 = panel.render(ctx)
        if not isinstance(b64, str):
            continue  # not applicable to this cast (e.g. no secondary sensor)
        assert _png_width(b64) == round(SLOTS[panel.slot][1] * FIG_DPI), pid
        checked.append(pid)
    assert len(checked) >= 10, checked


def test_slot_width_keeps_each_figures_aspect() -> None:
    """Passing the slot width changes nothing at today's widths: same PNG size as the default."""
    import base64
    import io

    from PIL import Image

    import ctdcast.reports._plots as rp

    ctx = _ctx(_CAST_011, ladcp_dir=_LADCP)
    defaults = {
        "station_map": lambda: rp._make_station_map_b64(
            ctx.lat, ctx.lon, ctx.all_meta, target_h=2.75, cfg=ctx.cfg
        ),
        "ts_updown": lambda: rp._make_ts_updown_b64(ctx.ds, cfg=ctx.cfg),
        "ct_sa_sigma0": lambda: rp._make_ct_sa_sigma0_b64(ctx.ds, cfg=ctx.cfg),
        "aux": lambda: rp._make_aux_profiles_b64(ctx.ds, cfg=ctx.cfg),
        "ts_diagram": lambda: rp._make_ts_diagram_b64(ctx.ds, cfg=ctx.cfg),
        "stability": lambda: rp._make_stability_b64(ctx.ds, cfg=ctx.cfg),
        "pressure_time": lambda: rp._make_pressure_time_b64(ctx.ds, cfg=ctx.cfg),
        "updown_diff": lambda: rp._make_updown_diff_b64(ctx.ds, cfg=ctx.cfg),
    }
    size = lambda b: Image.open(io.BytesIO(base64.b64decode(b))).size  # noqa: E731
    for pid, make in defaults.items():
        assert size(CAST_PANELS[pid].render(ctx)) == size(make()), pid


@pytest.mark.xfail(
    strict=True,
    reason="no-LADCP T–S profile is drawn at profile_figsize (7.0 in) in a 5.4 in slot",
)
def test_ts_density_without_ladcp_matches_its_slot() -> None:
    from ctdcast.reports._vendored.design_tokens import FIG_DPI, SLOTS

    panel = CAST_PANELS["ts_density"]
    b64 = panel.render(_ctx(_CAST_011))
    assert _png_width(b64) == round(SLOTS[panel.slot][1] * FIG_DPI)
