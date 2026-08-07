"""Base64 PNG encoders — thin wrappers that render a Figure for a page.

Each ``_make_*_b64`` builds a figure via a ``draw_*_fig`` in
:mod:`ctdcast.plotters.plots` and encodes it with :func:`render_b64`.  Two use a
custom wrapper instead of :func:`render_b64`: ``_make_all_sections_map_b64`` still
delegates drawing to its ``draw_*_fig`` but needs a post-``tight_layout``
adjustment, and ``_make_ladcp_section_b64`` does its own plotting because it
returns a list of :class:`Panel` rather than a single figure.
"""

from __future__ import annotations

import base64
import dataclasses
import io
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from ctdcast.analysis.bathymetry import (
    dense_bathy_along_track,
    interpolate_bathy_at_casts,
)
from ctdcast.plotters import plots as _pp
from ctdcast.plotters.plots import (
    _MPLSTYLE,
    _cast_markers,
    _hide_outer_spines,
    _nice_colorbar_bounds,
    draw_all_sections_map_fig,
    draw_aux_profiles_fig,
    draw_cruise_map_fig,
    draw_ct_sa_sigma0_fig,
    draw_ladcp_bottomtrack_fig,
    draw_overview_panel_fig,
    draw_pressure_time_fig,
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
    section_figsize_and_slot,
)
from ctdcast.readers.ladcp import find_ladcp_file, read_ladcp


