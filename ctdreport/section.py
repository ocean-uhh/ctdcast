"""Tier-2: generate a per-section HTML report page."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr
from jinja2 import Environment

from ctdreport import _templates as _tmpl
from ctdreport import plots as _plots
from ctdreport._version import __version__ as _VERSION
from ctdreport.analysis import (
    _add_aou,
    _add_teos10_profiles,
    _along_track_km,
    _compact_cast_list,
    _dense_bathy_along_track,
    _interpolate_bathy_at_casts,
    _section_orientation,
)
from ctdreport.plots import (
    _make_ladcp_section_b64,
    _make_section_b64,
    _make_section_map_b64,
    _make_section_ts_histogram_b64,
    _make_section_ts_o2_b64,
    _make_section_ts_profiles_b64,
)

# ---------------------------------------------------------------------------
# Section variables to plot (in order)
# ---------------------------------------------------------------------------

_SECTION_VARS: list[tuple[str, str, str]] = [
    ("CT", "Conservative Temperature (°C)", "CT"),
    ("SA", "Absolute Salinity (g kg⁻¹)", "SA"),
    ("oxygen_1", "O₂ saturation (%)", "O₂ (%)"),
    ("AOU", "O₂ deficit (% sat)", "AOU"),
    ("fluorescence", "Fluorescence (mg m⁻³)", "Fluor"),
    ("turbidity", "Turbidity (NTU)", "Turb"),
]

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_SECTION_TEMPLATE = (
    """<!DOCTYPE html>
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
  nav { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.4rem; }
  nav a { color: var(--ocean); text-decoration: none; font-size: 0.9rem; margin-right: 0.5rem; }
  nav a:hover { text-decoration: underline; }
  nav span { color: #888; font-size: 0.9rem; margin-right: 0.5rem; }
  nav .quicklinks { display: flex; gap: 0.4rem; flex-wrap: wrap; }
  nav .quicklinks a {
    color: var(--ocean); text-decoration: none; font-size: 0.8rem;
    border: 1px solid #cdd8e3; border-radius: 999px; padding: 0.15rem 0.6rem;
    background: #fff;
  }
  nav .quicklinks a:hover { background: var(--seafoam); }
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
  <div class="breadcrumb">
    <a href="../index.html">Index</a> <span>›</span>
    <a href="../sections.html">Sections</a> <span>›</span>
    <span>{{ section_name }}</span>
  </div>
  <div class="quicklinks">
    <a href="#s-meta">Metadata</a>
    {% if fig_map_b64 %}<a href="#s-map">Map</a>{% endif %}
    {% for panel in panels %}{% if panel.b64 %}<a href="#s-panel-{{ loop.index }}">{{ panel.short }}</a>{% endif %}{% endfor %}
    {% for card in extra_cards %}<a href="#s-{{ card.id }}">{{ card.short }}</a>{% endfor %}
  </div>
</nav>

<div id="top"></div>

<!-- Metadata -->
<div class="card" id="s-meta">
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
<div class="card" id="s-map">
  <h2>Section track</h2>
  <div class="plots">
    <img src="data:image/png;base64,{{ fig_map_b64 }}" alt="Section map">
  </div>
</div>
{% endif %}

{% for panel in panels %}
{% if panel.b64 %}
<div class="card" id="s-panel-{{ loop.index }}">
  <h2>{{ panel.title }}</h2>
  <div class="plot-wide">
    <img src="data:image/png;base64,{{ panel.b64 }}" alt="{{ panel.title }}">
  </div>
</div>
{% endif %}
{% endfor %}

{% for card in extra_cards %}
<div class="card" id="s-{{ card.id }}">
  <h2>{{ card.title }}</h2>
  {% if card.panels | length == 1 %}
  <div class="plot-wide">
    <img src="data:image/png;base64,{{ card.panels[0].b64 }}" alt="{{ card.panels[0].title }}">
  </div>
  {% else %}
  <div class="plots">
    {% for panel in card.panels %}
    <figure style="text-align:center; margin:0;">
      <img src="data:image/png;base64,{{ panel.b64 }}" alt="{{ panel.title }}"
           style="max-height:420px; width:auto; border-radius:4px;">
      <figcaption style="font-size:0.8rem; color:#555; margin-top:0.3rem;">{{ panel.title }}</figcaption>
    </figure>
    {% endfor %}
  </div>
  {% endif %}
</div>
{% endfor %}

"""
    + _tmpl.FOOTER_TAIL
)


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
    vmin_override: dict[str, float] | None = None,
    vmax_override: dict[str, float] | None = None,
    ladcp_dir: Path | None = None,
    ladcp_pattern: str | None = None,
) -> Path | None:
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
    ladcp_dir:
        Directory containing processed LADCP ``.mat`` files.
        If None, the LADCP velocity section panel is omitted.
    ladcp_pattern:
        Filename pattern for LADCP files, e.g. ``"msm_142_1_*.mat"``.
        The ``*`` is replaced with the zero-padded cast number.
        Falls back to ``NNN.mat`` if not given.

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

    # Along-track distance in km; flip to geographic convention (west-left / north-left)
    x_vals, x_label = _along_track_km(lats, lons)

    bathy = _interpolate_bathy_at_casts(lats, lons, path=_plots.GEBCO_PATH)
    dense_bathy_x, dense_bathy_d = _dense_bathy_along_track(
        lats, lons, x_vals, path=_plots.GEBCO_PATH
    )

    if _section_orientation(lats, lons):
        x_total = float(x_vals[-1])
        x_vals = x_total - x_vals
        if dense_bathy_x is not None:
            dense_bathy_x = x_total - dense_bathy_x

    cruise = ds_all.attrs.get("cruise", "odb2026")
    dist_str = f"{x_vals.max():.1f} km" if len(x_vals) > 1 else "—"
    cast_nums_int = [int(c) for c in sec_cast_nums]
    vmin = vmin_override or {}
    vmax = vmax_override or {}

    panels = []
    for var, label, short in _SECTION_VARS:
        b64 = _make_section_b64(
            ds_sec,
            var,
            label,
            x_vals,
            x_label,
            style=section_style,
            bathy_depths=dense_bathy_d if dense_bathy_d is not None else bathy,
            bathy_x=dense_bathy_x,
            cast_labels=cast_nums_int,
            vmin=vmin.get(var),
            vmax=vmax.get(var),
        )
        panels.append({"title": label, "short": short, "b64": b64})

    _ts_panels_raw = [
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
    _ladcp_b64 = (
        _make_ladcp_section_b64(
            cast_nums_int,
            x_vals,
            x_label,
            ladcp_dir,
            lats=lats,
            lons=lons,
            ladcp_pattern=ladcp_pattern,
        )
        if ladcp_dir is not None
        else None
    )
    _extra_raw: dict[str, dict | None] = {
        "ladcp": {
            "id": "ladcp",
            "title": "LADCP velocity (U east, V north)",
            "short": "LADCP",
            "panels": [{"b64": _ladcp_b64, "title": "LADCP"}],
        }
        if _ladcp_b64
        else None,
        "ts": {
            "id": "ts",
            "title": "T–S diagrams",
            "short": "T–S",
            "panels": [
                {"b64": p["b64"], "title": p["title"]}
                for p in _ts_panels_raw
                if p["b64"]
            ],
        }
        if any(p["b64"] for p in _ts_panels_raw)
        else None,
    }
    extra_cards = [_extra_raw[k] for k in _tmpl.EXTRA_CARD_ORDER if _extra_raw.get(k)]

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
        "extra_cards": extra_cards,
        "version": _VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
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
