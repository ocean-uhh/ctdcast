"""Tier-3: entry point — generates index, stations list, and sections list pages."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import xarray as xr

from ctdcast._version import __version__ as _VERSION
from ctdcast.analysis.bathymetry import interpolate_bathy_at_casts
from ctdcast.analysis.derive import derive_AOU as add_aou
from ctdcast.analysis.derive import derive_teos10_profiles as add_teos10_profiles
from ctdcast.analysis.geometry import distance_from_km
from ctdcast.config.loader import SectionsConfig
from ctdcast.config.report_config import DEFAULT_REPORT_CONFIG, ReportConfig
from ctdcast.config.parameters import (
    SECTION_BIOGEO_VARS,
    SECTION_PHYSICS_VARS,
    UNKNOWN_CRUISE_ID,
    vlabel,
)
from ctdcast.identity import (
    cast_id_from_name,
    compact_cast_list,
    expand_cast_numbers,
    format_cast_id,
)
from ctdcast.readers.ladcp import find_ladcp_file
from ctdcast.reports import _figdebug
from ctdcast.reports._cast import generate_station_page
from ctdcast.reports._report_css import _JS_TOP_LINKS, SHARED_CSS
from ctdcast.reports._env import get_template
from ctdcast.reports._plots import (
    _make_all_sections_map_b64,
    _make_cruise_map_b64,
    _make_overview_panel_b64,
    _make_section_ts_histogram_b64,
    _make_station_map_b64,  # noqa: F401 — kept for backward compat
)
from ctdcast.reports._section import generate_section_page
from ctdcast.reports._timeseries import generate_timeseries_page

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def report(
    nc_dir: Path,
    out_dir: Path,
    *,
    profiles_path: Path | None = None,
    section_yaml: Path | None = None,
    ladcp_dir: Path | None = None,
    ladcp_pattern: str | None = None,
    ship_track_nc: Path | None = None,
    generate: dict[str, bool] | None = None,
    force: bool = False,
    skip_existing: bool = False,
    section_style: str = "pcolormesh",
    timeseries_style: str = "pcolormesh",
    vmin_override: dict[str, float] | None = None,
    vmax_override: dict[str, float] | None = None,
    cruise_info: dict[str, Any] | None = None,
    config: ReportConfig | None = None,
    cast_filter: int | list[int] | None = None,
    sal_range: tuple[float, float] | None = None,
    trim_soak: bool = False,
    dbar_step: int = 1,
) -> int:
    """Generate the full ctdcast HTML report suite.

    Parameters
    ----------
    nc_dir:
        Directory containing per-cast ``.nc`` files.
    out_dir:
        Root output directory.
    profiles_path:
        Path to compiled ``profiles.nc``. Required for section and time series pages.
    section_yaml:
        Path to the sections/timeseries YAML file (``ctd_sections.yaml``).
    ladcp_dir:
        Directory containing processed LADCP ``.mat`` files named ``NNN.mat``
        or ``NNNb.mat`` (letter-suffix variants supported).
    ladcp_pattern:
        Optional filename glob for non-standard LADCP naming, e.g.
        ``"msm_142_1_*.mat"``.  The ``*`` is replaced with the zero-padded
        cast number.  See :func:`~ctdcast.readers.ladcp.find_ladcp_file`.
    ship_track_nc:
        Path to a ship-track netCDF for the Leaflet map background line.
    generate:
        Dict of booleans controlling which page types to build.
        Keys: ``"stations"``, ``"sections"``, ``"timeseries"``, ``"index"``, ``"map"``.
        Missing keys default to ``True``.
    force:
        Regenerate all pages regardless of file modification times.
    skip_existing:
        If True, skip any page whose output HTML already exists, regardless of
        whether the source files are newer.  Use this to fill in only missing
        pages without touching anything already generated.  Takes precedence over
        the mtime check but is overridden by ``force``.
    section_style:
        ``"pcolormesh"`` or ``"contourf"`` for section figures.
    timeseries_style:
        ``"pcolormesh"`` or ``"contourf"`` for time series figures.
    vmin_override, vmax_override:
        Per-variable colormap limit overrides (e.g. ``{"SA": 34.5}``).
    cruise_info:
        Cruise metadata dict (from the ``cruise_info:`` block in ``config.yaml``).
    config:
        Frozen display configuration (GEBCO path, figsizes, map bounds, colormaps).
        Defaults to DEFAULT_REPORT_CONFIG.
    cast_filter:
        If set, rebuild only the station page for this cast number
        (implies ``generate={"stations": True, rest False}``).
    sal_range:
        ``(sal_min, sal_max)`` — records with ``salinity_1`` outside this
        range are excluded from all station page plots.  The NC files are
        not modified.  Excluded record count is shown in each page header.
    trim_soak:
        If True, apply pre-soak detection on each cast: cut the first 60 s
        (pump activation) and any records up to the last near-surface record
        after pump-on.  Passed through to :func:`~ctdcast.reports._cast.generate_station_page`.
    dbar_step:
        Subsample the pressure axis by this step for section and timeseries
        plots (default 1, full 1-dbar resolution).  ``build_profiles()``
        always stores 1-dbar data; this controls plot-time resolution only.

    Returns
    -------
    int
        The number of pages that failed to build (0 on full success), so the CLI
        can exit non-zero when a requested page could not be generated.

    """
    cfg = config if config is not None else DEFAULT_REPORT_CONFIG
    _figdebug.clear()  # reset the per-figure debug registry for this build
    _failed = 0
    gen: dict[str, bool] = {
        "stations": True,
        "sections": True,
        "timeseries": True,
        "index": True,
        "map": True,
    }
    if generate is not None:
        gen.update(generate)
    if cast_filter is not None:
        gen = {
            "stations": True,
            "sections": False,
            "timeseries": False,
            "index": False,
            "map": False,
        }

    vmin_override = vmin_override or {}
    vmax_override = vmax_override or {}

    out_dir.mkdir(parents=True, exist_ok=True)

    # Load sections YAML once. SectionsConfig returns empty defaults when absent.
    _sections_cfg = (
        SectionsConfig.from_yaml(section_yaml) if section_yaml else SectionsConfig()
    )

    # cruise_info: explicit param wins; YAML cruise_info: block is the fallback.
    # None  → not provided: use YAML block entirely.
    # {}    → explicitly empty: suppress YAML block (caller opted out).
    # {...} → caller-provided: merge YAML as base, caller's keys override.
    if cruise_info is None:
        cruise_info = _sections_cfg.cruise_info
    elif cruise_info:
        cruise_info = {**_sections_cfg.cruise_info, **cruise_info}
    # else: cruise_info == {} → keep as-is, YAML block suppressed

    cast_files = _select_cast_files(nc_dir)
    if not cast_files:
        print(f"No cast .nc files found in {nc_dir}")
        return

    print(f"Found {len(cast_files)} cast files")
    all_meta_raw = [_read_cast_meta(p) for p in cast_files]
    all_meta = sorted(
        [m for m in all_meta_raw if m is not None],
        key=lambda m: m["time_start"],
        reverse=True,
    )
    _nc_cruise = all_meta[0].get("cruise") if all_meta else None
    cruise = cruise_info.get("cruise_id") or _nc_cruise or "UNK"

    # Pre-load GEBCO for the cruise area into memory so every map figure
    # subsets from numpy arrays rather than reopening the file from disk.
    from ctdcast.analysis.bathymetry import preload_gebco

    _gebco_path = cfg.gebco_path
    if _gebco_path is not None and all_meta:
        _cast_lats = [
            m["lat"] for m in all_meta if np.isfinite(m.get("lat", float("nan")))
        ]
        _cast_lons = [
            m["lon"] for m in all_meta if np.isfinite(m.get("lon", float("nan")))
        ]
        if _cast_lats:
            _t0 = perf_counter()
            preload_gebco(
                _gebco_path,
                float(min(_cast_lats)),
                float(max(_cast_lats)),
                float(min(_cast_lons)),
                float(max(_cast_lons)),
            )
            print(f"  GEBCO preloaded ({perf_counter() - _t0:.1f}s)")

    # Build cruise-wide cast_notes mapping from all sections and timeseries.
    all_cast_notes: dict[int, list[str]] = {}
    for _grp_dict in (_sections_cfg.sections, _sections_cfg.timeseries):
        for _cfg in _grp_dict.values():
            if not isinstance(_cfg, dict):
                continue
            for _cn, _note in (_cfg.get("cast_notes") or {}).items():
                _cn_int = int(_cn)
                all_cast_notes.setdefault(_cn_int, [])
                if _note and _note not in all_cast_notes[_cn_int]:
                    all_cast_notes[_cn_int].append(str(_note))

    if gen["stations"]:
        _t0 = perf_counter()
        cast_num_strs = [m["cast_num_str"] for m in all_meta]
        _cast_set: set[int] | None = (
            {cast_filter}
            if isinstance(cast_filter, int)
            else set(cast_filter)
            if cast_filter is not None
            else None
        )
        targets = [
            m for m in all_meta if _cast_set is None or m["cast_num"] in _cast_set
        ]
        if _cast_set is not None and not targets:
            print(f"Cast(s) {cast_filter} not found in {nc_dir}")
            return
        for meta in targets:
            orig_i = all_meta.index(meta)
            prev_cast_str = cast_num_strs[orig_i - 1] if orig_i > 0 else None
            next_cast_str = (
                cast_num_strs[orig_i + 1] if orig_i < len(all_meta) - 1 else None
            )
            _expected = out_dir / "casts" / f"cast_{meta['cast_num_str']}.html"
            _was_new = not _expected.exists()
            _html_mtime_str = _fmt_mtime(
                _expected
            )  # capture before page is (re)written

            # Resolve LADCP mat path before the skip check so it feeds the mtime comparison.
            _mat: Path | None = None
            if ladcp_dir is not None:
                _mat = find_ladcp_file(
                    ladcp_dir, meta["cast_num"], meta["cast_suffix"], ladcp_pattern
                )

            _extra: tuple[Path, ...] = (_mat,) if _mat is not None else ()
            _skip_reason = _mtime_skip_reason(
                _expected, meta["path"], force, *_extra, skip_existing=skip_existing
            )

            _ladcp_note = ""
            if (
                _skip_reason
                and _mat is not None
                and _expected.exists()
                and b"fig-profile-ladcp" not in _expected.read_bytes()
            ):
                _ladcp_note = " — LADCP available, use --force"

            out_page = generate_station_page(
                meta["path"],
                out_dir,
                all_meta,
                prev_cast_str=prev_cast_str,
                next_cast_str=next_cast_str,
                force=force or not _skip_reason,
                ladcp_dir=ladcp_dir,
                ladcp_pattern=ladcp_pattern,
                cast_num_str=meta["cast_num_str"],
                sal_range=sal_range,
                trim_soak=trim_soak,
                cast_notes=all_cast_notes.get(meta["cast_num"]),
                cruise_info=cruise_info,
                cfg=cfg,
            )
            if _skip_reason:
                _status = _skip_reason + _ladcp_note
            elif out_page is None:
                _status = "FAILED"
                _failed += 1
            elif force:
                _status = "regenerated (forced)"
            elif _was_new:
                _ladcp_part = f", ladcp: {_fmt_mtime(_mat)}" if _mat else ""
                _status = (
                    f"regenerated (new) [nc: {_fmt_mtime(meta['path'])}{_ladcp_part}]"
                )
            else:
                _ladcp_part = f", ladcp: {_fmt_mtime(_mat)}" if _mat else ""
                _status = (
                    f"regenerated (source updated)"
                    f" [html: {_html_mtime_str},"
                    f" nc: {_fmt_mtime(meta['path'])}{_ladcp_part}]"
                )
            print(f"  cast {meta['cast_num_str']}: {_status}")
        print(f"  [casts: {perf_counter() - _t0:.1f}s]")

    sections_cfg: dict[str, Any] = _sections_cfg.sections
    timeseries_cfg: dict[str, Any] = _sections_cfg.timeseries

    if gen["sections"]:
        _t0 = perf_counter()
        _sec_names = list(sections_cfg.keys())
        for _sec_i, (sec_name, sec_cfg) in enumerate(sections_cfg.items()):
            _sec_prev = _sec_names[_sec_i - 1] if _sec_i > 0 else None
            _sec_next = _sec_names[_sec_i + 1] if _sec_i < len(_sec_names) - 1 else None
            _expected = out_dir / "sections" / f"section_{sec_name}.html"
            _sec_was_new = not _expected.exists()
            _sec_html_mtime_str = _fmt_mtime(_expected)
            _src = profiles_path if profiles_path is not None else _expected
            _sec_skip = _mtime_skip_reason(
                _expected, _src, force, skip_existing=skip_existing
            )
            _sec_note = ""
            if _sec_skip and ladcp_dir is not None:
                _sec_casts = expand_cast_numbers(sec_cfg.get("cast_numbers", []))
                if (
                    any(
                        find_ladcp_file(ladcp_dir, cn, ladcp_pattern=ladcp_pattern)
                        is not None
                        for cn in _sec_casts
                    )
                    and _expected.exists()
                    and b"s-ladcp" not in _expected.read_bytes()
                ):
                    _sec_note = " — LADCP available, use --force"
            out_page = generate_section_page(
                sec_name,
                sec_cfg,
                profiles_path,
                out_dir,
                force=force or not _sec_skip,
                section_style=section_style,
                vmin_override=vmin_override,
                vmax_override=vmax_override,
                ladcp_dir=ladcp_dir,
                ladcp_pattern=ladcp_pattern,
                dbar_step=dbar_step,
                prev_name=_sec_prev,
                next_name=_sec_next,
                cruise_info=cruise_info,
                cfg=cfg,
            )
            if _sec_skip:
                _sec_status = _sec_skip + _sec_note
            elif out_page is None:
                _sec_status = "FAILED"
                _failed += 1
            elif force:
                _sec_status = "regenerated (forced)"
            elif _sec_was_new:
                _sec_status = f"regenerated (new) [src: {_fmt_mtime(_src)}]"
            else:
                _sec_status = (
                    f"regenerated (source updated)"
                    f" [html: {_sec_html_mtime_str}, src: {_fmt_mtime(_src)}]"
                )
            print(f"  section {sec_name}: {_sec_status}")
        print(f"  [sections: {perf_counter() - _t0:.1f}s]")

    if gen["timeseries"] and timeseries_cfg:
        _t0 = perf_counter()
        _ts_names = list(timeseries_cfg.keys())
        for _ts_i, (ts_name, ts_cfg) in enumerate(timeseries_cfg.items()):
            _ts_prev = _ts_names[_ts_i - 1] if _ts_i > 0 else None
            _ts_next = _ts_names[_ts_i + 1] if _ts_i < len(_ts_names) - 1 else None
            _expected = out_dir / "timeseries" / f"timeseries_{ts_name}.html"
            _ts_was_new = not _expected.exists()
            _ts_html_mtime_str = _fmt_mtime(_expected)
            _src = profiles_path if profiles_path is not None else _expected
            _ts_skip = _mtime_skip_reason(
                _expected, _src, force, skip_existing=skip_existing
            )
            _ts_note = ""
            if _ts_skip and ladcp_dir is not None:
                _ts_casts = expand_cast_numbers(ts_cfg.get("cast_numbers", []))
                if (
                    any(
                        find_ladcp_file(ladcp_dir, cn, ladcp_pattern=ladcp_pattern)
                        is not None
                        for cn in _ts_casts
                    )
                    and _expected.exists()
                    and b"s-ladcp" not in _expected.read_bytes()
                ):
                    _ts_note = " — LADCP available, use --force"
            out_page = generate_timeseries_page(
                ts_name,
                ts_cfg,
                profiles_path,
                out_dir,
                force=force or not _ts_skip,
                section_style=timeseries_style,
                vmin_override=vmin_override,
                vmax_override=vmax_override,
                all_meta=all_meta,
                ladcp_dir=ladcp_dir,
                ladcp_pattern=ladcp_pattern,
                dbar_step=dbar_step,
                prev_name=_ts_prev,
                next_name=_ts_next,
                cruise_info=cruise_info,
                cfg=cfg,
            )
            if _ts_skip:
                _ts_status = _ts_skip + _ts_note
            elif out_page is None:
                _ts_status = "FAILED"
                _failed += 1
            elif force:
                _ts_status = "regenerated (forced)"
            elif _ts_was_new:
                _ts_status = f"regenerated (new) [src: {_fmt_mtime(_src)}]"
            else:
                _ts_status = (
                    f"regenerated (source updated)"
                    f" [html: {_ts_html_mtime_str}, src: {_fmt_mtime(_src)}]"
                )
            print(f"  timeseries {ts_name}: {_ts_status}")
        print(f"  [timeseries: {perf_counter() - _t0:.1f}s]")

    if gen["index"]:
        _t0 = perf_counter()
        _write_index(
            all_meta,
            sections_cfg,
            cruise,
            out_dir,
            force,
            profiles_path=profiles_path,
            section_style=section_style,
            vmin_override=vmin_override,
            vmax_override=vmax_override,
            cruise_info=cruise_info,
            timeseries_cfg=timeseries_cfg,
            cfg=cfg,
        )
        print(f"  [index.html: {perf_counter() - _t0:.1f}s]")
        _t0 = perf_counter()
        _write_stations_list(
            all_meta,
            cruise,
            out_dir,
            sections_cfg=sections_cfg,
            timeseries_cfg=timeseries_cfg,
            ladcp_dir=ladcp_dir,
            ladcp_pattern=ladcp_pattern,
            cruise_info=cruise_info,
            cfg=cfg,
        )
        print(f"  [casts.html: {perf_counter() - _t0:.1f}s]")
        _t0 = perf_counter()
        _write_sections_list(
            sections_cfg,
            cruise,
            out_dir,
            all_meta=all_meta,
            ladcp_dir=ladcp_dir,
            cruise_info=cruise_info,
            cfg=cfg,
        )
        print(f"  [sections.html: {perf_counter() - _t0:.1f}s]")
        _t0 = perf_counter()
        _write_timeseries_list(
            timeseries_cfg,
            cruise,
            out_dir,
            all_meta=all_meta,
            ladcp_dir=ladcp_dir,
            cruise_info=cruise_info,
            cfg=cfg,
        )
        print(f"  [timeseries.html: {perf_counter() - _t0:.1f}s]")

    if gen["map"]:
        try:
            from ctdcast.reports._leaflet import generate_leaflet_map

            lf_out = generate_leaflet_map(
                all_meta,
                sections_cfg,
                out_dir,
                force=force,
                ship_track_nc=ship_track_nc,
                cruise=cruise,
                cfg=cfg,
            )
            print(f"  leaflet map: {'regenerated' if lf_out else 'skipped (no casts)'}")
        except Exception:  # noqa: BLE001
            import traceback

            print("  leaflet map: FAILED")
            _failed += 1
            traceback.print_exc()

    print(f"\nReport written to {out_dir}/index.html")
    return _failed


# ---------------------------------------------------------------------------
# Page writers
# ---------------------------------------------------------------------------


def _write_index(
    all_meta: list[dict[str, Any]],
    sections_cfg: dict[str, Any],
    cruise: str,
    out_dir: Path,
    force: bool,  # noqa: ARG001
    profiles_path: Path | None = None,
    section_style: str = "pcolormesh",
    vmin_override: dict[str, float] | None = None,
    vmax_override: dict[str, float] | None = None,
    cruise_info: dict[str, Any] | None = None,
    timeseries_cfg: dict[str, Any] | None = None,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> None:
    """Write index.html with header card, stats, overview map, and stacked property panels."""
    times = [m["time_start"] for m in all_meta if m.get("time_start")]
    times_str = sorted(str(t)[:10] for t in times if t)
    n_days = 0
    if len(times_str) >= 2:
        from datetime import date

        try:
            d0 = date.fromisoformat(times_str[0])  # earliest
            d1 = date.fromisoformat(times_str[-1])  # latest
            n_days = (d1 - d0).days + 1
        except ValueError:
            pass

    max_depth = max((m.get("max_depth", 0) for m in all_meta), default=0)
    ci = cruise_info or {}

    _valid_lats = [m["lat"] for m in all_meta if np.isfinite(m.get("lat", np.nan))]
    _valid_lons = [m["lon"] for m in all_meta if np.isfinite(m.get("lon", np.nan))]

    # Build combined sections+timeseries data for the map and for overview markers
    _ts_cfg = timeseries_cfg or {}
    _all_groups = {**sections_cfg, **_ts_cfg}
    sections_data_map: list[dict[str, Any]] = []
    # cast_groups: color → set of cast numbers (for overview panel top markers)
    cast_groups: dict[str, list[int]] = {}
    for _grp_name, grp_cfg in _all_groups.items():
        cast_nums_grp = expand_cast_numbers(grp_cfg.get("cast_numbers", []))
        color = grp_cfg.get("color", "#888888")
        if cast_nums_grp:
            cast_groups[color] = cast_groups.get(color, []) + list(cast_nums_grp)

    # For the index map, gather section track positions from all_meta
    cast_pos = {
        m["cast_num"]: (m["lat"], m["lon"])
        for m in all_meta
        if np.isfinite(m.get("lat", np.nan))
    }
    for grp_name, grp_cfg in sections_cfg.items():
        cast_nums_grp = expand_cast_numbers(grp_cfg.get("cast_numbers", []))
        lats_g = [cast_pos[cn][0] for cn in sorted(cast_nums_grp) if cn in cast_pos]
        lons_g = [cast_pos[cn][1] for cn in sorted(cast_nums_grp) if cn in cast_pos]
        if lats_g:
            sections_data_map.append(
                {
                    "name": grp_name,
                    "color": grp_cfg.get("color", "#888888"),
                    "lats": lats_g,
                    "lons": lons_g,
                }
            )
    for grp_name, grp_cfg in _ts_cfg.items():
        cast_nums_grp = expand_cast_numbers(grp_cfg.get("cast_numbers", []))
        lats_g = [cast_pos[cn][0] for cn in sorted(cast_nums_grp) if cn in cast_pos]
        lons_g = [cast_pos[cn][1] for cn in sorted(cast_nums_grp) if cn in cast_pos]
        if lats_g:
            sections_data_map.append(
                {
                    "name": grp_name,
                    "color": grp_cfg.get("color", "#888888"),
                    "lats": lats_g,
                    "lons": lons_g,
                }
            )

    if sections_data_map and _valid_lats:
        fig_map_b64 = _make_all_sections_map_b64(
            sections_data_map,
            _valid_lats,
            _valid_lons,
            legend_outside=True,
            target_h=3.0,
            cfg=cfg,
        )
    elif _valid_lats:
        # No sections configured (e.g. draft mode) — fall back to cruise-track map.
        fig_map_b64 = _make_cruise_map_b64(all_meta, target_h=3.0, cfg=cfg)
    else:
        fig_map_b64 = None

    # Stacked overview panels and cruise T-S diagram from profiles.nc
    physics_panels_idx: list[dict[str, Any]] = []
    biogeo_panels_idx: list[dict[str, Any]] = []
    ts_b64: str | None = None
    if profiles_path is not None and profiles_path.exists():
        try:
            ds_all = xr.open_dataset(
                profiles_path, decode_timedelta=False, engine="netcdf4"
            ).load()
            ds_all = add_teos10_profiles(ds_all)
            ds_all = add_aou(ds_all)

            mask_down = ds_all["cast_type"].values == "down"
            ds_down = ds_all.isel(N_PROF=mask_down)
            order = np.argsort(ds_down["cast_number"].values)
            ds_sorted = ds_down.isel(N_PROF=order)

            lats = ds_sorted["latitude"].values.tolist()
            lons = ds_sorted["longitude"].values.tolist()
            bathy = interpolate_bathy_at_casts(lats, lons, path=cfg.gebco_path)

            vmin = vmin_override or {}
            vmax = vmax_override or {}

            def _idx_panel(var: str, label: str) -> dict[str, Any]:
                b64 = _make_overview_panel_b64(
                    ds_sorted,
                    var,
                    label,
                    bathy_depths=bathy,
                    style=section_style,
                    vmin=vmin.get(var),
                    vmax=vmax.get(var),
                    cast_groups=cast_groups,
                    cfg=cfg,
                )
                return {"title": label, "b64": b64}

            physics_panels_idx = [
                _idx_panel(v, vlabel(v)) for v in SECTION_PHYSICS_VARS
            ]
            biogeo_panels_idx = [_idx_panel(v, vlabel(v)) for v in SECTION_BIOGEO_VARS]

            ts_b64 = _make_section_ts_histogram_b64(ds_sorted, cfg=cfg)
            ds_all.close()
        except Exception:  # noqa: BLE001
            pass  # Overview panels are optional; never crash index generation

    date_start = times_str[0] if times_str else ""
    date_end = times_str[-1] if len(times_str) >= 2 else ""

    ctx: dict[str, Any] = {
        "cruise": cruise,
        "ship": ci.get("ship", ""),
        "project": ci.get("project", ""),
        "date_start": date_start,
        "date_end": date_end,
        "n_casts": len(all_meta),
        "n_sections": len(sections_cfg),
        "max_depth_str": f"{max_depth:.0f} dbar",
        "n_days": n_days,
        "fig_map_b64": fig_map_b64,
        "physics_panels": physics_panels_idx,
        "biogeo_panels": biogeo_panels_idx,
        "ts_b64": ts_b64
        if profiles_path is not None and profiles_path.exists()
        else None,
        "version": _VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    html = get_template("index.html").render(
        **ctx,
        css=SHARED_CSS,
        js_top_links=_JS_TOP_LINKS,
        nav_prefix="",
        nav_current="summary",
    )
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def _dec_min(deg: float, pos_hem: str, neg_hem: str) -> str:
    """Format decimal degrees as degrees-decimal-minutes, e.g. 65°13.782′N."""
    if not np.isfinite(deg):
        return "—"
    hem = pos_hem if deg >= 0 else neg_hem
    deg = abs(deg)
    d = int(deg)
    m = (deg - d) * 60.0
    return f"{d}°{m:06.3f}′{hem}"


_DEPTH_PILL_PALETTE: list[tuple[str, str]] = [
    ("#deebf7", "#1a1a2e"),  # shallowest — very light blue, dark text
    ("#9ecae1", "#1a1a2e"),  # light blue, dark text
    ("#4292c6", "#ffffff"),  # medium blue, white text
    ("#2171b5", "#ffffff"),  # dark blue, white text
    ("#084594", "#ffffff"),  # deepest — very dark blue, white text
]


def _depth_pill_style(depth: float, rounded_max: float) -> tuple[str, str]:
    """Return (background_hex, text_hex) for a depth pill based on 5-class scheme."""
    if rounded_max <= 0 or not np.isfinite(depth):
        return _DEPTH_PILL_PALETTE[0]
    cls = min(4, int(depth / rounded_max * 5))
    return _DEPTH_PILL_PALETTE[cls]


def _round_max_depth(max_depth: float) -> float:
    """Round *max_depth* up to the nearest 100, 500, or 1000 dbar."""
    if max_depth <= 500:
        return float(np.ceil(max_depth / 100) * 100)
    if max_depth <= 2000:
        return float(np.ceil(max_depth / 500) * 500)
    return float(np.ceil(max_depth / 1000) * 1000)


def _write_stations_list(
    all_meta: list[dict[str, Any]],
    cruise: str,
    out_dir: Path,
    sections_cfg: dict[str, Any] | None = None,
    timeseries_cfg: dict[str, Any] | None = None,
    ladcp_dir: Path | None = None,
    ladcp_pattern: str | None = None,
    cruise_info: dict[str, Any] | None = None,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> None:
    """Write casts.html with cruise map, depth pills, and section/timeseries links."""
    # LADCP: collect cast numbers that have a processed .mat file.
    # Use find_ladcp_file per cast so non-NNN.mat filenames (e.g. msm_142_1_NNN.mat)
    # are handled correctly.
    ladcp_cast_nums: set[int] = set()
    if ladcp_dir is not None and ladcp_dir.exists():
        for meta in all_meta:
            cn = meta["cast_num"]
            cs = meta.get("cast_suffix", "")
            if find_ladcp_file(ladcp_dir, cn, cs, ladcp_pattern) is not None:
                ladcp_cast_nums.add(cn)

    # Section name → YAML color; cast → section names
    section_colors: dict[str, str] = {
        name: cfg.get("color", "#2c6e49") for name, cfg in (sections_cfg or {}).items()
    }
    cast_to_sections: dict[int, list[str]] = {}
    for sec_name, sec_cfg in (sections_cfg or {}).items():
        for cn in expand_cast_numbers(sec_cfg.get("cast_numbers", [])):
            cast_to_sections.setdefault(cn, []).append(sec_name)

    # Timeseries name → YAML color; cast → timeseries names
    ts_colors: dict[str, str] = {
        name: cfg.get("color", "#7b2d8b")
        for name, cfg in (timeseries_cfg or {}).items()
    }
    cast_to_timeseries: dict[int, list[str]] = {}
    for ts_name, ts_cfg in (timeseries_cfg or {}).items():
        for cn in expand_cast_numbers(ts_cfg.get("cast_numbers", [])):
            cast_to_timeseries.setdefault(cn, []).append(ts_name)

    all_depths = [
        m.get("max_depth", 0) for m in all_meta if np.isfinite(m.get("max_depth", 0))
    ]
    rounded_max = _round_max_depth(max(all_depths, default=100))

    stations = []
    for m in all_meta:
        lat = m.get("lat", np.nan)
        lon = m.get("lon", np.nan)
        depth = m.get("max_depth", 0)
        bg, fg = _depth_pill_style(float(depth), rounded_max)
        cast_num_int = m["cast_num"]
        stations.append(
            {
                "cast_num": m["cast_num_str"],
                "filename": m.get("raw_filename", "—"),
                "time_start_str": str(m.get("time_start", ""))[:16].replace("T", " "),
                "lat_str": _dec_min(lat, "N", "S"),
                "lon_str": _dec_min(lon, "E", "W"),
                "max_depth_str": f"{depth:.0f}",
                "depth_bg": bg,
                "depth_fg": fg,
                "sections": [
                    {"name": sn, "color": section_colors.get(sn, "#2c6e49")}
                    for sn in cast_to_sections.get(cast_num_int, [])
                ],
                "timeseries": [
                    {"name": tn, "color": ts_colors.get(tn, "#7b2d8b")}
                    for tn in cast_to_timeseries.get(cast_num_int, [])
                ],
                "ladcp_has": cast_num_int in ladcp_cast_nums,
            }
        )

    _ci = cruise_info or {}
    _times_str = sorted(
        str(m["time_start"])[:10] for m in all_meta if m.get("time_start")
    )
    _date_start = _times_str[0] if _times_str else ""
    _date_end = _times_str[-1] if len(_times_str) >= 2 else ""
    _duration_days = 0
    if _date_start and _date_end:
        try:
            from datetime import date as _date

            _duration_days = (
                _date.fromisoformat(_date_end) - _date.fromisoformat(_date_start)
            ).days + 1
        except ValueError:
            pass
    _max_depth = max((m.get("max_depth", 0) for m in all_meta), default=0)

    ctx: dict[str, Any] = {
        "cruise": cruise,
        "ship": _ci.get("ship", ""),
        "date_start": _date_start,
        "date_end": _date_end,
        "duration_days": _duration_days,
        "max_depth_str": f"{_max_depth:.0f} dbar" if _max_depth else "",
        "stations": stations,
        "cruise_map_b64": _make_cruise_map_b64(all_meta, target_h=3.0, cfg=cfg),
        "ladcp_configured": ladcp_dir is not None,
        "version": _VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    html = get_template("casts.html").render(
        **ctx,
        css=SHARED_CSS,
        js_top_links=_JS_TOP_LINKS,
        nav_prefix="",
        nav_current="casts",
    )
    (out_dir / "casts.html").write_text(html, encoding="utf-8")


def _write_sections_list(
    sections_cfg: dict[str, Any],
    cruise: str,
    out_dir: Path,
    all_meta: list[dict[str, Any]] | None = None,
    ladcp_dir: Path | None = None,
    cruise_info: dict[str, Any] | None = None,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> None:
    """Write sections.html with overview map and cards for each section."""
    ladcp_cast_nums: set[int] = set()
    if ladcp_dir is not None and ladcp_dir.exists():
        for f in ladcp_dir.glob("*.mat"):
            try:
                ladcp_cast_nums.add(int(f.stem))
            except ValueError:
                pass

    # Build cast → position lookup for the overview map
    cast_pos: dict[int, tuple[float, float]] = {}
    if all_meta:
        for m in all_meta:
            cn = m.get("cast_num")
            if (
                cn is not None
                and np.isfinite(m.get("lat", np.nan))
                and np.isfinite(m.get("lon", np.nan))
            ):
                cast_pos[int(cn)] = (float(m["lat"]), float(m["lon"]))

    sections = []
    sections_data: list[dict[str, Any]] = []
    _sec_n_casts_list: list[int] = []
    for name, grp_cfg in sections_cfg.items():
        cast_nums = expand_cast_numbers(grp_cfg.get("cast_numbers", []))
        report_path = out_dir / "sections" / f"section_{name}.html"
        ladcp_has = any(c in ladcp_cast_nums for c in cast_nums)
        n_casts_sec = len(cast_nums)
        _sec_n_casts_list.append(n_casts_sec)
        sections.append(
            {
                "name": name,
                "description": grp_cfg.get("description", ""),
                "color": grp_cfg.get("color", "#1a3a5c"),
                "n_casts": n_casts_sec,
                "cast_range": compact_cast_list(cast_nums) if cast_nums else "—",
                "report_exists": report_path.exists(),
                "ladcp_has": ladcp_has,
            }
        )
        if cast_pos:
            sec_lats = [cast_pos[c][0] for c in cast_nums if c in cast_pos]
            sec_lons = [cast_pos[c][1] for c in cast_nums if c in cast_pos]
            # Match the section page's key_cast ordering so the sections-map
            # polyline does not fold when the section is anchored to a distance
            # origin. (The cruise-track map on index.html keeps occupation order.)
            key_cfg = grp_cfg.get("key_cast")
            if key_cfg is not None and len(sec_lats) >= 2:
                _key_nums = expand_cast_numbers([key_cfg])
                _kn = _key_nums[0] if len(_key_nums) == 1 else None
                if _kn in cast_pos:
                    _kl, _ko = cast_pos[_kn]
                    _order = np.argsort(
                        distance_from_km(_kl, _ko, sec_lats, sec_lons), kind="stable"
                    )
                    sec_lats = [sec_lats[i] for i in _order]
                    sec_lons = [sec_lons[i] for i in _order]
            if sec_lats:
                sections_data.append(
                    {
                        "name": name,
                        "color": grp_cfg.get("color", "#555555"),
                        "lats": sec_lats,
                        "lons": sec_lons,
                    }
                )

    all_cast_lats = [v[0] for v in cast_pos.values()]
    all_cast_lons = [v[1] for v in cast_pos.values()]
    sections_map_b64 = (
        _make_all_sections_map_b64(
            sections_data, all_cast_lats, all_cast_lons, target_h=3.0, cfg=cfg
        )
        if sections_data
        else None
    )

    # Cruise-wide date range from all_meta
    _ci = cruise_info or {}
    _times_str = sorted(
        str(m["time_start"])[:10] for m in (all_meta or []) if m.get("time_start")
    )
    _date_start = _times_str[0] if _times_str else ""
    _date_end = _times_str[-1] if len(_times_str) >= 2 else ""
    _duration_days = 0
    if _date_start and _date_end:
        try:
            from datetime import date as _date

            _duration_days = (
                _date.fromisoformat(_date_end) - _date.fromisoformat(_date_start)
            ).days + 1
        except ValueError:
            pass
    # Summary ranges across sections
    _casts_range = ""
    if _sec_n_casts_list:
        mn, mx = min(_sec_n_casts_list), max(_sec_n_casts_list)
        _casts_range = f"{mn}–{mx}" if mn != mx else str(mn)

    ctx: dict[str, Any] = {
        "cruise": cruise,
        "ship": _ci.get("ship", ""),
        "date_start": _date_start,
        "date_end": _date_end,
        "duration_days": _duration_days,
        "casts_range": _casts_range,
        "sections": sections,
        "sections_map_b64": sections_map_b64,
        "ladcp_configured": ladcp_dir is not None,
        "version": _VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    html = get_template("sections.html").render(
        **ctx,
        css=SHARED_CSS,
        js_top_links=_JS_TOP_LINKS,
        nav_prefix="",
        nav_current="sections",
    )
    (out_dir / "sections.html").write_text(html, encoding="utf-8")


def _write_timeseries_list(
    timeseries_cfg: dict[str, Any],
    cruise: str,
    out_dir: Path,
    all_meta: list[dict[str, Any]] | None = None,
    ladcp_dir: Path | None = None,
    cruise_info: dict[str, Any] | None = None,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> None:
    """Write timeseries.html listing all timeseries groups with an overview map."""
    ladcp_cast_nums: set[int] = set()
    if ladcp_dir is not None and ladcp_dir.exists():
        for f in ladcp_dir.glob("*.mat"):
            try:
                ladcp_cast_nums.add(int(f.stem))
            except ValueError:
                pass

    # Build cast → position and time lookup
    cast_pos: dict[int, tuple[float, float]] = {}
    cast_times: dict[int, tuple[Any, Any]] = {}
    if all_meta:
        for m in all_meta:
            cn = m.get("cast_num")
            if cn is not None:
                if np.isfinite(m.get("lat", np.nan)) and np.isfinite(
                    m.get("lon", np.nan)
                ):
                    cast_pos[int(cn)] = (float(m["lat"]), float(m["lon"]))
                if m.get("time_start") is not None and m.get("time_end") is not None:
                    cast_times[int(cn)] = (m["time_start"], m["time_end"])

    items = []
    timeseries_data: list[dict[str, Any]] = []
    _ts_n_casts_list: list[int] = []
    _ts_dur_h_list: list[float] = []
    for name, grp_cfg in timeseries_cfg.items():
        cast_nums = expand_cast_numbers(grp_cfg.get("cast_numbers", []))
        report_path = out_dir / "timeseries" / f"timeseries_{name}.html"
        color = grp_cfg.get("color", "#7b2d8b")
        ladcp_has = any(c in ladcp_cast_nums for c in cast_nums)
        n_casts_ts = len(cast_nums)
        _ts_n_casts_list.append(n_casts_ts)
        # Compute per-group duration from cast timestamps
        grp_starts = [cast_times[c][0] for c in cast_nums if c in cast_times]
        grp_ends = [cast_times[c][1] for c in cast_nums if c in cast_times]
        if grp_starts and grp_ends:
            try:
                _t0 = np.min(np.array(grp_starts, dtype="datetime64[ns]"))
                _t1 = np.max(np.array(grp_ends, dtype="datetime64[ns]"))
                _dur_h = float((_t1 - _t0) / np.timedelta64(1, "h"))
                _ts_dur_h_list.append(_dur_h)
            except Exception:  # noqa: BLE001
                pass
        items.append(
            {
                "name": name,
                "description": grp_cfg.get("description", ""),
                "color": color,
                "n_casts": n_casts_ts,
                "cast_range": compact_cast_list(cast_nums) if cast_nums else "—",
                "report_exists": report_path.exists(),
                "ladcp_has": ladcp_has,
            }
        )
        if cast_pos:
            ts_lats = [cast_pos[c][0] for c in cast_nums if c in cast_pos]
            ts_lons = [cast_pos[c][1] for c in cast_nums if c in cast_pos]
            if ts_lats:
                timeseries_data.append(
                    {"name": name, "color": color, "lats": ts_lats, "lons": ts_lons}
                )

    all_cast_lats = [v[0] for v in cast_pos.values()]
    all_cast_lons = [v[1] for v in cast_pos.values()]
    timeseries_map_b64 = (
        _make_all_sections_map_b64(
            timeseries_data, all_cast_lats, all_cast_lons, target_h=3.0, cfg=cfg
        )
        if timeseries_data
        else None
    )

    # Cruise-wide date range
    _ci = cruise_info or {}
    _times_str = sorted(
        str(m["time_start"])[:10] for m in (all_meta or []) if m.get("time_start")
    )
    _date_start = _times_str[0] if _times_str else ""
    _date_end = _times_str[-1] if len(_times_str) >= 2 else ""
    _duration_days = 0
    if _date_start and _date_end:
        try:
            from datetime import date as _date

            _duration_days = (
                _date.fromisoformat(_date_end) - _date.fromisoformat(_date_start)
            ).days + 1
        except ValueError:
            pass
    # Summary ranges across timeseries groups
    _ts_casts_range = ""
    if _ts_n_casts_list:
        mn, mx = min(_ts_n_casts_list), max(_ts_n_casts_list)
        _ts_casts_range = f"{mn}–{mx}" if mn != mx else str(mn)
    _ts_dur_range = ""
    if _ts_dur_h_list:
        mn_h, mx_h = min(_ts_dur_h_list), max(_ts_dur_h_list)
        _ts_dur_range = f"{mn_h:.0f}–{mx_h:.0f} h" if mn_h != mx_h else f"{mn_h:.0f} h"

    ctx: dict[str, Any] = {
        "cruise": cruise,
        "ship": _ci.get("ship", ""),
        "date_start": _date_start,
        "date_end": _date_end,
        "duration_days": _duration_days,
        "ts_casts_range": _ts_casts_range,
        "ts_dur_range": _ts_dur_range,
        "timeseries": items,
        "timeseries_map_b64": timeseries_map_b64,
        "ladcp_configured": ladcp_dir is not None,
        "version": _VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    html = get_template("timeseries.html").render(
        **ctx,
        css=SHARED_CSS,
        js_top_links=_JS_TOP_LINKS,
        nav_prefix="",
        nav_current="timeseries",
    )
    (out_dir / "timeseries.html").write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Mtime helpers
# ---------------------------------------------------------------------------


def _fmt_mtime(path: Path) -> str:
    """Return a compact local datetime string for *path*'s mtime, or ``"missing"``."""
    try:
        return (
            datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M")
        )
    except OSError:
        return "missing"


