"""Tier-2: generate a per-cast HTML report page."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr
from jinja2 import Environment

from ctdreport import _templates as _tmpl


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


from ctdreport._css import _JS_TOP_LINKS, SHARED_CSS
from ctdreport._version import __version__ as _VERSION
from ctdreport.analysis import (
    _add_teos10,
    _find_cast_end,
    _find_ladcp_file,
    _find_soak_end,
    _fmt_utc,
    parse_sensor_info,
)
from ctdreport.plots import (
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

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_STATION_TEMPLATE = (
    """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cast {{ cast_num }} — {{ cruise }} CTD</title>
<style>
"""
    + SHARED_CSS
    + """\
/* Station page */
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 1.25rem; font-size: 0.85rem;
}
.breadcrumb a { color: var(--ocean); text-decoration: none; }
.breadcrumb a:hover { text-decoration: underline; }
.breadcrumb .sep { color: var(--muted); margin: 0 0.25rem; }
.cast-note {
  background: #f0f0f0; border-left: 4px solid #888; border-radius: 4px;
  padding: 0.5rem 1rem; margin-bottom: 0.5rem;
  font-size: 0.87rem; color: #333;
}
.trim-note {
  background: #f0f0f0; border-left: 4px solid #888; border-radius: 4px;
  padding: 0.5rem 1rem; margin-bottom: 0.5rem;
  font-size: 0.87rem; color: #333;
}
details.sensor-details {
  margin-bottom: 0.75rem; font-size: 0.82rem; color: var(--muted);
}
details.sensor-details summary { cursor: pointer; user-select: none; padding: 0.2rem 0; }
.sensor-table { border-collapse: collapse; font-size: 0.8rem; margin-top: 0.4rem; }
.sensor-table th, .sensor-table td {
  padding: 0.2rem 0.75rem 0.2rem 0; text-align: left; vertical-align: top;
}
.sensor-table th {
  color: var(--ocean); font-weight: 600; border-bottom: 1px solid var(--seafoam);
}
</style>
</head>
<body>
<div id="top"></div>

<div class="topbar">
  <nav class="breadcrumb">
    <a href="../index.html">Index</a>
    <span class="sep">›</span>
    <a href="../station_index.html">Stations</a>
    <span class="sep">›</span>
    <span>Cast {{ cast_num }}</span>
  </nav>
  <div class="nav-btns">
    {% if next_num %}<a class="btn-nav" href="cast_{{ next_num }}.html">← {{ next_num }}</a>{% endif %}
    {% if prev_num %}<a class="btn-nav" href="cast_{{ prev_num }}.html">{{ prev_num }} →</a>{% endif %}
  </div>
</div>

<div class="masthead" style="background:#1a3a5c;">
  <div class="masthead-header">
    <h1>Cast {{ cast_num }}</h1>
    <span class="masthead-type">Station</span>
  </div>
  <p class="sub" style="margin:0 0 0.6rem; text-align:right;">generated {{ generated_at }}</p>
  <div style="margin-top:0.65rem;margin-bottom:0.5rem">
    <span style="font-size:0.72rem;opacity:0.75;margin-right:0.3rem;">Pages:</span>
    <a href="../index.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#2980b9">Summary</a>
    <a href="../station_index.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#1a3a5c;opacity:0.55">Stations</a>
    <a href="../sections.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#8e44ad">Sections</a>
    <a href="../timeseries.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#27ae60">Timeseries</a>
    <a href="../leaflet.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#EE3377">Interactive</a>
  </div>
  <dl class="meta-grid">
    <div><dt>Cruise</dt><dd>{{ cruise }}</dd></div>
    <div><dt>Ship</dt><dd>{{ ship }}</dd></div>
    <div><dt>Latitude</dt><dd>{{ lat_str }}</dd></div>
    <div><dt>Longitude</dt><dd>{{ lon_str }}</dd></div>
    <div><dt>Start</dt><dd>{{ datetime_str }}</dd></div>
    <div><dt>End</dt><dd>{{ time_end_str }}</dd></div>
    <div><dt>Duration</dt><dd>{{ duration_str }}</dd></div>
    <div><dt>Max depth</dt><dd>{{ max_depth_str }}</dd></div>
    {% if ladcp_configured and not ladcp_available %}
    <div><dt>LADCP</dt><dd style="color:#f5a623;">⚠ not processed</dd></div>
    {% endif %}
  </dl>
