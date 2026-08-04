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
from ctdreport._version import __version__ as _VERSION
from ctdreport.analysis import (
    _add_teos10,
    _find_cast_end,
    _find_ladcp_file,
    _find_soak_end,
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
    _make_ts_density_ladcp_b64,
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
<title>Cast {{ cast_num }} — {{ cruise }}</title>
<style>
  :root {
    --ocean: #1a3a5c;
    --seafoam: #e8f4f8;
    --accent: #2e86ab;
    --text: #1a1a2e;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #f5f7fa; color: var(--text); }
  header {
    background: var(--ocean); color: #fff; padding: 1rem 1.5rem;
    display: flex; align-items: center; justify-content: space-between;
  }
  header h1 { font-size: 1.3rem; }
  header .meta { font-size: 0.85rem; opacity: 0.8; margin-top: 0.25rem; }
  nav { background: var(--seafoam); padding: 0.5rem 1.5rem; border-bottom: 1px solid #cdd8e3;
        display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.4rem; }
  nav .breadcrumb a { color: var(--ocean); text-decoration: none; font-size: 0.9rem; margin-right: 0.3rem; }
  nav .breadcrumb a:hover { text-decoration: underline; }
  nav .breadcrumb span { color: #888; font-size: 0.9rem; margin-right: 0.3rem; }
  nav .quicklinks { display: flex; gap: 0.4rem; flex-wrap: wrap; }
  nav .quicklinks a {
    color: var(--ocean); text-decoration: none; font-size: 0.8rem;
    border: 1px solid #cdd8e3; border-radius: 999px; padding: 0.15rem 0.6rem;
    background: #fff;
  }
  nav .quicklinks a:hover { background: var(--seafoam); }
  .btn {
    display: inline-block; background: var(--ocean); color: #fff;
    padding: 0.3rem 0.85rem; border-radius: 999px; text-decoration: none;
    font-size: 0.8rem; margin: 0.2rem;
  }
  .btn:hover { background: var(--accent); }
  .btn-prev { background: #4a6fa5; }
  .btn-next { background: #4a6fa5; }
  .card {
    background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    padding: 1.25rem; margin: 1rem 1.5rem;
  }
  .card-header {
    display: flex; align-items: baseline; justify-content: space-between;
    margin-bottom: 0.75rem;
  }
  .card-header h2 { font-size: 1rem; color: var(--ocean); }
  .jump { font-size: 0.75rem; color: #888; text-decoration: none; }
  .jump:hover { color: var(--ocean); }
  .plots { display: flex; flex-wrap: wrap; gap: 1rem; margin-top: 0.25rem; align-items: flex-start; }
  .plots img { width: auto; border-radius: 4px; }
  /* Row 1 profile widths */
  .fig-profile { width: 35%; max-height: 550px; height: auto; flex-shrink: 0; }
  .fig-profile-ladcp { width: 65%; max-height: 900px; height: auto; flex-shrink: 0; }
  /* Map + T-S stacked column to the right of the profile */
  .fig-stack { display: flex; flex-direction: column; gap: 0.75rem; flex: 1; min-width: 0; align-items: flex-start; }
  .fig-stack img { max-height: 320px; width: auto; border-radius: 4px; }
  /* Shared constraint for all multi-panel figures (aux, CT/SA/σ₀, diagnostics) */
  .fig-panel { max-height: 420px; }
  figure { margin: 0; display: inline-block; }
  figcaption { font-size: 0.78rem; color: #555; margin-top: 0.25rem; max-width: 30ch; }
  footer { text-align: center; padding: 1rem; font-size: 0.75rem; color: #999; }
  .cast-notes { margin: 0.75rem 1.5rem 0; }
  .cast-note {
    background: #fff3cd; border-left: 4px solid #e6ac00; border-radius: 4px;
    padding: 0.5rem 1rem; margin-bottom: 0.4rem; font-size: 0.87rem; color: #5a4200;
  }
  details.sensor-details { margin: 0.5rem 1.5rem 0; }
  details.sensor-details summary {
    cursor: pointer; font-size: 0.82rem; color: #555; user-select: none;
    padding: 0.2rem 0;
  }
  .sensor-table { border-collapse: collapse; font-size: 0.8rem; margin-top: 0.4rem; }
  .sensor-table th, .sensor-table td {
    padding: 0.2rem 0.75rem 0.2rem 0; text-align: left; vertical-align: top;
  }
  .sensor-table th { color: var(--ocean); font-weight: 600; border-bottom: 1px solid #cdd8e3; }
</style>
</head>
<body>
<div id="top"></div>

<header>
  <div>
    <h1>Cast {{ cast_num }} — {{ cruise }}</h1>
    <div class="meta">
      {{ datetime_str }} &nbsp;·&nbsp; {{ lat_str }}, {{ lon_str }} &nbsp;·&nbsp; max depth {{ max_depth_str }}
      {% if ladcp_configured and not ladcp_available %}&nbsp;·&nbsp; <span style="color:#f5a623;font-weight:600;">LADCP not processed</span>{% endif %}
    </div>
  </div>
  <div>
    {% if prev_num %}<a class="btn btn-prev" href="cast_{{ prev_num }}.html">← {{ prev_num }}</a>{% endif %}
    {% if next_num %}<a class="btn btn-next" href="cast_{{ next_num }}.html">{{ next_num }} →</a>{% endif %}
  </div>
</header>

<nav>
  <div class="breadcrumb">
    <a href="../index.html">Index</a> <span>›</span>
    <a href="../station_index.html">Stations</a> <span>›</span>
    <span>Cast {{ cast_num }}</span>
  </div>
  <div class="quicklinks">
    <a href="#s-overview">Overview</a>
    <a href="#s-profiles">Physics</a>
    <a href="#s-aux">Biogeochemistry</a>
    <a href="#s-ts">T–S diagram</a>
    <a href="#s-stability">Stability</a>
    <a href="#s-diagnostics">Diagnostics</a>
    {% if fig_ladcp_bottomtrack_b64 %}<a href="#s-ladcp">LADCP ▼</a>{% endif %}
  </div>
</nav>

{% if trim_note %}
<div style="background:#fff3cd;border-left:4px solid #e6ac00;border-radius:4px;
            padding:0.6rem 1rem;margin:0.75rem 1.5rem 0;font-size:0.87rem;color:#5a4200;">
  ⚠ {{ trim_note }}
</div>
{% endif %}

{% if cast_notes %}
<div class="cast-notes">
  {% for note in cast_notes %}
  <p class="cast-note">⚠ {{ note }}</p>
  {% endfor %}
</div>
{% endif %}

{% if sensor_info %}
<details class="sensor-details">
  <summary>Sensors ({{ sensor_info | length }})</summary>
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

<!-- Row 1: CT/SA/σ₀ [+ LADCP U/V if available] | T–S up/down | station map -->
<div class="card" id="s-overview">
  <div class="card-header">
    <h2>Overview</h2>
    <a class="jump" href="#top">↑ top</a>
  </div>
  <div class="plots">
    {% if fig_ts_density_b64 %}
    <img class="{% if ladcp_available %}fig-profile-ladcp{% else %}fig-profile{% endif %}"
         src="data:image/png;base64,{{ fig_ts_density_b64 }}" alt="CT/SA/σ₀ profile">
    {% endif %}
    <div class="fig-stack">
      {% if fig_station_map_b64 %}<img src="data:image/png;base64,{{ fig_station_map_b64 }}" alt="Station map">{% endif %}
      {% if fig_ts_updown_b64 %}<img src="data:image/png;base64,{{ fig_ts_updown_b64 }}" alt="T–S down vs up">{% endif %}
    </div>
  </div>
</div>

<!-- Row 2: CT | SA | σ₀ triple-panel profiles -->
{% if fig_ct_sa_sigma0_b64 %}
<div class="card" id="s-profiles">
  <div class="card-header">
    <h2>Physics</h2>
    <a class="jump" href="#top">↑ top</a>
  </div>
  <div class="plots">
    <figure>
      <img class="fig-panel" src="data:image/png;base64,{{ fig_ct_sa_sigma0_b64 }}" alt="CT · SA · σ₀ profiles">
      <figcaption>CT, SA, σ₀ vs pressure. Downcast in colour; upcast in grey.</figcaption>
    </figure>
  </div>
</div>
{% endif %}

<!-- Row 3: O2, fluorescence, turbidity -->
{% if fig_aux_b64 %}
<div class="card" id="s-aux">
  <div class="card-header">
    <h2>Biogeochemistry</h2>
    <a class="jump" href="#top">↑ top</a>
  </div>
  <div class="plots">
    <img class="fig-panel" src="data:image/png;base64,{{ fig_aux_b64 }}" alt="Auxiliary profiles">
  </div>
</div>
{% endif %}

<!-- Row 4: T-S diagram coloured by O2 saturation -->
{% if fig_ts_diagram_b64 %}
<div class="card" id="s-ts">
  <div class="card-header">
    <h2>T–S diagram (coloured by O₂ saturation)</h2>
    <a class="jump" href="#top">↑ top</a>
  </div>
  <div class="plots">
    <img src="data:image/png;base64,{{ fig_ts_diagram_b64 }}" alt="T-S diagram">
  </div>
</div>
{% endif %}

<!-- Row 5: stability -->
{% if fig_stability_b64 %}
<div class="card" id="s-stability">
  <div class="card-header">
    <h2>Stability (N² and Turner angle)</h2>
    <a class="jump" href="#top">↑ top</a>
  </div>
  <div class="plots">
    <img src="data:image/png;base64,{{ fig_stability_b64 }}" alt="Stability">
  </div>
</div>
{% endif %}

<!-- Row 6: diagnostic figures -->
{% if fig_sensor_diff_b64 or fig_pressure_time_b64 or fig_updown_diff_b64 %}
<div class="card" id="s-diagnostics">
  <div class="card-header">
    <h2>Diagnostics</h2>
    <a class="jump" href="#top">↑ top</a>
  </div>
  <div class="plots">
    {% if fig_pressure_time_b64 %}
    <figure>
      <img src="data:image/png;base64,{{ fig_pressure_time_b64 }}" alt="Pressure vs time">
      <figcaption>Cast trajectory: pressure vs elapsed time. Shows descent, bottom stop, and ascent.</figcaption>
    </figure>
    {% endif %}
    {% if fig_sensor_diff_b64 %}
    <figure>
      <img class="fig-panel" src="data:image/png;base64,{{ fig_sensor_diff_b64 }}" alt="Sensor 1 − Sensor 2">
      <figcaption>Primary minus secondary sensor (full cast). T₁−T₂ in blue, S₁−S₂ in orange. Ideal: scatter around zero with ±0.01 spread.</figcaption>
    </figure>
    {% endif %}
    {% if fig_updown_diff_b64 %}
    <figure>
      <img class="fig-panel" src="data:image/png;base64,{{ fig_updown_diff_b64 }}" alt="Down − up cast differences">
      <figcaption>Downcast minus upcast on a 1-dbar grid (ΔCT, ΔSA, Δσ₀). Measures hysteresis from pump lag or sensor response time.</figcaption>
    </figure>
    {% endif %}
  </div>
</div>
{% endif %}

<!-- Row 7: LADCP bottom track -->
{% if fig_ladcp_bottomtrack_b64 %}
<div class="card" id="s-ladcp">
  <div class="card-header">
    <h2>LADCP bottom track</h2>
    <a class="jump" href="#top">↑ top</a>
  </div>
  <div class="plots">
    <img class="fig-panel" src="data:image/png;base64,{{ fig_ladcp_bottomtrack_b64 }}" alt="LADCP bottom track">
  </div>
</div>
{% endif %}

"""
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
    t0 = str(ds["time"].values[0])[:16].replace("T", " ")
    cruise = ds.attrs.get("cruise", "odb2026")

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
        "datetime_str": t0,
        "lat_str": f"{lat:.4f}°N",
        "lon_str": f"{lon:.4f}°E",
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
        # Row 1 — use LADCP layout whenever LADCP is configured (file may be absent)
        "fig_ts_density_b64": (
            _make_ts_density_ladcp_b64(ds, ladcp_path)
            if ladcp_dir is not None
            else _make_ts_density_b64(ds)
        ),
        "fig_station_map_b64": _make_station_map_b64(lat, lon, all_meta),
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