def _mtime_skip_reason(
    expected: Path,
    source: Path,
    force: bool,
    *extra_sources: Path,
    skip_existing: bool = False,
) -> str:
    """Return a non-empty skip-reason string if *expected* should not be regenerated.

    Returns an empty string when the page should be (re)generated.

    Logic (evaluated in order):
    - *force* is True → always regenerate (return ``""``).
    - *expected* does not exist → must generate (return ``""``).
    - *skip_existing* is True → skip unconditionally: ``"skipped (exists)"``.
    - *expected* is newer than ALL of *source* and *extra_sources* → skip:
      ``"skipped (up to date)"``.
    - Any source newer than *expected* → regenerate (smart update, return ``""``).
    - mtime comparison fails (``OSError``) → conservative skip:
      ``"skipped (exists, use --force)"``.
    """
    if force or not expected.exists():
        return ""
    if skip_existing:
        return "skipped (exists)"
    try:
        html_mtime = expected.stat().st_mtime
        all_sources = [source, *extra_sources]
        if any(s.stat().st_mtime > html_mtime for s in all_sources):
            return ""  # at least one source is newer: regenerate
        return "skipped (up to date)"
    except OSError:
        return "skipped (exists, use --force)"


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------


def _select_cast_files(nc_dir: Path) -> list[Path]:
    """Return sorted list of cast .nc files from any cruise naming convention.

    Accepts any ``*.nc`` file whose stem contains a 3+-digit cast number,
    optionally followed by a letter suffix (e.g. ``mixsed2_004b.nc``,
    ``msm_142_1_001_1sec.nc``).  The **last** 3+-digit group in the stem is
    taken as the cast number so that cruise/leg numbers earlier in the name
    (e.g. the ``142`` in ``msm_142_1_001_1sec``) are not confused with cast
    numbers.  Sort order is cast number then suffix (plain before ``b``).
    """
    results: list[tuple[int, str, Path]] = []
    for p in sorted(nc_dir.glob("*.nc")):
        _id = cast_id_from_name(p.stem)
        if _id is None:
            continue
        results.append((_id[0], _id[1], p))
    results.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in results]


