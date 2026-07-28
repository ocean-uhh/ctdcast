"""Tier-2: self-contained interactive cruise map using Leaflet.js.

Leaflet JS/CSS (~160 KB) is bundled in ``ctd_report/leaflet/`` as package
data so the generated ``leaflet.html`` requires no internet access at either
generation or view time.

If ``ctd_report._plots.GEBCO_PATH`` is set, GEBCO bathymetry for the cruise
region is rendered as an embedded PNG image layer using discrete depth bands
(standard oceanographic levels: 0, 100, 200, 500, 1000, 2000, 3000, 4000,
6000 m).

Interaction:
  - Hover cast dot or section line → info panel updates (bottom-left).
  - Click cast dot → navigate directly to station page.
  - Click section line → navigate directly to section page.
  - Scroll or +/− buttons to zoom.
  - Shift+drag to box-zoom (Leaflet built-in).
"""

from __future__ import annotations

import base64
import io
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
from jinja2 import Environment

from ctd_report._section import _expand_cast_numbers
from ctd_report._version import __version__ as _VERSION

_SECTION_COLOR_DEFAULT = "#7b2d8b"
_LEAFLET_VERSION = "1.9.4"
_LEAFLET_JS_URLS = [
    f"https://cdn.jsdelivr.net/npm/leaflet@{_LEAFLET_VERSION}/dist/leaflet.min.js",
    f"https://cdnjs.cloudflare.com/ajax/libs/leaflet/{_LEAFLET_VERSION}/leaflet.min.js",
]
_LEAFLET_CSS_URLS = [
    f"https://cdn.jsdelivr.net/npm/leaflet@{_LEAFLET_VERSION}/dist/leaflet.min.css",
    f"https://cdnjs.cloudflare.com/ajax/libs/leaflet/{_LEAFLET_VERSION}/leaflet.min.css",
]
_LEAFLET_JS_URL = _LEAFLET_JS_URLS[0]
_LEAFLET_CSS_URL = _LEAFLET_CSS_URLS[0]

_LEAFLET_DIR = Path(__file__).parent / "leaflet"
_GEBCO_PAD = 0.5  # degrees of context beyond data extent

# Discrete depth levels (metres, positive down).  Bin i spans [levels[i], levels[i+1]).
_DEPTH_LEVELS = np.array(
    [0, 100, 200, 500, 1000, 2000, 3000, 4000, 6000], dtype=np.float32
)


# ---------------------------------------------------------------------------
# Info-panel HTML helpers
# ---------------------------------------------------------------------------


def _cast_panel_html(
    m: dict[str, Any],
    section_name: str,
    section_url: Optional[str],
) -> str:
    """Return HTML for the info panel when a cast marker is hovered."""
    cn = int(m["cast_num"])
    cast_url = f"stations/cast_{cn:03d}.html"
    dt = str(m.get("time_start", ""))[:16].replace("T", " ")
    lat = float(m.get("lat", float("nan")))
    lon = float(m.get("lon", float("nan")))
    depth = float(m.get("max_depth", 0))
    lat_str = f"{abs(lat):.4f}°{'N' if lat >= 0 else 'S'}"
    lon_str = f"{abs(lon):.4f}°{'E' if lon >= 0 else 'W'}"

    parts = [
        f"<strong>Cast {cn:03d}</strong>",
        dt or "—",
        f"{lat_str} &nbsp; {lon_str}",
        f"{depth:.0f} dbar",
    ]
    if section_name:
        parts.append(f"Section: {section_name}")

    html = "<br>".join(parts)
    html += f'<br><a href="{cast_url}">→ Station page</a>'
    if section_name and section_url:
        html += f'<br><a href="{section_url}">→ Section page</a>'
    return html


def _section_panel_html(
    section_name: str,
    scfg: dict[str, Any],
    n_found: int,
) -> str:
    """Return HTML for the info panel when a section line is hovered."""
    section_url = f"sections/section_{section_name}.html"
    desc = scfg.get("description", "")
    parts = [f"<strong>{section_name}</strong>"]
    if desc:
        parts.append(desc)
    parts.append(f"{n_found} casts")
    html = "<br>".join(parts)
    html += f'<br><a href="{section_url}">→ Section page</a>'
    return html


# ---------------------------------------------------------------------------
# Leaflet bundled asset loader
# ---------------------------------------------------------------------------