</div>

{% if trim_note %}<div class="trim-note">⚠ {{ trim_note }}</div>{% endif %}
{% for note in cast_notes %}<p class="cast-note">⚠ {{ note }}</p>{% endfor %}

<div class="jump-nav">
  <a href="#s-overview">Overview</a>
  <a href="#s-profiles">Hydrography</a>
  <a href="#s-aux">Biogeochemistry</a>
  <a href="#s-ts">T–S diagram</a>
  <a href="#s-stability">Stability</a>
  <a href="#s-diagnostics">Diagnostics</a>
  {% if fig_ladcp_bottomtrack_b64 %}<a href="#s-ladcp">Velocity ▼</a>{% endif %}
</div>

<h2 id="s-overview">Overview</h2>
<p class="note">CT/SA/σ₀{% if ladcp_configured %} + LADCP U/V{% endif %} profiles; station location; T–S down vs up</p>
<div class="fig-row">
  {% if fig_ts_density_b64 %}
  <figure class="slot-three-fifths">
    <img src="data:image/png;base64,{{ fig_ts_density_b64 }}" alt="CT/SA/σ₀{% if ladcp_configured %} + LADCP U/V{% endif %} profiles">
  </figure>
  {% endif %}
  <div class="fig-col slot-two-fifths">
    {% if fig_station_map_b64 %}
    <figure>
      <img src="data:image/png;base64,{{ fig_station_map_b64 }}" alt="Station map">
    </figure>
    {% endif %}
    {% if fig_ts_updown_b64 %}
    <figure>
      <img src="data:image/png;base64,{{ fig_ts_updown_b64 }}" alt="T–S down vs up">
    </figure>
    {% endif %}
  </div>
</div>

{% if fig_ct_sa_sigma0_b64 %}
<h2 id="s-profiles">Hydrography</h2>
<p class="note">CT · SA · σ₀ vs pressure — downcast in colour, upcast in grey</p>
<div class="fig-row">
  <figure class="slot-full">
    <img src="data:image/png;base64,{{ fig_ct_sa_sigma0_b64 }}" alt="CT · SA · σ₀ profiles">
  </figure>
</div>
{% endif %}

{% if fig_aux_b64 %}
<h2 id="s-aux">Biogeochemistry</h2>
<p class="note">O₂ saturation · fluorescence · turbidity</p>
<div class="fig-row">
  <figure class="slot-full">
    <img src="data:image/png;base64,{{ fig_aux_b64 }}" alt="Auxiliary profiles">
  </figure>
</div>
{% endif %}

{% if fig_ts_diagram_b64 %}
<h2 id="s-ts">T–S diagram</h2>
<p class="note">Coloured by O₂ saturation — downcast only</p>
<div class="fig-row">
  <figure class="slot-third">
    <img src="data:image/png;base64,{{ fig_ts_diagram_b64 }}" alt="T-S diagram">
    <figcaption>Contours: σ₀ (kg m⁻³) — potential density referenced to surface</figcaption>
  </figure>
</div>
{% endif %}

{% if fig_stability_b64 %}
<h2 id="s-stability">Stability</h2>
<p class="note">N² and Turner angle — downcast only</p>
<div class="fig-row">
  <figure class="slot-twothirds">
    <img src="data:image/png;base64,{{ fig_stability_b64 }}" alt="Stability">
  </figure>
</div>
{% endif %}