def _read_cast_meta(nc_path: Path) -> dict[str, Any] | None:
    """Read scalar metadata from a cast .nc file without loading all data."""
    try:
        ds = xr.open_dataset(nc_path, decode_timedelta=False, engine="netcdf4")
        _id = cast_id_from_name(nc_path.stem)
        if _id is None:
            return None
        cast_num, cast_suffix = _id
        import warnings as _w

        with _w.catch_warnings():
            _w.filterwarnings("ignore", "All-NaN slice encountered")
            lat = float(np.nanmedian(ds["latitude"].values))
            lon = float(np.nanmedian(ds["longitude"].values))
        max_depth = float(np.nanmax(ds["pressure"].values))
        time_start = ds["time"].values[0]
        time_end = ds["time"].values[-1]
        raw_filename = ds.attrs.get("raw_filename", nc_path.stem + ".cnv")
        cruise = ds.attrs.get("cruise", UNKNOWN_CRUISE_ID)
        ds.close()
        return {
            "cast_num": cast_num,
            "cast_suffix": cast_suffix,
            "cast_num_str": format_cast_id(cast_num, cast_suffix),
            "path": nc_path,
            "lat": lat,
            "lon": lon,
            "max_depth": max_depth,
            "time_start": time_start,
            "time_end": time_end,
            "raw_filename": raw_filename,
            "cruise": cruise,
        }
    except Exception:  # noqa: BLE001
        return None
