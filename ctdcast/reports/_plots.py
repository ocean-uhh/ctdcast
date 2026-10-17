"""Base64 PNG encoders — thin wrappers that render a Figure for a page.

Each ``_make_*_b64`` builds a figure via a ``draw_*_fig`` in
:mod:`ctdcast.plotters.plots` and encodes it with :func:`render_b64`.
``_make_all_sections_map_b64`` uses a custom wrapper instead: it still delegates
drawing to its ``draw_*_fig`` but needs a post-``tight_layout`` adjustment.
``_make_ladcp_section_b64`` returns a list of :class:`RenderedPanel` (U and V), so
it calls :func:`render_b64` once per component against ``draw_ladcp_section_fig``.
"""

from __future__ import annotations

import dataclasses
import warnings
from pathlib import Path
from typing import Any

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from ctdcast.analysis.bathymetry import (
    interpolate_bathy_at_casts,
)
from ctdcast.config.parameters import vunit
from ctdcast.config.report_config import DEFAULT_REPORT_CONFIG, ReportConfig
from ctdcast.plotters.plots import (
    _hide_outer_spines,
    _nice_colorbar_bounds,
    draw_all_sections_map_fig,
    draw_aux_profiles_fig,
    draw_cruise_map_fig,
    draw_ct_sa_sigma0_fig,
    draw_ladcp_bottomtrack_fig,
    draw_ladcp_section_fig,
    draw_overview_panel_fig,
    draw_pressure_time_fig,
    draw_qc_histogram_fig,
    draw_section_fig,
    draw_section_map_fig,
    draw_section_ts_histogram_fig,
    draw_section_ts_o2_fig,
    draw_section_ts_profiles_fig,
    draw_sensor_diff_fig,
    draw_stability_fig,
    draw_station_map_fig,
    draw_timeseries_fig,
    draw_ts_density_fig,
    draw_ts_diagram_fig,
    draw_ts_diagram_timeseries_fig,
    draw_ts_updown_fig,
    draw_updown_diff_fig,
)
from ctdcast.plotters.primitives import nice_colorbar_ticks, unit_colorbar

# render_b64 is imported from _figdebug (a package-local wrapper around the vendored
# encoder) so figures are geometry-recorded when CTDCAST_REPORT_DEBUG is set; it delegates
# straight to the encoder when off.
from ctdcast.reports._figdebug import record as _figdebug_record
from ctdcast.reports._figdebug import render_b64
from ctdcast.reports._vendored import design_tokens as report_tokens
from ctdcast.reports._vendored.figure_png import (
    _fig_to_base64,
    record_source,
    source_for,
)


@dataclasses.dataclass(frozen=True)
class RenderedPanel:
    """A rendered figure plus the layout metadata the HTML template needs."""

    b64: str | None
    """Base64-encoded PNG string, or ``None`` when the figure could not be rendered."""
    title: str = ""
    """Long descriptive title (used in ``alt`` attributes and headings)."""
    short: str = ""
    """Short label used in ``<figcaption>`` elements (e.g. ``"CT"``, ``"U"``)."""
    figsize: tuple[float, float] | None = None
    """Figure dimensions ``(width, height)`` in inches, or ``None`` when not recorded."""
    slot: str | None = None
    """CSS slot class (e.g. ``"slot-full"``) matching the PNG aspect ratio, or ``None``."""


