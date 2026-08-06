"""Tier-3: entry point — generates index, stations list, and sections list pages."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import xarray as xr
import yaml
from jinja2 import Environment

from ctdcast._version import __version__ as _VERSION
from ctdcast.analysis.bathymetry import interpolate_bathy_at_casts
from ctdcast.analysis.geometry import along_track_km
from ctdcast.analysis.teos10 import add_aou, add_teos10_profiles
from ctdcast.identity import compact_cast_list
from ctdcast.plots import (
    GEBCO_PATH,
    _make_all_sections_map_b64,
    _make_cruise_map_b64,
    _make_overview_panel_b64,
    _make_section_ts_histogram_b64,
    _make_station_map_b64,  # noqa: F401 — kept for backward compat
)
from ctdcast.readers.ladcp import find_ladcp_file
from ctdcast.reports import _chrome as _tmpl
from ctdcast.reports._cast import _extract_cast_id, generate_station_page
from ctdcast.reports._css import _JS_TOP_LINKS, SHARED_CSS
from ctdcast.reports._section import _expand_cast_numbers, generate_section_page
from ctdcast.reports._timeseries import generate_timeseries_page

# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

_INDEX_TEMPLATE = (
    """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CTD Report — {{ cruise }}</title>
<style>
"""
    + SHARED_CSS
    + """\
</style>
</head>
<body>
<div id="top"></div>

<div class="masthead" style="background:#2980b9;">
  <div class="masthead-header">
    <h1>{{ cruise }}</h1>
    <span class="masthead-type">CTD Report</span>
  </div>
  <p class="sub" style="margin:0 0 0.6rem; text-align:right;">generated {{ generated_at }}</p>
  <div style="margin-top:0.65rem;margin-bottom:0.5rem">
    <span style="font-size:0.72rem;opacity:0.75;margin-right:0.3rem;">Pages:</span>
    <a href="index.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#2980b9;opacity:0.55">Summary</a>
    <a href="station_index.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#1a3a5c">Stations</a>
    <a href="sections.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#8e44ad">Sections</a>
    <a href="timeseries.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#27ae60">Timeseries</a>
    <a href="leaflet.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#EE3377">Interactive</a>
  </div>
  <dl class="meta-grid">
    <div><dt>Cruise</dt><dd>{{ cruise }}</dd></div>
    {% if ship %}<div><dt>Ship</dt><dd>{{ ship }}</dd></div>{% endif %}
    {% if project %}<div><dt>Project</dt><dd>{{ project }}</dd></div>{% endif %}
    {% if date_start %}<div><dt>Departure</dt><dd>{{ date_start }}</dd></div>{% endif %}
    {% if date_end %}<div><dt>Arrival</dt><dd>{{ date_end }}</dd></div>{% endif %}
    {% if n_days %}<div><dt>Duration</dt><dd>{{ n_days }} d</dd></div>{% endif %}
    <div><dt>CTD casts</dt><dd>{{ n_casts }}</dd></div>
    <div><dt>Sections</dt><dd>{{ n_sections }}</dd></div>
    <div><dt>Max depth</dt><dd>{{ max_depth_str }}</dd></div>
  </dl>
</div>

<div class="jump-nav">
  {% if fig_map_b64 %}<a href="#s-map">Map</a>{% endif %}
  {% if physics_panels | selectattr("b64") | list %}<a href="#s-hydro">Hydrography</a>{% endif %}
  {% if biogeo_panels | selectattr("b64") | list %}<a href="#s-biogeo">Biogeochemistry</a>{% endif %}
  {% if ts_b64 %}<a href="#s-ts">T–S diagram</a>{% endif %}
</div>

{% if fig_map_b64 %}
<h2 id="s-map">Map</h2>
<div class="fig-row" style="justify-content:center;">
  <figure class="slot-half">
    <img src="data:image/png;base64,{{ fig_map_b64 }}" alt="Station map">
  </figure>
</div>
{% endif %}

{% if physics_panels | selectattr("b64") | list %}
<h2 id="s-hydro">Hydrography</h2>
{% for panel in physics_panels %}{% if panel.b64 %}
<p class="note">{{ panel.title }}</p>
<div class="fig-row">
  <figure class="slot-full">
    <img src="data:image/png;base64,{{ panel.b64 }}" alt="{{ panel.title }}">
  </figure>
</div>
{% endif %}{% endfor %}
{% endif %}

{% if biogeo_panels | selectattr("b64") | list %}
<h2 id="s-biogeo">Biogeochemistry</h2>
{% for panel in biogeo_panels %}{% if panel.b64 %}
<p class="note">{{ panel.title }}</p>
<div class="fig-row">
  <figure class="slot-full">
    <img src="data:image/png;base64,{{ panel.b64 }}" alt="{{ panel.title }}">
  </figure>
</div>
{% endif %}{% endfor %}
{% endif %}

{% if ts_b64 %}
<h2 id="s-ts">T-S diagram</h2>
<p class="note">All downcast profiles</p>
<div class="fig-row">
  <figure class="slot-third">
    <img src="data:image/png;base64,{{ ts_b64 }}" alt="Cruise T-S diagram">
  </figure>
</div>
{% endif %}

"""
    + _tmpl.FOOTER_TAIL
    + _JS_TOP_LINKS
)


_STATIONS_TEMPLATE = (
    """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Station index — {{ cruise }}</title>
<style>
"""
    + SHARED_CSS
    + """\