def _load_leaflet() -> tuple[str, str]:
    """Return (js_text, css_text) from bundled package files.

    Falls back to CDN fetch if bundled files are absent (requires internet at
    generation time).  Returns empty strings only if all sources fail.
    """
    js_path = _LEAFLET_DIR / "leaflet.min.js"
    css_path = _LEAFLET_DIR / "leaflet.min.css"

    if js_path.exists() and css_path.exists():
        return js_path.read_text(encoding="utf-8"), css_path.read_text(encoding="utf-8")

    for url_js, url_css in zip(_LEAFLET_JS_URLS, _LEAFLET_CSS_URLS):
        try:
            with urllib.request.urlopen(url_js, timeout=10) as r:
                js = r.read().decode("utf-8")
            with urllib.request.urlopen(url_css, timeout=10) as r:
                css = r.read().decode("utf-8")
            return js, css
        except Exception:  # noqa: BLE001
            continue
    return "", ""


# ---------------------------------------------------------------------------
# GEBCO rendering — discrete depth bands + vector contours
# ---------------------------------------------------------------------------

# Max pixels in either dimension for the contour grid.  Smaller than the
# raster max_px to keep the embedded GeoJSON compact (~400–500 KB).
_CONTOUR_MAX_PX = 400


def _make_gebco_layers(
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    raster_max_px: int = 1024,
) -> tuple[Optional[str], Optional[str]]:
    """Load GEBCO once and return (raster_b64, contour_geojson).

    ``raster_b64`` — base64 PNG with discrete depth-band fill (Blues colormap,
    levels from ``_DEPTH_LEVELS``).

    ``contour_geojson`` — GeoJSON FeatureCollection of LineString features at
    100 m intervals.  Each feature has properties ``depth`` (positive metres)
    and ``major`` (True for multiples of 500 m).  The Leaflet style function
    uses ``major`` to set line weight and opacity.

    Either value is None when GEBCO is unavailable or rendering fails.
    """
    from ctd_report import _plots as plots  # noqa: PLC0415

    if plots.GEBCO_PATH is None or not Path(str(plots.GEBCO_PATH)).exists():
        return None, None

    try:
        import matplotlib.pyplot as plt  # noqa: PLC0415
        import xarray as xr  # noqa: PLC0415

        ds = xr.open_dataset(str(plots.GEBCO_PATH), engine="netcdf4")
        ds_region = ds.sel(
            lat=slice(lat_min - _GEBCO_PAD, lat_max + _GEBCO_PAD),
            lon=slice(lon_min - _GEBCO_PAD, lon_max + _GEBCO_PAD),
        )
        elev = ds_region["elevation"].values.astype(np.float32)  # +up, (lat, lon)
        lat_vals = ds_region["lat"].values
        lon_vals = ds_region["lon"].values
        ds.close()

        if elev.size == 0:
            return None, None

        ny, nx = elev.shape

        # --- Raster: discrete depth-band PNG ---
        ocean = elev < 0
        land = ~ocean

        n_bins = len(_DEPTH_LEVELS) - 1
        lut = (plt.cm.Blues(np.linspace(0.15, 0.95, n_bins)) * 255).astype(np.uint8)

        depth_px = np.where(ocean, -elev, 0.0).astype(np.float32)
        bin_idx = np.clip(
            np.searchsorted(_DEPTH_LEVELS[1:], depth_px), 0, n_bins - 1
        ).astype(np.intp)

        rgba = lut[bin_idx]  # (ny, nx, 4)
        rgba[land] = [175, 185, 155, 255]

        rgba_png = rgba[::-1, :, :] if lat_vals[0] < lat_vals[-1] else rgba
        step_y = max(1, ny // raster_max_px)
        step_x = max(1, nx // raster_max_px)
        rgba_png = np.ascontiguousarray(rgba_png[::step_y, ::step_x])

        buf = io.BytesIO()
        plt.imsave(buf, rgba_png, format="png")
        raster_b64: Optional[str] = base64.b64encode(buf.getvalue()).decode("ascii")

        # --- Contours: vector GeoJSON at 100 m intervals ---
        cy = max(1, round(ny / _CONTOUR_MAX_PX))
        cx = max(1, round(nx / _CONTOUR_MAX_PX))
        elev_c = elev[::cy, ::cx]
        lats_c = lat_vals[::cy]
        lons_c = lon_vals[::cx]

        max_depth = int(-elev_c[elev_c < 0].min()) if (elev_c < 0).any() else 0
        contour_geojson: Optional[str] = None

        if max_depth >= 100:
            levels_m = list(range(100, min(max_depth + 100, 6100), 100))
            # matplotlib contour requires ascending levels; elevation is negative
            elev_levels = sorted([-d for d in levels_m])

            fig, ax = plt.subplots()
            cs = ax.contour(lons_c, lats_c, elev_c, levels=elev_levels)
            plt.close(fig)

            features = []
            for level_val, segs in zip(cs.levels, cs.allsegs):
                depth_m = round(-level_val)
                is_major = depth_m % 500 == 0
                for seg in segs:
                    if len(seg) < 2:
                        continue
                    seg = seg[::2]  # thin by 2× for compactness
                    coords = [
                        [round(float(x), 4), round(float(y), 4)] for x, y in seg
                    ]
                    features.append(
                        {
                            "type": "Feature",
                            "geometry": {"type": "LineString", "coordinates": coords},
                            "properties": {"depth": depth_m, "major": is_major},
                        }
                    )

            contour_geojson = json.dumps(
                {"type": "FeatureCollection", "features": features}
            )

        return raster_b64, contour_geojson

    except Exception:  # noqa: BLE001
        return None, None


# ---------------------------------------------------------------------------
# JSON helper
# ---------------------------------------------------------------------------


def _safe_json(obj: Any) -> str:
    """JSON-encode obj, escaping ``</`` for safe embedding inside a <script> block."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_LEAFLET_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cruise Map — {{ cruise | e }}</title>
{% if leaflet_inline %}
<style>
{{ leaflet_css }}
</style>
{% else %}
<link rel="stylesheet" href="{{ leaflet_css_url }}">
{% endif %}
<style>
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, sans-serif; background: #f5f7fa; }
  header {
    background: #1a3a5c; color: #fff; padding: 0.6rem 1.5rem;
    display: flex; align-items: center; gap: 1.5rem; height: 48px;
    position: relative; z-index: 2000;
  }
  header strong { font-size: 1rem; }
  header a { color: #aed6f1; text-decoration: none; font-size: 0.85rem; }
  header a:hover { text-decoration: underline; }
  #map { width: 100%; height: calc(100vh - 74px); }
  .gebco-layer { image-rendering: pixelated; image-rendering: crisp-edges; }
  #info-panel {
    position: fixed; bottom: 50px; left: 12px; z-index: 1500;
    background: #fff; border-radius: 8px; padding: 0.8rem 1rem;
    box-shadow: 0 2px 10px rgba(0,0,0,0.2); max-width: 240px; min-width: 170px;
    font-size: 0.82rem; line-height: 1.6; color: #1a1a2e; pointer-events: all;
  }
  #info-panel.empty { color: #aaa; font-style: italic; }
  #info-panel a { display: block; margin-top: 0.3rem; color: #1a3a5c; font-weight: 600; text-decoration: none; }
  #info-panel a:hover { text-decoration: underline; }
  footer { text-align: center; padding: 0.35rem; font-size: 0.72rem; color: #999; background: #fff; border-top: 1px solid #e0e0e0; }
</style>
</head>
<body>

<header>
  <strong>Cruise Map — {{ cruise | e }}</strong>
  <a href="index.html">← Index</a>
  <a href="station_index.html">Stations</a>
  <a href="sections.html">Sections</a>
  <a href="timeseries.html">Timeseries</a>
</header>

<div id="map"></div>
<div id="info-panel" class="empty">Hover over a cast or section.</div>
<footer>Generated by ctd_report v{{ version }} &nbsp;·&nbsp; {{ cruise | e }} &nbsp;·&nbsp; {{ generated_at }}</footer>

{% if leaflet_inline %}
<script>{{ leaflet_js }}</script>
{% else %}
<script src="{{ leaflet_js_url }}"></script>
{% endif %}
<script>
var CASTS    = {{ casts_json }};
var SECTIONS = {{ sections_json }};
var GEBCO_B64    = {{ gebco_b64_json }};
var GEBCO_BOUNDS = {{ gebco_bounds_json }};
var CONTOURS     = {{ contours_json }};
var DATA_BOUNDS  = [[{{ lat_min }}, {{ lon_min }}], [{{ lat_max }}, {{ lon_max }}]];

var map = L.map('map', { zoomSnap: 0.25, zoomControl: false });
L.control.zoom({ position: 'topright' }).addTo(map);
map.fitBounds(DATA_BOUNDS, { padding: [40, 40] });

if (GEBCO_B64) {
  L.imageOverlay('data:image/png;base64,' + GEBCO_B64, GEBCO_BOUNDS, {
    opacity: 1.0, interactive: false, className: 'gebco-layer'
  }).addTo(map);
}

if (CONTOURS) {
  L.geoJSON(CONTOURS, {
    interactive: false,
    style: function(feature) {
      var major = feature.properties.major;
      return {
        color: '#1a1a2e',
        weight: major ? 1.2 : 0.4,
        opacity: major ? 0.6 : 0.35,
      };
    }
  }).addTo(map);
}

var panel = document.getElementById('info-panel');
function showPanel(html) {
  panel.className = '';
  panel.innerHTML = html;
}

SECTIONS.forEach(function(s) {
  L.polyline(s.latlons, { color: s.color, weight: 3, opacity: 0.85 })
    .on('mouseover', function() { showPanel(s.info); })
    .on('click',     function() { window.location.href = s.url; })
    .addTo(map);
});

CASTS.forEach(function(c) {
  L.circleMarker([c.lat, c.lon], {
    radius: 7, color: 'white', weight: 1.5, fillColor: c.color, fillOpacity: 0.92
  })
    .on('mouseover', function() { showPanel(c.info); })
    .on('click',     function() { window.location.href = c.url; })
    .addTo(map);
});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def generate_leaflet_map(
    all_meta: list[dict[str, Any]],
    sections_cfg: dict[str, Any],
    out_dir: Path,
    force: bool = False,  # noqa: ARG001
) -> Optional[Path]:
    """Generate a Leaflet.js interactive cruise map at ``<out_dir>/leaflet.html``.

    Always regenerates (force is accepted for API symmetry but ignored).
    Returns the output path, or None if all_meta is empty.
    """
    if not all_meta:
        return None

    out_file = out_dir / "leaflet.html"
    cruise = str(all_meta[0].get("cruise", "cruise"))

    lats = [
        float(m["lat"])
        for m in all_meta
        if np.isfinite(float(m.get("lat", float("nan"))))
    ]
    lons = [
        float(m["lon"])
        for m in all_meta
        if np.isfinite(float(m.get("lon", float("nan"))))
    ]
    if not lats:
        return None

    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)

    meta_lookup: dict[int, dict[str, Any]] = {int(m["cast_num"]): m for m in all_meta}

    cast_section: dict[int, tuple[str, str]] = {}
    for sname, scfg in sections_cfg.items():
        color = str(scfg.get("color", _SECTION_COLOR_DEFAULT))
        for cn in _expand_cast_numbers(scfg.get("cast_numbers", [])):
            if cn not in cast_section:
                cast_section[cn] = (sname, color)

    sections_data: list[dict[str, Any]] = []
    for sname, scfg in sections_cfg.items():
        color = str(scfg.get("color", _SECTION_COLOR_DEFAULT))
        cast_nums = _expand_cast_numbers(scfg.get("cast_numbers", []))
        latlons: list[list[float]] = []
        for cn in cast_nums:
            if cn in meta_lookup:
                m = meta_lookup[cn]
                latlons.append([float(m["lat"]), float(m["lon"])])
        if len(latlons) < 2:
            continue
        sections_data.append(
            {
                "latlons": latlons,
                "color": color,
                "url": f"sections/section_{sname}.html",
                "info": _section_panel_html(sname, scfg, len(latlons)),
            }
        )

    casts_data: list[dict[str, Any]] = []
    for m in all_meta:
        cn = int(m["cast_num"])
        lat_f = float(m.get("lat", float("nan")))
        lon_f = float(m.get("lon", float("nan")))
        if not (np.isfinite(lat_f) and np.isfinite(lon_f)):
            continue
        sname_c, color_c = cast_section.get(cn, ("", "#888888"))
        section_url = f"sections/section_{sname_c}.html" if sname_c else None
        casts_data.append(
            {
                "lat": lat_f,
                "lon": lon_f,
                "color": color_c,
                "url": f"stations/cast_{cn:03d}.html",
                "info": _cast_panel_html(m, sname_c, section_url),
            }
        )

    print("  leaflet: rendering GEBCO...", end=" ", flush=True)
    gebco_b64 = _make_gebco_b64(lat_min, lat_max, lon_min, lon_max)
    print("ok" if gebco_b64 else "unavailable (no bathymetry layer)")

    gebco_bounds = [
        [lat_min - _GEBCO_PAD, lon_min - _GEBCO_PAD],
        [lat_max + _GEBCO_PAD, lon_max + _GEBCO_PAD],
    ]

    leaflet_js, leaflet_css = _load_leaflet()
    if not leaflet_js:
        print(
            "  leaflet: WARNING — Leaflet JS/CSS not found; "
            "CDN links used (requires internet at view time)"
        )

    env = Environment(autoescape=False)
    html = env.from_string(_LEAFLET_TEMPLATE).render(
        cruise=cruise,
        leaflet_inline=bool(leaflet_js),
        leaflet_js=leaflet_js,
        leaflet_css=leaflet_css,
        leaflet_js_url=_LEAFLET_JS_URL,
        leaflet_css_url=_LEAFLET_CSS_URL,
        casts_json=_safe_json(casts_data),
        sections_json=_safe_json(sections_data),
        gebco_b64_json=_safe_json(gebco_b64),
        gebco_bounds_json=_safe_json(gebco_bounds),
        lat_min=lat_min,
        lat_max=lat_max,
        lon_min=lon_min,
        lon_max=lon_max,
        version=_VERSION,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(html, encoding="utf-8")
    return out_file
