"""Tier-2: generate a per-section HTML report page."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from ctdcast._version import __version__ as _VERSION
from ctdcast.analysis.bathymetry import (
    dense_bathy_along_track,
    interpolate_bathy_at_casts,
)
from ctdcast.analysis.geometry import (
    along_track_km,
    distance_from_km,
    section_orientation,
)
from ctdcast.analysis.teos10 import add_aou, add_teos10_profiles
from ctdcast.identity import compact_cast_list, expand_cast_ids, format_cast_id
from ctdcast.plotters import plots as _plots
from ctdcast.plotters.plots import section_figsize_and_slot
from ctdcast.reports._chrome import EXTRA_CARD_ORDER
from ctdcast.reports._css import _JS_TOP_LINKS, SHARED_CSS
from ctdcast.reports._env import get_template
from ctdcast.reports._format import _fmt_utc, profile_cast_suffixes
from ctdcast.reports._plots import (
    Panel,
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

    cast_ids = expand_cast_ids(section_cfg.get("cast_numbers", []))
    if not cast_ids:
        return None

    if not profiles_path.exists():
        return None

    try:
        ds_all = xr.open_dataset(
            profiles_path, decode_timedelta=False, engine="netcdf4"
        ).load()
    except Exception:  # noqa: BLE001
        return None

    # Index profiles by (cast_number, cast_suffix). Identity is the pair, so a
    # plain cast and its lettered sibling are independent. down_idx_by_id drives
    # selection (downcasts only); pos_by_id gives a cast's position from any
    # profile so a key_cast without a downcast still resolves its origin.
    all_cast_nums = ds_all["cast_number"].values
    all_suffix = profile_cast_suffixes(ds_all)
    all_lats = ds_all["latitude"].values
    all_lons = ds_all["longitude"].values
    is_down = ds_all["cast_type"].values == "down"
    down_idx_by_id: dict[tuple[int, str], int] = {}
    pos_by_id: dict[tuple[int, str], tuple[float, float]] = {}
    for i, (n, s, d) in enumerate(zip(all_cast_nums, all_suffix, is_down)):
        cid = (int(n), str(s))
        pos_by_id.setdefault(cid, (float(all_lats[i]), float(all_lons[i])))
        if d:
            down_idx_by_id.setdefault(cid, i)

    # Select casts in the order written in the config (mode 1). A cast with no
    # matching downcast profile is skipped; a cast listed twice is picked twice.
    picked = [down_idx_by_id[cid] for cid in cast_ids if cid in down_idx_by_id]
    if not picked:
        ds_all.close()
        return None

    # Optional key_cast (mode 2): order casts by geographic distance from that
    # cast and use that distance as the x-axis. key_cast must be a single cast in
    # the section; otherwise fall back to mode 1 (validate reports the error).
    key_cfg = section_cfg.get("key_cast")
    key_id = None
    if key_cfg is not None:
        try:
            _key_ids = expand_cast_ids([key_cfg])
        except ValueError:
            _key_ids = []
        if len(_key_ids) == 1:
            key_id = _key_ids[0]
    cast_ids_set = set(cast_ids)
    use_key = key_id is not None and key_id in cast_ids_set and key_id in pos_by_id

    ds_sec = ds_all.isel(N_PROF=picked)
    if dbar_step > 1:
        p_idx = np.arange(0, ds_sec.sizes["pressure"], dbar_step)
        ds_sec = ds_sec.isel(pressure=p_idx)

    x_vals_key = None
    if use_key:
        key_lat, key_lon = pos_by_id[key_id]
        _d = distance_from_km(
            key_lat,
            key_lon,
            ds_sec["latitude"].values.tolist(),
            ds_sec["longitude"].values.tolist(),
        )
        order = np.argsort(_d, kind="stable")
        ds_sec = ds_sec.isel(N_PROF=order)
        # add_teos10/add_aou below don't reorder N_PROF, so the sorted distances
        # are the final x-axis — no need to recompute after.
        x_vals_key = _d[order]

    ds_sec = add_teos10_profiles(ds_sec)
    ds_sec = add_aou(ds_sec)

    lats = ds_sec["latitude"].values.tolist()
    lons = ds_sec["longitude"].values.tolist()
    sec_cast_nums = ds_sec["cast_number"].values.tolist()
    sec_cast_suffix = profile_cast_suffixes(ds_sec).tolist()

    if use_key:
        x_vals = x_vals_key
        x_label = f"Distance from cast {format_cast_id(*key_id)} (km)"
    else:
        # Cumulative along-track distance from the first cast in config order.
        x_vals, x_label = along_track_km(lats, lons)

    bathy = interpolate_bathy_at_casts(lats, lons, path=_plots.GEBCO_PATH)
    dense_bathy_x, dense_bathy_d = dense_bathy_along_track(
        lats, lons, x_vals, path=_plots.GEBCO_PATH
    )

    # Flip to geographic convention (west-left / north-left) only in mode 1;
    # key_cast fixes the origin at x=0, so its axis is not flipped. Mirror about
    # the maximum (not x_vals[-1], which is only the max when casts are listed in
    # monotonic geographic order).
    if not use_key and section_orientation(lats, lons):
        x_total = float(x_vals.max())
        x_vals = x_total - x_vals
        if dense_bathy_x is not None:
            dense_bathy_x = x_total - dense_bathy_x

    cruise = ds_all.attrs.get("cruise", "odb2026")
    ship = ds_all.attrs.get(
        "ship", ds_all.attrs.get("platform", ds_all.attrs.get("vessel", "UNK"))
    )
    dist_str = f"{x_vals.max():.1f} km" if len(x_vals) > 1 else "—"
    cast_nums_int = [int(c) for c in sec_cast_nums]
    # Suffixed ids ("010", "010b") for links/pills so a sibling event points at
    # its own cast page.
    cast_id_strs = [
        format_cast_id(int(n), s) for n, s in zip(sec_cast_nums, sec_cast_suffix)
    ]
    vmin = vmin_override or {}
    vmax = vmax_override or {}

    # Compute section figsize and CSS slot from section extent.
    # Use valid-data extent, not pressure coordinate max — the coordinate spans the full
    # cruise depth (e.g. 2200 dbar) even for shallow sections like KO (450 dbar).
    _dist_km = float(x_vals.max() - x_vals.min()) if len(x_vals) > 1 else 1.0
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

    def _section_panel(var: str, label: str, short: str) -> Panel:
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
        return Panel(b64=b64, title=label, short=short)

    physics_panels = [_section_panel(v, l, s) for v, l, s in _PHYSICS_VARS]
    biogeo_panels = [_section_panel(v, l, s) for v, l, s in _BIOGEO_VARS]

    _ts_panels_raw = [
        Panel(
            title="Profiles coloured by distance",
            short="Profiles",
            b64=_make_section_ts_profiles_b64(ds_sec, x_vals),
        ),
        Panel(
            title="2-D histogram (log count)",
            short="Histogram",
            b64=_make_section_ts_histogram_b64(ds_sec),
        ),
        Panel(
            title="Median O₂ saturation",
            short="O₂",
            b64=_make_section_ts_o2_b64(ds_sec),
        ),
    ]
    _ladcp_panels = (
        [
            p
            for p in _make_ladcp_section_b64(
                cast_nums_int,
                x_vals,
                x_label,
                ladcp_dir,
                lats=lats,
                lons=lons,
                ladcp_pattern=ladcp_pattern,
                style=section_style,
            )
            if p.b64
        ]
        if ladcp_dir is not None
        else []
    )
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
            "panels": [p for p in _ts_panels_raw if p.b64],
        }
        if any(p.b64 for p in _ts_panels_raw)
        else None,
    }
    extra_cards = [_extra_raw[k] for k in EXTRA_CARD_ORDER if _extra_raw.get(k)]

    ctx: dict[str, Any] = {
        "section_name": section_name,
        "section_description": section_cfg.get("description", ""),
        "cruise": cruise,
        "n_casts": len(sec_cast_nums),
        "dist_str": dist_str,
        "cast_list_str": compact_cast_list([int(c) for c in sec_cast_nums]),
        "ship": ship,
        "p_max_str": f"{_p_max_sec:.0f} dbar",
        "start_pos": start_pos,
        "end_pos": end_pos,
        "start_time": start_time,
        "end_time": end_time,
        "cast_nums": cast_id_strs,
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

    html = get_template("section.html").render(
        **ctx,
        css=SHARED_CSS,
        js_top_links=_JS_TOP_LINKS,
        nav_prefix="../",
        nav_current="sections",
        masthead_bg="#8e44ad",
    )
    out_file.write_text(html, encoding="utf-8")
    ds_all.close()
    return out_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
