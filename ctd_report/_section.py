"""Tier-2: generate a per-section HTML report page."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import numpy as np
import xarray as xr
from jinja2 import Environment

from ctd_report._analysis import (
    _add_aou,
    _add_teos10_profiles,
    _along_track_km,
    _compact_cast_list,
    _interpolate_bathy_at_casts,
)
from ctd_report._plots import (
    GEBCO_PATH,
    _make_section_b64,
    _make_section_map_b64,
    _make_section_ts_histogram_b64,
    _make_section_ts_o2_b64,
    _make_section_ts_profiles_b64,
)

# ---------------------------------------------------------------------------
# Section variables to plot (in order)
# ---------------------------------------------------------------------------

_SECTION_VARS: list[tuple[str, str]] = [
    ("CT", "Conservative Temperature (°C)"),
    ("SA", "Absolute Salinity (g kg⁻¹)"),
    ("oxygen_1", "O₂ saturation (%)"),
    ("AOU", "O₂ deficit (% sat)"),
    ("fluorescence", "Fluorescence (mg m⁻³)"),
    ("turbidity", "Turbidity (NTU)"),
]

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_SECTION_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ section_name }} — {{ cruise }}</title>
<style>
  :root { --ocean: #1a3a5c; --seafoam: #e8f4f8; --accent: #2e86ab; --text: #1a1a2e; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #f5f7fa; color: var(--text); }
  header { background: var(--ocean); color: #fff; padding: 1rem 1.5rem; }
  header h1 { font-size: 1.3rem; }
  header .meta { font-size: 0.85rem; opacity: 0.8; margin-top: 0.25rem; }
  nav { background: var(--seafoam); padding: 0.6rem 1.5rem; border-bottom: 1px solid #cdd8e3; }
  nav a { color: var(--ocean); text-decoration: none; font-size: 0.9rem; margin-right: 0.5rem; }
  nav a:hover { text-decoration: underline; }
  nav span { color: #888; font-size: 0.9rem; margin-right: 0.5rem; }
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
  .plot-wide { margin-top: 0.75rem; }
  .plot-wide img { max-width: 100%; height: auto; border-radius: 4px; }
  .plots { display: flex; flex-wrap: wrap; gap: 1rem; margin-top: 0.75rem; }
  .plots img { max-height: 380px; width: auto; border-radius: 4px; }
  footer { text-align: center; padding: 1rem; font-size: 0.75rem; color: #999; }
</style>
</head>
<body>

<header>
  <div>
    <h1>{{ section_name }} — {{ section_description }}</h1>
    <div class="meta">{{ cruise }} &nbsp;·&nbsp; {{ n_casts }} casts &nbsp;·&nbsp; {{ dist_str }}</div>
  </div>
</header>

<nav>
  <a href="../index.html">Index</a> <span>›</span>
  <a href="../sections.html">Sections</a> <span>›</span>
  <span>{{ section_name }}</span>
</nav>

<!-- Metadata -->
<div class="card">
  <h2>Section metadata</h2>
  <div class="meta-grid">
    <div class="meta-item"><span class="label">Section</span><span class="value">{{ section_name }}</span></div>
    <div class="meta-item"><span class="label">Description</span><span class="value">{{ section_description }}</span></div>
    <div class="meta-item"><span class="label">Casts</span><span class="value">{{ cast_list_str }}</span></div>
    <div class="meta-item"><span class="label">Along-track distance</span><span class="value">{{ dist_str }}</span></div>
  </div>
  <div style="margin-top:0.75rem; display:flex; gap:0.5rem; flex-wrap:wrap;">
    {% for cn in cast_nums %}
    <a style="display:inline-block; background:#4a6fa5; color:#fff; padding:0.2rem 0.6rem;
       border-radius:999px; font-size:0.78rem; text-decoration:none;"
       href="../stations/cast_{{ cn }}.html">{{ cn }}</a>
    {% endfor %}
  </div>
</div>

<!-- Section map + sections -->
{% if fig_map_b64 %}
<div class="card">
  <h2>Section track</h2>
  <div class="plots">
    <img src="data:image/png;base64,{{ fig_map_b64 }}" alt="Section map">
  </div>
</div>
{% endif %}

{% for panel in panels %}
{% if panel.b64 %}
<div class="card">
  <h2>{{ panel.title }}</h2>
  <div class="plot-wide">
    <img src="data:image/png;base64,{{ panel.b64 }}" alt="{{ panel.title }}">
  </div>
</div>
{% endif %}
{% endfor %}

{% if ts_panels %}
<div class="card">
  <h2>TS diagrams</h2>
  <div class="plots">
    {% for p in ts_panels %}
    <figure style="text-align:center; margin:0;">
      <img src="data:image/png;base64,{{ p.b64 }}" alt="{{ p.title }}"
           style="max-height:420px; width:auto; border-radius:4px;">
      <figcaption style="font-size:0.8rem; color:#555; margin-top:0.3rem;">{{ p.title }}</figcaption>
    </figure>
    {% endfor %}
  </div>
</div>
{% endif %}

<footer>Generated by ctd_report &nbsp;·&nbsp; {{ cruise }}</footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def generate_section_page(
    section_name: str,
    section_cfg: dict[str, Any],
    profiles_path: Path,
    out_dir: Path,
    force: bool = False,
    section_style: str = "pcolormesh",
    vmin_override: Optional[dict[str, float]] = None,
    vmax_override: Optional[dict[str, float]] = None,
) -> Optional[Path]:
    """Generate a section HTML report page.

    Parameters
    ----------
    section_name:
        Key from ``ctd_sections.yaml``, e.g. ``"KTout"``.
    section_cfg:
        Dict with keys ``description``, ``cast_numbers``, ``color``.
    profiles_path:
        Path to ``profiles.nc`` (built by ``cnv_build_profiles.py``).
    out_dir:
        Root output directory.
    force:
        Overwrite existing file if True.
    section_style:
        ``"pcolormesh"`` or ``"contourf"`` — passed through to each section figure.
    vmin_override, vmax_override:
        Per-variable colormap limit overrides (e.g. ``{"SA": 34.5}``).

    Returns
    -------
    Path to the written HTML file, or None on failure.
    """
    out_file = out_dir / "sections" / f"section_{section_name}.html"
    if out_file.exists() and not force:
        return out_file
    out_file.parent.mkdir(parents=True, exist_ok=True)

    cast_nums = _expand_cast_numbers(section_cfg.get("cast_numbers", []))
    if not cast_nums:
        return None

    if not profiles_path.exists():
        return None

    try:
        ds_all = xr.open_dataset(
            profiles_path, decode_timedelta=False, engine="netcdf4"
        ).load()
    except Exception:  # noqa: BLE001
        return None

    # Filter to downcast profiles for this section
    all_cast_nums = ds_all["cast_number"].values
    is_down = ds_all["cast_type"].values == "down"
    mask = np.isin(all_cast_nums, cast_nums) & is_down
    if not mask.any():
        ds_all.close()
        return None

    ds_sec = ds_all.isel(N_PROF=mask)
    ds_sec = _add_teos10_profiles(ds_sec)
    ds_sec = _add_aou(ds_sec)

    lats = ds_sec["latitude"].values.tolist()
    lons = ds_sec["longitude"].values.tolist()
    sec_cast_nums = ds_sec["cast_number"].values.tolist()

    # Along-track distance in km
    x_vals, x_label = _along_track_km(lats, lons)

    cruise = ds_all.attrs.get("cruise", "odb2026")
    dist_str = f"{x_vals[-1]:.1f} km" if len(x_vals) > 1 else "—"

    bathy = _interpolate_bathy_at_casts(lats, lons, path=GEBCO_PATH)
    cast_nums_int = [int(c) for c in sec_cast_nums]
    vmin = vmin_override or {}
    vmax = vmax_override or {}

    panels = []
    for var, label in _SECTION_VARS:
        b64 = _make_section_b64(
            ds_sec,
            var,
            label,
            x_vals,
            x_label,
            style=section_style,
            bathy_depths=bathy,
            cast_labels=cast_nums_int,
            vmin=vmin.get(var),
            vmax=vmax.get(var),
        )
        panels.append({"title": label, "b64": b64})

    ts_panels_raw = [
        {
            "title": "Profiles coloured by distance",
            "b64": _make_section_ts_profiles_b64(ds_sec, x_vals),
        },
        {
            "title": "2-D histogram (log count)",
            "b64": _make_section_ts_histogram_b64(ds_sec),
        },
        {"title": "Median O₂ saturation", "b64": _make_section_ts_o2_b64(ds_sec)},
    ]
    ts_panels = [p for p in ts_panels_raw if p["b64"]]

    ctx: dict[str, Any] = {
        "section_name": section_name,
        "section_description": section_cfg.get("description", ""),
        "cruise": cruise,
        "n_casts": len(sec_cast_nums),
        "dist_str": dist_str,
        "cast_list_str": _compact_cast_list([int(c) for c in sec_cast_nums]),
        "cast_nums": [f"{n:03d}" for n in cast_nums_int],
        "fig_map_b64": _make_section_map_b64(
            lats, lons, cast_nums_int, title=section_name
        ),
        "panels": panels,
        "ts_panels": ts_panels,
    }

    env = Environment(autoescape=True)
    html = env.from_string(_SECTION_TEMPLATE).render(**ctx)
    out_file.write_text(html, encoding="utf-8")
    ds_all.close()
    return out_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _expand_cast_numbers(cast_numbers: list) -> list[int]:
    """Expand a cast_numbers list (ranges + individuals) to a flat list of ints."""
    result: list[int] = []
    for item in cast_numbers:
        if isinstance(item, list) and len(item) == 2:
            result.extend(range(int(item[0]), int(item[1]) + 1))
        else:
            result.append(int(item))
    return sorted(set(result))
