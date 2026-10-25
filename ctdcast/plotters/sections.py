"""Section figure builders: depth–distance sections, section T–S panels and the overview panel."""

from __future__ import annotations

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from ctdcast.config.parameters import (
    vlabel,
    vunit,
)
from ctdcast.config.report_config import DEFAULT_REPORT_CONFIG, ReportConfig
from ctdcast.plotters.primitives import (
    _cast_markers,
    _discrete_norm,
    _sigma0_backdrop,
    hide_outer_spines,
    mesh_field,
    nice_colorbar_bounds,
    sigma0_isopycnals,
)
from ctdcast.reports._vendored.design_tokens import (
    MAX_SECTION_H as _MAX_SECTION_H,
)
from ctdcast.reports._vendored.design_tokens import (
    MIN_SECTION_H as _MIN_SECTION_H,
)
from ctdcast.reports._vendored.design_tokens import (
    SECTION_STRETCH as _SECTION_STRETCH,
)
from ctdcast.reports._vendored.design_tokens import (
    W_FULL as _W_FULL,
)
from ctdcast.reports._vendored.design_tokens import (
    W_HALF as _W_HALF,
)
from ctdcast.reports._vendored.design_tokens import (
    W_THIRD as _W_THIRD,
)
from ctdcast.reports._vendored.design_tokens import (
    W_TWOTHIRDS as _W_TWOTHIRDS,
)
from ctdcast.reports._vendored.design_tokens import (
    pen,
)


def overview_figsize(
    overview_size: tuple[float, float], width_in: float | None
) -> tuple[float, float]:
    """Return the overview-panel figure size: *width_in* wide at *overview_size*'s aspect.

    Parameters
    ----------
    overview_size : tuple of float
        ``(width, height)`` in inches from the report configuration; only its
        aspect ratio is used when *width_in* is given.
    width_in : float or None
        Figure width in inches (the slot the panel is shown in); None keeps
        *overview_size* unchanged.

    Returns
    -------
    tuple of float
        ``(width, height)`` in inches.
    """
    w, h = overview_size
    if width_in is None:
        return float(w), float(h)
    return float(width_in), float(width_in) * float(h) / float(w)


def section_figsize_and_slot(
    p_max_dbar: float,
    dist_km: float,
) -> tuple[tuple[float, float], str]:
    """Return figure size and CSS slot class for a section pcolormesh plot.

    The figure width is always a **canonical slot width** (one of ``SLOTS``), so
    the rendered PNG fills its slot at the same oversample as every other figure and
    the browser never rescales it — otherwise a section rendered at a between-slots
    width is squeezed into the nearest slot box, shrinking its baked-in fonts.

    Aspect is calibrated (``_SECTION_STRETCH``) so KTout (416 dbar, 94 km) is short
    at full width.  The widest slot whose resulting height stays within
    ``_MAX_SECTION_H`` is chosen; height then follows the data aspect (floored at
    ``_MIN_SECTION_H``).  A section too deep for even the narrowest slot keeps that
    slot's width and accepts the height cap.

    Parameters
    ----------
    p_max_dbar:
        Maximum pressure in the section (dbar).
    dist_km:
        Total along-track distance of the section (km).

    Returns
    -------
    tuple of ``((fig_w, fig_h), css_slot)`` where ``fig_w`` equals the slot's
    canonical inch width and ``css_slot`` is one of ``"slot-full"``,
    ``"slot-twothirds"``, ``"slot-half"``, or ``"slot-third"``.
    """
    dist = max(abs(dist_km), 1.0)  # abs: x_vals may be flipped for east→west sections
    ratio = p_max_dbar / (dist * _SECTION_STRETCH)  # fig_h per inch of fig_w
    # Widest canonical slot whose height stays within the cap; the aspect ratio
    # means a narrower width yields a shorter figure, so descending widths fit.
    candidates = (
        ("slot-full", _W_FULL),
        ("slot-twothirds", _W_TWOTHIRDS),
        ("slot-half", _W_HALF),
        ("slot-third", _W_THIRD),
    )
    slot, fig_w = candidates[-1]  # deepest sections fall back to the narrowest slot
    for name, width in candidates:
        if width * ratio <= _MAX_SECTION_H:
            slot, fig_w = name, width
            break
    fig_h = float(min(max(fig_w * ratio, _MIN_SECTION_H), _MAX_SECTION_H))
    return (fig_w, fig_h), slot


