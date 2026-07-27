"""Tier-2: generate a per-cast HTML report page."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import numpy as np
import xarray as xr
from jinja2 import Environment

from ctd_report._plots import (
    _add_teos10,
    _make_aux_profiles_b64,
    _make_profile_b64,
    _make_stability_b64,
    _make_station_map_b64,
    _make_ts_density_b64,
    _make_ts_diagram_b64,
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
  nav { background: var(--seafoam); padding: 0.6rem 1.5rem; border-bottom: 1px solid #cdd8e3; }
  nav a { color: var(--ocean); text-decoration: none; font-size: 0.9rem; margin-right: 0.5rem; }
  nav a:hover { text-decoration: underline; }
  nav span { color: #888; font-size: 0.9rem; margin-right: 0.5rem; }
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
  .card h2 { font-size: 1rem; color: var(--ocean); margin-bottom: 0.75rem; }
  .meta-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 0.5rem; font-size: 0.9rem;
  }
  .meta-item { display: flex; flex-direction: column; }
  .meta-item .label { font-size: 0.75rem; color: #888; }
  .meta-item .value { font-weight: 600; }
  .plots { display: flex; flex-wrap: wrap; gap: 1rem; margin-top: 0.75rem; }
  .plots img { max-height: 480px; width: auto; border-radius: 4px; }
  .plot-wide img { max-width: 100%; height: auto; }
  footer { text-align: center; padding: 1rem; font-size: 0.75rem; color: #999; }
</style>
</head>
<body>

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
  <a href="../index.html">Index</a> <span>›</span>
  <a href="../station_index.html">Stations</a> <span>›</span>
  <span>Cast {{ cast_num }}</span>
</nav>

<!-- Metadata card -->
<div class="card">
  <h2>Cast metadata</h2>
  <div class="meta-grid">
    <div class="meta-item"><span class="label">Cast</span><span class="value">{{ cast_num }}</span></div>
    <div class="meta-item"><span class="label">Date/time (UTC)</span><span class="value">{{ datetime_str }}</span></div>
    <div class="meta-item"><span class="label">Latitude</span><span class="value">{{ lat_str }}</span></div>
    <div class="meta-item"><span class="label">Longitude</span><span class="value">{{ lon_str }}</span></div>
    <div class="meta-item"><span class="label">Max depth</span><span class="value">{{ max_depth_str }}</span></div>
  </div>
</div>

<!-- Profiles: CT and T/S/sigma -->
<div class="card">
  <h2>Temperature · Salinity · Density profiles</h2>
  <div class="plots">
    {% if fig_ct_b64 %}<img src="data:image/png;base64,{{ fig_ct_b64 }}" alt="CT profile">{% endif %}
    {% if fig_ts_density_b64 %}<img src="data:image/png;base64,{{ fig_ts_density_b64 }}" alt="T/S/density profile">{% endif %}
    {% if fig_station_map_b64 %}<img src="data:image/png;base64,{{ fig_station_map_b64 }}" alt="Station map">{% endif %}
  </div>
</div>

<!-- T-S diagram -->
{% if fig_ts_diagram_b64 %}
<div class="card">
  <h2>T-S diagram (colored by O₂ saturation)</h2>
  <div class="plots">
    <img src="data:image/png;base64,{{ fig_ts_diagram_b64 }}" alt="T-S diagram">
  </div>
</div>
{% endif %}

<!-- Auxiliary profiles -->
{% if fig_aux_b64 %}
<div class="card">
  <h2>O₂ · Fluorescence · Turbidity</h2>
  <div class="plots">
    <img src="data:image/png;base64,{{ fig_aux_b64 }}" alt="Auxiliary profiles">
  </div>
</div>
{% endif %}

<!-- Stability -->
{% if fig_stability_b64 %}
<div class="card">
  <h2>Stability (N² and Turner angle)</h2>
  <div class="plots">
    <img src="data:image/png;base64,{{ fig_stability_b64 }}" alt="Stability">
  </div>
</div>
{% endif %}

<footer>Generated by ctd_report &nbsp;·&nbsp; {{ cruise }}</footer>
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
        ds = xr.open_dataset(nc_path, decode_timedelta=False).load()
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
        "fig_ct_b64": _make_profile_b64(ds, "CT", "Conservative Temperature (°C)"),
        "fig_ts_density_b64": _make_ts_density_b64(ds),
        "fig_ts_diagram_b64": _make_ts_diagram_b64(ds),
        "fig_aux_b64": _make_aux_profiles_b64(ds),
        "fig_stability_b64": _make_stability_b64(ds),
        "fig_station_map_b64": _make_station_map_b64(lat, lon, all_meta),
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