def _make_ts_density_b64(
    ds: xr.Dataset,
    ladcp_path: Path | None = None,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> str | None:
    """Return a base64 PNG of CT/SA/σ₀ profiles, optionally alongside LADCP U/V.

    When *ladcp_path* is ``None``, renders a single-column CT/SA/σ₀ triple-axis
    profile (downcast only).  When *ladcp_path* is given, renders a two-column layout
    with LADCP U/V on the right; shows a placeholder when the file does not exist so
    the cast page keeps a consistent appearance for all LADCP-configured casts.
    """
    return render_b64(draw_ts_density_fig, ds, ladcp_path, cfg=cfg)


def _make_ts_diagram_b64(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> str | None:
    """Return a base64 PNG of a T-S diagram colored by O₂ saturation."""
    return render_b64(draw_ts_diagram_fig, ds, cfg=cfg)


def _make_stability_b64(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> str | None:
    """Return a base64 PNG of N² and Turner angle (2-panel)."""
    return render_b64(draw_stability_fig, ds, cfg=cfg)


def _make_qc_histogram_b64(
    nc_path: Path, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> str | None:
    """Return a base64 PNG of per-variable data-value distributions with QC thresholds."""
    return render_b64(draw_qc_histogram_fig, nc_path, optional=True, cfg=cfg)


def _make_aux_profiles_b64(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> str | None:
    """Return a base64 PNG of O₂ sat, fluorescence, turbidity profiles (downcast + pale upcast)."""
    return render_b64(draw_aux_profiles_fig, ds, optional=True, cfg=cfg)


def _make_ct_sa_sigma0_b64(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> str | None:
    """Return a base64 PNG of CT, SA, σ₀ profiles side-by-side (downcast + grey upcast).

    Three-panel figure matching the style of ``_make_aux_profiles_b64``.
    """
    return render_b64(draw_ct_sa_sigma0_fig, ds, cfg=cfg)


def _make_ts_updown_b64(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> str | None:
    """Return a base64 PNG of CT–SA scatter: downcast in blue, upcast in red, σ₀ contours."""
    return render_b64(draw_ts_updown_fig, ds, cfg=cfg)


def _make_station_map_b64(
    lat: float,
    lon: float,
    all_meta: list[dict],
    target_h: float = 4.5,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> str | None:
    """Return a base64 PNG of a GEBCO map with all casts and this cast highlighted.

    The figure is laid out deterministically at a fixed slot width (see
    :func:`~ctdcast.plotters.plots._map_layout`); *target_h* is retained for
    call-site compatibility but no longer sets the size.
    """
    return render_b64(draw_station_map_fig, lat, lon, all_meta, target_h, cfg=cfg)


def _make_cruise_map_b64(
    all_meta: list[dict],
    *,
    target_h: float = 4.0,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> str | None:
    """Return a base64 PNG of all cast positions (no single-cast highlight).

    Casts are drawn as grey scatter over GEBCO bathymetry.  Cast numbers are
    annotated for the first and last cast and every 10th in between.
    """
    return render_b64(draw_cruise_map_fig, all_meta, target_h=target_h, cfg=cfg)


def _make_section_b64(
    ds_prof: xr.Dataset,
    var: str,
    label: str,
    x_vals: np.ndarray,
    x_label: str,
    title: str = "",
    style: str = "pcolormesh",
    bathy_depths: np.ndarray | None = None,
    bathy_x: np.ndarray | None = None,
    cast_labels: list | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    figsize: tuple[float, float] | None = None,
    optional: bool = False,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> str | None:
    """Return a base64 PNG of *var* vs pressure × *x_vals*.

    Parameters
    ----------
    ds_prof : xr.Dataset
        2-D profiles dataset gridded on pressure × *x_vals*.
    var : str
        Variable name to plot from *ds_prof*.
    label : str
        Variable label shown on the colorbar.
    x_vals : np.ndarray
        Along-track x positions for each profile.
    x_label : str
        Axis label for the x coordinate.
    title:
        Ignored (kept for call-site compatibility). Variable label appears on colorbar.
    style:
        ``"pcolormesh"`` (default) or ``"contourf"``.
    bathy_depths:
        GEBCO water depth (m) for the bathymetry fill.  If *bathy_x* is also provided
        the fill uses that dense along-track x array; otherwise falls back to *x_vals*.
    bathy_x:
        Along-track x positions (km) for *bathy_depths* when a denser grid is used.
        Must be the same length as *bathy_depths*.
    cast_labels:
        Cast numbers shown as ▼ markers and sparse tick labels along the top edge.
    vmin, vmax:
        Colormap limit overrides; auto from 2–98th percentile if ``None``.
    figsize:
        Figure size ``(width, height)`` in inches.  When supplied by the caller (e.g.
        from :func:`section_figsize_and_slot`), the caller's figsize is used unchanged so
        that the CSS slot and the PNG dimensions stay consistent.  When ``None``,
        :func:`section_figsize_and_slot` is called on the variable's own valid-data extent.
    optional:
        When ``True``, a ``None`` return from :func:`draw_section_fig` is silently
        accepted (variable absent from this cruise).  When ``False`` (default), ``None``
        raises :exc:`RuntimeError` if :data:`RAISE_ON_PLOT_ERROR` is set.
    cfg : ReportConfig
        Report configuration (GEBCO path, cruise info) threaded to the renderer.
    """
    return render_b64(
        draw_section_fig,
        ds_prof,
        var,
        label,
        x_vals,
        x_label,
        title=title,
        style=style,
        bathy_depths=bathy_depths,
        bathy_x=bathy_x,
        cast_labels=cast_labels,
        vmin=vmin,
        vmax=vmax,
        figsize=figsize,
        optional=optional,
        cfg=cfg,
    )


def _make_ladcp_section_b64(
    cast_nums: list[int],
    x_vals: np.ndarray,
    x_label: str,
    ladcp_dir: Path,
    lats: list[float] | None = None,
    lons: list[float] | None = None,
    figsize: tuple[float, float] | None = None,
    ladcp_pattern: str | None = None,
    style: str = "pcolormesh",
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> list[RenderedPanel]:
    """Return a list of ``RenderedPanel`` objects for LADCP U and V sections.

    Both panels use a matched symmetric RdBu_r colorbar (positive = east/north).
    Data are interpolated to a 10 m depth grid.  Dense GEBCO bathymetry is used
    when *lats*/*lons* and ``cfg.gebco_path`` are available.

    If *figsize* is given, each panel uses ``(figsize[0], figsize[1] / 2)``.
    Otherwise ``section_figsize_and_slot`` determines dimensions.

    If *ladcp_pattern* is given (e.g. ``"msm_142_1_*.mat"``), the ``*`` is replaced
    with the zero-padded cast number.  Falls back to ``NNN.mat``.

    Each panel is drawn by :func:`~ctdcast.plotters.plots.draw_ladcp_section_fig` and
    encoded via :func:`render_b64`, so the ``source:`` caption names the draw function
    and a panel is omitted (not an empty list for the pair) when its component has too
    few casts.
    """
    panels: list[RenderedPanel] = []
    for component, panel_title, panel_short in (
        ("U", "U velocity (east +)", "U"),
        ("V", "V velocity (north +)", "V"),
    ):
        b64 = render_b64(
            draw_ladcp_section_fig,
            cast_nums,
            x_vals,
            x_label,
            ladcp_dir,
            component=component,
            lats=lats,
            lons=lons,
            figsize=figsize,
            ladcp_pattern=ladcp_pattern,
            style=style,
            cfg=cfg,
            optional=True,
        )
        if b64 is not None:
            panels.append(RenderedPanel(b64=b64, title=panel_title, short=panel_short))
    return panels


def _make_ladcp_overview_b64(
    ds_ladcp: xr.Dataset,
    cast_groups: dict[str, list[int]] | None = None,
    style: str = "pcolormesh",
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> list[RenderedPanel]:
    """Return full-width LADCP U and V overview panels versus cast number × depth.

    The LADCP parallel of :func:`draw_overview_panel_fig`: reads the compiled
    ``ladcp_profiles.nc`` dataset (dims ``N_PROF`` × ``depth``), sorts by cast
    number, and draws two evenly-spaced cast-number panels sharing one symmetric
    RdBu_r colorbar (positive = east/north).  *cast_groups* draws the same
    coloured section markers as the CTD overview panels.  Returns ``[]`` if fewer
    than two casts carry finite velocity.
    """
    try:
        with plt.style.context(str(report_tokens.MPLSTYLE_PATH)):
            if "u" not in ds_ladcp or "v" not in ds_ladcp:
                return []
            order = np.argsort(ds_ladcp["cast_number"].values)
            ds = ds_ladcp.isel(N_PROF=order)
            cast_nums = ds["cast_number"].values.astype(int)
            depth = ds["depth"].values
            u = np.asarray(ds["u"].values, dtype=float)  # (N_PROF, depth)
            v = np.asarray(ds["v"].values, dtype=float)

            # Trim the depth axis to the deepest level with finite velocity.
            valid_rows = np.where(np.any(np.isfinite(u) | np.isfinite(v), axis=0))[0]
            if len(valid_rows) < 1 or len(cast_nums) < 2:
                return []
            z_hi = valid_rows[-1] + 1
            depth = depth[:z_hi]
            u = u[:, :z_hi]
            v = v[:, :z_hi]

            all_fin = np.concatenate([u[np.isfinite(u)], v[np.isfinite(v)]])
            if not len(all_fin):
                return []
            vmax_val = max(float(np.nanpercentile(np.abs(all_fin), 98)), 1e-4)
            bounds = _nice_colorbar_bounds(-vmax_val, vmax_val, n=20)
            cmap = plt.get_cmap("RdBu_r", len(bounds) - 1)
            norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

            x_pos = np.arange(len(cast_nums), dtype=float)
            _cast_to_xpos = {int(cn): x_pos[i] for i, cn in enumerate(cast_nums)}

            # Black bathymetry fill from GEBCO at each cast position (matches the
            # CTD overview panels on the same page).
            lats = ds["latitude"].values.tolist()
            lons = ds["longitude"].values.tolist()
            bathy = interpolate_bathy_at_casts(lats, lons, path=cfg.gebco_path)
            z_max = float(depth[-1])
            bathy_max = (
                float(np.nanmax(bathy))
                if bathy is not None and len(bathy) and np.any(np.isfinite(bathy))
                else 0.0
            )
            y_bottom = max(z_max, bathy_max) * 1.05

            # Evenly-spaced cast-number ticks and grid lines.  Unlike the CTD
            # overview panels (every cast present, ticks at multiples of 5), LADCP
            # coverage is sparse and unpredictable, so tick at ~10 evenly-spaced
            # actual casts — always integer cast numbers, never fractional defaults.
            _tick_step = max(1, round(len(cast_nums) / 10))
            _tick_idx = list(range(0, len(cast_nums), _tick_step))
            _tick_xpos = [x_pos[i] for i in _tick_idx]
            _tick_labels = [str(int(cast_nums[i])) for i in _tick_idx]

            panels: list[RenderedPanel] = []
            for grid_data, panel_title, panel_short, panel_label in (
                (u, "U velocity (east +)", "U", "U  East +"),
                (v, "V velocity (north +)", "V", "V  North +"),
            ):
                fig, ax = plt.subplots(figsize=cfg.overview_figsize)

                for _gx in _tick_xpos:
                    ax.axvline(_gx, color="white", alpha=0.25, zorder=0)

                if style == "contourf":
                    X, Y = np.meshgrid(x_pos, depth)
                    Z = np.ma.masked_invalid(grid_data.T)
                    mappable = ax.contourf(
                        X, Y, Z, levels=bounds, cmap="RdBu_r", extend="both"
                    )
                else:
                    mappable = ax.pcolormesh(
                        x_pos,
                        depth,
                        grid_data.T,
                        cmap=cmap,
                        norm=norm,
                        shading="nearest",
                    )
                unit_colorbar(
                    ax,
                    mappable,
                    unit=vunit("U"),
                    ticks=nice_colorbar_ticks(float(bounds[0]), float(bounds[-1])),
                    extend="both",
                    reserve=True,
                    title_loc="left",
                )

                if bathy is not None and len(bathy) == len(cast_nums):
                    ax.fill_between(
                        x_pos, bathy, y_bottom, color="black", step="mid", lw=0
                    )

                # Coloured section markers above the top axis, matching the CTD
                # overview panels.
                if cast_groups:
                    for color, group_casts in cast_groups.items():
                        gx = [
                            _cast_to_xpos[cn]
                            for cn in group_casts
                            if cn in _cast_to_xpos
                        ]
                        if gx:
                            ax.scatter(
                                gx,
                                np.ones(len(gx)) * 1.03,
                                marker="v",
                                facecolors="none",
                                edgecolors=color,
                                s=18,
                                clip_on=False,
                                zorder=6,
                                transform=ax.get_xaxis_transform(),
                            )

                ax.set_ylim(y_bottom, 0)
                ax.set_ylabel("Depth (m)")
                ax.set_xlabel("Cast number")

                ax.set_xticks(_tick_xpos)
                ax.set_xticklabels(_tick_labels, rotation=45, ha="right")

                ax.text(
                    0.01,
                    0.97,
                    panel_label,
                    transform=ax.transAxes,
                    va="top",
                    ha="left",
                    fontsize=report_tokens.ANNOT_FS,
                    bbox={
                        "facecolor": "white",
                        "alpha": 0.6,
                        "pad": 2,
                        "edgecolor": "none",
                    },
                )
                _hide_outer_spines(ax, clean=cfg.clean_spines)
                fig.tight_layout()
                _panel_b64 = _fig_to_base64(fig)
                _figdebug_record(_panel_b64, "_make_ladcp_overview_b64", fig)
                # Drawn inline in this adapter, not by a draw_* function — so the honest
                # source is the maker itself (until the drawing moves into a draw_* in plotters/).
                record_source(_panel_b64, source_for(_make_ladcp_overview_b64))
                panels.append(
                    RenderedPanel(b64=_panel_b64, title=panel_title, short=panel_short)
                )
                plt.close(fig)

            return panels
    except Exception:
        if report_tokens.RAISE_ON_PLOT_ERROR:
            raise
        warnings.warn(
            "_make_ladcp_overview_b64 failed; panels omitted",
            RuntimeWarning,
            stacklevel=2,
        )
        return []


def _make_section_ts_profiles_b64(
    ds_prof: xr.Dataset,
    x_vals: np.ndarray,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> str | None:
    """Return a base64 PNG of per-cast CT–SA profiles coloured by along-track distance.

    Each downcast in *ds_prof* is drawn as a CT–SA line with σ₀ background contours.
    Colour encodes the corresponding *x_vals* value (along-track km).
    """
    return render_b64(draw_section_ts_profiles_fig, ds_prof, x_vals, cfg=cfg)


def _make_ts_diagram_timeseries_b64(
    ds_ts: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> str | None:
    """Return a base64 PNG of a CT–SA diagram for all timeseries profiles, coloured by time.

    Each profile (N_PROF) is drawn as a line in CT–SA space.  Colour encodes hours
    since the first profile so temporal evolution is visible.  σ₀ background contours
    are overlaid.  Returns None if SA or CT are absent or fewer than two profiles exist.

    Parameters
    ----------
    ds_ts:
        2-D profiles dataset with dims ``(N_PROF, pressure)`` and variables
        ``SA``, ``CT``, ``time_start``.
    cfg : ReportConfig
        Report configuration threaded to the renderer.
    """
    return render_b64(draw_ts_diagram_timeseries_fig, ds_ts, cfg=cfg)


def _make_section_ts_histogram_b64(
    ds_prof: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> str | None:
    """Return a base64 PNG of a CT–SA 2-D count histogram (log₁₀ colour) for section profiles."""
    return render_b64(draw_section_ts_histogram_fig, ds_prof, cfg=cfg)


def _make_section_ts_o2_b64(
    ds_prof: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> str | None:
    """Return a base64 PNG of CT–SA histogram coloured by median O₂ saturation per bin."""
    return render_b64(draw_section_ts_o2_fig, ds_prof, optional=True, cfg=cfg)


def _make_section_map_b64(
    lats: list[float],
    lons: list[float],
    cast_nums: list[int],
    title: str = "",
    min_margin: float = 0.03,
    min_margin_lon: float | None = None,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> str | None:
    """Return a base64 PNG of a GEBCO map with the section track.

    *min_margin* sets a floor on the geographic margin for the latitude axis.
    *min_margin_lon*, when provided, sets a separate floor for the longitude
    axis and suppresses the N-S-section guard (use for co-located timeseries
    maps where lat and lon margins should be set independently for a
    Mercator-square view).

    The co-located/timeseries case (*min_margin_lon* set) renders at one-third
    width; the section case (no *min_margin_lon*) renders at half width.
    """
    fig_w = (
        report_tokens.W_THIRD if min_margin_lon is not None else report_tokens.W_HALF
    )
    return render_b64(
        draw_section_map_fig,
        lats,
        lons,
        cast_nums,
        title=title,
        min_margin=min_margin,
        min_margin_lon=min_margin_lon,
        fig_w=fig_w,
        cfg=cfg,
    )


def _make_overview_panel_b64(
    ds_prof: xr.Dataset,
    var: str,
    label: str,
    bathy_depths: np.ndarray | None = None,
    style: str = "pcolormesh",
    vmin: float | None = None,
    vmax: float | None = None,
    cast_groups: dict[str, list[int]] | None = None,
    optional: bool = False,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> str | None:
    """Return a base64 PNG of *var* vs pressure × cast number (cruise overview panel).

    *ds_prof* must already be filtered to downcasts and sorted by cast_number.
    X-axis positions are evenly spaced (0, 1, …, N-1) with cast numbers as tick labels.
    *bathy_depths* (m, same length as N_PROF) draws a filled black bathymetry below data.

    Parameters
    ----------
    ds_prof : xr.Dataset
        Downcast profiles, sorted by cast_number, gridded on pressure × cast.
    var : str
        Variable name to plot from *ds_prof*.
    label : str
        Variable label shown on the colorbar.
    bathy_depths : np.ndarray | None
        Water depth (m, same length as N_PROF) drawing a filled bathymetry below data.
    style:
        ``"pcolormesh"`` (default) or ``"contourf"``.
    vmin, vmax:
        Optional colormap limit overrides; auto from 1–99th percentile if ``None``.
    cast_groups : dict[str, list[int]] | None
        Named groups of cast numbers used to annotate spans along the top edge.
    optional:
        Pass ``True`` for biogeochemical variables that may be absent in some casts.
    cfg : ReportConfig
        Report configuration threaded to the renderer.
    """
    return render_b64(
        draw_overview_panel_fig,
        ds_prof,
        var,
        label,
        bathy_depths=bathy_depths,
        style=style,
        vmin=vmin,
        vmax=vmax,
        cast_groups=cast_groups,
        optional=optional,
        cfg=cfg,
    )


def _make_all_sections_map_b64(
    sections_data: list[dict[str, Any]],
    all_lats: list[float],
    all_lons: list[float],
    legend_outside: bool = False,
    *,
    target_h: float = 4.5,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> str | None:
    """Return a base64 PNG showing all section tracks coloured by section.

    Parameters
    ----------
    legend_outside:
        If True, place the legend east of the axes (wider figure).
    sections_data:
        List of dicts with keys ``name``, ``color``, ``lats``, ``lons``.
    all_lats, all_lons:
        Positions of all casts drawn as a grey background scatter.
    target_h:
        Target figure height in inches; width is computed from geographic aspect ratio.
    cfg : ReportConfig
        Report configuration threaded to the renderer.
    """
    fig_result = None
    try:
        with plt.style.context(str(report_tokens.MPLSTYLE_PATH)):
            fig_result = draw_all_sections_map_fig(
                sections_data,
                all_lats,
                all_lons,
                legend_outside,
                target_h=target_h,
                cfg=cfg,
            )
            if fig_result is None:
                return None
            # draw_all_sections_map_fig lays the figure out deterministically
            # (fixed slot width, colorbar + south legend in reserved space), so save
            # the full canvas — no tight_layout (which would warn and re-flow the
            # hand-placed axes) and no bbox crop (which would break the slot width).
            b64 = _fig_to_base64(fig_result)
            _figdebug_record(b64, "_make_all_sections_map_b64", fig_result)
            record_source(b64, source_for(draw_all_sections_map_fig))
            return b64
    except Exception:
        if report_tokens.RAISE_ON_PLOT_ERROR:
            raise
        warnings.warn(
            "_make_all_sections_map_b64 failed; panel omitted",
            RuntimeWarning,
            stacklevel=2,
        )
        return None
    finally:
        if fig_result is not None:
            plt.close(fig_result)


def _make_timeseries_b64(
    ds_prof: xr.Dataset,
    var: str,
    label: str,
    style: str = "pcolormesh",
    vmin: float | None = None,
    vmax: float | None = None,
    figw: float | None = None,
    optional: bool = False,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> str | None:
    """Return a base64 PNG of *var* vs cast time × pressure, both down and upcast.

    Parameters
    ----------
    ds_prof : xr.Dataset
        Profiles dataset gridded on cast time × pressure.
    var : str
        Variable name to plot from *ds_prof*.
    label : str
        Variable label shown on the colorbar.
    style:
        ``"pcolormesh"`` (default) or ``"contourf"``.
    vmin, vmax:
        Colormap limits; if None, 2nd–98th percentile of valid data.
    figw:
        Figure width in inches; auto-computed from profile count if None.
    optional:
        Pass ``True`` for biogeochemical variables that may be absent in some casts.
    cfg : ReportConfig
        Report configuration threaded to the renderer.
    """
    return render_b64(
        draw_timeseries_fig,
        ds_prof,
        var,
        label,
        style=style,
        vmin=vmin,
        vmax=vmax,
        figw=figw,
        optional=optional,
        cfg=cfg,
    )


def _make_sensor_diff_b64(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> str | None:
    """Return a base64 PNG of primary minus secondary sensor difference profiles.

    Shows T₁–T₂ and S₁–S₂ vs pressure with a fixed ±0.01 x-axis.
    Returns None if no secondary sensor variables are present.
    """
    return render_b64(draw_sensor_diff_fig, ds, optional=True, cfg=cfg)


def _make_pressure_time_b64(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> str | None:
    """Return a base64 PNG of pressure vs elapsed time (cast trajectory + bottle stops)."""
    return render_b64(draw_pressure_time_fig, ds, cfg=cfg)


def _make_updown_diff_b64(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> str | None:
    """Return a base64 PNG of downcast minus upcast profiles: ΔCT, ΔSA, Δσ₀.

    Both casts are interpolated to a shared 1-dbar pressure grid before differencing.
    Returns None if the overlap region is less than 10 dbar.
    """
    return render_b64(draw_updown_diff_fig, ds, cfg=cfg)


def _make_ladcp_bottomtrack_b64(
    ladcp_path: Path | None, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> str | None:
    """Return a base64 PNG of LADCP bottom-track U and V vs depth.

    Returns None if *ladcp_path* is None or the .mat file lacks ``zbot``, ``ubot``,
    or ``vbot`` fields.
    """
    if ladcp_path is None:
        return None
    return render_b64(draw_ladcp_bottomtrack_fig, ladcp_path, optional=True, cfg=cfg)