def _fig_to_base64(fig: Any) -> str:
    """Render *fig* to a PNG and return its base64-encoded bytes as a string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def render_b64(
    draw: Callable[..., plt.Figure | None],
    /,
    *args: Any,
    optional: bool = False,
    **kwargs: Any,
) -> str | None:
    """Run *draw* under the package mplstyle and return its figure as a base64 PNG.

    Parameters
    ----------
    draw:
        A ``draw_*`` function returning a :class:`matplotlib.figure.Figure`, or
        ``None`` if the dataset lacks the required variables.
    *args, **kwargs:
        Forwarded to *draw*.
    optional:
        ``True`` when this panel is legitimately absent for some casts — e.g. a
        secondary sensor is not fitted, LADCP bottom-track fields are missing, or
        a biogeochemical variable was not measured.  When ``False`` (default) and
        :data:`ctdcast.plotters.plots.RAISE_ON_PLOT_ERROR` is set, a ``None``
        return from *draw* raises :exc:`RuntimeError` so tests catch silently
        dropped required panels.

    Returns
    -------
    str or None
        Base64-encoded PNG bytes, or ``None`` if *draw* returned ``None`` or
        raised (unless :data:`RAISE_ON_PLOT_ERROR`).
    """
    fig = None
    try:
        with plt.style.context(str(_MPLSTYLE)):
            fig = draw(*args, **kwargs)
            if fig is None:
                if _pp.RAISE_ON_PLOT_ERROR and not optional:
                    raise RuntimeError(
                        f"{draw.__name__} returned None for a required panel; "
                        "check that all required variables are present in the dataset."
                    )
                return None
            fig.tight_layout()
            return _fig_to_base64(fig)
    except Exception:
        if _pp.RAISE_ON_PLOT_ERROR:
            raise
        warnings.warn(
            f"{draw.__name__} failed; panel omitted",
            RuntimeWarning,
            stacklevel=2,
        )
        return None
    finally:
        if fig is not None:
            plt.close(fig)


@dataclasses.dataclass(frozen=True)
class Panel:
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


def _make_ts_density_b64(ds: xr.Dataset, ladcp_path: Path | None = None) -> str | None:
    """Return a base64 PNG of CT/SA/σ₀ profiles, optionally alongside LADCP U/V.

    When *ladcp_path* is ``None``, renders a single-column CT/SA/σ₀ triple-axis
    profile (downcast only).  When *ladcp_path* is given, renders a two-column layout
    with LADCP U/V on the right; shows a placeholder when the file does not exist so
    the cast page keeps a consistent appearance for all LADCP-configured casts.
    """
    return render_b64(draw_ts_density_fig, ds, ladcp_path)


def _make_ts_diagram_b64(ds: xr.Dataset) -> str | None:
    """Return a base64 PNG of a T-S diagram colored by O₂ saturation."""
    return render_b64(draw_ts_diagram_fig, ds)


def _make_stability_b64(ds: xr.Dataset) -> str | None:
    """Return a base64 PNG of N² and Turner angle (2-panel)."""
    return render_b64(draw_stability_fig, ds)


def _make_aux_profiles_b64(ds: xr.Dataset) -> str | None:
    """Return a base64 PNG of O₂ sat, fluorescence, turbidity profiles (downcast + pale upcast)."""
    return render_b64(draw_aux_profiles_fig, ds, optional=True)


def _make_ct_sa_sigma0_b64(ds: xr.Dataset) -> str | None:
    """Return a base64 PNG of CT, SA, σ₀ profiles side-by-side (downcast + grey upcast).

    Three-panel figure matching the style of ``_make_aux_profiles_b64``.
    """
    return render_b64(draw_ct_sa_sigma0_fig, ds)


def _make_ts_updown_b64(ds: xr.Dataset) -> str | None:
    """Return a base64 PNG of CT–SA scatter: downcast in blue, upcast in red, σ₀ contours."""
    return render_b64(draw_ts_updown_fig, ds)


def _make_station_map_b64(
    lat: float,
    lon: float,
    all_meta: list[dict],
    target_h: float = 4.5,
) -> str | None:
    """Return a base64 PNG of a GEBCO map with all casts and this cast highlighted.

    *target_h* controls the figure height in inches; width is computed from the
    geographic aspect ratio via :func:`_geo_figsize`.
    """
    return render_b64(draw_station_map_fig, lat, lon, all_meta, target_h)


def _make_cruise_map_b64(all_meta: list[dict], *, target_h: float = 4.0) -> str | None:
    """Return a base64 PNG of all cast positions (no single-cast highlight).

    Casts are drawn as grey scatter over GEBCO bathymetry.  Cast numbers are
    annotated for the first and last cast and every 10th in between.
    """
    return render_b64(draw_cruise_map_fig, all_meta, target_h=target_h)


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
) -> str | None:
    """Return a base64 PNG of *var* vs pressure × *x_vals*.

    Parameters
    ----------
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
) -> list[Panel]:
    """Return a list of ``Panel`` objects for LADCP U and V sections.

    Both panels use a matched symmetric RdBu_r colorbar (positive = east/north).
    Data are interpolated to a 10 m depth grid.  Dense GEBCO bathymetry is used
    when *lats*/*lons* and ``GEBCO_PATH`` are available.

    If *figsize* is given, each panel uses ``(figsize[0], figsize[1] / 2)``.
    Otherwise ``section_figsize_and_slot`` determines dimensions.

    If *ladcp_pattern* is given (e.g. ``"msm_142_1_*.mat"``), the ``*`` is replaced
    with the zero-padded cast number.  Falls back to ``NNN.mat``.
    """
    try:
        with plt.style.context(str(_MPLSTYLE)):
            lat_map = dict(zip(cast_nums, lats)) if lats else {}
            lon_map = dict(zip(cast_nums, lons)) if lons else {}

            # Load available casts; record x, cast_num, lat, lon, z, u, v
            loaded: list[
                tuple[float, int, float, float, np.ndarray, np.ndarray, np.ndarray]
            ] = []
            for cn, xv in zip(cast_nums, x_vals):
                mat_path = find_ladcp_file(ladcp_dir, cn, ladcp_pattern=ladcp_pattern)
                if mat_path is None:
                    continue
                try:
                    m = read_ladcp(mat_path)
                    dr = m["dr"]
                    loaded.append(
                        (
                            float(xv),
                            int(cn),
                            lat_map.get(cn, float("nan")),
                            lon_map.get(cn, float("nan")),
                            np.asarray(dr.z, dtype=float),
                            np.asarray(dr.u, dtype=float),
                            np.asarray(dr.v, dtype=float),
                        )
                    )
                except Exception:  # noqa: BLE001, S112
                    continue

            if len(loaded) < 2:
                return []

            x_ladcp = np.array([t[0] for t in loaded])
            cast_nums_ladcp = [t[1] for t in loaded]
            filt_lats = [t[2] for t in loaded]
            filt_lons = [t[3] for t in loaded]
            n_cast = len(loaded)

            # Interpolate to common 10 m depth grid
            z_max = float(max(t[4].max() for t in loaded))
            z_grid = np.arange(0.0, z_max + 10.0, 10.0)
            n_z = len(z_grid)

            u_grid = np.full((n_cast, n_z), np.nan)
            v_grid = np.full((n_cast, n_z), np.nan)
            for i, (*_, z, u, v) in enumerate(loaded):
                idx = np.argsort(z)
                z_s, u_s, v_s = z[idx], u[idx], v[idx]
                in_range = (z_grid >= z_s.min()) & (z_grid <= z_s.max())
                u_grid[i, in_range] = np.interp(z_grid[in_range], z_s, u_s)
                v_grid[i, in_range] = np.interp(z_grid[in_range], z_s, v_s)

            # Symmetric RdBu_r colormap centred at zero — matched for both panels
            all_fin = np.concatenate(
                [u_grid[np.isfinite(u_grid)], v_grid[np.isfinite(v_grid)]]
            )
            if not len(all_fin):
                return []
            vmax_val = max(float(np.nanpercentile(np.abs(all_fin), 98)), 1e-4)
            bounds = _nice_colorbar_bounds(-vmax_val, vmax_val, n=20)
            cmap = plt.get_cmap("RdBu_r", len(bounds) - 1)
            norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

            # Figure size: caller override (timeseries) or aspect-ratio formula (sections)
            abs_dist = abs(float(x_ladcp[-1] - x_ladcp[0])) if n_cast > 1 else 10.0
            if figsize is not None:
                panel_w, panel_h = float(figsize[0]), float(figsize[1])
            else:
                (panel_w, panel_h), _ = section_figsize_and_slot(z_max, abs_dist)

            # Dense bathy (smooth fill); fall back to cast-position bathy
            dense_bathy_x, dense_bathy_d = dense_bathy_along_track(
                filt_lats, filt_lons, x_ladcp, path=_pp.GEBCO_PATH
            )
            bathy_coarse = interpolate_bathy_at_casts(
                filt_lats, filt_lons, path=_pp.GEBCO_PATH
            )
            bathy_max = (
                float(np.nanmax(dense_bathy_d))
                if dense_bathy_d is not None and len(dense_bathy_d)
                else float(np.nanmax(bathy_coarse))
                if bathy_coarse is not None and len(bathy_coarse)
                else 0.0
            )
            y_bottom = max(z_max, bathy_max) * 1.05

            panels: list[Panel] = []
            for grid_data, panel_title, panel_short, panel_label in (
                (u_grid, "U velocity (east +)", "U", "U  East +"),
                (v_grid, "V velocity (north +)", "V", "V  North +"),
            ):
                fig, ax = plt.subplots(figsize=(panel_w, panel_h))

                if style == "contourf":
                    X, Y = np.meshgrid(x_ladcp, z_grid)
                    Z = np.ma.masked_invalid(grid_data.T)
                    cf = ax.contourf(
                        X, Y, Z, levels=bounds, cmap="RdBu_r", extend="both"
                    )
                    fig.colorbar(
                        cf, ax=ax, ticks=bounds[::2], label="Velocity (m s⁻¹)", pad=0.02
                    )
                else:
                    pc = ax.pcolormesh(
                        x_ladcp,
                        z_grid,
                        grid_data.T,
                        cmap=cmap,
                        norm=norm,
                        shading="nearest",
                    )
                    fig.colorbar(
                        pc,
                        ax=ax,
                        ticks=bounds[::2],
                        label="Velocity (m s⁻¹)",
                        pad=0.02,
                        extend="both",
                    )

                # Bathymetry — dense interpolation preferred
                if dense_bathy_x is not None and dense_bathy_d is not None:
                    ax.fill_between(
                        dense_bathy_x, dense_bathy_d, y_bottom, color="black", lw=0
                    )
                elif bathy_coarse is not None and len(bathy_coarse) == n_cast:
                    ax.fill_between(
                        x_ladcp, bathy_coarse, y_bottom, color="black", step="mid", lw=0
                    )

                ax.set_ylim(y_bottom, 0)
                ax.set_ylabel("Depth (m)")
                ax.set_xlabel(x_label)

                # Cast markers — open triangles matching other section panels
                _cast_markers(ax, x_ladcp, cast_nums_ladcp)

                ax.text(
                    0.01,
                    0.97,
                    panel_label,
                    transform=ax.transAxes,
                    va="top",
                    ha="left",
                    fontsize=8,
                    bbox={
                        "facecolor": "white",
                        "alpha": 0.6,
                        "pad": 2,
                        "edgecolor": "none",
                    },
                )
                _hide_outer_spines(ax)
                fig.tight_layout()
                panels.append(
                    Panel(b64=_fig_to_base64(fig), title=panel_title, short=panel_short)
                )
                plt.close(fig)

            return panels
    except Exception:
        if _pp.RAISE_ON_PLOT_ERROR:
            raise
        warnings.warn(
            "_make_ladcp_section_b64 failed; panels omitted",
            RuntimeWarning,
            stacklevel=2,
        )
        return []


