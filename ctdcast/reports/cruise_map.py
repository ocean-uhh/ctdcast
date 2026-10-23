"""Tier-2: self-contained interactive cruise map using Leaflet.js.

Leaflet JS/CSS (~160 KB) is bundled in ``ctdcast/reports/_vendored/leaflet/`` as
package data (shared byte-identical across the sibling packages) so the generated
``leaflet.html`` requires no internet access at either generation or view time.

If a GEBCO path is configured, GEBCO bathymetry for the cruise
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
import importlib.util
import io
import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np

from ctdcast._version import __version__ as _VERSION
from ctdcast.analysis.bathymetry import load_gebco
from ctdcast.config.report_config import DEFAULT_REPORT_CONFIG, ReportConfig
from ctdcast.identity import expand_cast_numbers, format_cast_id
from ctdcast.reports._env import get_template
from ctdcast.reports._format import report_generated_at
from ctdcast.reports._navs import nav_for
from ctdcast.reports._vendored.leaflet import (
    coastline_geojson,
    load_leaflet,
    safe_json,
)
from ctdcast.reports.design import SHARED_CSS

_SECTION_COLOR_DEFAULT = "#7b2d8b"
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
    *,
    with_links: bool = True,
) -> str:
    """Return HTML for the info panel when a cast marker is hovered.

    With ``with_links=False`` the trailing station/section links are omitted, for a
    caller (the vendored ``track_map`` macro) that appends its own link from the
    payload's ``href`` / ``link_label``.
    """
    cn = int(m["cast_num"])
    cast_id = m.get("cast_num_str", format_cast_id(cn))
    cast_url = f"casts/cast_{cast_id}.html"
    dt = str(m.get("time_start", ""))[:16].replace("T", " ")
    lat = float(m.get("lat", float("nan")))
    lon = float(m.get("lon", float("nan")))
    depth = float(m.get("max_depth", 0))
    lat_str = f"{abs(lat):.4f}°{'N' if lat >= 0 else 'S'}"
    lon_str = f"{abs(lon):.4f}°{'E' if lon >= 0 else 'W'}"

    parts = [
        f"<strong>Cast {cast_id}</strong>",
        dt or "—",
        f"{lat_str} &nbsp; {lon_str}",
        f"{depth:.0f} dbar",
    ]
    if section_name:
        parts.append(f"Section: {section_name}")

    html = "<br>".join(parts)
    if with_links:
        html += f'<br><a href="{cast_url}">→ Station page</a>'
        if section_name and section_url:
            html += f'<br><a href="{section_url}">→ Section page</a>'
    return html


def _section_panel_html(
    section_name: str,
    scfg: dict[str, Any],
    n_found: int,
    *,
    with_links: bool = True,
) -> str:
    """Return HTML for the info panel when a section line is hovered.

    With ``with_links=False`` the trailing section link is omitted, for a caller
    (the vendored ``track_map`` macro) that appends its own link from the payload.
    """
    section_url = f"sections/section_{section_name}.html"
    desc = scfg.get("description", "")
    parts = [f"<strong>{section_name}</strong>"]
    if desc:
        parts.append(desc)
    parts.append(f"{n_found} casts")
    html = "<br>".join(parts)
    if with_links:
        html += f'<br><a href="{section_url}">→ Section page</a>'
    return html


#: Casts-map container height (CSS px), passed to the vendored ``map_styles`` macro.
CASTS_MAP_HEIGHT = 420

#: Minimum coastline extent (degrees) for the cast map.  A small open-ocean extent is grown to
#: this span so a zoom-out reveals nearby land (coastlines are cheap — see
#: ``coastline_geojson(min_clip_deg=...)``); the map still opens fitted to the casts.
_COASTLINE_MIN_SPAN_DEG = 10.0

#: Marker colour for a cast that belongs to no section (neutral grey, distinct from any section).
_UNSECTIONED_CAST_COLOR = "#888888"


def _finite_latlon(m: dict[str, Any]) -> bool:
    """Return True when *m* carries a finite latitude and longitude."""
    return bool(
        np.isfinite(float(m.get("lat", np.nan)))
        and np.isfinite(float(m.get("lon", np.nan)))
    )


def casts_map_payload(
    all_meta: list[dict[str, Any]],
    sections_cfg: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return the vendored ``track_map`` payload for ``casts.html``.

    One point per cast (``track`` is a single ``[lat, lon]`` → circle marker) and one
    polyline per section (in cast order), each a dict
    ``{id, href, color, track, info, link_label}``.  ``info`` is facts only; the macro
    appends the ``link_label`` link to ``href``.  Sections are listed before casts so the
    cast markers draw on top of the section lines.

    This overlaps :func:`generate_leaflet_map`, which builds the same cast/section geometry
    in ``leaflet.html``'s own (non-vendored) payload shape; the two stay separate only until
    V4, when ``leaflet.html`` migrates onto this ``track_map`` payload and the other builder
    is deleted rather than merged here.

    Parameters
    ----------
    all_meta : list of dict
        Per-cast metadata (``cast_num``, ``cast_num_str``, ``lat``, ``lon``, ``time_start``,
        ``max_depth``).
    sections_cfg : dict or None
        Section definitions (``cast_numbers``, ``color``, ``description``).

    Returns
    -------
    list of dict
        The track payload.  Casts with no finite position, and sections with fewer than two
        located casts, are omitted.
    """
    sections_cfg = sections_cfg or {}
    meta_lookup = {int(m["cast_num"]): m for m in all_meta}
    located = {cn for cn, m in meta_lookup.items() if _finite_latlon(m)}

    cast_section: dict[int, tuple[str, str]] = {}
    for sname, scfg in sections_cfg.items():
        color = str(scfg.get("color", _SECTION_COLOR_DEFAULT))
        for cn in expand_cast_numbers(scfg.get("cast_numbers", [])):
            cast_section.setdefault(cn, (sname, color))

    payload: list[dict[str, Any]] = []

    for sname, scfg in sections_cfg.items():
        color = str(scfg.get("color", _SECTION_COLOR_DEFAULT))
        latlons = [
            [float(meta_lookup[cn]["lat"]), float(meta_lookup[cn]["lon"])]
            for cn in expand_cast_numbers(scfg.get("cast_numbers", []))
            if cn in located
        ]
        if len(latlons) < 2:
            continue
        payload.append(
            {
                "id": f"section_{sname}",
                "href": f"sections/section_{sname}.html",
                "color": color,
                "track": latlons,
                "info": _section_panel_html(
                    sname, scfg, len(latlons), with_links=False
                ),
                "link_label": "→ Section page",
            }
        )

    for m in all_meta:
        cn = int(m["cast_num"])
        if cn not in located:
            continue
        cast_id = m.get("cast_num_str", format_cast_id(cn))
        sname_c, color_c = cast_section.get(cn, ("", _UNSECTIONED_CAST_COLOR))
        section_url = f"sections/section_{sname_c}.html" if sname_c else None
        payload.append(
            {
                "id": f"cast_{cast_id}",
                "href": f"casts/cast_{cast_id}.html",
                "color": color_c,
                "track": [[float(m["lat"]), float(m["lon"])]],
                "info": _cast_panel_html(m, sname_c, section_url, with_links=False),
                "link_label": "→ Station page",
            }
        )
    return payload


