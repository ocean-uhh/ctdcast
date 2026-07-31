"""Tier-2: generate a per-cast HTML report page."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr
from jinja2 import Environment

from ctd_report import _templates as _tmpl
from ctd_report._analysis import _add_teos10
from ctd_report._plots import (
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
from ctd_report._version import __version__ as _VERSION

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
  footer { text-align: center; padding: 1rem; font-size: 0.75rem; color: #999; }
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
    <img class="fig-panel" src="data:image/png;base64,{{ fig_ct_sa_sigma0_b64 }}" alt="CT · SA · σ₀ profiles">
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
    {% if fig_pressure_time_b64 %}<img src="data:image/png;base64,{{ fig_pressure_time_b64 }}" alt="Pressure vs time">{% endif %}
    {% if fig_sensor_diff_b64 %}<img class="fig-panel" src="data:image/png;base64,{{ fig_sensor_diff_b64 }}" alt="Sensor 1 − Sensor 2">{% endif %}
    {% if fig_updown_diff_b64 %}<img class="fig-panel" src="data:image/png;base64,{{ fig_updown_diff_b64 }}" alt="Down − up cast differences">{% endif %}
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
    prev_num: int | None = None,
    next_num: int | None = None,
    force: bool = False,
    ladcp_dir: Path | None = None,
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
    prev_num:
        Cast number of the previous cast for nav links (or None).
    next_num:
        Cast number of the next cast for nav links (or None).
    force:
        Overwrite existing file if True.
    ladcp_dir:
        Directory containing processed LADCP ``.mat`` files named ``NNN.mat``.
        If None or if the matching file does not exist, LADCP panels are omitted.

    Returns
    -------
    Path to the written HTML file, or None on failure.
    """
    cast_num = _cast_num_from_path(nc_path)
    out_file = out_dir / "stations" / f"cast_{cast_num:03d}.html"
    if out_file.exists() and not force:
        return out_file

    out_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        ds = xr.open_dataset(nc_path, decode_timedelta=False, engine="netcdf4").load()
        ds = _add_teos10(ds)
    except Exception:  # noqa: BLE001
        return None

    lat = float(np.nanmedian(ds["latitude"].values))
    lon = float(np.nanmedian(ds["longitude"].values))
    max_depth = float(np.nanmax(ds["pressure"].values))
    t0 = str(ds["time"].values[0])[:16].replace("T", " ")
    cruise = ds.attrs.get("cruise", "odb2026")

    prev_str = f"{prev_num:03d}" if prev_num is not None else ""
    next_str = f"{next_num:03d}" if next_num is not None else ""

    ladcp_path = ladcp_dir / f"{cast_num:03d}.mat" if ladcp_dir is not None else None
    ladcp_exists = ladcp_path is not None and ladcp_path.exists()

    ctx: dict[str, Any] = {
        "cast_num": f"{cast_num:03d}",
        "cruise": cruise,
        "datetime_str": t0,
        "lat_str": f"{lat:.4f}°N",
        "lon_str": f"{lon:.4f}°E",
        "max_depth_str": f"{max_depth:.0f} dbar",
        "prev_num": prev_str,
        "next_num": next_str,
        "ladcp_configured": ladcp_dir is not None,
        "ladcp_available": ladcp_exists,
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


def _cast_num_from_path(nc_path: Path) -> int:
    """Return the integer cast number from a filename like ``mixsed2_042.nc``."""
    m = re.search(r"_(\d+)(_b)?\.nc$", nc_path.name)
    if m:
        return int(m.group(1))
    return 0
