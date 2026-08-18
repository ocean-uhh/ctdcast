"""Tier-2: generate a per-cast HTML report page."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr
from markupsafe import escape

from ctdcast._version import __version__ as _VERSION
from ctdcast.analysis.derive import derive_teos10 as add_teos10
from ctdcast.config.parameters import (
    SECTION_BIOGEO_VARS,
    UNKNOWN_CRUISE_ID,
    resolve_sensor_var,
)
from ctdcast.config.report_config import DEFAULT_REPORT_CONFIG, ReportConfig
from ctdcast.config.report_tokens import ROLE_ACCENT
from ctdcast.identity import cast_id_from_name, format_cast_id
from ctdcast.processors.stage2 import find_cast_end, find_soak_end
from ctdcast.readers.ladcp import find_ladcp_file
from ctdcast.readers.metadata import parse_sensor_info
from ctdcast.reports._dataset import read_dataset_meta
from ctdcast.reports._manifest import Panel, Profile, ResolvedReport, Section, resolve
from ctdcast.reports._report_css import _JS_TOP_LINKS, SHARED_CSS
from ctdcast.reports._env import get_template
from ctdcast.reports._format import _fmt_utc
from ctdcast.reports._plots import (
    _make_aux_profiles_b64,
    _make_ct_sa_sigma0_b64,
    _make_ladcp_bottomtrack_b64,
    _make_pressure_time_b64,
    _make_sensor_diff_b64,
    _make_stability_b64,
    _make_station_map_b64,
    _make_ts_density_b64,
    _make_ts_diagram_b64,
    _make_ts_updown_b64,
    _make_updown_diff_b64,
)


def _dec_to_ddm(deg: float, axis: str) -> str:
    """Convert decimal degrees to degrees-decimal-minutes string.

    Examples: 64.7415 lat → '64 44.49 N', -31.4003 lon → '031 24.02 W'.
    """
    hemi = ("N" if deg >= 0 else "S") if axis == "lat" else ("E" if deg >= 0 else "W")
    d = int(abs(deg))
    m = (abs(deg) - d) * 60.0
    if axis == "lon":
        return f"{d:03d}° {m:05.2f}′ {hemi}"
    return f"{d:02d}° {m:05.2f}′ {hemi}"


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def generate_station_page(
    nc_path: Path,
    out_dir: Path,
    all_meta: list[dict[str, Any]],
    prev_cast_str: str | None = None,
    next_cast_str: str | None = None,
    force: bool = False,
    ladcp_dir: Path | None = None,
    ladcp_pattern: str | None = None,
    cast_num_str: str | None = None,
    sal_range: tuple[float, float] | None = None,
    trim_soak: bool = False,
    cast_notes: list[str] | None = None,
    cruise_info: dict | None = None,
    drop_stub: bool = False,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> Path | None:
    """Generate a per-cast HTML report page and write it to *out_dir/casts/*.

    Parameters
    ----------
    nc_path:
        Path to a single cast ``.nc`` file.
    out_dir:
        Root output directory.
    all_meta:
        List of dicts with keys ``lat``, ``lon`` for all casts (used for map).
    prev_cast_str:
        Full cast identifier string of the previous cast for nav links, e.g.
        ``"010"`` or ``"004b"`` (or None for no previous link).
    next_cast_str:
        Full cast identifier string of the next cast for nav links (or None).
    force:
        Overwrite existing file if True.
    ladcp_dir:
        Directory containing processed LADCP ``.mat`` files named ``NNN.mat``
        or ``NNNb.mat``.  If None or no matching file exists, LADCP panels
        are omitted.
    ladcp_pattern:
        Optional filename glob for non-standard LADCP naming conventions,
        e.g. ``"msm_142_1_*.mat"``.  The ``*`` is replaced with the
        zero-padded cast number.  Falls back to glob-based discovery when omitted.
    cast_num_str:
        Full cast identifier string, e.g. ``"011"`` or ``"004b"``.  Derived
        from *nc_path* if not provided.
    sal_range:
        ``(sal_min, sal_max)`` — records with ``salinity_1`` outside this
        range are excluded from all plots (but the NC file is not modified).
        The count of excluded records is shown in the page header.
    trim_soak:
        If True, apply pre-soak detection via :func:`~ctdcast.processors.stage2.find_soak_end`.
        Finds the last record within 10 dbar of the surface before the cast
        maximum depth, crawls back up to 20 seconds to the shallowest point
        preceding the real descent, and trims everything up to that point.
        Applied before *sal_range* trimming.  NC files are not modified.
    cast_notes:
        Optional list of free-text notes for this cast (e.g. "SBE43 malfunction").
        Rendered as warning banners near the top of the page.

    Returns
    -------
    Path to the written HTML file, or None on failure.

    """
    cast_num, cast_suffix = _cast_id_from_path(nc_path)
    if cast_num_str is None:
        cast_num_str = format_cast_id(cast_num, cast_suffix)
    out_file = out_dir / "casts" / f"cast_{cast_num_str}.html"
    if out_file.exists() and not force:
        return out_file

    out_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        ds = xr.open_dataset(nc_path, decode_timedelta=False, engine="netcdf4").load()
        sensor_info = parse_sensor_info(ds)
        ds = add_teos10(ds)
    except Exception:  # noqa: BLE001
        return None

    # Pre-soak and post-recovery trim (both applied when trim_soak is True)
    n_soak_trimmed = 0
    n_deck_trimmed = 0
    if trim_soak and "pressure" in ds and "time" in ds:
        p = ds["pressure"].values
        t = ds["time"].values
        n_total_records = len(t)
        soak_end = find_soak_end(p, t)
        cast_end = find_cast_end(p, t)
        if cast_end <= soak_end:
            cast_end = n_total_records
        n_soak_trimmed = max(0, soak_end)
        n_deck_trimmed = (
            (n_total_records - cast_end) if cast_end < n_total_records else 0
        )
        if n_soak_trimmed > 0 or n_deck_trimmed > 0:
            ds = ds.isel(
                time=slice(
                    soak_end if soak_end > 0 else None,
                    cast_end if cast_end < n_total_records else None,
                )
            )

    # Salinity range trim (applied after soak trim)
    n_sal_trimmed = 0
    sal_lo = sal_hi = 0.0
    _sal_var = next(
        (v for v in ("ctd_salinity", "ctd_salinity_1", "salinity_1") if v in ds), None
    )
    if sal_range is not None and _sal_var is not None:
        sal_lo, sal_hi = sal_range
        sal_vals = ds[_sal_var].values
        mask = (sal_vals >= sal_lo) & (sal_vals <= sal_hi) & np.isfinite(sal_vals)
        n_sal_trimmed = int((~mask).sum())
        if n_sal_trimmed > 0:
            ds = ds.isel(time=mask)

    # Build a single human-readable trim note for the page header
    trim_note = ""
    soak_parts = []
    if n_soak_trimmed > 0:
        soak_parts.append(f"{n_soak_trimmed} pre-soak")
    if n_deck_trimmed > 0:
        soak_parts.append(f"{n_deck_trimmed} post-recovery")
    if n_sal_trimmed > 0:
        soak_parts.append(f"{n_sal_trimmed} salinity outside [{sal_lo}, {sal_hi}]")
    if soak_parts:
        n_total = n_soak_trimmed + n_deck_trimmed + n_sal_trimmed
        trim_note = f"{n_total} records excluded ({', '.join(soak_parts)})"

    lat = float(np.nanmedian(ds["latitude"].values))
    lon = float(np.nanmedian(ds["longitude"].values))
    max_depth = float(np.nanmax(ds["pressure"].values))
    t_raw = ds["time"].values
    t0 = _fmt_utc(t_raw[0])
    t_end = _fmt_utc(t_raw[-1])
    dur_s = int((t_raw[-1] - t_raw[0]) / np.timedelta64(1, "s"))
    dur_h, dur_rem = divmod(dur_s, 3600)
    dur_m = dur_rem // 60
    duration_str = f"{dur_h}h {dur_m:02d}m"
    _ci = cruise_info or {}
    cruise = _ci.get("cruise_id") or ds.attrs.get("cruise", UNKNOWN_CRUISE_ID)
    ship = (
        _ci.get("ship")
        or ds.attrs.get("ship")
        or ds.attrs.get("platform")
        or ds.attrs.get("vessel")
        or "UNK"
    )

    ladcp_path: Path | None = None
    if ladcp_dir is not None:
        found = find_ladcp_file(ladcp_dir, cast_num, cast_suffix, ladcp_pattern)
        # Keep a non-None path even when no file exists so downstream callers
        # that gate on ladcp_dir-is-not-None still get the LADCP plot layout.
        ladcp_path = (
            found
            if found is not None
            else ladcp_dir / f"{format_cast_id(cast_num, cast_suffix)}.mat"
        )
    ladcp_exists = ladcp_path is not None and ladcp_path.exists()

    # The page body is now driven by the section manifest: build the per-cast
    # context once, resolve the profile (numbers, inclusion, stubs all fall out),
    # and hand the resolved report to the template's generic section loop.
    page_ctx = PageCtx(
        ds=ds,
        cfg=cfg,
        lat=lat,
        lon=lon,
        all_meta=all_meta,
        ladcp_path=ladcp_path,
        ladcp_configured=ladcp_dir is not None,
        ladcp_exists=ladcp_exists,
        sensor_info=sensor_info,
        nc_path=nc_path,
    )
    report = resolve_cast(page_ctx, drop_stub=drop_stub)

    ctx: dict[str, Any] = {
        "cast_num": cast_num_str,
        "cruise": cruise,
        "ship": ship,
        "datetime_str": t0,
        "time_end_str": t_end,
        "duration_str": duration_str,
        "lat_str": _dec_to_ddm(lat, "lat"),
        "lon_str": _dec_to_ddm(lon, "lon"),
        "max_depth_str": f"{max_depth:.0f} dbar",
        "prev_num": prev_cast_str or "",
        "next_num": next_cast_str or "",
        "ladcp_configured": ladcp_dir is not None,
        "ladcp_available": ladcp_exists,
        "trim_note": trim_note,
        "cast_notes": cast_notes or [],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "version": _VERSION,
        "report": report,
        "section_columns": CAST_SECTION_COLUMNS,
    }

    html = get_template("cast.html").render(
        **ctx,
        css=SHARED_CSS,
        js_top_links=_JS_TOP_LINKS,
        nav_prefix="../",
        nav_current="casts",
        masthead_bg=ROLE_ACCENT["entity"],
    )
    out_file.write_text(html, encoding="utf-8")
    ds.close()
    return out_file


def _cast_id_from_path(nc_path: Path) -> tuple[int, str]:
    """Return ``(cast_num, cast_suffix)`` from a cast filename.

    Thin wrapper over :func:`ctdcast.identity.cast_id_from_name` that falls back
    to ``(0, "")`` when the stem contains no 3+-digit cast number.
    """
    return cast_id_from_name(nc_path.stem) or (0, "")


# ---------------------------------------------------------------------------
# Section manifest — the cast page as data (see .claude/rep-section-manifest-plan.md)
#
# NOTE (2026-08-16, autonomous): this is the model layer only.  It is NOT yet
# wired into generate_station_page() / cast.html — that template port is a
# separate commit that needs a visual review.  These declarations + the
# integrity tests (tests/test_cast_manifest.py) let the numbering/inclusion be
# checked before the page is switched over.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PageCtx:
    """Per-cast render context: the frozen inputs every cast panel/predicate reads.

    Wraps the frozen :class:`ReportConfig` (``cfg``) with the values derived once
    per cast, so a panel's ``render``/``applies_to`` depends only on this object.
    Keeping it frozen and section-independent is what makes "derived context must
    not depend on section inclusion" enforceable rather than aspirational.
    """

    ds: Any
    cfg: ReportConfig
    lat: float
    lon: float
    all_meta: list[dict[str, Any]]
    ladcp_path: Path | None
    ladcp_configured: bool
    ladcp_exists: bool
    sensor_info: list[dict[str, Any]]
    nc_path: Path


def _render_sensor_table(sensor_info: list[dict[str, Any]]) -> str | None:
    """Return the sensor-metadata table markup, or None when there is no info.

    Values are escaped here because the manifest table macro emits this payload
    with ``|safe`` — the escaping that Jinja does today for ``{{ s.sensor_type }}``
    moves into this builder so the autoescape guarantee is preserved.
    """
    if not sensor_info:
        return None
    rows = "".join(
        f"<tr><td>{escape(s.get('sensor_type', ''))}</td>"
        f"<td>{escape(s.get('serial_number', ''))}</td>"
        f"<td>{escape(s.get('calibration_date', ''))}</td></tr>"
        for s in sensor_info
    )
    return (
        '<table class="sensor-table">'
        "<tr><th>Sensor</th><th>S/N</th><th>Cal date</th></tr>"
        f"{rows}</table>"
    )


def _render_data_ranges_table(nc_path: Path) -> str | None:
    """Return the per-cast netCDF data-ranges table markup, or None when empty.

    Lists min/max/valid for every variable in the file on disk (not the trimmed
    or derived data plotted above), plus the display ``label_units`` so a reader
    can see how a figure's axis label was derived.  Values are escaped here
    because the manifest table macro emits this payload with ``|safe``.
    """
    meta = read_dataset_meta(nc_path)
    rows_data = meta.get("coords", []) + meta.get("data_vars", [])
    if not rows_data:
        return None
    rows = "".join(
        f"<tr><td class='mono'>{escape(v['name'])}</td>"
        f"<td>{escape(str(v['units']))}</td>"
        f"<td>{escape(str(v['label_units']))}</td>"
        f"<td class='num'>{escape(str(v['v_min']))}</td>"
        f"<td class='num'>{escape(str(v['v_max']))}</td>"
        f"<td class='num'>{escape(str(v['n_valid']))}"
        f"{' / ' + escape(str(v['n'])) if v['n_valid'] < v['n'] else ''}</td></tr>"
        for v in rows_data
    )
    return (
        '<table class="nc data-ranges">'
        "<thead><tr><th>Variable</th><th>Units</th><th>Label units</th>"
        "<th class='num'>Min</th><th class='num'>Max</th>"
        "<th class='num'>Valid</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


# applies_to answers "could this section/panel exist for this cast?" — NOT "did it
# render?".  A None render from an applicable panel is a defect, and shows as a
# stub with a reason; a section that genuinely cannot exist (no such variable) is
# omitted and named in the not-applicable footer.  Do not leave figure panels on
# the default _always where a structural predicate applies.


def _has_biogeo(c: PageCtx) -> bool:
    """True when any biogeochemistry variable is present (single- or dual-sensor)."""
    return any(resolve_sensor_var(c.ds, v) in c.ds for v in SECTION_BIOGEO_VARS)


def _has_ts(c: PageCtx) -> bool:
    """True when temperature and salinity are present (CT/SA/σ₀ derivable).

    Gates Hydrography, T–S diagram and Stability: a cast with T and S *could* have
    them, so if the figure then returns None it is a defect (a stub), not a silent
    omission.  A file genuinely without T/S omits these sections into the footer.
    """
    return "conservative_temperature" in c.ds and "absolute_salinity" in c.ds


def _has_dual_sensors(c: PageCtx) -> bool:
    """True when a second temperature *or* salinity sensor is present.

    Mirrors :func:`~ctdcast.plotters.plots.draw_sensor_diff_fig`, which draws the
    T₁−T₂ and/or S₁−S₂ difference when either pair exists — so the panel must apply
    whenever either is dual, not temperature alone.  (In practice a cast is dual on
    both channels or neither, but gating on both keeps the predicate honest to the
    figure.)  Checks canonical and legacy names, matching the figure's own resolver
    so it stays correct on both pre- and post-rename datasets.
    """
    dual_t = ("ctd_temperature_1" in c.ds or "temperature_1" in c.ds) and (
        "ctd_temperature_2" in c.ds or "temperature_2" in c.ds
    )
    dual_s = ("ctd_salinity_1" in c.ds or "salinity_1" in c.ds) and (
        "ctd_salinity_2" in c.ds or "salinity_2" in c.ds
    )
    return dual_t or dual_s


#: Cast panel registry — each wraps an existing ``_make_*_b64`` adapter unchanged,
#: reading only from :class:`PageCtx`.  Slots mirror the current cast.html layout.
CAST_PANELS: dict[str, Panel] = {
    "ts_density": Panel(
        id="ts_density",
        slot="three-fifths",
        render=lambda c: _make_ts_density_b64(
            c.ds, c.ladcp_path if c.ladcp_configured else None, cfg=c.cfg
        ),
    ),
    "station_map": Panel(
        id="station_map",
        slot="two-fifths",
        render=lambda c: _make_station_map_b64(
            c.lat, c.lon, c.all_meta, target_h=2.75, cfg=c.cfg
        ),
    ),
    "ts_updown": Panel(
        id="ts_updown",
        slot="two-fifths",
        render=lambda c: _make_ts_updown_b64(c.ds, cfg=c.cfg),
    ),
    "ct_sa_sigma0": Panel(
        id="ct_sa_sigma0",
        slot="full",
        render=lambda c: _make_ct_sa_sigma0_b64(c.ds, cfg=c.cfg),
    ),
    "aux": Panel(
        id="aux", slot="full", render=lambda c: _make_aux_profiles_b64(c.ds, cfg=c.cfg)
    ),
    "ts_diagram": Panel(
        id="ts_diagram",
        slot="third",
        caption="Contours: σ₀ (kg m⁻³) — potential density referenced to surface",
        render=lambda c: _make_ts_diagram_b64(c.ds, cfg=c.cfg),
    ),
    "stability": Panel(
        id="stability",
        slot="twothirds",
        render=lambda c: _make_stability_b64(c.ds, cfg=c.cfg),
    ),
    "ladcp_bottomtrack": Panel(
        id="ladcp_bottomtrack",
        slot="third",
        render=lambda c: _make_ladcp_bottomtrack_b64(c.ladcp_path, cfg=c.cfg)
        if c.ladcp_exists
        else None,
    ),
    "pressure_time": Panel(
        id="pressure_time",
        slot="third",
        caption="Cast trajectory: pressure vs elapsed time",
        render=lambda c: _make_pressure_time_b64(c.ds, cfg=c.cfg),
    ),
    "sensor_diff": Panel(
        id="sensor_diff",
        slot="twothirds",
        applies_to=_has_dual_sensors,
        caption=(
            "T₁−T₂, S₁−S₂: primary minus secondary sensor. "
            "Ideal: scatter around zero with ±0.01 spread."
        ),
        render=lambda c: _make_sensor_diff_b64(c.ds, cfg=c.cfg),
    ),
    "updown_diff": Panel(
        id="updown_diff",
        slot="full",
        caption=(
            "ΔCT, ΔSA, Δσ₀ downcast minus upcast on 1-dbar grid — "
            "measures hysteresis from pump lag or sensor response time"
        ),
        render=lambda c: _make_updown_diff_b64(c.ds, cfg=c.cfg),
    ),
    "sensors_table": Panel(
        id="sensors_table",
        kind="table",
        render=lambda c: _render_sensor_table(c.sensor_info),
    ),
    "data_ranges": Panel(
        id="data_ranges",
        kind="table",
        render=lambda c: _render_data_ranges_table(c.nc_path),
    ),
}


#: The cast page profile.  Conservative port of the current page: same figures,
#: same grouping — the manifest only renumbers (closing the D1 gaps), generates
#: the jump-nav, and turns section ids into anchors (the D3 fix).
CAST_DEFAULT: Profile = Profile(
    numbering="flat",
    entries=(
        Section(
            "overview",
            "Overview",
            ("ts_density", "station_map", "ts_updown"),
            intro="CT · SA · σ₀ profiles, station location, and T–S down-vs-up.",
        ),
        Section(
            "hydrography",
            "Hydrography",
            ("ct_sa_sigma0",),
            intro="CT · SA · σ₀ vs pressure — downcast in colour, upcast in grey.",
            applies_to=_has_ts,
        ),
        Section(
            "biogeochemistry",
            "Biogeochemistry",
            ("aux",),
            intro="O₂ saturation · fluorescence · turbidity.",
            applies_to=_has_biogeo,
        ),
        Section(
            "ts_diagram",
            "T–S diagram",
            ("ts_diagram",),
            intro="Coloured by O₂ saturation — downcast only.",
            applies_to=_has_ts,
        ),
        Section(
            "stability",
            "Stability",
            ("stability",),
            intro="N² and Turner angle — downcast only.",
            applies_to=_has_ts,
        ),
        Section(
            "velocity",
            "Velocity (bottom track)",
            ("ladcp_bottomtrack",),
            applies_to=lambda c: c.ladcp_exists,
        ),
        Section(
            "diagnostics",
            "Diagnostics",
            ("pressure_time", "sensor_diff", "updown_diff"),
        ),
        Section(
            "sensors",
            "Sensors",
            ("sensors_table",),
            role="appendix",
            applies_to=lambda c: bool(c.sensor_info),
        ),
        Section(
            "data_ranges",
            "netCDF data ranges",
            ("data_ranges",),
            intro="Min · max · valid count for every variable in the cast file on disk.",
            role="appendix",
        ),
    ),
)


#: Presentational intra-section layout, kept out of the layout-neutral manifest
#: model.  Maps a section id to the panel index from which the trailing panels
#: stack in a right-hand ``fig-col`` (rather than wrapping onto their own row).
#: ``overview: 1`` puts the CT·SA·σ₀ profiles on the left and stacks the station
#: map above the T–S down-vs-up plot in the right column.
CAST_SECTION_COLUMNS: dict[str, int] = {"overview": 1}


def resolve_cast(ctx: PageCtx, *, drop_stub: bool = False) -> ResolvedReport:
    """Resolve the cast profile against *ctx* into numbered, rendered sections.

    *drop_stub* (from the ``--drop-stub`` CLI flag) drops an applicable section
    whose panels all failed to render, instead of keeping its heading with a stub.
    """
    return resolve(CAST_DEFAULT, ctx, CAST_PANELS, drop_stub=drop_stub)
