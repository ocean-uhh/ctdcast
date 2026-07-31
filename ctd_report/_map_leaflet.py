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
from typing import Any

import numpy as np
from jinja2 import Environment

from ctd_report import _templates as _tmpl
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
_GEBCO_PAD = 2.0  # degrees of context beyond data extent

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
    section_url: str | None,
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
# Ship track loader
# ---------------------------------------------------------------------------


def _load_ship_track(
    ship_track_nc: Path,
    max_points: int = 2000,
) -> list | None:
    """Subsample a ship-track netCDF and return ``[[lat, lon], ...]``.

    Filters invalid positions and returns None if the file is unreadable or
    contains no valid positions.  ``max_points`` caps the output size so the
    embedded GeoJSON stays small.
    """
    try:
        import xarray as xr

        ds = xr.open_dataset(str(ship_track_nc), engine="netcdf4")
        lats = ds["latitude"].values.astype(float)
        lons = ds["longitude"].values.astype(float)
        ds.close()

        valid = (
            np.isfinite(lats)
            & np.isfinite(lons)
            & (np.abs(lats) <= 90)
            & (np.abs(lons) <= 180)
        )
        lats, lons = lats[valid], lons[valid]
        if len(lats) == 0:
            return None

        step = max(1, len(lats) // max_points)
        lats = lats[::step]
        lons = lons[::step]
        return [
            [round(float(la), 5), round(float(lo), 5)] for la, lo in zip(lats, lons)
        ]
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Depth legend HTML builder
# ---------------------------------------------------------------------------


def _depth_legend_html() -> str:
    """Return pre-rendered HTML rows for the depth-band legend panel.

    Colours match the Blues LUT used in ``_make_gebco_layers``:
    ``Blues(linspace(0.15, 0.95, n_bins))`` where bin 0 is shallowest.
    """
    import matplotlib.pyplot as plt

    n_bins = len(_DEPTH_LEVELS) - 1
    blues = plt.cm.Blues(np.linspace(0.15, 0.95, n_bins))
    parts = ['<div class="dl-title">Depth&nbsp;(m)</div>']
    for i in range(n_bins):
        d0 = int(_DEPTH_LEVELS[i])
        d1 = int(_DEPTH_LEVELS[i + 1])
        r, g, b = (int(blues[i, k] * 255) for k in range(3))
        hex_c = f"#{r:02x}{g:02x}{b:02x}"
        label = f"{d0}–{d1}" if d1 < 6000 else f"&gt;{d0}"
        parts.append(
            f'<div class="dl-row">'
            f'<span class="dl-swatch" style="background:{hex_c}"></span>'
            f"{label}</div>"
        )
    # Land swatch — colour must match rgba[~ocean_merc] assignment in _make_gebco_layers.
    parts.append(
        '<div class="dl-row">'
        '<span class="dl-swatch" style="background:#afb99b"></span>'
        "Land</div>"
    )
    return "".join(parts)


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

# Max pixels in either dimension for the shared fill+contour grid.
# Both the raster fill and the GeoJSON contours use this same grid,
# guaranteeing that fill-band edges and contour lines are co-located.
_CONTOUR_MAX_PX = 600


def _make_gebco_layers(
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
) -> tuple[str | None, str | None, list | None]:
    """Load GEBCO once and return (raster_b64, contour_geojson, bounds).

    ``raster_b64`` — base64 PNG of discrete depth bands, reprojected to Web
    Mercator.  ``L.imageOverlay`` stretches images linearly in Mercator pixel
    space, so without reprojection a geographic (equirectangular) image appears
    shifted northward relative to GeoJSON features at 60 °N by ~0.035 °
    (~4 km) — visible on screen.  We fix this by building the image on a grid
    that is uniformly spaced in Mercator Y, so each row maps directly to its
    correct Mercator pixel position.

    ``contour_geojson`` — GeoJSON FeatureCollection of LineString features at
    100 m intervals.  Each feature has properties ``depth`` (positive metres)
    and ``major`` (True for multiples of 500 m).

    ``bounds`` — ``[[south, west], [north, east]]`` geographic degrees for the
    Leaflet ``imageOverlay``.

    Any returned value is None when GEBCO is unavailable or rendering fails.
    """
    from ctd_report import _plots as plots

    if plots.GEBCO_PATH is None or not Path(str(plots.GEBCO_PATH)).exists():
        return None, None, None

    try:
        import matplotlib.pyplot as plt
        import xarray as xr

        ds = xr.open_dataset(str(plots.GEBCO_PATH), engine="netcdf4")
        ds_region = ds.sel(
            lat=slice(lat_min - _GEBCO_PAD, lat_max + _GEBCO_PAD),
            lon=slice(lon_min - _GEBCO_PAD, lon_max + _GEBCO_PAD),
        )
        elev = ds_region["elevation"].values.astype(np.float32)  # +up, (lat, lon)
        lat_vals = ds_region["lat"].values  # ascending S→N
        lon_vals = ds_region["lon"].values  # ascending W→E
        ds.close()

        if elev.size == 0:
            return None, None, None

        ny, nx = elev.shape

        # Geographic pixel-edge bounds (cell centres ± half cell).
        dlat = abs(float(lat_vals[1] - lat_vals[0])) if ny > 1 else 1 / 240
        dlon = abs(float(lon_vals[1] - lon_vals[0])) if nx > 1 else 1 / 240
        south_b = float(lat_vals[0]) - dlat / 2
        north_b = float(lat_vals[-1]) + dlat / 2
        west_b = float(lon_vals[0]) - dlon / 2
        east_b = float(lon_vals[-1]) + dlon / 2
        actual_bounds: list = [[south_b, west_b], [north_b, east_b]]

        # --- Raster: Mercator-reprojected discrete depth-band PNG ---
        # Build output image on a grid that is UNIFORMLY SPACED in Mercator Y
        # so each row maps to its correct Mercator screen position.
        n_rows = min(ny, 1024)
        n_cols = min(nx, 1024)

        y_n = float(np.log(np.tan(np.pi / 4 + np.radians(north_b) / 2)))
        y_s = float(np.log(np.tan(np.pi / 4 + np.radians(south_b) / 2)))

        # Row 0 = northernmost (image top), row n_rows-1 = southernmost.
        merc_y_rows = np.linspace(y_n, y_s, n_rows)
        # Inverse-project each row's Mercator Y back to geographic latitude.
        geo_lats_rows = np.degrees(2 * np.arctan(np.exp(merc_y_rows)) - np.pi / 2)
        # Longitude is linear in Mercator, so cols stay geographic.
        geo_lons_cols = np.linspace(west_b, east_b, n_cols)

        # Nearest-neighbour lookup of GEBCO elevation on the Mercator grid.
        row_idx = np.clip(
            np.searchsorted(lat_vals, geo_lats_rows, side="right") - 1, 0, ny - 1
        )
        col_idx = np.clip(
            np.searchsorted(lon_vals, geo_lons_cols, side="right") - 1, 0, nx - 1
        )
        # elev_merc[i, j] = GEBCO elevation at (geo_lats_rows[i], geo_lons_cols[j])
        elev_merc = elev[np.ix_(row_idx, col_idx)]  # (n_rows, n_cols)

        ocean_merc = elev_merc < 0
        depth_merc = np.where(ocean_merc, -elev_merc, 0.0).astype(np.float32)
        n_bins = len(_DEPTH_LEVELS) - 1
        lut = (plt.cm.Blues(np.linspace(0.15, 0.95, n_bins)) * 255).astype(np.uint8)
        bin_idx = np.clip(
            np.searchsorted(_DEPTH_LEVELS[1:], depth_merc), 0, n_bins - 1
        ).astype(np.intp)
        rgba = lut[bin_idx]  # (n_rows, n_cols, 4)
        rgba[~ocean_merc] = [175, 185, 155, 255]  # land colour

        buf = io.BytesIO()
        plt.imsave(buf, rgba, format="png")
        raster_b64: str | None = base64.b64encode(buf.getvalue()).decode("ascii")

        # --- Contours: vector GeoJSON at 100 m intervals ---
        cy = max(1, round(ny / _CONTOUR_MAX_PX))
        cx = max(1, round(nx / _CONTOUR_MAX_PX))
        elev_c = elev[::cy, ::cx]
        lats_c = lat_vals[::cy]
        lons_c = lon_vals[::cx]

        max_depth = int(-elev_c[elev_c < 0].min()) if (elev_c < 0).any() else 0
        contour_geojson: str | None = None

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
                    coords = [[round(float(x), 4), round(float(y), 4)] for x, y in seg]
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

        return raster_b64, contour_geojson, actual_bounds

    except Exception:  # noqa: BLE001
        return None, None, None


# ---------------------------------------------------------------------------
# JSON helper
# ---------------------------------------------------------------------------


def _safe_json(obj: Any) -> str:
    """JSON-encode obj, escaping ``</`` for safe embedding inside a <script> block."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_LEAFLET_TEMPLATE = (
    """\
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
  .cast-label {
    font-size: 8px; font-weight: 600; color: #111; white-space: nowrap;
    pointer-events: none; line-height: 1;
    text-shadow: 0 0 2px #fff, 0 0 2px #fff;
  }
  #depth-legend {
    position: fixed; bottom: 50px; right: 12px; z-index: 1500;
    background: #fff; border-radius: 6px; padding: 0.5rem 0.7rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.18); font-size: 0.72rem; color: #1a1a2e;
    line-height: 1.4;
  }
  #depth-legend .dl-title { font-weight: 700; margin-bottom: 0.25rem; }
  #depth-legend .dl-row { display: flex; align-items: center; gap: 5px; margin: 1px 0; }
  #depth-legend .dl-swatch { width: 12px; height: 9px; flex-shrink: 0; border: 1px solid rgba(0,0,0,0.12); }
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
{% if depth_legend_html %}<div id="depth-legend">{{ depth_legend_html }}</div>{% endif %}
"""
    + _tmpl.FOOTER_LINE
    + """

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
var SHIP_TRACK   = {{ ship_track_json }};
var DATA_BOUNDS  = [[{{ lat_min }}, {{ lon_min }}], [{{ lat_max }}, {{ lon_max }}]];