def draw_section_fig(
    ds_prof: xr.Dataset,
    var: str,
    label: str,  # noqa: ARG001 — full label retained for callers; figure shows units only
    x_vals: np.ndarray,
    x_label: str,
    title: str = "",  # noqa: ARG001
    style: str = "pcolormesh",
    bathy_depths: np.ndarray | None = None,
    bathy_x: np.ndarray | None = None,
    cast_labels: list | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    figsize: tuple[float, float] | None = None,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> plt.Figure | None:
    """Return a Figure of *var* vs pressure × along-track distance.

    Parameters
    ----------
    ds_prof : xarray.Dataset
        Profiles gridded on ``pressure`` × profile, one profile per *x_vals* entry.
    var : str
        Variable to plot from *ds_prof*.
    label : str
        Accepted for call-site compatibility; the colorbar shows units only.
    x_vals : numpy.ndarray
        Along-track position of each profile.
    x_label : str
        x-axis label.
    title : str
        Accepted for call-site compatibility and ignored.
    style : {"pcolormesh", "contourf"}
        Field rendering.
    bathy_depths : numpy.ndarray, optional
        Water depth (m) for the bathymetry fill, at *bathy_x* when given, else at
        *x_vals*.
    bathy_x : numpy.ndarray, optional
        Denser along-track positions (km) for *bathy_depths*; used only when its
        length matches, otherwise the fill falls back to *x_vals*.
    cast_labels : list, optional
        Cast numbers drawn as markers along the top edge (same length as *x_vals*).
    vmin, vmax : float, optional
        Colour limits; each defaults to the 2nd / 98th percentile of the data.
    figsize : tuple of float, optional
        ``(width, height)`` in inches, used unchanged so a caller can keep the PNG
        and its slot consistent; when None, :func:`section_figsize_and_slot` sets it
        from the data's depth and along-track extent.
    cfg : ReportConfig
        Report configuration; ``var_cmaps`` gives the colormap for *var*.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when *var* is absent or has no finite values.
    """
    if var not in ds_prof:
        return None
    pressure = ds_prof["pressure"].values
    data = ds_prof[var].values

    valid_cols = np.where(np.any(np.isfinite(data), axis=0))[0]
    if not len(valid_cols):
        return None
    p_trim = pressure[: valid_cols[-1] + 1]
    data_trim = data[:, : valid_cols[-1] + 1]

    d_fin = data_trim[np.isfinite(data_trim)]
    if not len(d_fin):
        return None

    cmap, norm, bounds, cmap_name = _discrete_norm(
        d_fin, var, vmin, vmax, var_cmaps=cfg.var_cmaps
    )

    dist = abs(float(x_vals[-1] - x_vals[0])) if len(x_vals) > 1 else 10.0
    p_max_data = float(p_trim[-1])
    if figsize is not None:
        fig_w, fig_h = figsize
    else:
        (fig_w, fig_h), _ = section_figsize_and_slot(p_max_data, dist)

    # Y extent: deeper of data max and bathy max
    p_max_bathy = (
        float(np.nanmax(bathy_depths))
        if bathy_depths is not None and len(bathy_depths)
        else 0.0
    )
    y_bottom = max(p_max_data, p_max_bathy) * 1.05

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    mesh_field(
        ax,
        fig,
        x_vals,
        p_trim,
        data_trim,
        cmap=cmap,
        norm=norm,
        cmap_name=cmap_name,
        bounds=bounds,
        style=style,
        cbar_label=vunit(var),
    )

    if bathy_depths is not None:
        bx = (
            bathy_x
            if (bathy_x is not None and len(bathy_x) == len(bathy_depths))
            else x_vals
        )
        if len(bathy_depths) == len(bx):
            step = "mid" if bathy_x is None else None
            ax.fill_between(
                bx, bathy_depths, y_bottom, color="#3a3a3a", step=step, lw=0
            )

    if var == "sigma0":
        sigma0_isopycnals(ax, x_vals, p_trim, data_trim)

    ax.set_ylim(y_bottom, 0)
    ax.set_xlim(float(x_vals[0]), float(x_vals[-1]))
    ax.set_ylabel(vlabel("pressure"))
    ax.set_xlabel(x_label)

    if cast_labels is not None and len(cast_labels) == len(x_vals):
        _cast_markers(ax, x_vals, cast_labels)

    return fig


def draw_section_ts_profiles_fig(
    ds_prof: xr.Dataset,
    x_vals: np.ndarray,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_THIRD,
) -> plt.Figure | None:
    """Return a Figure of per-cast CT–SA profiles coloured by along-track distance.

    Parameters
    ----------
    ds_prof : xarray.Dataset
        Section profiles with ``absolute_salinity`` and ``conservative_temperature``.
    x_vals : numpy.ndarray
        Along-track position (km) of each profile; sets the colour.
    cfg : ReportConfig
        Report configuration; ``clean_spines`` sets the despine.
    width_in : float, default ``W_THIRD``
        Figure width in inches (third slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when SA or CT is absent or has no finite values.
    """
    if "absolute_salinity" not in ds_prof or "conservative_temperature" not in ds_prof:
        return None
    sa_all = ds_prof["absolute_salinity"].values  # (N_PROF, N_P)
    ct_all = ds_prof["conservative_temperature"].values  # (N_PROF, N_P)
    sa_fin = sa_all[np.isfinite(sa_all)]
    ct_fin = ct_all[np.isfinite(ct_all)]
    if not len(sa_fin) or not len(ct_fin):
        return None

    sa_lo = float(np.nanpercentile(sa_fin, 0.5))
    sa_hi = float(np.nanpercentile(sa_fin, 99.5))
    ct_lo = float(np.nanpercentile(ct_fin, 0.5))
    ct_hi = float(np.nanpercentile(ct_fin, 99.5))

    x_lo, x_hi = float(x_vals.min()), float(x_vals.max())
    if x_hi <= x_lo:
        x_hi = x_lo + 1.0
    bounds = nice_colorbar_bounds(x_lo, x_hi, n=12)
    cmap = plt.get_cmap("plasma", len(bounds) - 1)
    norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

    fig, ax = plt.subplots(figsize=(width_in, width_in * 3.8 / _W_THIRD))

    for i in range(sa_all.shape[0]):
        mask = np.isfinite(sa_all[i]) & np.isfinite(ct_all[i])
        if not mask.any():
            continue
        ax.plot(
            sa_all[i, mask],
            ct_all[i, mask],
            color=cmap(norm(float(x_vals[i]))),
            alpha=0.6,
            lw=pen("thin"),
        )
    _sigma0_backdrop(ax)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cb = fig.colorbar(
        sm,
        ax=ax,
        orientation="horizontal",
        location="bottom",
        ticks=bounds[::2],
        pad=0.18,
        shrink=0.9,
        aspect=20,
    )
    cb.set_label("Along-track distance (km)", loc="left")

    ax.set_xlim(sa_lo, sa_hi)
    ax.set_ylim(ct_lo, ct_hi)
    ax.set_xlabel(vlabel("absolute_salinity"))
    ax.set_ylabel(vlabel("conservative_temperature"))
    ax.grid(False)
    hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_ts_diagram_timeseries_fig(
    ds_ts: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_THIRD,
) -> plt.Figure | None:
    """Return a CT–SA diagram Figure for all time-series profiles, coloured by time.

    Parameters
    ----------
    ds_ts : xarray.Dataset
        Profiles (``N_PROF`` × ``pressure``) with ``absolute_salinity``,
        ``conservative_temperature`` and ``time_start``.
    cfg : ReportConfig
        Report configuration; ``clean_spines`` sets the despine.
    width_in : float, default ``W_THIRD``
        Figure width in inches (third slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when SA or CT is absent, fewer than two profiles exist, or no value is finite.
    """
    if "absolute_salinity" not in ds_ts or "conservative_temperature" not in ds_ts:
        return None
    sa_all = ds_ts["absolute_salinity"].values  # (N_PROF, N_P)
    ct_all = ds_ts["conservative_temperature"].values
    if sa_all.shape[0] < 2:
        return None

    sa_fin = sa_all[np.isfinite(sa_all)]
    ct_fin = ct_all[np.isfinite(ct_all)]
    if not len(sa_fin) or not len(ct_fin):
        return None

    sa_lo = float(np.nanpercentile(sa_fin, 0.5))
    sa_hi = float(np.nanpercentile(sa_fin, 99.5))
    ct_lo = float(np.nanpercentile(ct_fin, 0.5))
    ct_hi = float(np.nanpercentile(ct_fin, 99.5))

    # Colourbar: hours since first profile
    t_ns = ds_ts["time_start"].values.astype("datetime64[ns]").astype(float)
    t_hours = (t_ns - t_ns[0]) / 3.6e12
    t_lo, t_hi = float(t_hours[0]), float(t_hours[-1])
    if t_hi <= t_lo:
        t_hi = t_lo + 1.0
    bounds = nice_colorbar_bounds(t_lo, t_hi, n=12)
    cmap = plt.get_cmap("plasma", len(bounds) - 1)
    norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

    fig, ax = plt.subplots(figsize=(width_in, width_in * 3.8 / _W_THIRD))

    for i in range(sa_all.shape[0]):
        mask = np.isfinite(sa_all[i]) & np.isfinite(ct_all[i])
        if not mask.any():
            continue
        ax.plot(
            sa_all[i, mask],
            ct_all[i, mask],
            color=cmap(norm(float(t_hours[i]))),
            alpha=0.6,
            lw=pen("thin"),
        )
    _sigma0_backdrop(ax)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cb = fig.colorbar(
        sm,
        ax=ax,
        orientation="horizontal",
        location="bottom",
        ticks=bounds[::2],
        pad=0.18,
        shrink=0.9,
        aspect=20,
    )
    cb.set_label("Hours since start", loc="left")

    ax.set_xlim(sa_lo, sa_hi)
    ax.set_ylim(ct_lo, ct_hi)
    ax.set_xlabel(vlabel("absolute_salinity"))
    ax.set_ylabel(vlabel("conservative_temperature"))
    ax.grid(False)
    hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_section_ts_histogram_fig(
    ds_prof: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_THIRD,
) -> plt.Figure | None:
    """Return a CT–SA two-dimensional count histogram Figure (log₁₀ colour) for section profiles.

    Parameters
    ----------
    ds_prof : xarray.Dataset
        Profiles with ``absolute_salinity`` and ``conservative_temperature``.
    cfg : ReportConfig
        Report configuration; ``clean_spines`` sets the despine.
    width_in : float, default ``W_THIRD``
        Figure width in inches (third slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when SA or CT is absent or fewer than ten valid points remain.
    """
    if "absolute_salinity" not in ds_prof or "conservative_temperature" not in ds_prof:
        return None
    sa = ds_prof["absolute_salinity"].values.ravel()
    ct = ds_prof["conservative_temperature"].values.ravel()
    mask = np.isfinite(sa) & np.isfinite(ct)
    sa, ct = sa[mask], ct[mask]
    if len(sa) < 10:
        return None

    # Clip to 0.5–99.5th percentile so a single outlier cast doesn't blow out the range.
    sa_lo = float(np.nanpercentile(sa, 0.5))
    sa_hi = float(np.nanpercentile(sa, 99.5))
    ct_lo = float(np.nanpercentile(ct, 0.5))
    ct_hi = float(np.nanpercentile(ct, 99.5))

    sa_edges = np.linspace(sa_lo, sa_hi, 51)
    ct_edges = np.linspace(ct_lo, ct_hi, 51)
    counts, _, _ = np.histogram2d(sa, ct, bins=[sa_edges, ct_edges])

    sa_c = (sa_edges[:-1] + sa_edges[1:]) / 2
    ct_c = (ct_edges[:-1] + ct_edges[1:]) / 2
    counts_log = np.log10(np.where(counts.T > 0, counts.T, np.nan))

    c_fin = counts_log[np.isfinite(counts_log)]
    if not len(c_fin):
        return None
    bounds_c = nice_colorbar_bounds(float(c_fin.min()), float(c_fin.max()), n=12)
    cmap_c = plt.cm.YlOrRd.copy()
    cmap_c.set_bad("white")
    norm_c = mcolors.BoundaryNorm(bounds_c, ncolors=256)

    fig, ax = plt.subplots(figsize=(width_in, width_in * 3.8 / _W_THIRD))
    pc = ax.pcolormesh(sa_c, ct_c, counts_log, cmap=cmap_c, norm=norm_c)
    _sigma0_backdrop(ax)
    cb = fig.colorbar(
        pc,
        ax=ax,
        orientation="horizontal",
        location="bottom",
        ticks=bounds_c[::2],
        pad=0.18,
        shrink=0.9,
        aspect=20,
    )
    cb.set_label(r"$\log_{10}$(count)", loc="left")

    ax.set_xlim(sa_lo, sa_hi)
    ax.set_ylim(ct_lo, ct_hi)
    ax.set_xlabel(vlabel("absolute_salinity"))
    ax.set_ylabel(vlabel("conservative_temperature"))
    ax.grid(False)
    hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_section_ts_o2_fig(
    ds_prof: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_THIRD,
) -> plt.Figure | None:
    """Return a CT–SA Figure coloured by the median oxygen in each T–S bin (bins with at least two points).

    Parameters
    ----------
    ds_prof : xarray.Dataset
        Profiles with ``absolute_salinity``, ``conservative_temperature`` and an
        oxygen variable.
    cfg : ReportConfig
        Report configuration; ``clean_spines`` sets the despine.
    width_in : float, default ``W_THIRD``
        Figure width in inches (third slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when SA, CT or oxygen is absent or fewer than ten valid points remain.
    """
    _o2_var = next((v for v in ("oxygen_saturation", "oxsat_1") if v in ds_prof), None)
    if (
        "absolute_salinity" not in ds_prof
        or "conservative_temperature" not in ds_prof
        or _o2_var is None
    ):
        return None
    sa = ds_prof["absolute_salinity"].values.ravel()
    ct = ds_prof["conservative_temperature"].values.ravel()
    o2 = ds_prof[_o2_var].values.ravel()
    mask = np.isfinite(sa) & np.isfinite(ct) & np.isfinite(o2)
    sa, ct, o2 = sa[mask], ct[mask], o2[mask]
    if len(sa) < 10:
        return None

    sa_lo = float(np.nanpercentile(sa, 0.5))
    sa_hi = float(np.nanpercentile(sa, 99.5))
    ct_lo = float(np.nanpercentile(ct, 0.5))
    ct_hi = float(np.nanpercentile(ct, 99.5))

    n_sa, n_ct = 50, 50
    sa_edges = np.linspace(sa_lo, sa_hi, n_sa + 1)
    ct_edges = np.linspace(ct_lo, ct_hi, n_ct + 1)
    sa_c = (sa_edges[:-1] + sa_edges[1:]) / 2
    ct_c = (ct_edges[:-1] + ct_edges[1:]) / 2

    sa_b = np.clip(np.searchsorted(sa_edges, sa, side="right") - 1, 0, n_sa - 1)
    ct_b = np.clip(np.searchsorted(ct_edges, ct, side="right") - 1, 0, n_ct - 1)
    flat = sa_b * n_ct + ct_b

    order = np.argsort(flat)
    flat_s, o2_s = flat[order], o2[order]
    uniq_f, starts = np.unique(flat_s, return_index=True)
    stops = np.r_[starts[1:], len(flat_s)]

    o2_flat = np.full(n_sa * n_ct, np.nan)
    for k, fi in enumerate(uniq_f):
        pts = o2_s[starts[k] : stops[k]]
        if len(pts) >= 2:
            o2_flat[int(fi)] = float(np.median(pts))

    o2_grid = o2_flat.reshape(n_sa, n_ct).T  # (ct_bins, sa_bins) for pcolormesh
    o2_fin = o2_grid[np.isfinite(o2_grid)]
    if not len(o2_fin):
        return None

    bounds_o = nice_colorbar_bounds(
        float(np.nanpercentile(o2_fin, 2)),
        float(np.nanpercentile(o2_fin, 98)),
        n=16,
    )
    cmap_o = plt.get_cmap("RdYlGn", len(bounds_o) - 1)
    norm_o = mcolors.BoundaryNorm(bounds_o, ncolors=cmap_o.N)

    fig, ax = plt.subplots(figsize=(width_in, width_in * 3.8 / _W_THIRD))
    pc = ax.pcolormesh(sa_c, ct_c, o2_grid, cmap=cmap_o, norm=norm_o)
    _sigma0_backdrop(ax)
    cb = fig.colorbar(
        pc,
        ax=ax,
        orientation="horizontal",
        location="bottom",
        ticks=bounds_o[::2],
        pad=0.18,
        shrink=0.9,
        aspect=20,
    )
    cb.set_label(r"Median $O_2$ saturation (%)", loc="left")

    ax.set_xlim(sa_lo, sa_hi)
    ax.set_ylim(ct_lo, ct_hi)
    ax.set_xlabel(vlabel("absolute_salinity"))
    ax.set_ylabel(vlabel("conservative_temperature"))
    ax.grid(False)
    hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_overview_panel_fig(
    ds_prof: xr.Dataset,
    var: str,
    label: str,  # noqa: ARG001 — full label retained for callers; figure shows units only
    bathy_depths: np.ndarray | None = None,
    style: str = "pcolormesh",
    vmin: float | None = None,
    vmax: float | None = None,
    cast_groups: dict[str, list[int]] | None = None,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> plt.Figure | None:
    """Return a Figure of *var* vs pressure × cast number (cruise overview panel).

    Parameters
    ----------
    ds_prof : xarray.Dataset
        Downcast profiles sorted by ``cast_number``; casts are evenly spaced
        along x with cast numbers as tick labels.
    var : str
        Variable to plot from *ds_prof*.
    label : str
        Accepted for call-site compatibility; the colorbar shows units only.
    bathy_depths : numpy.ndarray, optional
        Water depth (m) at each cast (length ``N_PROF``), drawn as a black fill.
    style : {"pcolormesh", "contourf"}
        Field rendering.
    vmin, vmax : float, optional
        Colour limits; each defaults to the 2nd / 98th percentile of the data.
    cast_groups : dict of str to list of int, optional
        Section colour → cast numbers, drawn as coloured markers above the axes.
    cfg : ReportConfig
        Report configuration; ``var_cmaps`` is used, and ``overview_figsize``
        sets the size (its aspect ratio only, when *width_in* is given).
    width_in : float, optional
        Figure width in inches (the slot the panel is shown in); the height
        follows ``overview_figsize``'s aspect.  None uses ``overview_figsize`` as is.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when *var* is absent or has no finite values.
    """
    if var not in ds_prof:
        return None
    pressure = ds_prof["pressure"].values
    data = ds_prof[var].values  # (N_PROF, N_P)
    cast_nums = ds_prof["cast_number"].values.astype(int)

    valid_cols = np.where(np.any(np.isfinite(data), axis=0))[0]
    if not len(valid_cols):
        return None
    p_trim = pressure[: valid_cols[-1] + 1]
    data_trim = data[:, : valid_cols[-1] + 1]

    d_fin = data_trim[np.isfinite(data_trim)]
    if not len(d_fin):
        return None

    cmap, norm, bounds, cmap_name = _discrete_norm(
        d_fin, var, vmin, vmax, var_cmaps=cfg.var_cmaps
    )

    x_pos = np.arange(len(cast_nums), dtype=float)

    # Y extent: deeper of data max and bathy
    p_max_data = float(p_trim[-1])
    p_max_bathy = (
        float(np.nanmax(bathy_depths))
        if bathy_depths is not None and len(bathy_depths)
        else 0.0
    )
    y_bottom = max(p_max_data, p_max_bathy) * 1.05

    fig, ax = plt.subplots(figsize=overview_figsize(cfg.overview_figsize, width_in))

    # Subtle cast-position gridlines drawn before the fill so the fill sits on top.
    # Use multiples of 5 or 10 cast numbers as grid positions.
    n_casts = len(cast_nums)
    _grid_step = 5 if n_casts <= 100 else 10
    _cast_to_xpos = {int(cn): x_pos[i] for i, cn in enumerate(cast_nums)}
    for cn_i, cn in enumerate(cast_nums):
        if int(cn) % _grid_step == 0:
            ax.axvline(
                x_pos[cn_i], color="white", lw=pen("thinner"), alpha=0.25, zorder=0
            )

    mesh_field(
        ax,
        fig,
        x_pos,
        p_trim,
        data_trim,
        cmap=cmap,
        norm=norm,
        cmap_name=cmap_name,
        bounds=bounds,
        style=style,
        cbar_label=vunit(var),
    )

    if bathy_depths is not None:
        ax.fill_between(
            x_pos, bathy_depths, y_bottom, color="#3a3a3a", step="mid", lw=0
        )

    if var == "sigma0":
        sigma0_isopycnals(ax, x_pos, p_trim, data_trim)

    # Open triangle markers above top axis for casts belonging to each group
    if cast_groups:
        for color, group_casts in cast_groups.items():
            gx = [_cast_to_xpos[cn] for cn in group_casts if cn in _cast_to_xpos]
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
    ax.set_ylabel(vlabel("pressure"))
    ax.set_xlabel("Cast number")

    # Tick marks at multiples of 5 or 10, matching the grid lines
    tick_cast_nums = [cn for cn in cast_nums if int(cn) % _grid_step == 0]
    tick_xpos = [
        _cast_to_xpos[int(cn)] for cn in tick_cast_nums if int(cn) in _cast_to_xpos
    ]
    if tick_xpos:
        ax.set_xticks(tick_xpos)
        ax.set_xticklabels(
            [str(int(cn)) for cn in tick_cast_nums if int(cn) in _cast_to_xpos],
            rotation=45,
            ha="right",
        )

    return fig