def _coastline_backend_available() -> bool:
    """Return True when cartopy (the coastline backend) is importable, without importing it."""
    return importlib.util.find_spec("cartopy") is not None


def casts_map_context(
    all_meta: list[dict[str, Any]],
    sections_cfg: dict[str, Any] | None,
) -> dict[str, str]:
    """Return the JSON strings the ``casts.html`` interactive map needs.

    Builds the ``track_map`` payload, the land-coastline GeoJSON for the data extent, and
    the fit bounds, each serialised for the template.  When the coastline is ``"null"``
    *and* cartopy is not installed, warns (``RuntimeWarning``) so a land-less map traces to a
    missing optional dependency rather than being silent.  A ``"null"`` coastline with cartopy
    present is not flagged — it means the extent simply contains no land (an open-ocean cruise),
    which the graticule covers.

    Returns
    -------
    dict
        ``{"casts_map_payload_json", "coastline_json", "map_bounds_json"}``.  With no located
        cast the payload is ``"[]"`` and the coastline/bounds are ``"null"``.
    """
    payload = casts_map_payload(all_meta, sections_cfg)
    # Bounds from fully-located casts only (both lat and lon finite), matching the drawn markers —
    # a half-located cast must not stretch the fit box to a corner with nothing in it.
    located = [
        (float(m["lat"]), float(m["lon"])) for m in all_meta if _finite_latlon(m)
    ]
    if not (payload and located):
        return {
            "casts_map_payload_json": safe_json(payload),
            "coastline_json": "null",
            "map_bounds_json": "null",
        }

    lat_min, lat_max = min(la for la, _ in located), max(la for la, _ in located)
    lon_min, lon_max = min(lo for _, lo in located), max(lo for _, lo in located)
    coastline = coastline_geojson(
        (lon_min, lat_min, lon_max, lat_max), min_clip_deg=_COASTLINE_MIN_SPAN_DEG
    )
    if coastline == "null" and not _coastline_backend_available():
        warnings.warn(
            "cast map has no land because cartopy is not installed; the map shows tracks "
            "and the lat/lon graticule. Install the optional dependency with "
            "'pip install ctdcast[maps]' for a coastline.",
            RuntimeWarning,
            stacklevel=2,
        )
    return {
        "casts_map_payload_json": safe_json(payload),
        # Escape `</` so an embedded `</script>` in the GeoJSON cannot close the tag.
        "coastline_json": coastline.replace("</", "<\\/"),
        "map_bounds_json": safe_json([[lat_min, lon_min], [lat_max, lon_max]]),
    }


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
            [round(float(la), 5), round(float(lo), 5)]
            for la, lo in zip(lats, lons, strict=True)
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
    gebco_path: Path | None,
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
    if gebco_path is None or not Path(str(gebco_path)).exists():
        return None, None, None

    try:
        import matplotlib.pyplot as plt

        # Size the longitude margin so a wide map has bathymetry to its edges
        # instead of grey bars.  A widescreen map at latitude φ shows far more
        # longitude than latitude (1° lon ≈ cos φ × 1° lat in Mercator), so a
        # fixed pad that suits latitude leaves the sides bare — most visibly for
        # a tall cruise at high latitude.  Aim to fill a ~1.6-aspect map at the
        # data's latitude, capped so an extreme latitude span does not extract
        # half an ocean.  Latitude keeps the fixed pad.
        _mean_lat = (lat_min + lat_max) / 2.0
        _cos_lat = float(max(0.15, np.cos(np.radians(_mean_lat))))
        # 1.8 ≈ a wide screen's aspect with headroom, so the extracted GEBCO is a
        # touch wider than the client fits (which caps the view at this extent).
        _lon_fill = 1.8 * (lat_max - lat_min) / _cos_lat
        _lon_pad = float(
            min(15.0, max(_GEBCO_PAD, (_lon_fill - (lon_max - lon_min)) / 2.0))
        )
        _gebco = load_gebco(
            lat_min - _GEBCO_PAD,
            lat_max + _GEBCO_PAD,
            lon_min - _lon_pad,
            lon_max + _lon_pad,
            margin=0.0,
            path=gebco_path,
            # Read the file directly: this region is wider than the preloaded
            # cruise extent, which would clip the map's longitude to grey bars.
            use_cache=False,
        )
        if _gebco is None:
            return None, None, None
        lon_vals, lat_vals, depth = _gebco
        # load_gebco stores depth positive-down; downstream code uses elevation (+up).
        elev = (-depth).astype(np.float32)

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
            for level_val, segs in zip(cs.levels, cs.allsegs, strict=True):
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
# HTML template
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


