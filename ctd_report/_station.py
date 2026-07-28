"""Tier-2: generate a per-cast HTML report page."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import numpy as np
import xarray as xr
from jinja2 import Environment

from ctd_report._analysis import _add_teos10
from ctd_report._plots import (
    _make_aux_profiles_b64,
    _make_ct_sa_sigma0_b64,
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

_STATION_TEMPLATE = """<!DOCTYPE html>
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
  /* Row 1: profile gets 50% of row width; map and T–S share the rest */
  .fig-profile { width: 40%; height: auto; flex-shrink: 0; }
  .fig-map { max-height: 340px; }
  .fig-updown { max-height: 280px; }
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
    <div class="meta">{{ datetime_str }} &nbsp;·&nbsp; {{ lat_str }}, {{ lon_str }} &nbsp;·&nbsp; max depth {{ max_depth_str }}</div>
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
    <a href="#s-profiles">CT · SA · σ₀</a>
    <a href="#s-aux">O₂ · Fluor · Turb</a>
    <a href="#s-ts">T–S diagram</a>
    <a href="#s-stability">Stability</a>
    <a href="#s-diagnostics">Diagnostics</a>
  </div>
</nav>

<!-- Row 1: triple-axis profile | station map | TS up/down -->
<div class="card" id="s-overview">
  <div class="card-header">
    <h2>Overview</h2>
    <a class="jump" href="#top">↑ top</a>
  </div>
  <div class="plots">
    {% if fig_ts_density_b64 %}<img class="fig-profile" src="data:image/png;base64,{{ fig_ts_density_b64 }}" alt="CT/SA/σ₀ profile">{% endif %}
    {% if fig_ts_updown_b64 %}<img class="fig-updown" src="data:image/png;base64,{{ fig_ts_updown_b64 }}" alt="T–S down vs up">{% endif %}
    {% if fig_station_map_b64 %}<img class="fig-map" src="data:image/png;base64,{{ fig_station_map_b64 }}" alt="Station map">{% endif %}
  </div>
</div>

<!-- Row 2: CT | SA | σ₀ triple-panel profiles -->
{% if fig_ct_sa_sigma0_b64 %}
<div class="card" id="s-profiles">
  <div class="card-header">
    <h2>CT · SA · σ₀ profiles</h2>
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
    <h2>O₂ · Fluorescence · Turbidity</h2>
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

<footer>Generated by ctd_report &nbsp;·&nbsp; {{ cruise }} &nbsp;·&nbsp; cast start: {{ datetime_str }} UTC</footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def generate_station_page(
    nc_path: Path,
    out_dir: Path,
    all_meta: list[dict[str, Any]],
    prev_num: Optional[int] = None,
    next_num: Optional[int] = None,
    force: bool = False,
) -> Optional[Path]:
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

    ctx: dict[str, Any] = {
        "cast_num": f"{cast_num:03d}",
        "cruise": cruise,
        "datetime_str": t0,
        "lat_str": f"{lat:.4f}°N",
        "lon_str": f"{lon:.4f}°E",
        "max_depth_str": f"{max_depth:.0f} dbar",
        "prev_num": prev_str,
        "next_num": next_str,
        # Row 1
        "fig_ts_density_b64": _make_ts_density_b64(ds),
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