var map = L.map('map', { zoomSnap: 0.25, zoomControl: false });
L.control.zoom({ position: 'topright' }).addTo(map);
map.fitBounds(DATA_BOUNDS, { padding: [40, 40] });

if (GEBCO_B64) {
  L.imageOverlay('data:image/png;base64,' + GEBCO_B64, GEBCO_BOUNDS, {
    opacity: 1.0, interactive: false
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

if (SHIP_TRACK && SHIP_TRACK.length > 1) {
  L.polyline(SHIP_TRACK, {
    color: '#888', weight: 1.5, opacity: 0.45, interactive: false
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

  // Cast number label offset just to the right of the dot
  L.marker([c.lat, c.lon], {
    icon: L.divIcon({
      className: '',
      html: '<span class="cast-label">' + c.num + '</span>',
      iconAnchor: [-9, 4],
    }),
    interactive: false,
    keyboard: false,
  }).addTo(map);
});
</script>
</body>
</html>"""
)


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def generate_leaflet_map(
    all_meta: list[dict[str, Any]],
    sections_cfg: dict[str, Any],
    out_dir: Path,
    force: bool = False,
    ship_track_nc: Path | None = None,
) -> Path | None:
    """Generate a Leaflet.js interactive cruise map at ``<out_dir>/leaflet.html``.

    Always regenerates (force is accepted for API symmetry but ignored).
    If ``ship_track_nc`` is provided and the file exists, the ship track is
    loaded, subsampled, and rendered as a grey polyline behind cast markers.
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
                "num": cn,
                "url": f"stations/cast_{cn:03d}.html",
                "info": _cast_panel_html(m, sname_c, section_url),
            }
        )

    print("  leaflet: rendering GEBCO...", end=" ", flush=True)
    gebco_b64, contour_geojson, actual_bounds = _make_gebco_layers(
        lat_min, lat_max, lon_min, lon_max
    )
    if gebco_b64:
        n_features = contour_geojson.count('"Feature"') if contour_geojson else 0
        print(f"ok ({n_features} contour segments)")
    else:
        print("unavailable (no bathymetry layer)")

    gebco_bounds = actual_bounds or [
        [lat_min - _GEBCO_PAD, lon_min - _GEBCO_PAD],
        [lat_max + _GEBCO_PAD, lon_max + _GEBCO_PAD],
    ]

    ship_track: list | None = None
    if ship_track_nc is not None and ship_track_nc.exists():
        print("  leaflet: loading ship track...", end=" ", flush=True)
        ship_track = _load_ship_track(ship_track_nc)
        if ship_track:
            print(f"ok ({len(ship_track)} points)")
        else:
            print("failed (no valid positions)")

    depth_legend: str = _depth_legend_html() if gebco_b64 else ""

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
        contours_json=contour_geojson.replace("</", "<\\/")
        if contour_geojson
        else "null",
        ship_track_json=_safe_json(ship_track or []),
        depth_legend_html=depth_legend,
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