{% if fig_sensor_diff_b64 or fig_pressure_time_b64 or fig_updown_diff_b64 %}
<h2 id="s-diagnostics">Diagnostics</h2>
<div class="fig-row">
  {% if fig_pressure_time_b64 %}
  <figure class="slot-third">
    <img src="data:image/png;base64,{{ fig_pressure_time_b64 }}" alt="Pressure vs time">
    <figcaption>Cast trajectory: pressure vs elapsed time</figcaption>
  </figure>
  {% endif %}
  {% if fig_sensor_diff_b64 %}
  <figure class="slot-twothirds">
    <img src="data:image/png;base64,{{ fig_sensor_diff_b64 }}" alt="Sensor 1 − Sensor 2">
    <figcaption>T₁−T₂, S₁−S₂: primary minus secondary sensor. Ideal: scatter around zero with ±0.01 spread.</figcaption>
  </figure>
  {% endif %}
</div>
{% if fig_updown_diff_b64 %}
<div class="fig-row">
  <figure class="slot-full">
    <img src="data:image/png;base64,{{ fig_updown_diff_b64 }}" alt="Down − up cast differences">
    <figcaption>ΔCT, ΔSA, Δσ₀ downcast minus upcast on 1-dbar grid — measures hysteresis from pump lag or sensor response time</figcaption>
  </figure>
</div>
{% endif %}
{% endif %}

{% if fig_ladcp_bottomtrack_b64 %}
<h2 id="s-ladcp">Velocity (bottom track)</h2>
<div class="fig-row">
  <figure class="slot-third">
    <img src="data:image/png;base64,{{ fig_ladcp_bottomtrack_b64 }}" alt="LADCP bottom track">
  </figure>
</div>
{% endif %}

{% if sensor_info %}
<h2 id="s-sensors">Sensors</h2>
<details class="sensor-details">
  <summary>{{ sensor_info | length }} sensor(s)</summary>
  <table class="sensor-table">
    <tr><th>Sensor</th><th>S/N</th><th>Cal date</th></tr>
    {% for s in sensor_info %}
    <tr>
      <td>{{ s.sensor_type }}</td>
      <td>{{ s.serial_number }}</td>
      <td>{{ s.calibration_date }}</td>
    </tr>
    {% endfor %}
  </table>
</details>
{% endif %}

