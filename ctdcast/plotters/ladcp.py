"""LADCP figure builders: velocity sections and bottom-track panels."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
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
    overview_figsize,
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


class LadcpSectionGrid(NamedTuple):
    """LADCP velocity along a section on a common 10 m depth grid, shared by U and V.

    Built once per section by :func:`ladcp_section_grid` so the two panels share one
    read of the ``.mat`` files, one colour scale and one GEBCO lookup.
    """

    x: np.ndarray
    """Along-track x position of each cast that has LADCP data."""
    cast_nums: list[int]
    """Cast numbers of those casts, in the same order."""
    z_grid: np.ndarray
    """Depth axis (m), 0 to the deepest cast in 10 m steps."""
    u: np.ndarray
    """Eastward velocity, shape ``(cast, depth)``."""
    v: np.ndarray
    """Northward velocity, shape ``(cast, depth)``."""
    bounds: np.ndarray
    """Symmetric discrete colour boundaries shared by both components."""
    z_max: float
    """Deepest LADCP depth (m)."""
    dense_bathy_x: np.ndarray | None
    """Along-track x of the dense GEBCO profile, or None."""
    dense_bathy_d: np.ndarray | None
    """Water depth (m) of the dense GEBCO profile, or None."""
    bathy_coarse: np.ndarray | None
    """GEBCO water depth (m) at each cast, or None."""
    y_bottom: float
    """Lower plot limit (m): 5 % below the deeper of the data and the bathymetry."""


def ladcp_section_grid(
    cast_nums: list[int],
    x_vals: np.ndarray,
    ladcp_dir: Path,
    *,
    lats: list[float] | None = None,
    lons: list[float] | None = None,
    ladcp_pattern: str | None = None,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> LadcpSectionGrid | None:
    """Read and grid the LADCP casts of one section for the U and V panels.

    Parameters
    ----------
    cast_nums : list of int
        Cast numbers along the section, in along-track order.
    x_vals : numpy.ndarray
        Along-track x position of each cast (same length as *cast_nums*).
    ladcp_dir : pathlib.Path
        Directory holding the LADCP ``.mat`` files.
    lats, lons : list of float, optional
        Cast latitudes/longitudes, used for the GEBCO bathymetry.
    ladcp_pattern : str, optional
        Filename glob (e.g. ``"msm_142_1_*.mat"``) with ``*`` replaced by the
        zero-padded cast number; falls back to ``NNN.mat``.
    cfg : ReportConfig
        Report configuration; ``gebco_path`` supplies the bathymetry.

    Returns
    -------
    LadcpSectionGrid or None
        The shared grid, or None when fewer than two casts carry LADCP data or no
        finite velocity remains after gridding.
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
    return LadcpSectionGrid(
        x=x_ladcp,
        cast_nums=[t[1] for t in loaded],
        z_grid=z_grid,
        u=u_grid,
        v=v_grid,
        bounds=bounds,
        z_max=z_max,
        dense_bathy_x=dense_bathy_x,
        dense_bathy_d=dense_bathy_d,
        bathy_coarse=bathy_coarse,
        y_bottom=max(z_max, bathy_max) * 1.05,
    )


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
    grid: LadcpSectionGrid | None = None,
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
        components are gridded either way, so the symmetric RdBu_r colorbar is
        matched across the two panels regardless of which one is drawn.
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
    grid : LadcpSectionGrid, optional
        A grid already built by :func:`ladcp_section_grid` for these casts.  Pass it
        when drawing both components so the files are read once; when ``None`` it is
        built here from the arguments above.  When given, *cast_nums*, *x_vals*,
        *ladcp_dir*, *lats*, *lons* and *ladcp_pattern* are not read: the grid must
        have been built from the same casts.

    Returns
    -------
    matplotlib.figure.Figure or None
        The panel, or ``None`` when fewer than two casts carry LADCP data or no finite
        velocity remains after gridding.
    """
    if grid is None:
        grid = ladcp_section_grid(
            cast_nums,
            x_vals,
            ladcp_dir,
            lats=lats,
            lons=lons,
            ladcp_pattern=ladcp_pattern,
            cfg=cfg,
        )
    if grid is None:
        return None
    bounds = grid.bounds
    x_ladcp = grid.x
    cmap = plt.get_cmap("RdBu_r", len(bounds) - 1)
    norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

    grid_data, panel_label = (
        (grid.u, "U  East +") if component == "U" else (grid.v, "V  North +")
    )

    # Figure size: caller override (timeseries) or aspect-ratio formula (sections).
    abs_dist = abs(float(x_ladcp[-1] - x_ladcp[0])) if len(x_ladcp) > 1 else 10.0
    if figsize is not None:
        panel_w, panel_h = float(figsize[0]), float(figsize[1])
    else:
        (panel_w, panel_h), _ = section_figsize_and_slot(grid.z_max, abs_dist)

    fig, ax = plt.subplots(figsize=(panel_w, panel_h))
    if style == "contourf":
        X, Y = np.meshgrid(x_ladcp, grid.z_grid)
        Z = np.ma.masked_invalid(grid_data.T)
        mappable = ax.contourf(X, Y, Z, levels=bounds, cmap="RdBu_r", extend="both")
    else:
        mappable = ax.pcolormesh(
            x_ladcp,
            grid.z_grid,
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
    if grid.dense_bathy_x is not None and grid.dense_bathy_d is not None:
        ax.fill_between(
            grid.dense_bathy_x, grid.dense_bathy_d, grid.y_bottom, color="black", lw=0
        )
    elif grid.bathy_coarse is not None and len(grid.bathy_coarse) == len(x_ladcp):
        ax.fill_between(
            x_ladcp, grid.bathy_coarse, grid.y_bottom, color="black", step="mid", lw=0
        )

    ax.set_ylim(grid.y_bottom, 0)
    ax.set_ylabel("Depth (m)")
    ax.set_xlabel(x_label)

    # Cast markers — open triangles matching the other section panels.
    _cast_markers(ax, x_ladcp, grid.cast_nums)

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
    """Return LADCP bottom-track U and V vs depth.

    Parameters
    ----------
    ladcp_path : pathlib.Path or None
        LADCP ``.mat`` file for this cast.
    cfg : ReportConfig
        Report configuration; ``clean_spines`` sets the despine.
    width_in : float, default ``W_THIRD``
        Figure width in inches (third slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when *ladcp_path* is None or the file has no bottom-track solution.
    """
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


class LadcpOverviewGrid(NamedTuple):
    """Cruise-wide LADCP velocity on a cast-index × depth grid, shared by the U and V panels.

    Built once per page by :func:`ladcp_overview_grid` so the two panels share one
    colour scale and one GEBCO lookup.
    """

    cast_nums: np.ndarray
    """Cast numbers in ascending order, one per column."""
    x_pos: np.ndarray
    """Evenly spaced column positions (0, 1, 2, ...), one per cast."""
    depth: np.ndarray
    """Depth axis (m), trimmed to the deepest level with finite velocity."""
    u: np.ndarray
    """Eastward velocity, shape ``(cast, depth)``."""
    v: np.ndarray
    """Northward velocity, shape ``(cast, depth)``."""
    bounds: np.ndarray
    """Symmetric discrete colour boundaries shared by both components."""
    bathy: np.ndarray | None
    """GEBCO water depth (m) at each cast, or None without bathymetry."""
    y_bottom: float
    """Lower plot limit (m): 5 % below the deeper of the data and the bathymetry."""


def ladcp_overview_grid(
    ds_ladcp: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> LadcpOverviewGrid | None:
    """Sort, trim and scale a compiled ``ladcp_profiles.nc`` for the overview panels.

    Parameters
    ----------
    ds_ladcp : xarray.Dataset
        Compiled LADCP profiles (dims ``N_PROF`` × ``depth``) with ``u``, ``v``,
        ``cast_number``, ``latitude`` and ``longitude``.
    cfg : ReportConfig
        Report configuration; ``gebco_path`` supplies the bathymetry.

    Returns
    -------
    LadcpOverviewGrid or None
        The shared grid, or None when ``u``/``v`` are missing, fewer than two
        casts are present, or no velocity is finite.
    """
    if "u" not in ds_ladcp or "v" not in ds_ladcp:
        return None
    order = np.argsort(ds_ladcp["cast_number"].values)
    ds = ds_ladcp.isel(N_PROF=order)
    cast_nums = ds["cast_number"].values.astype(int)
    depth = ds["depth"].values
    u = np.asarray(ds["u"].values, dtype=float)  # (N_PROF, depth)
    v = np.asarray(ds["v"].values, dtype=float)

    # Trim the depth axis to the deepest level with finite velocity.
    valid_rows = np.where(np.any(np.isfinite(u) | np.isfinite(v), axis=0))[0]
    if len(valid_rows) < 1 or len(cast_nums) < 2:
        return None
    z_hi = valid_rows[-1] + 1
    depth = depth[:z_hi]
    u = u[:, :z_hi]
    v = v[:, :z_hi]

    all_fin = np.concatenate([u[np.isfinite(u)], v[np.isfinite(v)]])
    if not len(all_fin):
        return None
    vmax_val = max(float(np.nanpercentile(np.abs(all_fin), 98)), 1e-4)
    bounds = nice_colorbar_bounds(-vmax_val, vmax_val, n=20)

    # Bathymetry from GEBCO at each cast position (matches the CTD overview panels
    # on the same page).
    lats = ds["latitude"].values.tolist()
    lons = ds["longitude"].values.tolist()
    bathy = interpolate_bathy_at_casts(lats, lons, path=cfg.gebco_path)
    z_max = float(depth[-1])
    bathy_max = (
        float(np.nanmax(bathy))
        if bathy is not None and len(bathy) and np.any(np.isfinite(bathy))
        else 0.0
    )
    return LadcpOverviewGrid(
        cast_nums=cast_nums,
        x_pos=np.arange(len(cast_nums), dtype=float),
        depth=depth,
        u=u,
        v=v,
        bounds=bounds,
        bathy=bathy,
        y_bottom=max(z_max, bathy_max) * 1.05,
    )


def draw_ladcp_overview_fig(
    grid: LadcpOverviewGrid,
    component: str,
    cast_groups: dict[str, list[int]] | None = None,
    style: str = "pcolormesh",
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> plt.Figure:
    """Return one full-width LADCP velocity panel versus cast number × depth.

    The LADCP parallel of :func:`ctdcast.plotters.sections.draw_overview_panel_fig`:
    casts are evenly spaced along x, with a symmetric RdBu_r colorbar (positive =
    east/north) shared with the other component through *grid*.

    Parameters
    ----------
    grid : LadcpOverviewGrid
        The shared grid from :func:`ladcp_overview_grid`.
    component : {"U", "V"}
        Which velocity component to draw.
    cast_groups : dict of str to list of int, optional
        Section colour → cast numbers; drawn as coloured markers above the axes.
    style : {"pcolormesh", "contourf"}
        Field rendering.
    cfg : ReportConfig
        Report configuration; ``clean_spines`` is used, and ``overview_figsize``
        sets the size (its aspect ratio only, when *width_in* is given).
    width_in : float, optional
        Figure width in inches (the slot the panel is shown in); the height
        follows ``overview_figsize``'s aspect.  None uses ``overview_figsize`` as is.

    Returns
    -------
    matplotlib.figure.Figure
        The panel.
    """
    data, panel_label = {
        "U": (grid.u, "U  East +"),
        "V": (grid.v, "V  North +"),
    }[component]
    bounds = grid.bounds
    x_pos = grid.x_pos
    cast_nums = grid.cast_nums
    cmap = plt.get_cmap("RdBu_r", len(bounds) - 1)
    norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)
    cast_to_xpos = {int(cn): x_pos[i] for i, cn in enumerate(cast_nums)}

    # Evenly-spaced cast-number ticks and grid lines.  Unlike the CTD overview
    # panels (every cast present, ticks at multiples of 5), LADCP coverage is
    # sparse and unpredictable, so tick at ~10 evenly-spaced actual casts — always
    # integer cast numbers, never fractional defaults.
    tick_step = max(1, round(len(cast_nums) / 10))
    tick_idx = list(range(0, len(cast_nums), tick_step))
    tick_xpos = [x_pos[i] for i in tick_idx]
    tick_labels = [str(int(cast_nums[i])) for i in tick_idx]

    fig, ax = plt.subplots(figsize=overview_figsize(cfg.overview_figsize, width_in))

    for gx in tick_xpos:
        ax.axvline(gx, color="white", alpha=0.25, zorder=0)

    if style == "contourf":
        X, Y = np.meshgrid(x_pos, grid.depth)
        Z = np.ma.masked_invalid(data.T)
        mappable = ax.contourf(X, Y, Z, levels=bounds, cmap="RdBu_r", extend="both")
    else:
        mappable = ax.pcolormesh(
            x_pos, grid.depth, data.T, cmap=cmap, norm=norm, shading="nearest"
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

    if grid.bathy is not None and len(grid.bathy) == len(cast_nums):
        ax.fill_between(
            x_pos, grid.bathy, grid.y_bottom, color="black", step="mid", lw=0
        )

    # Coloured section markers above the top axis, matching the CTD overview panels.
    if cast_groups:
        for color, group_casts in cast_groups.items():
            gx = [cast_to_xpos[cn] for cn in group_casts if cn in cast_to_xpos]
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

    ax.set_ylim(grid.y_bottom, 0)
    ax.set_ylabel("Depth (m)")
    ax.set_xlabel("Cast number")
    ax.set_xticks(tick_xpos)
    ax.set_xticklabels(tick_labels, rotation=45, ha="right")
    ax.text(
        0.01,
        0.97,
        panel_label,
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=ANNOT_FS,
        bbox={"facecolor": "white", "alpha": 0.6, "pad": 2, "edgecolor": "none"},
    )
    hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig
