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
from ctdreport._css import _JS_TOP_LINKS, SHARED_CSS
from ctdreport._version import __version__ as _VERSION
from ctdreport.analysis import (
    _add_aou,
    _add_teos10_profiles,
    _along_track_km,
    _compact_cast_list,
    _dense_bathy_along_track,
    _fmt_utc,
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
    section_figsize_and_slot,
)

# ---------------------------------------------------------------------------
# Section variables to plot (in order)
# ---------------------------------------------------------------------------

_PHYSICS_VARS: list[tuple[str, str, str]] = [
    ("CT", "Conservative Temperature (°C)", "CT"),
    ("SA", "Absolute Salinity (g kg⁻¹)", "SA"),
    ("sigma0", "Potential density σ₀ (kg m⁻³)", "σ₀"),
]

_BIOGEO_VARS: list[tuple[str, str, str]] = [
    ("oxygen_1", "O₂ saturation (%)", "O₂ (%)"),
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
"""
    + SHARED_CSS
    + """\
/* Section page */
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 1.25rem; font-size: 0.85rem;
}
.breadcrumb a { color: var(--ocean); text-decoration: none; }
.breadcrumb a:hover { text-decoration: underline; }
.breadcrumb .sep { color: var(--muted); margin: 0 0.25rem; }
.cast-pill {
  display: inline-block; background: #4a6fa5; color: #fff;
  padding: 0.2rem 0.6rem; border-radius: 999px;
  font-size: 0.78rem; text-decoration: none; margin: 0.1rem 0.05rem;
}
.cast-pill:hover { opacity: 0.85; }
</style>
</head>
<body>
<div id="top"></div>

<div class="topbar">
  <nav class="breadcrumb">
    <a href="../index.html">Index</a>
    <span class="sep">›</span>
    <a href="../sections.html">Sections</a>
    <span class="sep">›</span>
    <span>{{ section_name }}</span>
  </nav>
  <div class="nav-btns">
    {% if prev_name %}<a class="btn-nav" href="section_{{ prev_name }}.html">← {{ prev_name }}</a>{% endif %}
    {% if next_name %}<a class="btn-nav" href="section_{{ next_name }}.html">{{ next_name }} →</a>{% endif %}
  </div>
</div>

<div class="masthead" style="background:#8e44ad;">
  <div class="masthead-header">
    <h1>{{ section_name }}</h1>
    <span class="masthead-type">Section</span>
  </div>
  <p class="sub" style="margin:0 0 0.6rem; text-align:right;">generated {{ generated_at }}</p>
  <div style="margin-top:0.65rem;margin-bottom:0.5rem">
    <span style="font-size:0.72rem;opacity:0.75;margin-right:0.3rem;">Pages:</span>
    <a href="../index.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#2980b9">Summary</a>
    <a href="../station_index.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#1a3a5c">Stations</a>
    <a href="../sections.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#8e44ad;opacity:0.55">Sections</a>
    <a href="../timeseries.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#27ae60">Timeseries</a>
    <a href="../leaflet.html" style="display:inline-block;padding:0.2em 0.65em;border-radius:4px;font-size:0.78rem;font-weight:700;text-decoration:none;color:#fff;margin:0 0.2rem 0.25rem 0;background:#EE3377">Interactive</a>
  </div>
  <dl class="meta-grid">
    <div><dt>Cruise</dt><dd>{{ cruise }}</dd></div>
    <div><dt>Ship</dt><dd>{{ ship }}</dd></div>
    <div><dt>Description</dt><dd>{{ section_description }}</dd></div>
    <div><dt>CTD casts</dt><dd>{{ cast_list_str }}</dd></div>
    <div><dt>Distance</dt><dd>{{ dist_str }}</dd></div>
    <div><dt>Max depth</dt><dd>{{ p_max_str }}</dd></div>
    <div><dt>Start position</dt><dd>{{ start_pos }}</dd></div>
    <div><dt>Start time</dt><dd>{{ start_time }}</dd></div>
    <div><dt>End position</dt><dd>{{ end_pos }}</dd></div>
    <div><dt>End time</dt><dd>{{ end_time }}</dd></div>
  </dl>
</div>

<div class="jump-nav">
  {% if fig_map_b64 %}<a href="#s-map">Map</a>{% endif %}
  {% if physics_panels | selectattr("b64") | list %}<a href="#s-physics">Hydrography</a>{% endif %}
  {% if biogeo_panels | selectattr("b64") | list %}<a href="#s-biogeo">Biogeochemistry</a>{% endif %}
  {% for card in extra_cards %}<a href="#s-{{ card.id }}">{{ card.short }}</a>{% endfor %}
</div>

<div style="margin-bottom:1rem;">
  {% for cn in cast_nums %}
  <a class="cast-pill" href="../stations/cast_{{ cn }}.html">{{ cn }}</a>
  {% endfor %}
</div>

{% if fig_map_b64 %}
<h2 id="s-map">Map</h2>
<div class="fig-row">
  <figure class="slot-third">
    <img src="data:image/png;base64,{{ fig_map_b64 }}" alt="Section map">
  </figure>
</div>
{% endif %}

{% macro section_panel_group(panels, slot, anchor, heading) %}
{% if panels | selectattr("b64") | list %}
{% if heading %}<h2 id="{{ anchor }}">{{ heading }}</h2>{% endif %}
{% if slot == "slot-third" %}
<div class="fig-row">
  {% for panel in panels %}{% if panel.b64 %}
  <figure class="{{ slot }}">
    <img src="data:image/png;base64,{{ panel.b64 }}" alt="{{ panel.title }}">
    <figcaption>{{ panel.short }}</figcaption>
  </figure>
  {% endif %}{% endfor %}
</div>
{% elif slot == "slot-half" %}
{% for row in panels | batch(2, None) %}
<div class="fig-row">
  {% for panel in row %}{% if panel and panel.b64 %}
  <figure class="{{ slot }}">
    <img src="data:image/png;base64,{{ panel.b64 }}" alt="{{ panel.title }}">
    <figcaption>{{ panel.short }}</figcaption>
  </figure>
  {% endif %}{% endfor %}
</div>
{% endfor %}
{% else %}
{% for panel in panels %}{% if panel.b64 %}
<div class="fig-row">
  <figure class="{{ slot }}">
    <img src="data:image/png;base64,{{ panel.b64 }}" alt="{{ panel.title }}">
  </figure>
</div>
{% endif %}{% endfor %}
{% endif %}
{% endif %}
{% endmacro %}

{{ section_panel_group(physics_panels, section_slot, "s-physics", "Hydrography") }}
{{ section_panel_group(biogeo_panels, section_slot, "s-biogeo", "Biogeochemistry") }}

{% for card in extra_cards %}
<h2 id="s-{{ card.id }}">{{ card.title }}</h2>
{% if card.id == "ladcp" %}
{{ section_panel_group(card.panels, section_slot, "", "") }}
{% elif card.panels | length == 1 %}
<div class="fig-row">
  <figure class="{{ section_slot }}">
    <img src="data:image/png;base64,{{ card.panels[0].b64 }}" alt="{{ card.panels[0].title }}">
  </figure>
</div>
{% else %}
<div class="fig-row">
  {% for panel in card.panels %}
  <figure class="slot-third">
    <img src="data:image/png;base64,{{ panel.b64 }}" alt="{{ panel.title }}">
    <figcaption>{{ panel.title }}</figcaption>
  </figure>
  {% endfor %}
</div>
{% endif %}
{% endfor %}