/* Stations index */
table { width: 100%; border-collapse: collapse; font-size: 0.88rem; white-space: nowrap; overflow-x: auto; display: block; }
th {
  background: var(--ocean); color: #fff; padding: 0.5rem 0.75rem;
  text-align: left; position: sticky; top: 0; z-index: 1;
}
td { padding: 0.42rem 0.75rem; border-bottom: 1px solid #eee; vertical-align: middle; }
tbody tr { cursor: pointer; }
tbody tr:hover td { background: var(--seafoam); }
  .cast-link { color: var(--ocean); font-weight: 600; text-decoration: none; }
  .cast-link:hover { text-decoration: underline; }
  .filename { font-family: monospace; font-size: 0.82rem; color: #444; }
  .depth-pill {
    display: inline-block; padding: 0.18rem 0.55rem; border-radius: 999px;
    font-size: 0.78rem; font-weight: 600; white-space: nowrap;
  }
  .pill-btn {
    display: inline-block; padding: 0.18rem 0.55rem; border-radius: 999px;
    font-size: 0.75rem; text-decoration: none; white-space: nowrap; margin: 0.1rem 0.05rem;
  }
  .pill-profile { background: #1a3a5c; color: #fff; }
  .pill-section { background: #2c6e49; color: #fff; }
  .pill-btn:hover { opacity: 0.85; }
  .ladcp-yes { display:inline-block; padding:0.18rem 0.5rem; border-radius:999px; font-size:0.75rem; font-weight:600; background:#2c6e49; color:#fff; }
  .ladcp-no  { display:inline-block; padding:0.18rem 0.5rem; border-radius:999px; font-size:0.75rem; font-weight:600; background:#c0392b; color:#fff; }
</style>
</head>
<body>
<div id="top"></div>

<div class="masthead" style="background:#1a3a5c;">
  <div class="masthead-header">
    <h1>{{ cruise }}</h1>
    <span class="masthead-type">Station index</span>
  </div>
  <p class="sub" style="margin:0 0 0.6rem; text-align:right;">generated {{ generated_at }}</p>
  <div style="margin-top:0.65rem;margin-bottom:0.5rem">
    <span style="font-size:0.72rem;opacity:0.75;margin-right:0.3rem;">Pages:</span>
    <a href="index.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#2980b9">Summary</a>
    <a href="station_index.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#1a3a5c;opacity:0.55">Stations</a>
    <a href="sections.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#8e44ad">Sections</a>
    <a href="timeseries.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#27ae60">Timeseries</a>
    <a href="leaflet.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#EE3377">Interactive</a>
  </div>
  <dl class="meta-grid">
    <div><dt>Cruise</dt><dd>{{ cruise }}</dd></div>
    {% if ship %}<div><dt>Ship</dt><dd>{{ ship }}</dd></div>{% endif %}
    {% if date_start %}<div><dt>Departure</dt><dd>{{ date_start }}</dd></div>{% endif %}
    {% if date_end %}<div><dt>Arrival</dt><dd>{{ date_end }}</dd></div>{% endif %}
    {% if duration_days %}<div><dt>Duration</dt><dd>{{ duration_days }} d</dd></div>{% endif %}
    <div><dt>CTD casts</dt><dd>{{ stations|length }}</dd></div>
    {% if max_depth_str %}<div><dt>Max depth</dt><dd>{{ max_depth_str }}</dd></div>{% endif %}
  </dl>
</div>

{% if cruise_map_b64 %}
<h2 id="s-map">Map</h2>
<div class="fig-row">
  <figure class="slot-third">
    <img src="data:image/png;base64,{{ cruise_map_b64 }}" alt="All cast positions">
  </figure>
</div>
{% endif %}

<h2 id="s-table">Casts</h2>
<table>
    <thead>
      <tr>
        <th>Cast</th>
        <th>File</th>
        <th>Start (UTC)</th>
        <th>Latitude</th>
        <th>Longitude</th>
        <th>Depth</th>
        {% if ladcp_configured %}<th>LADCP</th>{% endif %}
        <th>Links</th>
      </tr>
    </thead>
    <tbody>
    {% for s in stations %}
      <tr onclick="window.location='stations/cast_{{ s.cast_num }}.html'">
        <td><a class="cast-link" href="stations/cast_{{ s.cast_num }}.html">{{ s.cast_num }}</a></td>
        <td class="filename">{{ s.filename }}</td>
        <td>{{ s.time_start_str }}</td>
        <td>{{ s.lat_str }}</td>
        <td>{{ s.lon_str }}</td>
        <td><span class="depth-pill" style="background:{{ s.depth_bg }};color:{{ s.depth_fg }};">{{ s.max_depth_str }} dbar</span></td>
        {% if ladcp_configured %}
        <td>{% if s.ladcp_has %}<span class="ladcp-yes">✓</span>{% else %}<span class="ladcp-no">–</span>{% endif %}</td>
        {% endif %}
        <td>
          <a class="pill-btn pill-profile" href="stations/cast_{{ s.cast_num }}.html">Profile</a>
          {% for sec in s.sections %}
          <a class="pill-btn" style="background:{{ sec.color }};color:#fff;" href="sections/section_{{ sec.name }}.html">{{ sec.name }}</a>
          {% endfor %}
          {% for ts in s.timeseries %}
          <a class="pill-btn" style="background:{{ ts.color }};color:#fff;" href="timeseries/timeseries_{{ ts.name }}.html">{{ ts.name }}</a>
          {% endfor %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

"""
    + _tmpl.FOOTER_TAIL
    + _JS_TOP_LINKS
)


_SECTIONS_TEMPLATE = (
    """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sections — {{ cruise }}</title>
<style>
"""
    + SHARED_CSS
    + """\
/* Sections index */
.sec-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 1rem; margin-bottom: 1.5rem;
}
.sec-card {
  background: #fff; border-radius: 8px; border-left: 4px solid #1a3a5c;
  padding: 1.1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.sec-card h3 { font-size: 1rem; color: var(--ocean); margin: 0 0 0.25rem; }
.sec-card .desc { font-size: 0.85rem; color: #555; margin-bottom: 0.5rem; }
.sec-card .info { font-size: 0.82rem; color: #777; }
.btn-card {
  display: inline-block; background: #8e44ad; color: #fff;
  padding: 0.25rem 0.8rem; border-radius: 999px; text-decoration: none;
  font-size: 0.8rem; margin-top: 0.6rem;
}
.btn-card:hover { opacity: 0.85; }
.ladcp-yes { display:inline-block; padding:0.18rem 0.5rem; border-radius:999px; font-size:0.75rem; font-weight:600; background:#2c6e49; color:#fff; }
.ladcp-no  { display:inline-block; padding:0.18rem 0.5rem; border-radius:999px; font-size:0.75rem; font-weight:600; background:#c0392b; color:#fff; }
</style>
</head>
<body>
<div id="top"></div>

<div class="masthead" style="background:#8e44ad;">
  <div class="masthead-header">
    <h1>{{ cruise }}</h1>
    <span class="masthead-type">Section index</span>
  </div>
  <p class="sub" style="margin:0 0 0.6rem; text-align:right;">generated {{ generated_at }}</p>
  <div style="margin-top:0.65rem;margin-bottom:0.5rem">
    <span style="font-size:0.72rem;opacity:0.75;margin-right:0.3rem;">Pages:</span>
    <a href="index.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#2980b9">Summary</a>
    <a href="station_index.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#1a3a5c">Stations</a>
    <a href="sections.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#8e44ad;opacity:0.55">Sections</a>
    <a href="timeseries.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#27ae60">Timeseries</a>
    <a href="leaflet.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#EE3377">Interactive</a>
  </div>
  <dl class="meta-grid">
    <div><dt>Cruise</dt><dd>{{ cruise }}</dd></div>
    {% if ship %}<div><dt>Ship</dt><dd>{{ ship }}</dd></div>{% endif %}
    {% if date_start %}<div><dt>Departure</dt><dd>{{ date_start }}</dd></div>{% endif %}
    {% if date_end %}<div><dt>Arrival</dt><dd>{{ date_end }}</dd></div>{% endif %}
    {% if duration_days %}<div><dt>Duration</dt><dd>{{ duration_days }} d</dd></div>{% endif %}
    <div><dt>Sections</dt><dd>{{ sections|length }}</dd></div>
    {% if casts_range %}<div><dt>Casts per section</dt><dd>{{ casts_range }}</dd></div>{% endif %}
    {% if dist_range %}<div><dt>Distance range</dt><dd>{{ dist_range }}</dd></div>{% endif %}
  </dl>
</div>

{% if sections_map_b64 %}
<h2 id="s-map">Section tracks</h2>
<div class="fig-row">
  <figure class="slot-third">
    <img src="data:image/png;base64,{{ sections_map_b64 }}" alt="Sections overview map">
  </figure>
</div>
{% endif %}

<h2 id="s-list">Sections</h2>
<div class="sec-grid">
{% for sec in sections %}
<div class="sec-card" style="border-left-color:{{ sec.color }}">
  <h3>{{ sec.name }}</h3>
  <div class="desc">{{ sec.description }}</div>
  <div class="info">{{ sec.n_casts }} casts &nbsp;·&nbsp; {{ sec.cast_range }}</div>
  {% if ladcp_configured %}
  <div style="margin-top:0.4rem;">
    {% if sec.ladcp_has %}<span class="ladcp-yes">✓ LADCP</span>{% else %}<span class="ladcp-no">– LADCP</span>{% endif %}
  </div>
  {% endif %}
  {% if sec.report_exists %}
  <a class="btn-card" href="sections/section_{{ sec.name }}.html">view section →</a>
  {% else %}
  <span style="font-size:0.8rem;color:#aaa;margin-top:0.4rem;display:inline-block;">report not yet generated</span>
  {% endif %}
</div>
{% endfor %}
</div>

"""
    + _tmpl.FOOTER_TAIL
    + _JS_TOP_LINKS
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def report(
    nc_dir: Path,
    out_dir: Path,
    *,
    profiles_path: Path | None = None,
    section_yaml: Path | None = None,
    ladcp_dir: Path | None = None,
    ladcp_pattern: str | None = None,
    ship_track_nc: Path | None = None,
    generate: dict[str, bool] | None = None,
    force: bool = False,
    skip_existing: bool = False,
    section_style: str = "pcolormesh",
    timeseries_style: str = "pcolormesh",
    vmin_override: dict[str, float] | None = None,
    vmax_override: dict[str, float] | None = None,
    cruise_info: dict[str, Any] | None = None,
    cast_filter: int | list[int] | None = None,
    sal_range: tuple[float, float] | None = None,
    trim_soak: bool = False,
    dbar_step: int = 1,
) -> None:
    """Generate the full ctdcast HTML report suite.

    Parameters
    ----------
    nc_dir:
        Directory containing per-cast ``.nc`` files.
    out_dir:
        Root output directory.
    profiles_path:
        Path to compiled ``profiles.nc``. Required for section and time series pages.
    section_yaml:
        Path to the sections/timeseries YAML file (``ctd_sections.yaml``).
    ladcp_dir:
        Directory containing processed LADCP ``.mat`` files named ``NNN.mat``
        or ``NNNb.mat`` (letter-suffix variants supported).
    ladcp_pattern:
        Optional filename glob for non-standard LADCP naming, e.g.
        ``"msm_142_1_*.mat"``.  The ``*`` is replaced with the zero-padded
        cast number.  See :func:`~ctdcast.readers.ladcp.find_ladcp_file`.
    ship_track_nc:
        Path to a ship-track netCDF for the Leaflet map background line.
    generate:
        Dict of booleans controlling which page types to build.
        Keys: ``"stations"``, ``"sections"``, ``"timeseries"``, ``"index"``, ``"map"``.
        Missing keys default to ``True``.
    force:
        Regenerate all pages regardless of file modification times.
    skip_existing:
        If True, skip any page whose output HTML already exists, regardless of
        whether the source files are newer.  Use this to fill in only missing
        pages without touching anything already generated.  Takes precedence over
        the mtime check but is overridden by ``force``.
    section_style:
        ``"pcolormesh"`` or ``"contourf"`` for section figures.
    timeseries_style:
        ``"pcolormesh"`` or ``"contourf"`` for time series figures.
    vmin_override, vmax_override:
        Per-variable colormap limit overrides (e.g. ``{"SA": 34.5}``).
    cruise_info:
        Cruise metadata dict (from the ``cruise_info:`` block in ``config.yaml``).
    cast_filter:
        If set, rebuild only the station page for this cast number
        (implies ``generate={"stations": True, rest False}``).
    sal_range:
        ``(sal_min, sal_max)`` — records with ``salinity_1`` outside this
        range are excluded from all station page plots.  The NC files are
        not modified.  Excluded record count is shown in each page header.
    trim_soak:
        If True, apply pre-soak detection on each cast: cut the first 60 s
        (pump activation) and any records up to the last near-surface record
        after pump-on.  Passed through to :func:`~ctdcast.reports._cast.generate_station_page`.
    dbar_step:
        Subsample the pressure axis by this step for section and timeseries
        plots (default 1, full 1-dbar resolution).  ``build_profiles()``
        always stores 1-dbar data; this controls plot-time resolution only.

    """
    gen: dict[str, bool] = {
        "stations": True,
        "sections": True,
        "timeseries": True,
        "index": True,
        "map": True,
    }
    if generate is not None:
        gen.update(generate)
    if cast_filter is not None:
        gen = {
            "stations": True,
            "sections": False,
            "timeseries": False,
            "index": False,
            "map": False,
        }

    vmin_override = vmin_override or {}
    vmax_override = vmax_override or {}
    cruise_info = cruise_info or {}

    out_dir.mkdir(parents=True, exist_ok=True)

    cast_files = _select_cast_files(nc_dir)
    if not cast_files:
        print(f"No cast .nc files found in {nc_dir}")
        return

    print(f"Found {len(cast_files)} cast files")
    all_meta_raw = [_read_cast_meta(p) for p in cast_files]
    all_meta = sorted(
        [m for m in all_meta_raw if m is not None],
        key=lambda m: m["time_start"],
        reverse=True,
    )
    cruise = all_meta[0].get("cruise", "UNK") if all_meta else "UNK"

    # Pre-load GEBCO for the cruise area into memory so every map figure
    # subsets from numpy arrays rather than reopening the file from disk.
    from ctdcast import plots as _plots_mod
    from ctdcast.analysis.bathymetry import preload_gebco

    _gebco_path = _plots_mod.GEBCO_PATH
    if _gebco_path is not None and all_meta:
        _cast_lats = [
            m["lat"] for m in all_meta if np.isfinite(m.get("lat", float("nan")))
        ]
        _cast_lons = [
            m["lon"] for m in all_meta if np.isfinite(m.get("lon", float("nan")))
        ]
        if _cast_lats:
            _t0 = perf_counter()
            preload_gebco(
                _gebco_path,
                float(min(_cast_lats)),
                float(max(_cast_lats)),
                float(min(_cast_lons)),
                float(max(_cast_lons)),
            )
            print(f"  GEBCO preloaded ({perf_counter() - _t0:.1f}s)")

    # Load sections YAML once — needed for cast_notes before stations are written.
    yaml_data: dict[str, Any] = {}
    if section_yaml and section_yaml.exists():
        with open(section_yaml) as f:
            yaml_data = yaml.safe_load(f) or {}

    # Build cruise-wide cast_notes mapping from all sections and timeseries.
    all_cast_notes: dict[int, list[str]] = {}
    for _grp in ("sections", "timeseries"):
        for _cfg in (yaml_data.get(_grp) or {}).values():
            if not isinstance(_cfg, dict):
                continue
            for _cn, _note in (_cfg.get("cast_notes") or {}).items():
                _cn_int = int(_cn)
                all_cast_notes.setdefault(_cn_int, [])
                if _note and _note not in all_cast_notes[_cn_int]:
                    all_cast_notes[_cn_int].append(str(_note))

    if gen["stations"]:
        _t0 = perf_counter()
        cast_num_strs = [m["cast_num_str"] for m in all_meta]
        _cast_set: set[int] | None = (
            {cast_filter}
            if isinstance(cast_filter, int)
            else set(cast_filter)
            if cast_filter is not None
            else None
        )
        targets = [
            m for m in all_meta if _cast_set is None or m["cast_num"] in _cast_set
        ]
        if _cast_set is not None and not targets:
            print(f"Cast(s) {cast_filter} not found in {nc_dir}")
            return
        for meta in targets:
            orig_i = all_meta.index(meta)
            prev_cast_str = cast_num_strs[orig_i - 1] if orig_i > 0 else None
            next_cast_str = (
                cast_num_strs[orig_i + 1] if orig_i < len(all_meta) - 1 else None
            )
            _expected = out_dir / "stations" / f"cast_{meta['cast_num_str']}.html"
            _was_new = not _expected.exists()
            _html_mtime_str = _fmt_mtime(
                _expected
            )  # capture before page is (re)written

            # Resolve LADCP mat path before the skip check so it feeds the mtime comparison.
            _mat: Path | None = None
            if ladcp_dir is not None:
                _mat = find_ladcp_file(
                    ladcp_dir, meta["cast_num"], meta["cast_suffix"], ladcp_pattern
                )

            _extra: tuple[Path, ...] = (_mat,) if _mat is not None else ()
            _skip_reason = _mtime_skip_reason(
                _expected, meta["path"], force, *_extra, skip_existing=skip_existing
            )

            _ladcp_note = ""
            if (
                _skip_reason
                and _mat is not None
                and _expected.exists()
                and b"fig-profile-ladcp" not in _expected.read_bytes()
            ):
                _ladcp_note = " — LADCP available, use --force"

            out_page = generate_station_page(
                meta["path"],
                out_dir,
                all_meta,
                prev_cast_str=prev_cast_str,
                next_cast_str=next_cast_str,
                force=force or not _skip_reason,
                ladcp_dir=ladcp_dir,
                ladcp_pattern=ladcp_pattern,
                cast_num_str=meta["cast_num_str"],
                sal_range=sal_range,
                trim_soak=trim_soak,
                cast_notes=all_cast_notes.get(meta["cast_num"]),
                cruise_info=cruise_info,
            )
            if _skip_reason:
                _status = _skip_reason + _ladcp_note
            elif out_page is None:
                _status = "FAILED"
            elif force:
                _status = "regenerated (forced)"
            elif _was_new:
                _ladcp_part = f", ladcp: {_fmt_mtime(_mat)}" if _mat else ""
                _status = (
                    f"regenerated (new) [nc: {_fmt_mtime(meta['path'])}{_ladcp_part}]"
                )
            else:
                _ladcp_part = f", ladcp: {_fmt_mtime(_mat)}" if _mat else ""
                _status = (
                    f"regenerated (source updated)"
                    f" [html: {_html_mtime_str},"
                    f" nc: {_fmt_mtime(meta['path'])}{_ladcp_part}]"
                )
            print(f"  station cast_{meta['cast_num_str']}: {_status}")
        print(f"  [stations: {perf_counter() - _t0:.1f}s]")

    sections_cfg: dict[str, Any] = yaml_data.get("sections", {})
    timeseries_cfg: dict[str, Any] = yaml_data.get("timeseries", {})

    if gen["sections"]:
        _t0 = perf_counter()
        _sec_names = list(sections_cfg.keys())
        for _sec_i, (sec_name, sec_cfg) in enumerate(sections_cfg.items()):
            _sec_prev = _sec_names[_sec_i - 1] if _sec_i > 0 else None
            _sec_next = _sec_names[_sec_i + 1] if _sec_i < len(_sec_names) - 1 else None
            _expected = out_dir / "sections" / f"section_{sec_name}.html"
            _sec_was_new = not _expected.exists()
            _sec_html_mtime_str = _fmt_mtime(_expected)
            _src = profiles_path if profiles_path is not None else _expected
            _sec_skip = _mtime_skip_reason(
                _expected, _src, force, skip_existing=skip_existing
            )
            _sec_note = ""
            if _sec_skip and ladcp_dir is not None:
                _sec_casts = _expand_cast_numbers(sec_cfg.get("cast_numbers", []))
                if (
                    any(
                        find_ladcp_file(ladcp_dir, cn, ladcp_pattern=ladcp_pattern)
                        is not None
                        for cn in _sec_casts
                    )
                    and _expected.exists()
                    and b"s-ladcp" not in _expected.read_bytes()
                ):
                    _sec_note = " — LADCP available, use --force"
            out_page = generate_section_page(
                sec_name,
                sec_cfg,
                profiles_path,
                out_dir,
                force=force or not _sec_skip,
                section_style=section_style,
                vmin_override=vmin_override,
                vmax_override=vmax_override,
                ladcp_dir=ladcp_dir,
                ladcp_pattern=ladcp_pattern,
                dbar_step=dbar_step,
                prev_name=_sec_prev,
                next_name=_sec_next,
            )
            if _sec_skip:
                _sec_status = _sec_skip + _sec_note
            elif out_page is None:
                _sec_status = "FAILED"
            elif force:
                _sec_status = "regenerated (forced)"
            elif _sec_was_new:
                _sec_status = f"regenerated (new) [src: {_fmt_mtime(_src)}]"
            else:
                _sec_status = (
                    f"regenerated (source updated)"
                    f" [html: {_sec_html_mtime_str}, src: {_fmt_mtime(_src)}]"
                )
            print(f"  section {sec_name}: {_sec_status}")
        print(f"  [sections: {perf_counter() - _t0:.1f}s]")

    if gen["timeseries"] and timeseries_cfg:
        _t0 = perf_counter()
        _ts_names = list(timeseries_cfg.keys())
        for _ts_i, (ts_name, ts_cfg) in enumerate(timeseries_cfg.items()):
            _ts_prev = _ts_names[_ts_i - 1] if _ts_i > 0 else None
            _ts_next = _ts_names[_ts_i + 1] if _ts_i < len(_ts_names) - 1 else None
            _expected = out_dir / "timeseries" / f"timeseries_{ts_name}.html"
            _ts_was_new = not _expected.exists()
            _ts_html_mtime_str = _fmt_mtime(_expected)
            _src = profiles_path if profiles_path is not None else _expected
            _ts_skip = _mtime_skip_reason(
                _expected, _src, force, skip_existing=skip_existing
            )
            _ts_note = ""
            if _ts_skip and ladcp_dir is not None:
                _ts_casts = _expand_cast_numbers(ts_cfg.get("cast_numbers", []))
                if (
                    any(
                        find_ladcp_file(ladcp_dir, cn, ladcp_pattern=ladcp_pattern)
                        is not None
                        for cn in _ts_casts
                    )
                    and _expected.exists()
                    and b"s-ladcp" not in _expected.read_bytes()
                ):
                    _ts_note = " — LADCP available, use --force"
            out_page = generate_timeseries_page(
                ts_name,
                ts_cfg,
                profiles_path,
                out_dir,
                force=force or not _ts_skip,
                section_style=timeseries_style,
                vmin_override=vmin_override,
                vmax_override=vmax_override,
                all_meta=all_meta,
                ladcp_dir=ladcp_dir,
                ladcp_pattern=ladcp_pattern,
                dbar_step=dbar_step,
                prev_name=_ts_prev,
                next_name=_ts_next,
            )
            if _ts_skip:
                _ts_status = _ts_skip + _ts_note
            elif out_page is None:
                _ts_status = "FAILED"
            elif force:
                _ts_status = "regenerated (forced)"
            elif _ts_was_new:
                _ts_status = f"regenerated (new) [src: {_fmt_mtime(_src)}]"
            else:
                _ts_status = (
                    f"regenerated (source updated)"
                    f" [html: {_ts_html_mtime_str}, src: {_fmt_mtime(_src)}]"
                )
            print(f"  timeseries {ts_name}: {_ts_status}")
        print(f"  [timeseries: {perf_counter() - _t0:.1f}s]")

    if gen["index"]:
        _t0 = perf_counter()
        _write_index(
            all_meta,
            sections_cfg,
            cruise,
            out_dir,
            force,
            profiles_path=profiles_path,
            section_style=section_style,
            vmin_override=vmin_override,
            vmax_override=vmax_override,
            cruise_info=cruise_info,
            timeseries_cfg=timeseries_cfg,
        )
        print(f"  [index.html: {perf_counter() - _t0:.1f}s]")
        _t0 = perf_counter()
        _write_stations_list(
            all_meta,
            cruise,
            out_dir,
            sections_cfg=sections_cfg,
            timeseries_cfg=timeseries_cfg,
            ladcp_dir=ladcp_dir,
            ladcp_pattern=ladcp_pattern,
            cruise_info=cruise_info,
        )
        print(f"  [station_index.html: {perf_counter() - _t0:.1f}s]")
        _t0 = perf_counter()
        _write_sections_list(
            sections_cfg,
            cruise,
            out_dir,
            all_meta=all_meta,
            ladcp_dir=ladcp_dir,
            cruise_info=cruise_info,
        )
        print(f"  [sections.html: {perf_counter() - _t0:.1f}s]")
        _t0 = perf_counter()
        _write_timeseries_list(
            timeseries_cfg,
            cruise,
            out_dir,
            all_meta=all_meta,
            ladcp_dir=ladcp_dir,
            cruise_info=cruise_info,
        )
        print(f"  [timeseries.html: {perf_counter() - _t0:.1f}s]")

    if gen["map"]:
        try:
            from ctdcast.reports._leaflet import generate_leaflet_map

            lf_out = generate_leaflet_map(
                all_meta,
                sections_cfg,
                out_dir,
                force=force,
                ship_track_nc=ship_track_nc,
            )
            print(f"  leaflet map: {'regenerated' if lf_out else 'skipped (no casts)'}")
        except Exception:  # noqa: BLE001
            import traceback

            print("  leaflet map: FAILED")
            traceback.print_exc()

    print(f"\nReport written to {out_dir}/index.html")


# ---------------------------------------------------------------------------
# Page writers
# ---------------------------------------------------------------------------

_OVERVIEW_PHYSICS_VARS: list[tuple[str, str]] = [
    ("CT", "Conservative Temperature (°C)"),
    ("SA", "Absolute Salinity (g kg⁻¹)"),
    ("sigma0", "Potential density σ₀ (kg m⁻³)"),
]

_OVERVIEW_BIOGEO_VARS: list[tuple[str, str]] = [
    ("oxygen_1", "O₂ saturation (%)"),
    ("fluorescence", "Fluorescence (mg m⁻³)"),
    ("turbidity", "Turbidity (NTU)"),
]


def _write_index(
    all_meta: list[dict[str, Any]],
    sections_cfg: dict[str, Any],
    cruise: str,
    out_dir: Path,
    force: bool,
    profiles_path: Path | None = None,
    section_style: str = "pcolormesh",
    vmin_override: dict[str, float] | None = None,
    vmax_override: dict[str, float] | None = None,
    cruise_info: dict[str, Any] | None = None,
    timeseries_cfg: dict[str, Any] | None = None,
) -> None:
    """Write index.html with header card, stats, overview map, and stacked property panels."""
    times = [m["time_start"] for m in all_meta if m.get("time_start")]
    times_str = sorted(str(t)[:10] for t in times if t)
    n_days = 0
    if len(times_str) >= 2:
        from datetime import date

        try:
            d0 = date.fromisoformat(times_str[0])  # earliest
            d1 = date.fromisoformat(times_str[-1])  # latest
            n_days = (d1 - d0).days + 1
        except ValueError:
            pass

    max_depth = max((m.get("max_depth", 0) for m in all_meta), default=0)
    ci = cruise_info or {}

    _valid_lats = [m["lat"] for m in all_meta if np.isfinite(m.get("lat", np.nan))]
    _valid_lons = [m["lon"] for m in all_meta if np.isfinite(m.get("lon", np.nan))]

    # Build combined sections+timeseries data for the map and for overview markers
    _ts_cfg = timeseries_cfg or {}
    _all_groups = {**sections_cfg, **_ts_cfg}
    sections_data_map: list[dict[str, Any]] = []
    # cast_groups: color → set of cast numbers (for overview panel top markers)
    cast_groups: dict[str, list[int]] = {}
    for grp_name, grp_cfg in _all_groups.items():
        cast_nums_grp = _expand_cast_numbers(grp_cfg.get("cast_numbers", []))
        color = grp_cfg.get("color", "#888888")
        if cast_nums_grp:
            cast_groups[color] = cast_groups.get(color, []) + list(cast_nums_grp)

    # For the index map, gather section track positions from all_meta
    cast_pos = {
        m["cast_num"]: (m["lat"], m["lon"])
        for m in all_meta
        if np.isfinite(m.get("lat", np.nan))
    }
    for grp_name, grp_cfg in sections_cfg.items():
        cast_nums_grp = _expand_cast_numbers(grp_cfg.get("cast_numbers", []))
        lats_g = [cast_pos[cn][0] for cn in sorted(cast_nums_grp) if cn in cast_pos]
        lons_g = [cast_pos[cn][1] for cn in sorted(cast_nums_grp) if cn in cast_pos]
        if lats_g:
            sections_data_map.append(
                {
                    "name": grp_name,
                    "color": grp_cfg.get("color", "#888888"),
                    "lats": lats_g,
                    "lons": lons_g,
                }
            )
    for grp_name, grp_cfg in _ts_cfg.items():
        cast_nums_grp = _expand_cast_numbers(grp_cfg.get("cast_numbers", []))
        lats_g = [cast_pos[cn][0] for cn in sorted(cast_nums_grp) if cn in cast_pos]
        lons_g = [cast_pos[cn][1] for cn in sorted(cast_nums_grp) if cn in cast_pos]
        if lats_g:
            sections_data_map.append(
                {
                    "name": grp_name,
                    "color": grp_cfg.get("color", "#888888"),
                    "lats": lats_g,
                    "lons": lons_g,
                }
            )

    if sections_data_map and _valid_lats:
        fig_map_b64 = _make_all_sections_map_b64(
            sections_data_map,
            _valid_lats,
            _valid_lons,
            legend_outside=True,
            target_h=3.0,
        )
    elif _valid_lats:
        # No sections configured (e.g. draft mode) — fall back to cruise-track map.
        fig_map_b64 = _make_cruise_map_b64(all_meta, target_h=3.0)
    else:
        fig_map_b64 = None

    # Stacked overview panels and cruise T-S diagram from profiles.nc
    physics_panels_idx: list[dict[str, Any]] = []
    biogeo_panels_idx: list[dict[str, Any]] = []
    ts_b64: str | None = None
    if profiles_path is not None and profiles_path.exists():
        try:
            ds_all = xr.open_dataset(
                profiles_path, decode_timedelta=False, engine="netcdf4"
            ).load()
            ds_all = add_teos10_profiles(ds_all)
            ds_all = add_aou(ds_all)

            mask_down = ds_all["cast_type"].values == "down"
            ds_down = ds_all.isel(N_PROF=mask_down)
            order = np.argsort(ds_down["cast_number"].values)
            ds_sorted = ds_down.isel(N_PROF=order)

            lats = ds_sorted["latitude"].values.tolist()
            lons = ds_sorted["longitude"].values.tolist()
            bathy = interpolate_bathy_at_casts(lats, lons, path=GEBCO_PATH)

            vmin = vmin_override or {}
            vmax = vmax_override or {}

            def _idx_panel(var: str, label: str) -> dict[str, Any]:
                b64 = _make_overview_panel_b64(
                    ds_sorted,
                    var,
                    label,
                    bathy_depths=bathy,
                    style=section_style,
                    vmin=vmin.get(var),
                    vmax=vmax.get(var),
                    cast_groups=cast_groups,
                )
                return {"title": label, "b64": b64}

            physics_panels_idx = [_idx_panel(v, l) for v, l in _OVERVIEW_PHYSICS_VARS]
            biogeo_panels_idx = [_idx_panel(v, l) for v, l in _OVERVIEW_BIOGEO_VARS]

            ts_b64 = _make_section_ts_histogram_b64(ds_sorted)
            ds_all.close()
        except Exception:  # noqa: BLE001, S110
            pass  # Overview panels are optional; never crash index generation

    date_start = times_str[0] if times_str else ""
    date_end = times_str[-1] if len(times_str) >= 2 else ""

    ctx: dict[str, Any] = {
        "cruise": cruise,
        "ship": ci.get("ship", ""),
        "project": ci.get("project", ""),
        "date_start": date_start,
        "date_end": date_end,
        "n_casts": len(all_meta),
        "n_sections": len(sections_cfg),
        "max_depth_str": f"{max_depth:.0f} dbar",
        "n_days": n_days,
        "fig_map_b64": fig_map_b64,
        "physics_panels": physics_panels_idx,
        "biogeo_panels": biogeo_panels_idx,
        "ts_b64": ts_b64
        if profiles_path is not None and profiles_path.exists()
        else None,
        "version": _VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    env = Environment(autoescape=True)
    html = env.from_string(_INDEX_TEMPLATE).render(**ctx)
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def _dec_min(deg: float, pos_hem: str, neg_hem: str) -> str:
    """Format decimal degrees as degrees-decimal-minutes, e.g. 65°13.782′N."""
    if not np.isfinite(deg):
        return "—"
    hem = pos_hem if deg >= 0 else neg_hem
    deg = abs(deg)
    d = int(deg)
    m = (deg - d) * 60.0
    return f"{d}°{m:06.3f}′{hem}"


_DEPTH_PILL_PALETTE: list[tuple[str, str]] = [
    ("#deebf7", "#1a1a2e"),  # shallowest — very light blue, dark text
    ("#9ecae1", "#1a1a2e"),  # light blue, dark text
    ("#4292c6", "#ffffff"),  # medium blue, white text
    ("#2171b5", "#ffffff"),  # dark blue, white text
    ("#084594", "#ffffff"),  # deepest — very dark blue, white text
]


def _depth_pill_style(depth: float, rounded_max: float) -> tuple[str, str]:
    """Return (background_hex, text_hex) for a depth pill based on 5-class scheme."""
    if rounded_max <= 0 or not np.isfinite(depth):
        return _DEPTH_PILL_PALETTE[0]
    cls = min(4, int(depth / rounded_max * 5))
    return _DEPTH_PILL_PALETTE[cls]


def _round_max_depth(max_depth: float) -> float:
    """Round *max_depth* up to the nearest 100, 500, or 1000 dbar."""
    if max_depth <= 500:
        return float(np.ceil(max_depth / 100) * 100)
    if max_depth <= 2000:
        return float(np.ceil(max_depth / 500) * 500)
    return float(np.ceil(max_depth / 1000) * 1000)


def _write_stations_list(
    all_meta: list[dict[str, Any]],
    cruise: str,
    out_dir: Path,
    sections_cfg: dict[str, Any] | None = None,
    timeseries_cfg: dict[str, Any] | None = None,
    ladcp_dir: Path | None = None,
    ladcp_pattern: str | None = None,
    cruise_info: dict[str, Any] | None = None,
) -> None:
    """Write station_index.html with cruise map, depth pills, and section/timeseries links."""
    # LADCP: collect cast numbers that have a processed .mat file.
    # Use find_ladcp_file per cast so non-NNN.mat filenames (e.g. msm_142_1_NNN.mat)
    # are handled correctly.
    ladcp_cast_nums: set[int] = set()
    if ladcp_dir is not None and ladcp_dir.exists():
        for meta in all_meta:
            cn = meta["cast_num"]
            cs = meta.get("cast_suffix", "")
            if find_ladcp_file(ladcp_dir, cn, cs, ladcp_pattern) is not None:
                ladcp_cast_nums.add(cn)

    # Section name → YAML color; cast → section names
    section_colors: dict[str, str] = {
        name: cfg.get("color", "#2c6e49") for name, cfg in (sections_cfg or {}).items()
    }
    cast_to_sections: dict[int, list[str]] = {}
    for sec_name, sec_cfg in (sections_cfg or {}).items():
        for cn in _expand_cast_numbers(sec_cfg.get("cast_numbers", [])):
            cast_to_sections.setdefault(cn, []).append(sec_name)

    # Timeseries name → YAML color; cast → timeseries names
    ts_colors: dict[str, str] = {
        name: cfg.get("color", "#7b2d8b")
        for name, cfg in (timeseries_cfg or {}).items()
    }
    cast_to_timeseries: dict[int, list[str]] = {}
    for ts_name, ts_cfg in (timeseries_cfg or {}).items():
        for cn in _expand_cast_numbers(ts_cfg.get("cast_numbers", [])):
            cast_to_timeseries.setdefault(cn, []).append(ts_name)

    all_depths = [
        m.get("max_depth", 0) for m in all_meta if np.isfinite(m.get("max_depth", 0))
    ]
    rounded_max = _round_max_depth(max(all_depths, default=100))

    stations = []
    for m in all_meta:
        lat = m.get("lat", np.nan)
        lon = m.get("lon", np.nan)
        depth = m.get("max_depth", 0)
        bg, fg = _depth_pill_style(float(depth), rounded_max)
        cast_num_int = m["cast_num"]
        stations.append(
            {
                "cast_num": m["cast_num_str"],
                "filename": m.get("raw_filename", "—"),
                "time_start_str": str(m.get("time_start", ""))[:16].replace("T", " "),
                "lat_str": _dec_min(lat, "N", "S"),
                "lon_str": _dec_min(lon, "E", "W"),
                "max_depth_str": f"{depth:.0f}",
                "depth_bg": bg,
                "depth_fg": fg,
                "sections": [
                    {"name": sn, "color": section_colors.get(sn, "#2c6e49")}
                    for sn in cast_to_sections.get(cast_num_int, [])
                ],
                "timeseries": [
                    {"name": tn, "color": ts_colors.get(tn, "#7b2d8b")}
                    for tn in cast_to_timeseries.get(cast_num_int, [])
                ],
                "ladcp_has": cast_num_int in ladcp_cast_nums,
            }
        )

    _ci = cruise_info or {}
    _times_str = sorted(
        str(m["time_start"])[:10] for m in all_meta if m.get("time_start")
    )
    _date_start = _times_str[0] if _times_str else ""
    _date_end = _times_str[-1] if len(_times_str) >= 2 else ""
    _duration_days = 0
    if _date_start and _date_end:
        try:
            from datetime import date as _date

            _duration_days = (
                _date.fromisoformat(_date_end) - _date.fromisoformat(_date_start)
            ).days + 1
        except ValueError:
            pass
    _max_depth = max((m.get("max_depth", 0) for m in all_meta), default=0)

    ctx: dict[str, Any] = {
        "cruise": cruise,
        "ship": _ci.get("ship", ""),
        "date_start": _date_start,
        "date_end": _date_end,
        "duration_days": _duration_days,
        "max_depth_str": f"{_max_depth:.0f} dbar" if _max_depth else "",
        "stations": stations,
        "cruise_map_b64": _make_cruise_map_b64(all_meta, target_h=3.0),
        "ladcp_configured": ladcp_dir is not None,
        "version": _VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    env = Environment(autoescape=True)
    html = env.from_string(_STATIONS_TEMPLATE).render(**ctx)
    (out_dir / "station_index.html").write_text(html, encoding="utf-8")


def _write_sections_list(
    sections_cfg: dict[str, Any],
    cruise: str,
    out_dir: Path,
    all_meta: list[dict[str, Any]] | None = None,
    ladcp_dir: Path | None = None,
    cruise_info: dict[str, Any] | None = None,
) -> None:
    """Write sections.html with overview map and cards for each section."""
    ladcp_cast_nums: set[int] = set()
    if ladcp_dir is not None and ladcp_dir.exists():
        for f in ladcp_dir.glob("*.mat"):
            try:
                ladcp_cast_nums.add(int(f.stem))
            except ValueError:
                pass

    # Build cast → position lookup for the overview map
    cast_pos: dict[int, tuple[float, float]] = {}
    if all_meta:
        for m in all_meta:
            cn = m.get("cast_num")
            if (
                cn is not None
                and np.isfinite(m.get("lat", np.nan))
                and np.isfinite(m.get("lon", np.nan))
            ):
                cast_pos[int(cn)] = (float(m["lat"]), float(m["lon"]))

    sections = []
    sections_data: list[dict[str, Any]] = []
    _sec_n_casts_list: list[int] = []
    _sec_dist_list: list[float] = []
    for name, cfg in sections_cfg.items():
        cast_nums = _expand_cast_numbers(cfg.get("cast_numbers", []))
        report_path = out_dir / "sections" / f"section_{name}.html"
        ladcp_has = any(c in ladcp_cast_nums for c in cast_nums)
        n_casts_sec = len(cast_nums)
        _sec_n_casts_list.append(n_casts_sec)
        sections.append(
            {
                "name": name,
                "description": cfg.get("description", ""),
                "color": cfg.get("color", "#1a3a5c"),
                "n_casts": n_casts_sec,
                "cast_range": compact_cast_list(cast_nums) if cast_nums else "—",
                "report_exists": report_path.exists(),
                "ladcp_has": ladcp_has,
            }
        )
        if cast_pos:
            sec_lats = [cast_pos[c][0] for c in cast_nums if c in cast_pos]
            sec_lons = [cast_pos[c][1] for c in cast_nums if c in cast_pos]
            if sec_lats:
                sections_data.append(
                    {
                        "name": name,
                        "color": cfg.get("color", "#555555"),
                        "lats": sec_lats,
                        "lons": sec_lons,
                    }
                )
                if len(sec_lats) >= 2:
                    _km, _ = along_track_km(sec_lats, sec_lons)
                    _sec_dist_list.append(float(_km[-1]))

    all_cast_lats = [v[0] for v in cast_pos.values()]
    all_cast_lons = [v[1] for v in cast_pos.values()]
    sections_map_b64 = (
        _make_all_sections_map_b64(
            sections_data, all_cast_lats, all_cast_lons, target_h=3.0
        )
        if sections_data
        else None
    )

    # Cruise-wide date range from all_meta
    _ci = cruise_info or {}
    _times_str = sorted(
        str(m["time_start"])[:10] for m in (all_meta or []) if m.get("time_start")
    )
    _date_start = _times_str[0] if _times_str else ""
    _date_end = _times_str[-1] if len(_times_str) >= 2 else ""
    _duration_days = 0
    if _date_start and _date_end:
        try:
            from datetime import date as _date

            _duration_days = (
                _date.fromisoformat(_date_end) - _date.fromisoformat(_date_start)
            ).days + 1
        except ValueError:
            pass
    # Summary ranges across sections
    _casts_range = ""
    if _sec_n_casts_list:
        mn, mx = min(_sec_n_casts_list), max(_sec_n_casts_list)
        _casts_range = f"{mn}–{mx}" if mn != mx else str(mn)
    _dist_range = ""
    if _sec_dist_list:
        mn_d, mx_d = min(_sec_dist_list), max(_sec_dist_list)
        _dist_range = f"{mn_d:.0f}–{mx_d:.0f} km" if mn_d != mx_d else f"{mn_d:.0f} km"

    ctx: dict[str, Any] = {
        "cruise": cruise,
        "ship": _ci.get("ship", ""),
        "date_start": _date_start,
        "date_end": _date_end,
        "duration_days": _duration_days,
        "casts_range": _casts_range,
        "dist_range": _dist_range,
        "sections": sections,
        "sections_map_b64": sections_map_b64,
        "ladcp_configured": ladcp_dir is not None,
        "version": _VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    env = Environment(autoescape=True)
    html = env.from_string(_SECTIONS_TEMPLATE).render(**ctx)
    (out_dir / "sections.html").write_text(html, encoding="utf-8")


_TIMESERIES_LIST_TEMPLATE = (
    """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Timeseries — {{ cruise }}</title>
<style>
"""
    + SHARED_CSS
    + """\
/* Timeseries index */
.ts-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 1rem; margin-bottom: 1.5rem;
}
.ts-card {
  background: #fff; border-radius: 8px; border-left: 4px solid #1a3a5c;
  padding: 1.1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.ts-card h3 { font-size: 1rem; color: var(--ocean); margin: 0 0 0.25rem; }
.ts-card .desc { font-size: 0.85rem; color: #555; margin-bottom: 0.5rem; }
.ts-card .info { font-size: 0.82rem; color: #777; }
.btn-card {
  display: inline-block; background: #27ae60; color: #fff;
  padding: 0.25rem 0.8rem; border-radius: 999px; text-decoration: none;
  font-size: 0.8rem; margin-top: 0.6rem;
}
.btn-card:hover { opacity: 0.85; }
.ladcp-yes { display:inline-block; padding:0.18rem 0.5rem; border-radius:999px; font-size:0.75rem; font-weight:600; background:#2c6e49; color:#fff; }
.ladcp-no  { display:inline-block; padding:0.18rem 0.5rem; border-radius:999px; font-size:0.75rem; font-weight:600; background:#c0392b; color:#fff; }
</style>
</head>
<body>
<div id="top"></div>

<div class="masthead" style="background:#27ae60;">
  <div class="masthead-header">
    <h1>{{ cruise }}</h1>
    <span class="masthead-type">Timeseries index</span>
  </div>
  <p class="sub" style="margin:0 0 0.6rem; text-align:right;">generated {{ generated_at }}</p>
  <div style="margin-top:0.65rem;margin-bottom:0.5rem">
    <span style="font-size:0.72rem;opacity:0.75;margin-right:0.3rem;">Pages:</span>
    <a href="index.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#2980b9">Summary</a>
    <a href="station_index.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#1a3a5c">Stations</a>
    <a href="sections.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#8e44ad">Sections</a>
    <a href="timeseries.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#27ae60;opacity:0.55">Timeseries</a>
    <a href="leaflet.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#EE3377">Interactive</a>
  </div>
  <dl class="meta-grid">
    <div><dt>Cruise</dt><dd>{{ cruise }}</dd></div>
    {% if ship %}<div><dt>Ship</dt><dd>{{ ship }}</dd></div>{% endif %}
    {% if date_start %}<div><dt>Departure</dt><dd>{{ date_start }}</dd></div>{% endif %}
    {% if date_end %}<div><dt>Arrival</dt><dd>{{ date_end }}</dd></div>{% endif %}
    {% if duration_days %}<div><dt>Duration</dt><dd>{{ duration_days }} d</dd></div>{% endif %}
    <div><dt>Timeseries groups</dt><dd>{{ timeseries|length }}</dd></div>
    {% if ts_casts_range %}<div><dt>Casts per group</dt><dd>{{ ts_casts_range }}</dd></div>{% endif %}
    {% if ts_dur_range %}<div><dt>Duration range</dt><dd>{{ ts_dur_range }}</dd></div>{% endif %}
  </dl>
</div>

{% if timeseries_map_b64 %}
<h2 id="s-map">Timeseries locations</h2>
<div class="fig-row">
  <figure class="slot-third">
    <img src="data:image/png;base64,{{ timeseries_map_b64 }}" alt="Timeseries locations map">
  </figure>
</div>
{% endif %}

<h2 id="s-list">Timeseries groups</h2>
<div class="ts-grid">
{% for ts in timeseries %}
<div class="ts-card" style="border-left-color:{{ ts.color }}">
  <h3>{{ ts.name }}</h3>
  <div class="desc">{{ ts.description }}</div>
  <div class="info">{{ ts.n_casts }} casts &nbsp;·&nbsp; {{ ts.cast_range }}</div>
  {% if ladcp_configured %}
  <div style="margin-top:0.4rem;">
    {% if ts.ladcp_has %}<span class="ladcp-yes">✓ LADCP</span>{% else %}<span class="ladcp-no">– LADCP</span>{% endif %}
  </div>
  {% endif %}
  {% if ts.report_exists %}
  <a class="btn-card" href="timeseries/timeseries_{{ ts.name }}.html">view timeseries →</a>
  {% else %}
  <span style="font-size:0.8rem;color:#aaa;margin-top:0.4rem;display:inline-block;">report not yet generated</span>
  {% endif %}
</div>
{% endfor %}
{% if not timeseries %}
<p style="color:#888">No timeseries groups configured.</p>
{% endif %}
</div>

"""
    + _tmpl.FOOTER_TAIL
    + _JS_TOP_LINKS
)


def _write_timeseries_list(
    timeseries_cfg: dict[str, Any],
    cruise: str,
    out_dir: Path,
    all_meta: list[dict[str, Any]] | None = None,
    ladcp_dir: Path | None = None,
    cruise_info: dict[str, Any] | None = None,
) -> None:
    """Write timeseries.html listing all timeseries groups with an overview map."""
    from ctdcast.reports._section import _expand_cast_numbers

    ladcp_cast_nums: set[int] = set()
    if ladcp_dir is not None and ladcp_dir.exists():
        for f in ladcp_dir.glob("*.mat"):
            try:
                ladcp_cast_nums.add(int(f.stem))
            except ValueError:
                pass

    # Build cast → position and time lookup
    cast_pos: dict[int, tuple[float, float]] = {}
    cast_times: dict[int, tuple[Any, Any]] = {}
    if all_meta:
        for m in all_meta:
            cn = m.get("cast_num")
            if cn is not None:
                if np.isfinite(m.get("lat", np.nan)) and np.isfinite(
                    m.get("lon", np.nan)
                ):
                    cast_pos[int(cn)] = (float(m["lat"]), float(m["lon"]))
                if m.get("time_start") is not None and m.get("time_end") is not None:
                    cast_times[int(cn)] = (m["time_start"], m["time_end"])

    items = []
    timeseries_data: list[dict[str, Any]] = []
    _ts_n_casts_list: list[int] = []
    _ts_dur_h_list: list[float] = []
    for name, cfg in timeseries_cfg.items():
        cast_nums = _expand_cast_numbers(cfg.get("cast_numbers", []))
        report_path = out_dir / "timeseries" / f"timeseries_{name}.html"
        color = cfg.get("color", "#7b2d8b")
        ladcp_has = any(c in ladcp_cast_nums for c in cast_nums)
        n_casts_ts = len(cast_nums)
        _ts_n_casts_list.append(n_casts_ts)
        # Compute per-group duration from cast timestamps
        grp_starts = [cast_times[c][0] for c in cast_nums if c in cast_times]
        grp_ends = [cast_times[c][1] for c in cast_nums if c in cast_times]
        if grp_starts and grp_ends:
            try:
                _t0 = np.min(np.array(grp_starts, dtype="datetime64[ns]"))
                _t1 = np.max(np.array(grp_ends, dtype="datetime64[ns]"))
                _dur_h = float((_t1 - _t0) / np.timedelta64(1, "h"))
                _ts_dur_h_list.append(_dur_h)
            except Exception:  # noqa: BLE001,S110
                pass
        items.append(
            {
                "name": name,
                "description": cfg.get("description", ""),
                "color": color,
                "n_casts": n_casts_ts,
                "cast_range": compact_cast_list(cast_nums) if cast_nums else "—",
                "report_exists": report_path.exists(),
                "ladcp_has": ladcp_has,
            }
        )
        if cast_pos:
            ts_lats = [cast_pos[c][0] for c in cast_nums if c in cast_pos]
            ts_lons = [cast_pos[c][1] for c in cast_nums if c in cast_pos]
            if ts_lats:
                timeseries_data.append(
                    {"name": name, "color": color, "lats": ts_lats, "lons": ts_lons}
                )

    all_cast_lats = [v[0] for v in cast_pos.values()]
    all_cast_lons = [v[1] for v in cast_pos.values()]
    timeseries_map_b64 = (
        _make_all_sections_map_b64(
            timeseries_data, all_cast_lats, all_cast_lons, target_h=3.0
        )
        if timeseries_data
        else None
    )

    # Cruise-wide date range
    _ci = cruise_info or {}
    _times_str = sorted(
        str(m["time_start"])[:10] for m in (all_meta or []) if m.get("time_start")
    )
    _date_start = _times_str[0] if _times_str else ""
    _date_end = _times_str[-1] if len(_times_str) >= 2 else ""
    _duration_days = 0
    if _date_start and _date_end:
        try:
            from datetime import date as _date

            _duration_days = (
                _date.fromisoformat(_date_end) - _date.fromisoformat(_date_start)
            ).days + 1
        except ValueError:
            pass
    # Summary ranges across timeseries groups
    _ts_casts_range = ""
    if _ts_n_casts_list:
        mn, mx = min(_ts_n_casts_list), max(_ts_n_casts_list)
        _ts_casts_range = f"{mn}–{mx}" if mn != mx else str(mn)
    _ts_dur_range = ""
    if _ts_dur_h_list:
        mn_h, mx_h = min(_ts_dur_h_list), max(_ts_dur_h_list)
        _ts_dur_range = f"{mn_h:.0f}–{mx_h:.0f} h" if mn_h != mx_h else f"{mn_h:.0f} h"

    ctx: dict[str, Any] = {
        "cruise": cruise,
        "ship": _ci.get("ship", ""),
        "date_start": _date_start,
        "date_end": _date_end,
        "duration_days": _duration_days,
        "ts_casts_range": _ts_casts_range,
        "ts_dur_range": _ts_dur_range,
        "timeseries": items,
        "timeseries_map_b64": timeseries_map_b64,
        "ladcp_configured": ladcp_dir is not None,
        "version": _VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    env = Environment(autoescape=True)
    html = env.from_string(_TIMESERIES_LIST_TEMPLATE).render(**ctx)
    (out_dir / "timeseries.html").write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Mtime helpers
# ---------------------------------------------------------------------------


def _fmt_mtime(path: Path) -> str:
    """Return a compact local datetime string for *path*'s mtime, or ``"missing"``."""
    try:
        return (
            datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M")
        )
    except OSError:
        return "missing"


def _mtime_skip_reason(
    expected: Path,
    source: Path,
    force: bool,
    *extra_sources: Path,
    skip_existing: bool = False,
) -> str:
    """Return a non-empty skip-reason string if *expected* should not be regenerated.

    Returns an empty string when the page should be (re)generated.

    Logic (evaluated in order):
    - *force* is True → always regenerate (return ``""``).
    - *expected* does not exist → must generate (return ``""``).
    - *skip_existing* is True → skip unconditionally: ``"skipped (exists)"``.
    - *expected* is newer than ALL of *source* and *extra_sources* → skip:
      ``"skipped (up to date)"``.
    - Any source newer than *expected* → regenerate (smart update, return ``""``).
    - mtime comparison fails (``OSError``) → conservative skip:
      ``"skipped (exists, use --force)"``.
    """
    if force or not expected.exists():
        return ""
    if skip_existing:
        return "skipped (exists)"
    try:
        html_mtime = expected.stat().st_mtime
        all_sources = [source, *extra_sources]
        if any(s.stat().st_mtime > html_mtime for s in all_sources):
            return ""  # at least one source is newer: regenerate
        return "skipped (up to date)"
    except OSError:
        return "skipped (exists, use --force)"


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------


def _select_cast_files(nc_dir: Path) -> list[Path]:
    """Return sorted list of cast .nc files from any cruise naming convention.

    Accepts any ``*.nc`` file whose stem contains a 3+-digit cast number,
    optionally followed by a letter suffix (e.g. ``mixsed2_004b.nc``,
    ``msm_142_1_001_1sec.nc``).  The **last** 3+-digit group in the stem is
    taken as the cast number so that cruise/leg numbers earlier in the name
    (e.g. the ``142`` in ``msm_142_1_001_1sec``) are not confused with cast
    numbers.  Sort order is cast number then suffix (plain before ``b``).
    """
    results: list[tuple[int, str, Path]] = []
    for p in sorted(nc_dir.glob("*.nc")):
        _id = _extract_cast_id(p.stem)
        if _id is None:
            continue
        results.append((_id[0], _id[1], p))
    results.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in results]


def _read_cast_meta(nc_path: Path) -> dict[str, Any] | None:
    """Read scalar metadata from a cast .nc file without loading all data."""
    try:
        ds = xr.open_dataset(nc_path, decode_timedelta=False, engine="netcdf4")
        _id = _extract_cast_id(nc_path.stem)
        if _id is None:
            return None
        cast_num, cast_suffix = _id
        import warnings as _w

        with _w.catch_warnings():
            _w.filterwarnings("ignore", "All-NaN slice encountered")
            lat = float(np.nanmedian(ds["latitude"].values))
            lon = float(np.nanmedian(ds["longitude"].values))
        max_depth = float(np.nanmax(ds["pressure"].values))
        time_start = ds["time"].values[0]
        time_end = ds["time"].values[-1]
        raw_filename = ds.attrs.get("raw_filename", nc_path.stem + ".cnv")
        cruise = ds.attrs.get("cruise", "odb2026")
        ds.close()
        return {
            "cast_num": cast_num,
            "cast_suffix": cast_suffix,
            "cast_num_str": f"{cast_num:03d}{cast_suffix}",
            "path": nc_path,
            "lat": lat,
            "lon": lon,
            "max_depth": max_depth,
            "time_start": time_start,
            "time_end": time_end,
            "raw_filename": raw_filename,
            "cruise": cruise,
        }
    except Exception:  # noqa: BLE001
        return None
