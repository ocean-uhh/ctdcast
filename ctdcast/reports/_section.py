"""Tier-2: generate a per-section HTML report page."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import xarray as xr

from ctdcast._version import __version__ as _VERSION
from ctdcast.analysis.bathymetry import (
    dense_bathy_along_track,
    interpolate_bathy_at_casts,
)
from ctdcast.analysis.derive import derive_AOU as add_aou
from ctdcast.analysis.derive import derive_teos10_profiles as add_teos10_profiles
from ctdcast.analysis.geometry import (
    along_track_km,
    distance_from_km,
    section_orientation,
)
from ctdcast.config.parameters import (
    SECTION_BIOGEO_VARS,
    SECTION_PHYSICS_VARS,
    UNKNOWN_CRUISE_ID,
    resolve_sensor_var,
    vlabel,
)
from ctdcast.config.report_config import DEFAULT_REPORT_CONFIG, ReportConfig
from ctdcast.config.report_tokens import ROLE_ACCENT
from ctdcast.identity import compact_cast_list, expand_cast_ids, format_cast_id
from ctdcast.plotters.plots import section_figsize_and_slot
from ctdcast.reports._manifest import (
    Panel,
    PanelGroup,
    Profile,
    ResolvedReport,
    Section,
    resolve,
)
from ctdcast.reports._report_css import _JS_TOP_LINKS, SHARED_CSS
from ctdcast.reports._env import get_template
from ctdcast.reports._format import _fmt_utc, profile_cast_suffixes
from ctdcast.reports._plots import (
    RenderedPanel,
    _make_ladcp_section_b64,
    _make_section_b64,
    _make_section_map_b64,
    _make_section_ts_histogram_b64,
    _make_section_ts_o2_b64,
    _make_section_ts_profiles_b64,
)

# Panel variables are defined in ctdcast.config.parameters:
#   SECTION_PHYSICS_VARS / SECTION_BIOGEO_VARS  (shared with _index.py, _timeseries.py)
# Labels come from vlabel() so they stay in sync with VARIABLES.

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
    cruise_info: dict[str, Any] | None = None,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
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
    for i, (n, s, d) in enumerate(zip(all_cast_nums, all_suffix, is_down, strict=True)):
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

    bathy = interpolate_bathy_at_casts(lats, lons, path=cfg.gebco_path)
    dense_bathy_x, dense_bathy_d = dense_bathy_along_track(
        lats, lons, x_vals, path=cfg.gebco_path
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

    _ci = cruise_info or {}
    cruise = _ci.get("cruise_id") or ds_all.attrs.get("cruise") or UNKNOWN_CRUISE_ID
    ship = (
        _ci.get("ship")
        or ds_all.attrs.get("ship")
        or ds_all.attrs.get("platform")
        or ds_all.attrs.get("vessel")
        or "UNK"
    )
    dist_str = f"{x_vals.max():.1f} km" if len(x_vals) > 1 else "—"
    cast_nums_int = [int(c) for c in sec_cast_nums]
    # Suffixed ids ("010", "010b") for links/pills so a sibling event points at
    # its own cast page.
    cast_id_strs = [
        format_cast_id(int(n), s)
        for n, s in zip(sec_cast_nums, sec_cast_suffix, strict=True)
    ]
    vmin = vmin_override or {}
    vmax = vmax_override or {}

    # Compute section figsize and CSS slot from section extent.
    # Use valid-data extent, not pressure coordinate max — the coordinate spans the full
    # cruise depth (e.g. 2200 dbar) even for shallow sections like KO (450 dbar).
    _dist_km = float(x_vals.max() - x_vals.min()) if len(x_vals) > 1 else 1.0
    _ref_var = next(
        (v for v in ("conservative_temperature", "absolute_salinity") if v in ds_sec),
        None,
    )
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

    # T–S diagram panels are auxiliary (optional=True renderers): a None means the
    # plot is genuinely empty for this section's data, not a defect, so they are
    # rendered here and only the non-None ones fed to the T–S section — preserving
    # the previous page's silent omission rather than showing an "unavailable" stub.
    ts_panels = tuple(
        p
        for p in (
            RenderedPanel(
                title="Profiles coloured by distance",
                short="Profiles",
                b64=_make_section_ts_profiles_b64(ds_sec, x_vals, cfg=cfg),
            ),
            RenderedPanel(
                title="2-D histogram (log count)",
                short="Histogram",
                b64=_make_section_ts_histogram_b64(ds_sec, cfg=cfg),
            ),
            RenderedPanel(
                title="Median O₂ saturation",
                short="O₂",
                b64=_make_section_ts_o2_b64(ds_sec, cfg=cfg),
            ),
        )
        if p.b64
    )

    # LADCP U/V panels are a batch render (one .mat read yields both), so they are
    # produced here and fed to the Velocity section as a PanelGroup, rather than
    # rendered lazily per panel like the rest.
    ladcp_panels = (
        tuple(
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
                cfg=cfg,
            )
            if p.b64
        )
        if ladcp_dir is not None
        else ()
    )

    # Pre-render the section map so its panel gates on the result (None → omitted
    # and renumbered, like the index and timeseries location maps), rather than
    # rendering live inside resolve() where a None would surface as a stub.
    map_b64 = _make_section_map_b64(
        lats, lons, cast_nums_int, title=section_name, cfg=cfg
    )

    page_ctx = SectionPageCtx(
        ds_sec=ds_sec,
        x_vals=x_vals,
        x_label=x_label,
        section_style=section_style,
        bathy_depths=dense_bathy_d if dense_bathy_d is not None else bathy,
        bathy_x=dense_bathy_x,
        cast_labels=cast_nums_int,
        vmin=vmin,
        vmax=vmax,
        section_figsize=section_figsize,
        section_slot_key=section_slot.removeprefix("slot-"),
        section_name=section_name,
        lats=lats,
        lons=lons,
        map_b64=map_b64,
        ts_panels=ts_panels,
        ladcp_panels=ladcp_panels,
        cfg=cfg,
    )
    report = resolve_section(page_ctx)

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
        "report": report,
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
        masthead_bg=ROLE_ACCENT["aggregate-a"],
    )
    out_file.write_text(html, encoding="utf-8")
    ds_all.close()
    return out_file


# ---------------------------------------------------------------------------
# Section manifest — the section page as data (see rep-section-manifest-plan.md)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class SectionPageCtx:
    """Per-section render context: the frozen inputs every section panel reads.

    Holds the values derived once per section (selected profiles, x-axis, bathy,
    colour limits, the computed figure geometry) so a panel's ``render`` depends
    only on this object.
    """

    ds_sec: Any
    x_vals: Any
    x_label: str
    section_style: str
    bathy_depths: Any
    bathy_x: Any
    cast_labels: list[int]
    vmin: dict[str, float]
    vmax: dict[str, float]
    section_figsize: tuple[float, float]
    section_slot_key: str
    section_name: str
    lats: list[float]
    lons: list[float]
    map_b64: str | None
    ts_panels: tuple[RenderedPanel, ...]
    ladcp_panels: tuple[RenderedPanel, ...]
    cfg: ReportConfig


def _section_slot(c: SectionPageCtx) -> str:
    """Return the computed CSS slot key shared by every full-width field panel.

    Exercises ``Panel.slot``'s callable path: a section field's width is a property
    of the section geometry (``section_figsize_and_slot``), identical across the
    fields, so it is read from the context rather than fixed on each panel.
    """
    return c.section_slot_key


def _field_render(
    var: str, *, canonical: str | None, optional: bool
) -> Callable[[SectionPageCtx], str | None]:
    """Build the render closure for one section pcolormesh field.

    *var* is resolved at render time for biogeo fields (single-sensor casts promote
    the suffixed name), so the closure — not the profile — owns the ds lookup and
    the colour-limit fallback from resolved name to canonical name.
    """

    def _render(c: SectionPageCtx) -> str | None:
        resolved = resolve_sensor_var(c.ds_sec, var) if optional else var
        key = canonical or var
        _vmin = (
            c.vmin.get(resolved)
            if c.vmin.get(resolved) is not None
            else c.vmin.get(key)
        )
        _vmax = (
            c.vmax.get(resolved)
            if c.vmax.get(resolved) is not None
            else c.vmax.get(key)
        )
        return _make_section_b64(
            c.ds_sec,
            resolved,
            vlabel(var),
            c.x_vals,
            c.x_label,
            style=c.section_style,
            bathy_depths=c.bathy_depths,
            bathy_x=c.bathy_x,
            cast_labels=c.cast_labels,
            vmin=_vmin,
            vmax=_vmax,
            figsize=c.section_figsize,
            optional=optional,
            cfg=c.cfg,
        )

    return _render


def _field_panel(
    var: str, *, canonical: str | None = None, optional: bool = False
) -> Panel:
    """Build a section field :class:`Panel` for *var* at the computed section slot."""
    return Panel(
        id=f"section_{canonical or var}",
        slot=_section_slot,
        render=_field_render(var, canonical=canonical, optional=optional),
    )


def _ladcp_panel(rp: RenderedPanel) -> Panel:
    """Wrap a pre-rendered LADCP U/V panel as a manifest :class:`Panel`."""
    return Panel(
        id=f"velocity_{rp.short}",
        slot=_section_slot,
        render=lambda _c, _b64=rp.b64: _b64,
    )


def _ts_panel(rp: RenderedPanel) -> Panel:
    """Wrap a pre-rendered T–S diagram panel as a third-width manifest :class:`Panel`."""
    return Panel(
        id=f"ts_{rp.short}",
        slot="third",
        caption=rp.title,
        render=lambda _c, _b64=rp.b64: _b64,
    )


def _biogeo_present(c: SectionPageCtx) -> list[str]:
    """Return the biogeo vars structurally present on this section, in canonical order.

    Drops vars whose variable is *absent* from the dataset, so the Biogeochemistry
    PanelGroup never yields a panel for a channel this section lacks.  A var that is
    present but whose plot returns ``None`` (e.g. all-NaN) is *not* dropped here — it
    surfaces as an "unavailable" stub, since a present-but-unplottable channel is a
    defect worth showing rather than hiding.
    """
    return [
        v for v in SECTION_BIOGEO_VARS if resolve_sensor_var(c.ds_sec, v) in c.ds_sec
    ]


#: String-addressable section panels.  Only the Map is fixed; field panels
#: (physics/biogeo), LADCP and T–S panels are all data-driven PanelGroups.
SECTION_PANELS: dict[str, Panel] = {
    "section_map": Panel(
        id="section_map",
        slot="half",
        applies_to=lambda c: c.map_b64 is not None,
        render=lambda c: c.map_b64,
    ),
}


#: The section page profile.  Same order as the previous hand-authored page — Map,
#: Hydrography, Biogeochemistry, then the former "extra cards" Velocity and T–S —
#: now numbered and anchored by the resolver.  Physics/biogeo are PanelGroups over
#: their variables; Velocity is a PanelGroup over the pre-rendered LADCP panels.
SECTION_DEFAULT: Profile = Profile(
    numbering="flat",
    entries=(
        Section(
            "map",
            "Map",
            ("section_map",),
            intro="The section track and the CTD stations it comprises.",
        ),
        Section(
            "hydrography",
            "Hydrography",
            (
                PanelGroup(
                    over=lambda _c: list(SECTION_PHYSICS_VARS), panel=_field_panel
                ),
            ),
            intro=(
                "Sections of conservative temperature (CT), absolute salinity (SA) "
                "and potential density (σ₀) against distance along the section. The "
                "σ₀ panel carries the 27.7 and 27.8 kg m⁻³ isopycnals (black, "
                "labelled). Open triangles along the top of each panel mark the "
                "profiles; station numbers are labelled at intervals."
            ),
        ),
        Section(
            "biogeochemistry",
            "Biogeochemistry",
            (
                PanelGroup(
                    over=_biogeo_present,
                    panel=lambda v: _field_panel(v, canonical=v, optional=True),
                ),
            ),
            intro=(
                "Sections of the biogeochemical sensors present on this section — "
                "oxygen, fluorescence and turbidity where available — against "
                "distance along the section."
            ),
        ),
        Section(
            "velocity",
            "Velocity (U east, V north)",
            (PanelGroup(over=lambda c: c.ladcp_panels, panel=_ladcp_panel),),
            intro=(
                "Eastward (U) and northward (V) velocity from the LADCP, against "
                "distance along the section."
            ),
        ),
        Section(
            "ts_diagram",
            "T–S diagrams",
            (PanelGroup(over=lambda c: c.ts_panels, panel=_ts_panel),),
            intro="Water-mass structure of the section in temperature–salinity space.",
        ),
    ),
)


def resolve_section(ctx: SectionPageCtx) -> ResolvedReport:
    """Resolve the section profile against *ctx* into numbered, rendered sections."""
    return resolve(SECTION_DEFAULT, ctx, SECTION_PANELS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
