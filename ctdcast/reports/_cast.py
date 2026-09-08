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
from ctdcast.config.cnv_header import (
    CONFORMANCE_DIFFER,
    CONFORMANCE_MATCH,
    CONFORMANCE_NO_REFERENCE,
    ConformanceTick,
    Correction,
    SensorCalibration,
    cal_value_nondefault,
    conformance_advisories,
    conformance_supported,
    conformance_ticks,
    correction_records,
    detect_instrument,
    header_from_raw_metadata,
    provenance_advisories,
    sensor_calibrations,
)
from ctdcast.config.global_attrs import cruise_name
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
from ctdcast.readers.metadata import parse_sensor_info, source_to_canonical
from ctdcast.reports._dataset import read_dataset_meta
from ctdcast.reports._env import get_template
from ctdcast.reports._format import _fmt_utc
from ctdcast.reports._manifest import Panel, Profile, ResolvedReport, Section, resolve
from ctdcast.reports._plots import (
    _make_aux_profiles_b64,
    _make_ct_sa_sigma0_b64,
    _make_ladcp_bottomtrack_b64,
    _make_pressure_time_b64,
    _make_qc_histogram_b64,
    _make_sensor_diff_b64,
    _make_stability_b64,
    _make_station_map_b64,
    _make_ts_density_b64,
    _make_ts_diagram_b64,
    _make_ts_updown_b64,
    _make_updown_diff_b64,
)
from ctdcast.reports._qc import qc_summary, qc_thresholds
from ctdcast.reports._report_css import _JS_TOP_LINKS, SHARED_CSS


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
    cruise_info : dict | None
        Optional cruise-level metadata used in the page header.
    drop_stub : bool
        If True, omit sections whose figure returned None instead of rendering a stub.
    cfg : ReportConfig
        Report configuration (styling, paths, display options) threaded to the plotters.

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
    cruise = cruise_name(_ci) or ds.attrs.get("cruise", UNKNOWN_CRUISE_ID)
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

    # Source provenance: which file on disk this page was built from (the stage
    # is encoded in the filename) and when that file was written — so a report
    # always says what data produced it, and a stale/wrong-source page is obvious.
    source_str = nc_path.name
    processed_str = datetime.fromtimestamp(
        nc_path.stat().st_mtime, tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

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
        "source_str": source_str,
        "processed_str": processed_str,
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
# Section manifest — the cast page as data
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
    # Mark primary/secondary only for a sensor type that has more than one instance.
    # SBE puts the primary sensor on the lower channel and parse_sensor_info preserves
    # channel order, so the first instance of a type is primary, the second secondary.
    # A type with a single instance leaves the column empty.
    counts: dict[str, int] = {}
    for s in sensor_info:
        counts[s.get("sensor_type", "")] = counts.get(s.get("sensor_type", ""), 0) + 1
    _ORDINAL = {1: "primary", 2: "secondary"}
    seen: dict[str, int] = {}
    rows = ""
    for s in sensor_info:
        stype = s.get("sensor_type", "")
        seen[stype] = seen.get(stype, 0) + 1
        role = _ORDINAL.get(seen[stype], str(seen[stype])) if counts[stype] > 1 else ""
        rows += (
            f"<tr><td>{escape(stype)}</td>"
            f"<td>{escape(role)}</td>"
            f"<td>{escape(s.get('serial_number', ''))}</td>"
            f"<td>{escape(s.get('calibration_date', ''))}</td></tr>"
        )
    return (
        '<table class="sensor-table">'
        "<tr><th>Sensor</th><th>Primary/secondary</th><th>S/N</th><th>Cal date</th></tr>"
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
        f"{' / ' + escape(str(v['n'])) if v['n_valid'] < v['n'] else ''}</td>"
        f"<td>{escape(str(v.get('processing_level', '')))}</td></tr>"
        for v in rows_data
    )
    return (
        '<table class="nc data-ranges">'
        "<thead><tr><th>Variable</th><th>Units</th><th>Label units</th>"
        "<th class='num'>Min</th><th class='num'>Max</th>"
        "<th class='num'>Valid</th><th>Processing level</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


#: Global attributes shown in the file-provenance table, in order, with their row labels.
#: Only those present on the file are shown, so a legacy file skips the ones it lacks.
_FILE_PROVENANCE_FIELDS: tuple[tuple[str, str], ...] = (
    ("cast_id", "Cast"),
    ("data_mode", "Data mode"),
    ("processing_stage", "Processing stage"),
    ("source_cnv", "Source CNV"),
    ("tracking_id", "Tracking id"),
    ("source_tracking_id", "Made from"),
    ("date_created", "Created"),
    ("date_modified", "Modified"),
)


def _render_file_provenance(c: PageCtx) -> str | None:
    """Return the file-identity/provenance key-value table, or None when the file has none.

    Surfaces the global attributes ctdcast writes — cast identity, OceanSITES ``data_mode``,
    ``processing_stage``, and the ``tracking_id`` lineage back to the CNV — so a reader can
    confirm from the report which stage and mode produced the page.
    """
    a = c.ds.attrs
    rows: list[str] = []
    for key, label in _FILE_PROVENANCE_FIELDS:
        val = a.get(key)
        if val in (None, ""):
            continue
        text = str(val)
        if key == "data_mode":
            meaning = str(a.get("data_mode_meaning", "")).strip()
            text = f"{text} ({meaning})" if meaning else text
        rows.append(
            f"<tr><th>{escape(label)}</th><td class='mono'>{escape(text)}</td></tr>"
        )
    if not rows:
        return None
    return f'<table class="nc file-provenance"><tbody>{"".join(rows)}</tbody></table>'


#: Fields that on their own justify the file-provenance section.  Dates are excluded: almost
#: every file has them, the footer already shows a processed date, and a two-row Created /
#: Modified table on a legacy file is noise — the section is for identity, mode and lineage.
_FILE_PROVENANCE_TRIGGERS: frozenset[str] = frozenset(
    {k for k, _ in _FILE_PROVENANCE_FIELDS} - {"date_created", "date_modified"}
)


def _has_file_provenance(c: PageCtx) -> bool:
    """Return True when the cast file carries a substantive file-provenance attribute (not just dates)."""
    return any(c.ds.attrs.get(k) for k in _FILE_PROVENANCE_TRIGGERS)


def _render_qc_table(nc_path: Path) -> str | None:
    """Return the per-cast QC panel markup, or None when the file has no flags.

    Two tables in cause→effect order: the two-tier (suspect/fail) gross-range and
    spike thresholds recorded on each ``{var}_qc`` companion, then per variable the
    QARTOD flag-count breakdown with a coloured distribution bar.  Reads the file on
    disk — the flags the pipeline recorded — not the trimmed, derived dataset
    plotted above.  Count columns always show the core QARTOD flags (pass, suspect,
    fail, missing) so a clean cast reads as a fixed table; any other declared flag
    shows only when it occurs.  Labels come from each file's own
    ``flag_values``/``flag_meanings``.  Values escaped here (emitted ``|safe``).
    """
    summary = qc_summary(nc_path)
    if not summary:
        return None

    # Columns: always show the core QARTOD flags — pass (1), suspect (3), fail (4),
    # missing (9) — so a clean cast still reads as a fixed pass/suspect/fail/missing
    # table (matching oceanarray) rather than collapsing to only the flags that
    # happen to occur.  Any other declared flag (e.g. not_evaluated, 2) is shown only
    # when it actually occurs, so a scheme value ctdcast never assigns adds no dead
    # column.  Zero-count core flags render as "–".
    _CORE_FLAGS = (1, 3, 4, 9)
    present: dict[int, dict[str, Any]] = {}
    for row in summary:
        for f in row["flags"]:
            if f["flag"] in _CORE_FLAGS or f["n"] > 0:
                present.setdefault(f["flag"], f)
    cols = [present[k] for k in sorted(present)]

    legend = "".join(
        f'<span style="background:{f["color"]}"></span>'
        f"{escape(f['label'])}&nbsp;({f['flag']}) "
        for f in cols
    )
    header = "".join(f"<th class='num'>{escape(f['label'])}&nbsp;%</th>" for f in cols)

    body = []
    for row in summary:
        by_flag = {f["flag"]: f for f in row["flags"]}
        cells = ""
        for col in cols:
            f = by_flag.get(col["flag"])
            if f and f["n"] > 0:
                txt = f"{f['pct']}" if f["pct"] > 0 else f"&lt;0.1&nbsp;({f['n']})"
                cells += f"<td class='num'>{txt}</td>"
            else:
                cells += "<td class='num'>&ndash;</td>"
        bar = "".join(
            f'<div style="width:{f["pct"]}%;background:{f["color"]};" '
            f'title="{escape(f["label"])}: {f["pct"]}%"></div>'
            for f in row["flags"]
            if f["pct"] > 0
        )
        body.append(
            f"<tr><td class='mono'>{escape(row['var'])}</td>"
            f"<td class='num'>{row['total']:,}</td>{cells}"
            f"<td><div class='qc-bar'>{bar}</div></td></tr>"
        )

    thresholds = qc_thresholds(nc_path)
    thr_html = ""
    if thresholds:
        trows = "".join(
            f"<tr><td class='mono'>{escape(r['var'])}</td>"
            f"<td>{escape(r['test'])}</td>"
            f"<td class='num'>{escape(r['suspect'])}</td>"
            f"<td class='num'>{escape(r['fail'])}</td></tr>"
            for r in thresholds
        )
        thr_html = (
            "<h3>Thresholds applied (as stored in stage 3 file)</h3>"
            "<table class='nc qc-thresholds'><thead><tr><th>Variable</th>"
            "<th>Test</th><th class='num'>Suspect range / threshold</th>"
            "<th class='num'>Fail range / threshold</th></tr></thead>"
            f"<tbody>{trows}</tbody></table>"
        )

    # Self-contained layout CSS for the distribution bar and legend; the flag
    # colours are inline hex (from QC_FLAG_COLORS), so this needs no CSS vars.
    style = (
        "<style>"
        ".qc-bar{display:flex;width:200px;height:13px;border-radius:3px;"
        "overflow:hidden;gap:1px;background:#ecf0f1}"
        ".qc-bar div{height:100%}"
        ".qc-legend{display:flex;flex-wrap:wrap;gap:0.3rem 0.9rem;"
        "font-size:0.75rem;margin:0.2rem 0 0.6rem}"
        ".qc-legend span{display:inline-block;width:10px;height:10px;"
        "border-radius:2px;vertical-align:middle;margin-right:3px}"
        "</style>"
    )
    # Provenance caveat: flag 4 (fail) is not solely this variable's own test.
    # Stage 2 trims the pre-descent soak and post-recovery on-deck scans by setting
    # flag 4 on EVERY variable at those same scans, so a variable can show flagged
    # samples its own gross-range/spike thresholds never raised.  Say so, or the
    # distribution reads as if the variable itself failed those values.
    note = (
        "<p class='caption'>Flag 4 (fail) combines two independent exclusions: this "
        "variable&rsquo;s own gross-range and spike tests, and the whole-cast soak / "
        "on-deck trim, which flags the same pre-descent and post-recovery scans on "
        "every variable. A variable can therefore show flagged samples that its own "
        "thresholds did not raise.</p>"
    )
    # Thresholds first (what the pipeline was told to do), then the flag counts
    # (what that produced) — matching the cause→effect reading order.
    return (
        f"{style}{thr_html}"
        "<h3>Flag counts</h3>"
        f"<div class='qc-legend'>{legend}</div>"
        "<table class='nc qc-counts'><thead><tr><th>Variable</th>"
        f"<th class='num'>N</th>{header}<th>Distribution</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
        f"{note}"
    )


def _render_sensor_calibration_table(cals: list[SensorCalibration]) -> str:
    """Return the sensor calibration-state table, or ``""`` when no sensors were read.

    Reports each frequency sensor's drift Slope/Offset (:func:`sensor_calibrations`) so a
    reader can see whether a correction is already baked in before ctdcast: a non-identity
    slope/offset means ``datcnv`` applied ``corrected = slope * computed + offset``.  This
    is provenance, not a conformance verdict -- there is no universal reference slope.
    """
    if not cals:
        return ""
    tight = " style='margin-bottom:0.25rem'"

    def _value(text: str, *, nondefault: bool) -> str:
        """Bold a value that departs from its default, so the eye finds the correction."""
        cell = escape(text)
        return f"<strong>{cell}</strong>" if nondefault else cell

    row_items = []
    for c in cals:
        # A row carrying any drift/span correction is tinted amber (the vendored --warn-bg,
        # applied per-cell so it beats the even-row zebra rule); the specific value that
        # differs is bolded.
        bg = " style='background:var(--warn-bg)'" if c.drift_applied else ""
        state = (
            "drift/span correction applied"
            if c.drift_applied
            else "pre-cruise coefficients — no drift correction"
        )
        row_items.append(
            f"<tr><td class='mono'{bg}>{escape(c.label)}</td>"
            f"<td class='mono'{bg}>{escape(c.serial)}</td>"
            f"<td class='mono'{bg}>{_value(c.slope, nondefault=c.slope_nondefault)}</td>"
            f"<td class='mono'{bg}>{_value(c.offset, nondefault=c.offset_nondefault)}</td>"
            f"<td{bg}>{state}</td></tr>"
        )
    rows = "".join(row_items)
    return (
        f"<h3{tight}>Sensor calibration state</h3>"
        "<table class='nc' style='margin-top:0'><thead><tr><th>Sensor</th>"
        "<th>Serial</th><th>Slope</th><th>Offset</th><th>State</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _is_sensor_catalog_var(name: str) -> bool:
    """Return True for a ``SENSOR_*`` catalog entry, excluding any ``_qc`` companion.

    QC can stamp a ``{var}_qc`` companion on the dimensionless ``SENSOR_*`` scalars; those
    are not catalog entries and must not be read as sensors.
    """
    return name.startswith("SENSOR_") and not name.endswith("_qc")


def _has_sensor_catalog(ds: xr.Dataset) -> bool:
    """Return True when the cast carries the stage-1 ``SENSOR_*`` sensor catalog."""
    return any(_is_sensor_catalog_var(str(v)) for v in ds.variables)


def _render_sensor_catalog_table(ds: xr.Dataset) -> str:
    """Return the per-cast sensor table built from the ``SENSOR_*`` catalog, or ``""``.

    One row per catalogued device, joined to the science variable it produced via that
    variable's ``sensor=`` link, so a reader sees in one row what measured each number, on
    which channel, and whether a correction was baked in.  Reads the catalog stage 1 built,
    not the CNV header — the same facts without a third parse.  Frequency sensors (T/C/P)
    carry a drift Slope/Offset; a non-identity value is amber-tinted and bolded, matching the
    calibration-state convention.  A sensor with no stored variable (pH, transmissometer)
    still lists, with an empty Variable/Channel.  Rows are ordered by acquisition channel.
    Returns ``""`` for a cast with no catalog, so the caller falls back to the header parse.
    """
    catalog = [str(v) for v in ds.variables if _is_sensor_catalog_var(str(v))]
    if not catalog:
        return ""
    # Invert the per-variable ``sensor=`` links so each catalog entry names its variable(s);
    # pressure is a coordinate, so iterate every variable, not only data_vars.
    var_by_sensor: dict[str, list[str]] = {}
    for v in ds.variables:
        linked = ds[v].attrs.get("sensor")
        if linked:
            var_by_sensor.setdefault(str(linked), []).append(str(v))

    def _channel(name: str) -> int:
        """Sort key: acquisition channel, unstated channels last."""
        try:
            return int(ds[name].attrs.get("sensor_channel", 9999))
        except (TypeError, ValueError):
            return 9999

    def _value(text: str, *, nondefault: bool) -> str:
        """Bold a slope/offset that departs from its default, so the eye finds the correction."""
        cell = escape(text)
        return f"<strong>{cell}</strong>" if nondefault else cell

    rows = []
    for name in sorted(catalog, key=_channel):
        a = ds[name].attrs
        slope = str(a.get("sensor_calibration_slope", ""))
        offset = str(a.get("sensor_calibration_offset", ""))
        slope_nd = bool(slope) and cal_value_nondefault(slope, 1.0)
        offset_nd = bool(offset) and cal_value_nondefault(offset, 0.0)
        # A row carrying any drift/span correction is tinted amber (the vendored --warn-bg,
        # per-cell so it beats the even-row zebra rule); the differing value is bolded.
        bg = " style='background:var(--warn-bg)'" if (slope_nd or offset_nd) else ""
        variables = ", ".join(var_by_sensor.get(name, [])) or "—"
        chan = a.get("sensor_channel")
        chan_text = "" if chan is None else str(int(chan))
        serial = str(a.get("sensor_serial_number", "")).strip()
        device = f"SN {serial}" if serial else "—"
        rows.append(
            f"<tr><td class='mono'{bg}>{escape(variables)}</td>"
            f"<td{bg}>{escape(str(a.get('sensor_role', '')))}</td>"
            f"<td class='num'{bg}>{escape(chan_text)}</td>"
            f"<td{bg}>{escape(device)}</td>"
            f"<td{bg}>{escape(str(a.get('sensor_model', '')))}</td>"
            f"<td{bg}>{escape(str(a.get('sensor_calibration_date', '')))}</td>"
            f"<td class='mono'{bg}>{_value(slope, nondefault=slope_nd)}</td>"
            f"<td class='mono'{bg}>{_value(offset, nondefault=offset_nd)}</td></tr>"
        )
    # No <h3>: this single table sits directly under the "Sensors" appendix heading, so a
    # heading of its own would just repeat it.  The pre-catalog fallback keeps its headings,
    # where there really are two tables (device inventory, then calibration state).
    return (
        "<table class='nc'><thead><tr>"
        "<th>Variable</th><th>Role</th><th>Ch</th><th>Device</th><th>Model</th>"
        "<th>Cal date</th><th>Slope</th><th>Offset</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _render_sensors_section(c: PageCtx) -> str | None:
    """Render the Sensors appendix, or None when the cast has no sensor information.

    A cast carrying the ``SENSOR_*`` catalog gets the one merged table joining each science
    variable to the device that produced it and its calibration.  A file predating the
    catalog falls back to the header-derived device inventory plus the drift calibration-state
    table.  This is the single home for sensor information; the processing-provenance panel
    points here rather than duplicating it.
    """
    merged = _render_sensor_catalog_table(c.ds)
    if merged:
        return merged
    parts = [_render_sensor_table(c.sensor_info) or ""]
    header = header_from_raw_metadata(c.ds.attrs.get("raw_metadata")) or ""
    if header:
        parts.append(_render_sensor_calibration_table(sensor_calibrations(header)))
    return "".join(parts) or None


#: The status pip (CSS class, glyph) each conformance state renders as in the match column:
#: a green ✓, a red ✗, a neutral ringed dash (no reference — no match, no warning).
_TICK_BADGE = {
    CONFORMANCE_MATCH: ("conf-match", "✓"),
    CONFORMANCE_DIFFER: ("conf-differ", "✗"),
    CONFORMANCE_NO_REFERENCE: ("conf-none", "–"),
}


def _match_cell(tick: ConformanceTick, bg: str) -> str:
    """Return the "Matches reference" cell: a coloured status pip (the reference is in a caption)."""
    cls, glyph = _TICK_BADGE.get(tick.state, _TICK_BADGE[CONFORMANCE_NO_REFERENCE])
    return f"<td{bg}><span class='conf {cls}'>{glyph}</span></td>"


def _references_caption(ticks: list[ConformanceTick]) -> str:
    """Return a caption listing each documented reference value and its source, under the table.

    Collects the distinct (step, reference, source) triples from the ticks, so the match
    pips stay uncluttered and the reader still sees what each was checked against and where
    it came from (e.g. the SBE-manual page).
    """
    seen: list[tuple[str, str, str]] = []
    for t in ticks:
        # Only the checked (✓/✗) references — the documented values with a source. A
        # no-reference row (e.g. Wild Edit's example thresholds) is not a reference to cite.
        if t.state not in (CONFORMANCE_MATCH, CONFORMANCE_DIFFER):
            continue
        triple = (t.label, t.reference, t.source)
        if t.reference and t.source and triple not in seen:
            seen.append(triple)
    if not seen:
        return ""
    items = "; ".join(
        f"{escape(label)} {escape(ref)} — {escape(src)}" for label, ref, src in seen
    )
    return f"<p class='caption'>Reference values: {items}.</p>"


def _variables_cell(text: str, bg: str) -> str:
    """Return the "Variables" cell: the channels a step touched; a long list collapses behind a disclosure."""
    if not text:
        return f"<td{bg}></td>"
    if len(text) > 60:
        return (
            f"<td{bg}><details><summary class='caption'>channels</summary>"
            f"<span class='caption'>{escape(text)}</span></details></td>"
        )
    return f"<td{bg}><span class='caption'>{escape(text)}</span></td>"


def _corrections_rows_with_ticks(
    records: list[Correction], ticks: list[ConformanceTick]
) -> str:
    """One row per conformance tick, so a per-channel deck advance or per-cell celltm splits.

    Ticks are grouped to their :class:`Correction` by ``key``; a record with several ticks
    (the deck advance, cell thermal mass, the filter's two low-pass groups) becomes several
    rows, each showing its own value, modified variable and match, and repeating the shared
    producer/version. A differing (✗) row is tinted amber.
    """
    by_key: dict[str, list[ConformanceTick]] = {}
    for tick in ticks:
        by_key.setdefault(tick.key, []).append(tick)
    rows: list[str] = []
    for r in records:
        rec_ticks = by_key.get(r.key) or [None]
        split = len(rec_ticks) > 1  # a per-channel/per-cell/per-group expansion
        for tick in rec_ticks:
            step = escape(tick.label) if tick else escape(r.label)
            differ = tick is not None and tick.state == CONFORMANCE_DIFFER
            bg = " style='background:var(--warn-bg)'" if differ else ""
            match = _match_cell(tick, bg) if tick else f"<td{bg}>—</td>"
            # A split row shows its own channel/cell value (the tick detail); a plain row
            # keeps the record's file parameters. Each row names the variable it modified.
            params = tick.detail if (split and tick and tick.detail) else r.parameters
            var_cell = _variables_cell(tick.variables if tick else "", bg)
            rows.append(
                f"<tr><td class='mono'{bg}>{step}</td>"
                f"<td{bg}>{escape(r.producer)}</td>"
                f"<td class='mono'{bg}>{escape(r.version)}</td>"
                f"<td{bg}>{escape(params)}</td>"
                f"{var_cell}{match}</tr>"
            )
    return "".join(rows)


def _corrections_table_html(
    records: list[Correction], ticks: list[ConformanceTick] | None, tight: str
) -> str:
    """Return the corrections table, with Variables and match columns when *ticks* are supplied."""
    if not records:
        return ""
    if ticks:
        body = _corrections_rows_with_ticks(records, ticks)
        head = (
            "<th>Step</th><th>Producer</th><th>Version</th><th>Parameters</th>"
            "<th>Variables</th><th>Matches reference</th>"
        )
    else:
        body = "".join(
            f"<tr><td class='mono'>{escape(r.label)}</td>"
            f"<td>{escape(r.producer)}</td>"
            f"<td class='mono'>{escape(r.version)}</td>"
            f"<td>{escape(r.parameters)}</td></tr>"
            for r in records
        )
        head = "<th>Step</th><th>Producer</th><th>Version</th><th>Parameters</th>"
    return (
        f"<h3{tight}>Corrections applied before ctdcast</h3>"
        f"<table class='nc' style='margin-top:0'><thead><tr>{head}</tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _render_provenance_table(
    records: list[Correction],
    attrs: dict[str, Any],
    advisories: list[str] | None = None,
    ticks: list[ConformanceTick] | None = None,
    conformance: list[str] | None = None,
    instrument_note: str | None = None,
    sensor_xref: str = "",
) -> str | None:
    """Return the SBE upstream-provenance tables, or None when the cast carries no ledger.

    Focused on *what was done* to the data before ctdcast: *records* are the structured
    corrections (deck-unit align first, then each Sea-Bird Data Processing module in file
    order, a repeat suffixed); *attrs* supplies the time coordinate's source and offset;
    *advisories* are the structural implications
    (:func:`~ctdcast.config.cnv_header.provenance_advisories`) drawn as a note beneath the
    tables.  *ticks* are the conformance comparisons
    (:func:`~ctdcast.config.cnv_header.conformance_ticks`); when present they add a
    "Matches reference" column to the corrections table, splitting a per-channel/per-cell
    correction into one row each.  *conformance* are the deviation sentences
    (:func:`~ctdcast.config.cnv_header.conformance_advisories`) drawn as a "Conformance"
    note.  *instrument_note* is a caption shown under the corrections table (e.g. when the
    instrument has no encoded references).  *sensor_xref*, when set, is a one-line pointer to
    the Sensors appendix, where per-sensor calibration state now lives.  The full verbatim
    blocks stay in the ``sbe_acquisition`` / ``sbe_processing`` attributes.  Values escaped
    here (emitted ``|safe``).
    """
    advisories = advisories or []
    conformance = conformance or []
    src = attrs.get("time_coordinate_source")
    off = attrs.get("time_clock_offset_seconds")
    if not records and not src and off is None and not advisories and not conformance:
        return None

    # A tight heading-to-table gap reads better than the default h3 margin here.
    tight = " style='margin-bottom:0.25rem'"
    corr_html = _corrections_table_html(records, ticks, tight)
    if corr_html and ticks:
        corr_html += _references_caption(ticks)
    if corr_html and instrument_note:
        corr_html += f"<p class='caption'>{escape(instrument_note)}</p>"

    time_rows: list[tuple[str, str]] = []
    if src:
        time_rows.append(("Time coordinate source", str(src)))
    if off is not None:
        time_rows.append(("Clock offset (NMEA − system)", f"{off} s"))
    time_html = ""
    if time_rows:
        trows = "".join(
            f"<tr><td>{escape(k)}</td><td class='mono'>{escape(v)}</td></tr>"
            for k, v in time_rows
        )
        time_html = (
            f"<h3{tight}>Time coordinate</h3>"
            "<table class='nc' style='margin-top:0'><thead><tr><th>Property</th>"
            f"<th>Value</th></tr></thead><tbody>{trows}</tbody></table>"
        )

    advisory_html = ""
    if advisories:
        items = "".join(f"<li>{escape(a)}</li>" for a in advisories)
        advisory_html = f"<h3{tight}>Advisories</h3><ul class='caption' style='margin-top:0'>{items}</ul>"

    conformance_html = ""
    if conformance:
        items = "".join(f"<li>{escape(a)}</li>" for a in conformance)
        conformance_html = (
            f"<h3{tight}>Conformance</h3>"
            f"<ul class='caption' style='margin-top:0'>{items}</ul>"
        )

    # Per-sensor calibration state lives in the Sensors appendix (one table joining each
    # variable to the device that produced it); this panel keeps its focus on processing and
    # just points there.
    xref_html = f"<p class='caption'>{escape(sensor_xref)}</p>" if sensor_xref else ""

    note = (
        "<p class='caption'>Recovered from the raw Sea-Bird header on the cast file; the "
        "full verbatim blocks are kept in the <code>sbe_acquisition</code> and "
        "<code>sbe_processing</code> attributes.</p>"
    )
    # Wrap in one block (`.prov-panel` is a full-width flex item) so the panel's headings
    # and tables stack instead of tiling across the section's `.fig-row`.
    return (
        "<div class='prov-panel'>"
        f"{corr_html}{time_html}{advisory_html}{conformance_html}{xref_html}{note}"
        "</div>"
    )


def _render_provenance_panel(c: PageCtx) -> str | None:
    """Parse the SBE header once and render the upstream-provenance tables for a cast."""
    header = header_from_raw_metadata(c.ds.attrs.get("raw_metadata")) or ""
    supported = conformance_supported(header)
    instrument = detect_instrument(header)
    instrument_note = (
        f"Conformance references are not yet available for {instrument}; the corrections "
        "above are shown without a match check."
        if header and instrument and not supported
        else None
    )
    # The reader stamped each variable's source SBE column; that is the authoritative rename
    # this cast used, so the Variables column canonicalises through it (it covers unit
    # spellings CNV_ALIASES misses, e.g. c0mS/cm → conductivity_1).  Lower-cased keys so the
    # lookup is case-insensitive against the header channel names.
    rename_map = source_to_canonical(c.ds, lower_keys=True)
    # The sensor calibration state moved to the Sensors appendix (built from the catalog, not
    # a header re-parse); this panel points there rather than carrying its own sensor table.
    sensor_xref = (
        "Per-sensor calibration state (drift Slope/Offset) and the device inventory are in "
        "the Sensors appendix."
        if c.sensor_info
        else ""
    )
    table = _render_provenance_table(
        correction_records(header),
        dict(c.ds.attrs),
        provenance_advisories(header),
        ticks=conformance_ticks(header, rename_map),
        conformance=conformance_advisories(header),
        instrument_note=instrument_note,
        sensor_xref=sensor_xref,
    )
    if table is not None:
        return table
    if header:
        return (
            "<p class='caption'>No SBE processing steps recorded in the raw header.</p>"
        )
    return None


# applies_to answers "could this section/panel exist for this cast?" — NOT "did it
# render?".  A None render from an applicable panel is a defect, and shows as a
# stub with a reason; a section that genuinely cannot exist (no such variable) is
# omitted and named in the not-applicable footer.  Do not leave figure panels on
# the default _always where a structural predicate applies.


def _has_biogeo(c: PageCtx) -> bool:
    """Return True when any biogeochemistry variable is present (single- or dual-sensor)."""
    return any(resolve_sensor_var(c.ds, v) in c.ds for v in SECTION_BIOGEO_VARS)


def _has_ts(c: PageCtx) -> bool:
    """Return True when temperature and salinity are present (CT/SA/σ₀ derivable).

    Gates Hydrography, T–S diagram and Stability: a cast with T and S *could* have
    them, so if the figure then returns None it is a defect (a stub), not a silent
    omission.  A file genuinely without T/S omits these sections into the footer.
    """
    return "conservative_temperature" in c.ds and "absolute_salinity" in c.ds


def _has_dual_sensors(c: PageCtx) -> bool:
    """Return True when a second temperature *or* salinity sensor is present.

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


def _has_qc(c: PageCtx) -> bool:
    """Return True when the cast file carries QARTOD ``{var}_qc`` companions.

    Stage-2/3 files have them; a stage-1-only cast does not, so the QC section is
    omitted (into the not-applicable footer) rather than stubbed.  Presence is
    read from the dataset — trimming changes flag *counts*, not their existence —
    while the counts themselves are read from the file on disk in the render.
    """
    return any(str(v).endswith("_qc") for v in c.ds.data_vars)


def _has_provenance(c: PageCtx) -> bool:
    """Return True when the cast carries a raw Sea-Bird header to recover provenance from.

    The provenance panel renders from the verbatim SBE header in ``raw_metadata``
    (corrections, sensor calibrations, advisories, time coordinate) -- not from the
    stage-1 ``correction_*`` attrs, which not every stage-1 build stamps. Gate on the
    header so any CTD cast with an SBE header shows the panel; a LADCP cast, which has
    no ``raw_metadata``, does not.
    """
    return header_from_raw_metadata(c.ds.attrs.get("raw_metadata")) is not None


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
        render=lambda c: (
            _make_ladcp_bottomtrack_b64(c.ladcp_path, cfg=c.cfg)
            if c.ladcp_exists
            else None
        ),
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
        # The one home for sensor information: the merged catalog table (variable → device →
        # calibration), or the header-derived inventory for a pre-catalog file.
        render=lambda c: _render_sensors_section(c),
    ),
    "file_provenance": Panel(
        id="file_provenance",
        kind="table",
        render=_render_file_provenance,
    ),
    "data_ranges": Panel(
        id="data_ranges",
        kind="table",
        render=lambda c: _render_data_ranges_table(c.nc_path),
    ),
    "qc_histogram": Panel(
        id="qc_histogram",
        slot="full",
        caption=(
            "Data-value distributions: grey = all data, colour = kept "
            "(soak/deck and missing excluded); orange dashed = gross-range "
            "suspect threshold. A threshold outside the data flags a mis-set bound."
        ),
        render=lambda c: _make_qc_histogram_b64(c.nc_path, cfg=c.cfg),
    ),
    "qc_flags": Panel(
        id="qc_flags",
        kind="table",
        render=lambda c: _render_qc_table(c.nc_path),
    ),
    "provenance": Panel(
        id="provenance",
        kind="table",
        render=_render_provenance_panel,
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
            "qc_flags",
            "QC flags",
            ("qc_histogram", "qc_flags"),
            intro=(
                "QARTOD flags recorded by the pipeline, read back from the cast "
                "file: gross-range thresholds applied and the flag-count breakdown "
                "per variable."
            ),
            applies_to=_has_qc,
        ),
        Section(
            "sensors",
            "Sensors",
            ("sensors_table",),
            role="appendix",
            # Applicable whenever the cast has sensor information — a catalog-bearing cast is
            # exactly where it is *most* applicable, so the predicate must not gate on the
            # catalog (that would route "Sensors" into the not-applicable footer).
            applies_to=lambda c: bool(c.sensor_info) or _has_sensor_catalog(c.ds),
        ),
        Section(
            "file_provenance",
            "File provenance",
            ("file_provenance",),
            intro=(
                "File identity read back from the cast file: cast, OceanSITES data mode, "
                "processing stage, and the tracking_id lineage to the source CNV."
            ),
            role="appendix",
            applies_to=_has_file_provenance,
        ),
        Section(
            "data_ranges",
            "netCDF data ranges",
            ("data_ranges",),
            intro="Min · max · valid count for every variable in the cast file on disk.",
            role="appendix",
        ),
        Section(
            "provenance",
            "Processing provenance",
            ("provenance",),
            intro=(
                "What the SBE deck unit and Sea-Bird Data Processing did to this cast "
                "before ctdcast read it, recovered from the raw header."
            ),
            role="appendix",
            applies_to=_has_provenance,
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