"""
    + _tmpl.FOOTER_TAIL
    + _JS_TOP_LINKS
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
    dbar_step: int = 1,
    prev_name: str | None = None,
    next_name: str | None = None,
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
    dbar_step:
        Subsample the pressure axis by this step before plotting (default 1,
        no subsampling).  ``build_profiles()`` always stores 1-dbar data;
        this controls plot-time resolution only.
    prev_name:
        Name of the preceding section (for the ← nav button).  None omits the button.
    next_name:
        Name of the following section (for the → nav button).  None omits the button.

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
    if dbar_step > 1:
        p_idx = np.arange(0, ds_sec.sizes["pressure"], dbar_step)
        ds_sec = ds_sec.isel(pressure=p_idx)
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
    ship = ds_all.attrs.get(
        "ship", ds_all.attrs.get("platform", ds_all.attrs.get("vessel", "UNK"))
    )
    dist_str = f"{x_vals.max():.1f} km" if len(x_vals) > 1 else "—"
    cast_nums_int = [int(c) for c in sec_cast_nums]
    vmin = vmin_override or {}
    vmax = vmax_override or {}

    # Compute section figsize and CSS slot from section extent.
    # Use valid-data extent, not pressure coordinate max — the coordinate spans the full
    # cruise depth (e.g. 2200 dbar) even for shallow sections like KO (450 dbar).
    _dist_km = abs(float(x_vals[-1] - x_vals[0])) if len(x_vals) > 1 else 1.0
    _ref_var = next((v for v in ("CT", "SA") if v in ds_sec), None)
    if _ref_var is not None:
        _ref_data = ds_sec[_ref_var].values
        _valid_p = np.where(np.any(np.isfinite(_ref_data), axis=0))[0]
        _p_max_sec = (
            float(ds_sec["pressure"].values[_valid_p[-1]])
            if len(_valid_p)
            else float(ds_sec["pressure"].values.max())
        )
    else:
        _p_max_sec = float(ds_sec["pressure"].values.max())
    section_figsize, section_slot = section_figsize_and_slot(_p_max_sec, _dist_km)

    # Start/end position and time from first/last downcast
    def _latlon_str(lat: float, lon: float) -> str:
        lat_h = "N" if lat >= 0 else "S"
        lon_h = "E" if lon >= 0 else "W"
        return f"{abs(lat):.4f}°{lat_h}, {abs(lon):.4f}°{lon_h}"

    _lat0, _lon0 = float(lats[0]), float(lons[0])
    _lat1, _lon1 = float(lats[-1]), float(lons[-1])
    _ts_vals = ds_sec["time_start"].values if "time_start" in ds_sec else None
    _te_vals = ds_sec["time_end"].values if "time_end" in ds_sec else None
    start_pos = _latlon_str(_lat0, _lon0)
    end_pos = _latlon_str(_lat1, _lon1)
    start_time = (
        _fmt_utc(_ts_vals[0]) if _ts_vals is not None and len(_ts_vals) else "—"
    )
    end_time = _fmt_utc(_te_vals[-1]) if _te_vals is not None and len(_te_vals) else "—"

    def _section_panel(var: str, label: str, short: str) -> dict:
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
            figsize=section_figsize,
        )
        return {"title": label, "short": short, "b64": b64}

    physics_panels = [_section_panel(v, l, s) for v, l, s in _PHYSICS_VARS]
    biogeo_panels = [_section_panel(v, l, s) for v, l, s in _BIOGEO_VARS]

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
    _ladcp_u_b64, _ladcp_v_b64 = (
        _make_ladcp_section_b64(
            cast_nums_int,
            x_vals,
            x_label,
            ladcp_dir,
            lats=lats,
            lons=lons,
            ladcp_pattern=ladcp_pattern,
            style=section_style,
        )
        if ladcp_dir is not None
        else (None, None)
    )
    _ladcp_panels = [
        p
        for p in (
            {"b64": _ladcp_u_b64, "title": "U velocity (east +)"},
            {"b64": _ladcp_v_b64, "title": "V velocity (north +)"},
        )
        if p["b64"]
    ]
    _extra_raw: dict[str, dict | None] = {
        "ladcp": {
            "id": "ladcp",
            "title": "Velocity (U east, V north)",
            "short": "Velocity",
            "panels": _ladcp_panels,
        }
        if _ladcp_panels
        else None,
        "ts": {
            "id": "ts",
            "title": "T–S diagrams",
            "short": "T–S diagram",
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
        "ship": ship,
        "p_max_str": f"{_p_max_sec:.0f} dbar",
        "start_pos": start_pos,
        "end_pos": end_pos,
        "start_time": start_time,
        "end_time": end_time,
        "cast_nums": [f"{n:03d}" for n in cast_nums_int],
        "fig_map_b64": _make_section_map_b64(
            lats, lons, cast_nums_int, title=section_name
        ),
        "section_slot": section_slot,
        "physics_panels": physics_panels,
        "biogeo_panels": biogeo_panels,
        "extra_cards": extra_cards,
        "prev_name": prev_name or "",
        "next_name": next_name or "",
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