def _make_section_ts_profiles_b64(
    ds_prof: xr.Dataset,
    x_vals: np.ndarray,
) -> str | None:
    """Return a base64 PNG of per-cast CT–SA profiles coloured by along-track distance.

    Each downcast in *ds_prof* is drawn as a CT–SA line with σ₀ background contours.
    Colour encodes the corresponding *x_vals* value (along-track km).
    """
    return render_b64(draw_section_ts_profiles_fig, ds_prof, x_vals)


def _make_ts_diagram_timeseries_b64(ds_ts: xr.Dataset) -> str | None:
    """Return a base64 PNG of a CT–SA diagram for all timeseries profiles, coloured by time.

    Each profile (N_PROF) is drawn as a line in CT–SA space.  Colour encodes hours
    since the first profile so temporal evolution is visible.  σ₀ background contours
    are overlaid.  Returns None if SA or CT are absent or fewer than two profiles exist.

    Parameters
    ----------
    ds_ts:
        2-D profiles dataset with dims ``(N_PROF, pressure)`` and variables
        ``SA``, ``CT``, ``time_start``.
    """
    return render_b64(draw_ts_diagram_timeseries_fig, ds_ts)


def _make_section_ts_histogram_b64(ds_prof: xr.Dataset) -> str | None:
    """Return a base64 PNG of a CT–SA 2-D count histogram (log₁₀ colour) for section profiles."""
    return render_b64(draw_section_ts_histogram_fig, ds_prof)


