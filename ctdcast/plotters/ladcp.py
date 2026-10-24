"""LADCP figure builders: velocity sections and bottom-track panels."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter, MaxNLocator

from ctdcast.analysis.bathymetry import (
    dense_bathy_along_track,
    interpolate_bathy_at_casts,
)
from ctdcast.config.parameters import (
    VAR_COLORS,
    vlabel,
    vunit,
)
from ctdcast.config.report_config import DEFAULT_REPORT_CONFIG, ReportConfig
from ctdcast.plotters.primitives import (
    _cast_markers,
    hide_outer_spines,
    nice_colorbar_bounds,
    nice_colorbar_ticks,
    unit_colorbar,
)
from ctdcast.plotters.sections import (
    section_figsize_and_slot,
)
from ctdcast.readers.ladcp import find_ladcp_file, read_ladcp
from ctdcast.reports._vendored.design_tokens import (
    ANNOT_FS,
    pen,
)
from ctdcast.reports._vendored.design_tokens import (
    W_THIRD as _W_THIRD,
)

if TYPE_CHECKING:
    pass


def draw_ladcp_section_fig(
    cast_nums: list[int],
    x_vals: np.ndarray,
    x_label: str,
    ladcp_dir: Path,
    *,
    component: str,
    lats: list[float] | None = None,
    lons: list[float] | None = None,
    figsize: tuple[float, float] | None = None,
    ladcp_pattern: str | None = None,
    style: str = "pcolormesh",
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> plt.Figure | None:
    """Return one LADCP velocity-section panel (U or V) vs depth × along-track x.

    Parameters
    ----------
    cast_nums : list of int
        Cast numbers along the section, in along-track order.
    x_vals : numpy.ndarray
        Along-track x position of each cast (same length as *cast_nums*).
    x_label : str
        Axis label for the x coordinate.
    ladcp_dir : pathlib.Path
        Directory holding the LADCP ``.mat`` files.
    component : str
        ``"U"`` for the eastward panel or ``"V"`` for the northward panel.  Both
        components are loaded and gridded either way, so the symmetric RdBu_r colorbar
        is matched across the two panels regardless of which one is drawn.
    lats, lons : list of float, optional
        Cast latitudes/longitudes, used for the GEBCO bathymetry fill.
    figsize : tuple of float, optional
        Panel ``(width, height)`` in inches; when ``None`` the aspect-ratio formula
        :func:`section_figsize_and_slot` sets it from the depth and along-track extent.
    ladcp_pattern : str, optional
        Filename glob (e.g. ``"msm_142_1_*.mat"``) with ``*`` replaced by the
        zero-padded cast number; falls back to ``NNN.mat``.
    style : str
        ``"pcolormesh"`` (default) or ``"contourf"``.
    cfg : ReportConfig
        Report configuration (GEBCO path, spine style) threaded to the renderer.

    Returns
    -------
    matplotlib.figure.Figure or None
        The panel, or ``None`` when fewer than two casts carry LADCP data or no finite
        velocity remains after gridding.
    """
    lat_map = dict(zip(cast_nums, lats, strict=True)) if lats else {}
    lon_map = dict(zip(cast_nums, lons, strict=True)) if lons else {}

    # Load available casts; record x, cast_num, lat, lon, z, u, v.
    loaded: list[
        tuple[float, int, float, float, np.ndarray, np.ndarray, np.ndarray]
    ] = []
    for cn, xv in zip(cast_nums, x_vals, strict=True):
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
        except Exception:  # noqa: BLE001
            continue

    if len(loaded) < 2:
        return None

    x_ladcp = np.array([t[0] for t in loaded])
    cast_nums_ladcp = [t[1] for t in loaded]
    filt_lats = [t[2] for t in loaded]
    filt_lons = [t[3] for t in loaded]
    n_cast = len(loaded)

    # Interpolate to a common 10 m depth grid.
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

    # Symmetric RdBu_r colormap centred at zero — matched across both panels.
    all_fin = np.concatenate([u_grid[np.isfinite(u_grid)], v_grid[np.isfinite(v_grid)]])
    if not len(all_fin):
        return None
    vmax_val = max(float(np.nanpercentile(np.abs(all_fin), 98)), 1e-4)
    bounds = nice_colorbar_bounds(-vmax_val, vmax_val, n=20)
    cmap = plt.get_cmap("RdBu_r", len(bounds) - 1)
    norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

    grid_data, panel_label = (
        (u_grid, "U  East +") if component == "U" else (v_grid, "V  North +")
    )

    # Figure size: caller override (timeseries) or aspect-ratio formula (sections).
    abs_dist = abs(float(x_ladcp[-1] - x_ladcp[0])) if n_cast > 1 else 10.0
    if figsize is not None:
        panel_w, panel_h = float(figsize[0]), float(figsize[1])
    else:
        (panel_w, panel_h), _ = section_figsize_and_slot(z_max, abs_dist)

    # Dense bathy (smooth fill); fall back to cast-position bathy.
    dense_bathy_x, dense_bathy_d = dense_bathy_along_track(
        filt_lats, filt_lons, x_ladcp, path=cfg.gebco_path
    )
    bathy_coarse = interpolate_bathy_at_casts(filt_lats, filt_lons, path=cfg.gebco_path)
    bathy_max = (
        float(np.nanmax(dense_bathy_d))
        if dense_bathy_d is not None and len(dense_bathy_d)
        else float(np.nanmax(bathy_coarse))
        if bathy_coarse is not None and len(bathy_coarse)
        else 0.0
    )
    y_bottom = max(z_max, bathy_max) * 1.05

    fig, ax = plt.subplots(figsize=(panel_w, panel_h))
    if style == "contourf":
        X, Y = np.meshgrid(x_ladcp, z_grid)
        Z = np.ma.masked_invalid(grid_data.T)
        mappable = ax.contourf(X, Y, Z, levels=bounds, cmap="RdBu_r", extend="both")
    else:
        mappable = ax.pcolormesh(
            x_ladcp,
            z_grid,
            grid_data.T,
            cmap=cmap,
            norm=norm,
            shading="nearest",
        )
    # Same fixed-width, unit-on-top colorbar as the other field figures.
    unit_colorbar(
        ax,
        mappable,
        unit=vunit("U"),
        ticks=nice_colorbar_ticks(float(bounds[0]), float(bounds[-1])),
        extend="both",
        reserve=True,
        title_loc="left",
    )

    # Bathymetry — dense interpolation preferred.
    if dense_bathy_x is not None and dense_bathy_d is not None:
        ax.fill_between(dense_bathy_x, dense_bathy_d, y_bottom, color="black", lw=0)
    elif bathy_coarse is not None and len(bathy_coarse) == n_cast:
        ax.fill_between(
            x_ladcp, bathy_coarse, y_bottom, color="black", step="mid", lw=0
        )

    ax.set_ylim(y_bottom, 0)
    ax.set_ylabel("Depth (m)")
    ax.set_xlabel(x_label)

    # Cast markers — open triangles matching the other section panels.
    _cast_markers(ax, x_ladcp, cast_nums_ladcp)

    ax.text(
        0.01,
        0.97,
        panel_label,
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=ANNOT_FS,
        bbox={
            "facecolor": "white",
            "alpha": 0.6,
            "pad": 2,
            "edgecolor": "none",
        },
    )
    hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_ladcp_bottomtrack_fig(
    ladcp_path: Path | None,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_THIRD,
) -> plt.Figure | None:
    """Return a LADCP bottom-track U and V vs depth Figure."""
    if ladcp_path is None:
        return None

    m = read_ladcp(ladcp_path)
    dr = m["dr"]
    if not all(hasattr(dr, f) for f in ("zbot", "ubot", "vbot")):
        return None
    z = np.asarray(dr.zbot, dtype=float)
    u = np.asarray(dr.ubot, dtype=float)
    v = np.asarray(dr.vbot, dtype=float)
    if not len(z):
        return None

    fig, axes = plt.subplots(
        1, 2, sharey=True, figsize=(width_in, width_in * 1.8 / _W_THIRD)
    )

    for ax, vel, xlabel, color in zip(
        axes,
        [u, v],
        [f"{vlabel('U')}\nEast +", f"{vlabel('V')}\nNorth +"],
        [VAR_COLORS["U"], VAR_COLORS["V"]],
        strict=True,
    ):
        ax.fill_betweenx(z, 0, np.where(vel > 0, vel, 0.0), color=color, alpha=0.5)
        ax.fill_betweenx(z, np.where(vel < 0, vel, 0.0), 0, color=color, alpha=0.5)
        ax.plot(vel, z, color=color, lw=pen("thin"))
        ax.axvline(0, color="0.5", lw=pen("thinner"), ls="--")
        ax.set_xlabel(xlabel)
        ax.grid(True)

    axes[0].set_ylabel("Depth (m)")
    axes[0].set_ylim(float(z.max()) * 1.02, float(z.min()) * 0.98)
    xlim = float(np.nanmax(np.abs(np.concatenate([u, v])))) * 1.05
    for ax in axes:
        ax.set_xlim(-xlim, xlim)
        # Narrow panels: cap the ticks and show one decimal so the labels do not
        # collide (2-dp ticks ran together as "−0.250.000.25").
        ax.xaxis.set_major_locator(MaxNLocator(nbins=3))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda val, _pos: f"{val:.1f}"))
    hide_outer_spines(*axes, clean=cfg.clean_spines)
    return fig