__all__ = ["casts_map_context", "casts_map_payload", "generate_leaflet_map"]


def generate_leaflet_map(
    all_meta: list[dict[str, Any]],
    sections_cfg: dict[str, Any],
    out_dir: Path,
    force: bool = False,  # noqa: ARG001
    ship_track_nc: Path | None = None,
    cruise: str = "UNK",
    inventory: list[dict[str, str]] | None = None,
    generated_at: str | None = None,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> Path | None:
    """Generate a Leaflet.js interactive cruise map at ``<out_dir>/leaflet.html``.

    Always regenerates. When ``ship_track_nc`` exists the ship track is loaded,
    subsampled, and drawn as a grey polyline behind the cast markers.

    Parameters
    ----------
    all_meta : list of dict
        Per-cast metadata (lat/lon/time/max depth/…); an empty list returns ``None``.
    sections_cfg : dict
        Section/grouping definitions (``cast_numbers``, ``color``, …) used to
        colour and group the cast markers.
    out_dir : pathlib.Path
        Report root; the page is written to ``out_dir / "leaflet.html"``.
    force : bool, default False
        Accepted for parity with the other page builders; ignored (the map is
        always regenerated).
    ship_track_nc : pathlib.Path or None, optional
        Ship-track netCDF, drawn as a background polyline when present and
        readable; ``None`` or a missing file omits the track.
    cruise : str, default "UNK"
        Resolved cruise identifier, shown in the map page title.
    inventory : list of dict or None, optional
        The "Data inventory:" strip pills (``{"label", "href"}``) under the
        masthead; ``None`` omits the strip.
    generated_at : str or None, optional
        Page build stamp; ``None`` uses the current UTC time.  Threaded from
        :func:`ctdcast.report` so one build stamps every page identically.
    cfg : ReportConfig, optional
        Report configuration (bathymetry path, map bounds, …) threaded to the drawers.

    Returns
    -------
    pathlib.Path or None
        The written ``leaflet.html`` path, or ``None`` when ``all_meta`` is empty.
    """
    if not all_meta:
        return None

    out_file = out_dir / "leaflet.html"

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
        for cn in expand_cast_numbers(scfg.get("cast_numbers", [])):
            if cn not in cast_section:
                cast_section[cn] = (sname, color)

    sections_data: list[dict[str, Any]] = []
    for sname, scfg in sections_cfg.items():
        color = str(scfg.get("color", _SECTION_COLOR_DEFAULT))
        cast_nums = expand_cast_numbers(scfg.get("cast_numbers", []))
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
        cast_id = m.get("cast_num_str", format_cast_id(cn))
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
                "num": cast_id,
                "url": f"casts/cast_{cast_id}.html",
                "info": _cast_panel_html(m, sname_c, section_url),
            }
        )

    print("  leaflet: rendering GEBCO...", end=" ", flush=True)
    gebco_b64, contour_geojson, actual_bounds = _make_gebco_layers(
        lat_min, lat_max, lon_min, lon_max, gebco_path=cfg.gebco_path
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

    leaflet_js, leaflet_css = load_leaflet()

    html = get_template("leaflet.html").render(
        css=SHARED_CSS,
        nav=nav_for("interactive", prefix="", inventory=inventory or ()),
        nav_prefix="",
        masthead_role="map",
        cruise=cruise,
        leaflet_js=leaflet_js,
        leaflet_css=leaflet_css,
        casts_json=safe_json(casts_data),
        sections_json=safe_json(sections_data),
        gebco_b64_json=safe_json(gebco_b64),
        gebco_bounds_json=safe_json(gebco_bounds),
        contours_json=contour_geojson.replace("</", "<\\/")
        if contour_geojson
        else "null",
        ship_track_json=safe_json(ship_track or []),
        depth_legend_html=depth_legend,
        lat_min=lat_min,
        lat_max=lat_max,
        lon_min=lon_min,
        lon_max=lon_max,
        version=_VERSION,
        generated_at=report_generated_at(generated_at),
    )

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(html, encoding="utf-8")
    return out_file