def _make_section_ts_o2_b64(ds_prof: xr.Dataset) -> str | None:
    """Return a base64 PNG of CT–SA histogram coloured by median O₂ saturation per bin."""
    return render_b64(draw_section_ts_o2_fig, ds_prof, optional=True)


def _make_section_map_b64(
    lats: list[float],
    lons: list[float],
    cast_nums: list[int],
    title: str = "",
    min_margin: float = 0.03,
    min_margin_lon: float | None = None,
) -> str | None:
    """Return a base64 PNG of a GEBCO map with the section track.

    *min_margin* sets a floor on the geographic margin for the latitude axis.
    *min_margin_lon*, when provided, sets a separate floor for the longitude
    axis and suppresses the N-S-section guard (use for co-located timeseries
    maps where lat and lon margins should be set independently for a
    Mercator-square view).
    """
    return render_b64(
        draw_section_map_fig,
        lats,
        lons,
        cast_nums,
        title=title,
        min_margin=min_margin,
        min_margin_lon=min_margin_lon,
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
) -> str | None:
    """Return a base64 PNG of *var* vs pressure × cast number (cruise overview panel).

    *ds_prof* must already be filtered to downcasts and sorted by cast_number.
    X-axis positions are evenly spaced (0, 1, …, N-1) with cast numbers as tick labels.
    *bathy_depths* (m, same length as N_PROF) draws a filled black bathymetry below data.

    Parameters
    ----------
    vmin, vmax:
        Optional colormap limit overrides; auto from 1–99th percentile if ``None``.
    style:
        ``"pcolormesh"`` (default) or ``"contourf"``.
    optional:
        Pass ``True`` for biogeochemical variables that may be absent in some casts.
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
    )


def _make_all_sections_map_b64(
    sections_data: list[dict[str, Any]],
    all_lats: list[float],
    all_lons: list[float],
    legend_outside: bool = False,
    *,
    target_h: float = 4.5,
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
    """
    fig_result = None
    try:
        with plt.style.context(str(_MPLSTYLE)):
            fig_result = draw_all_sections_map_fig(
                sections_data, all_lats, all_lons, legend_outside, target_h=target_h
            )
            if fig_result is None:
                return None
            fig_result.tight_layout()
            if legend_outside:
                fig_result.subplots_adjust(right=0.72)
            return _fig_to_base64(fig_result)
    except Exception:
        if _pp.RAISE_ON_PLOT_ERROR:
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
) -> str | None:
    """Return a base64 PNG of *var* vs cast time × pressure, both down and upcast.

    Parameters
    ----------
    style:
        ``"pcolormesh"`` (default) or ``"contourf"``.
    vmin, vmax:
        Colormap limits; if None, 2nd–98th percentile of valid data.
    figw:
        Figure width in inches; auto-computed from profile count if None.
    optional:
        Pass ``True`` for biogeochemical variables that may be absent in some casts.
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
    )


def _make_sensor_diff_b64(ds: xr.Dataset) -> str | None:
    """Return a base64 PNG of primary minus secondary sensor difference profiles.

    Shows T₁–T₂ and S₁–S₂ vs pressure with a fixed ±0.01 x-axis.
    Returns None if no secondary sensor variables are present.
    """
    return render_b64(draw_sensor_diff_fig, ds, optional=True)


def _make_pressure_time_b64(ds: xr.Dataset) -> str | None:
    """Return a base64 PNG of pressure vs elapsed time (cast trajectory + bottle stops)."""
    return render_b64(draw_pressure_time_fig, ds)


def _make_updown_diff_b64(ds: xr.Dataset) -> str | None:
    """Return a base64 PNG of downcast minus upcast profiles: ΔCT, ΔSA, Δσ₀.

    Both casts are interpolated to a shared 1-dbar pressure grid before differencing.
    Returns None if the overlap region is less than 10 dbar.
    """
    return render_b64(draw_updown_diff_fig, ds)


def _make_ladcp_bottomtrack_b64(ladcp_path: Path | None) -> str | None:
    """Return a base64 PNG of LADCP bottom-track U and V vs depth.

    Returns None if *ladcp_path* is None or the .mat file lacks ``zbot``, ``ubot``,
    or ``vbot`` fields.
    """
    if ladcp_path is None:
        return None
    return render_b64(draw_ladcp_bottomtrack_fig, ladcp_path, optional=True)