"""
    + _JS_TOP_LINKS
    + _tmpl.FOOTER_TAIL
)


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
) -> Path | None:
    """Generate a per-cast HTML report page and write it to *out_dir/stations/*.

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
        If True, apply pre-soak detection via :func:`~ctdreport.analysis._find_soak_end`.
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
        cast_num_str = f"{cast_num:03d}{cast_suffix}"
    out_file = out_dir / "stations" / f"cast_{cast_num_str}.html"
    if out_file.exists() and not force:
        return out_file

    out_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        ds = xr.open_dataset(nc_path, decode_timedelta=False, engine="netcdf4").load()
        sensor_info = parse_sensor_info(ds)
        ds = _add_teos10(ds)
    except Exception:  # noqa: BLE001
        return None

    # Pre-soak and post-recovery trim (both applied when trim_soak is True)
    n_soak_trimmed = 0
    n_deck_trimmed = 0
    if trim_soak and "pressure" in ds and "time" in ds:
        p = ds["pressure"].values
        t = ds["time"].values
        n_total_records = len(t)
        soak_end = _find_soak_end(p, t)
        cast_end = _find_cast_end(p, t)
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
    if sal_range is not None and "salinity_1" in ds:
        sal_lo, sal_hi = sal_range
        sal_vals = ds["salinity_1"].values
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
    cruise = _ci.get("cruise_id") or ds.attrs.get("cruise", "odb2026")
    ship = (
        _ci.get("ship")
        or ds.attrs.get("ship")
        or ds.attrs.get("platform")
        or ds.attrs.get("vessel")
        or "UNK"
    )

    ladcp_path: Path | None = None
    if ladcp_dir is not None:
        found = _find_ladcp_file(ladcp_dir, cast_num, cast_suffix, ladcp_pattern)
        # Keep a non-None path even when no file exists so downstream callers
        # that gate on ladcp_dir-is-not-None still get the LADCP plot layout.
        ladcp_path = (
            found
            if found is not None
            else ladcp_dir / f"{cast_num:03d}{cast_suffix}.mat"
        )
    ladcp_exists = ladcp_path is not None and ladcp_path.exists()

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
        "sensor_info": sensor_info,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "version": _VERSION,
        # Overview row — CT/SA/σ₀ triple-axis + LADCP U/V panel
        "fig_ts_density_b64": _make_ts_density_b64(
            ds, ladcp_path if ladcp_dir is not None else None
        ),
        "fig_station_map_b64": _make_station_map_b64(lat, lon, all_meta, target_h=2.75),
        "fig_ts_updown_b64": _make_ts_updown_b64(ds),
        # Row 2
        "fig_ct_sa_sigma0_b64": _make_ct_sa_sigma0_b64(ds),
        # Row 3
        "fig_aux_b64": _make_aux_profiles_b64(ds),
        # Row 4
        "fig_ts_diagram_b64": _make_ts_diagram_b64(ds),
        # Row 5
        "fig_stability_b64": _make_stability_b64(ds),
        # Row 6: diagnostics
        "fig_pressure_time_b64": _make_pressure_time_b64(ds),
        "fig_sensor_diff_b64": _make_sensor_diff_b64(ds),
        "fig_updown_diff_b64": _make_updown_diff_b64(ds),
        # Row 7: LADCP bottom track
        "fig_ladcp_bottomtrack_b64": _make_ladcp_bottomtrack_b64(ladcp_path)
        if ladcp_exists
        else None,
    }

    env = Environment(autoescape=True)
    html = env.from_string(_STATION_TEMPLATE).render(**ctx)
    out_file.write_text(html, encoding="utf-8")
    ds.close()
    return out_file


def _extract_cast_id(stem: str) -> tuple[int, str] | None:
    """Extract ``(cast_num, cast_suffix)`` from a NC file stem.

    Handles directly-appended suffixes (``mixsed2_004b``) and
    underscore-separated suffixes (``mixsed2_004_b``), while ignoring
    cruise/leg numbers earlier in the stem (e.g. ``142`` in
    ``msm_142_1_001_1sec``).  Returns ``None`` if no 3+-digit group is found.
    """
    matches = re.findall(r"_(\d{3,})([a-z]*)(?=_|$)", stem)
    if not matches:
        return None
    cast_num_str, cast_suffix = matches[-1]
    if not cast_suffix:
        m = re.search(rf"_{re.escape(cast_num_str)}_([a-z]+)$", stem)
        if m:
            cast_suffix = m.group(1)
    return int(cast_num_str), cast_suffix


def _cast_id_from_path(nc_path: Path) -> tuple[int, str]:
    """Return ``(cast_num, cast_suffix)`` from a cast filename.

    Uses the last 3+-digit group in the stem as the cast number so that
    cruise/leg numbers earlier in the name (e.g. ``142`` in
    ``msm_142_1_001_1sec.nc``) are not confused with cast numbers.
    Letter suffixes directly appended (``004b``) or underscore-separated
    (``004_b``) at the very end of the stem are both handled.
    Returns ``(0, "")`` if no 3+-digit group is found.
    """
    return _extract_cast_id(nc_path.stem) or (0, "")


def _cast_num_from_path(nc_path: Path) -> int:
    """Return the integer cast number from a filename like ``mixsed2_042.nc``.

    Deprecated: use :func:`_cast_id_from_path` to also retrieve the suffix.
    """
    return _cast_id_from_path(nc_path)[0]
