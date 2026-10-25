"""Per-cast profile figure builders: T–S diagrams, stability, auxiliary profiles, QC histograms."""

from __future__ import annotations

import math
import warnings
from pathlib import Path

import gsw
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from ctdcast.analysis.derive import derive_teos10 as add_teos10
from ctdcast.config.parameters import (
    VAR_COLORS,
    vlabel,
    vunit,
)
from ctdcast.config.report_config import DEFAULT_REPORT_CONFIG, ReportConfig
from ctdcast.plotters.primitives import (
    _SIGMA0_CONTOUR_COLOR,
    _TS_COLORS,
    _UPCAST_COLOR,
    _sigma0_backdrop,
    hide_outer_spines,
)
from ctdcast.processors.stage2 import split_cast
from ctdcast.readers.ladcp import read_ladcp
from ctdcast.reports._vendored.design_tokens import (
    ANNOT_FS,
    CLABEL_FS,
    pen,
)
from ctdcast.reports._vendored.design_tokens import (
    W_FULL as _W_FULL,
)
from ctdcast.reports._vendored.design_tokens import (
    W_THIRD as _W_THIRD,
)
from ctdcast.reports._vendored.design_tokens import (
    W_THREE_FIFTHS as _W_THREE_FIFTHS,
)
from ctdcast.reports._vendored.design_tokens import (
    W_TWO_FIFTHS as _W_TWO_FIFTHS,
)
from ctdcast.reports._vendored.design_tokens import (
    W_TWOTHIRDS as _W_TWOTHIRDS,
)

_LADCP_U_COLOR: str = VAR_COLORS["U"]

_LADCP_V_COLOR: str = VAR_COLORS["V"]


def draw_ts_density_fig(
    ds: xr.Dataset,
    ladcp_path: Path | None = None,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> plt.Figure | None:
    """Return a CT/SA/σ₀ profile Figure, optionally alongside LADCP U/V.

    Parameters
    ----------
    ds : xarray.Dataset
        Per-cast dataset with ``pressure`` and the T/S channels; CT, SA and σ₀
        are derived here (TEOS-10) and the downcast is selected.
    ladcp_path : pathlib.Path, optional
        LADCP ``.mat`` file for this cast.  None draws the single-column profile
        at ``cfg.profile_figsize``; a path draws a second column with U/V, or a
        placeholder when the file does not exist.
    cfg : ReportConfig
        Report configuration; ``clean_spines`` and ``profile_figsize`` are used.

    Returns
    -------
    matplotlib.figure.Figure
        The figure.
    """
    ds_teos = add_teos10(ds)
    ds_down, _ = split_cast(ds_teos)
    p = ds_down["pressure"].values
    ct = ds_down["conservative_temperature"].values
    sa = ds_down["absolute_salinity"].values
    sig = ds_down["sigma0"].values

    if ladcp_path is None:
        # Single-column: CT/SA/σ₀ triple-axis profile only
        fig, ax0 = plt.subplots(figsize=cfg.profile_figsize)
        ax1 = ax0.twiny()
        ax2 = ax0.twiny()
        (l0,) = ax0.plot(ct, p, color=_TS_COLORS[0], label="CT")
        (l1,) = ax1.plot(sa, p, color=_TS_COLORS[1], label="SA")
        (l2,) = ax2.plot(sig, p, color=_TS_COLORS[2], label="σ₀")
        # ax1/ax2 use the top spine — restore visibility even if cfg.clean_spines.
        ax2.spines["top"].set_position(("axes", 1.12))
        ax1.spines["top"].set_visible(True)
        ax2.spines["top"].set_visible(True)
        for ax, line in zip((ax0, ax1, ax2), (l0, l1, l2), strict=True):
            ax.xaxis.label.set_color(line.get_color())
            ax.tick_params(axis="x", colors=line.get_color())
            ax.spines["top"].set_edgecolor(line.get_color())
        for ax, vals in ((ax0, ct), (ax1, sa), (ax2, sig)):
            fin = vals[np.isfinite(vals)]
            if len(fin) > 1:
                lo, hi = float(np.percentile(fin, 1)), float(np.percentile(fin, 99))
                pad = max((hi - lo) * 0.05, 1e-6)
                ax.set_xlim(lo - pad, hi + pad)
        ax0.set_ylim(float(np.nanmax(p)), 0)
        ax0.set_ylabel(vlabel("pressure"))
        ax0.set_xlabel(vlabel("conservative_temperature"), color=_TS_COLORS[0])
        ax1.set_xlabel(vlabel("absolute_salinity"), color=_TS_COLORS[1])
        ax2.set_xlabel(vlabel("sigma0"), color=_TS_COLORS[2])
        ax0.grid(True)
        if cfg.clean_spines:
            ax0.spines["right"].set_visible(False)
        return fig

    # Two-column: CT/SA/σ₀ on left + LADCP U/V on right
    ladcp_available = ladcp_path.exists()
    z: np.ndarray | None = None
    u: np.ndarray | None = None
    v: np.ndarray | None = None
    if ladcp_available:
        m = read_ladcp(ladcp_path)
        dr = m["dr"]
        z = np.asarray(dr.z, dtype=float)
        u = np.asarray(dr.u, dtype=float)
        v = np.asarray(dr.v, dtype=float)

    fig, (ax_ctd, ax_ladcp) = plt.subplots(
        1,
        2,
        sharey=True,
        figsize=(_W_THREE_FIFTHS, 5.5),
        gridspec_kw={"width_ratios": [2, 1]},
    )

    # Left panel: CT / SA / σ₀ triple-axis
    ax1 = ax_ctd.twiny()
    ax2 = ax_ctd.twiny()

    (l0,) = ax_ctd.plot(ct, p, color=_TS_COLORS[0], lw=pen("thickest"), label="CT")
    (l1,) = ax1.plot(sa, p, color=_TS_COLORS[1], lw=pen("thickest"), label="SA")
    (l2,) = ax2.plot(sig, p, color=_TS_COLORS[2], label="σ₀")

    ax2.spines["top"].set_position(("axes", 1.12))
    ax1.spines["top"].set_visible(True)
    ax2.spines["top"].set_visible(True)

    for ax, line in zip((ax_ctd, ax1, ax2), (l0, l1, l2), strict=True):
        ax.xaxis.label.set_color(line.get_color())
        ax.tick_params(axis="x", colors=line.get_color())
        ax.spines["top"].set_edgecolor(line.get_color())
        ax.spines["top"].set_linewidth(0.6)

    ax_ctd.set_ylabel(vlabel("pressure"))
    ax_ctd.set_xlabel(vlabel("conservative_temperature"), color=_TS_COLORS[0])
    ax1.set_xlabel(vlabel("absolute_salinity"), color=_TS_COLORS[1])
    ax2.set_xlabel(vlabel("sigma0"), color=_TS_COLORS[2])
    ax_ctd.legend(handles=[l0, l1, l2], loc="center left", framealpha=0.7)
    ax_ctd.grid(True)
    if cfg.clean_spines:
        ax_ctd.spines["right"].set_visible(False)

    # Right panel: LADCP data or placeholder text
    if ladcp_available and u is not None and z is not None and v is not None:
        ax_ladcp.plot(u, z, color=_LADCP_U_COLOR, label="U (E+)")
        ax_ladcp.plot(v, z, color=_LADCP_V_COLOR, label="V (N+)")
        ax_ladcp.axvline(0, color="0.5", lw=pen("thinner"), ls="--")
        ax_ladcp.set_xlabel(f"Velocity ({vunit('U')})")
        ax_ladcp.legend(loc="upper left")
        ax_ladcp.grid(True)
    else:
        ax_ladcp.text(
            0.5,
            0.5,
            "no processed\nLADCP file",
            ha="center",
            va="center",
            transform=ax_ladcp.transAxes,
            color="0.6",
            fontsize=ANNOT_FS,
        )
        ax_ladcp.set_xlabel("LADCP")
    hide_outer_spines(ax_ladcp, clean=cfg.clean_spines)

    ax_ctd.set_ylim(float(np.nanmax(p)), 0)
    return fig


def draw_ts_diagram_fig(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_THIRD,
) -> plt.Figure | None:
    """Return a T–S diagram Figure coloured by oxygen saturation.

    Parameters
    ----------
    ds : xarray.Dataset
        Per-cast dataset with ``pressure`` and the T/S channels; CT, SA and σ₀
        are derived here (TEOS-10) and the downcast is selected.
        Needs ``oxygen_saturation`` (or the old ``oxsat_1``).
    cfg : ReportConfig
        Report configuration; ``clean_spines`` sets the despine.
    width_in : float, default ``W_THIRD``
        Figure width in inches (third slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when there is no oxygen saturation or fewer than five valid points.
    """
    ds_teos = add_teos10(ds)
    ds_down, _ = split_cast(ds_teos)
    sa = ds_down["absolute_salinity"].values
    ct = ds_down["conservative_temperature"].values
    _oxsat_var = next(
        (v for v in ("oxygen_saturation", "oxsat_1") if v in ds_down), None
    )
    if _oxsat_var is None:
        return None
    o2 = ds_down[_oxsat_var].values

    mask = np.isfinite(sa) & np.isfinite(ct) & np.isfinite(o2)
    sa, ct, o2 = sa[mask], ct[mask], o2[mask]
    if len(sa) < 5:
        return None

    o2_fin = o2[np.isfinite(o2)]
    o2_lo = float(np.nanpercentile(o2_fin, 2))
    o2_hi = float(np.nanpercentile(o2_fin, 98))
    # Fixed 2.5 % color steps; tick labels every 5 % (bounds[::2])
    _step_c = 2.5
    b_lo = np.floor(o2_lo / _step_c) * _step_c
    b_hi = np.ceil(o2_hi / _step_c) * _step_c
    bounds = np.arange(b_lo, b_hi + _step_c, _step_c)
    cmap = plt.get_cmap("RdYlGn", len(bounds) - 1)
    norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

    fig, ax = plt.subplots(figsize=(width_in, width_in * 3.8 / _W_THIRD))

    sc = ax.scatter(sa, ct, c=o2, cmap=cmap, norm=norm, s=6, alpha=0.8)
    _sigma0_backdrop(ax)
    cb = fig.colorbar(
        sc,
        ax=ax,
        orientation="horizontal",
        location="bottom",
        ticks=bounds[::2],
        pad=0.18,
        shrink=0.9,
        aspect=20,
    )
    cb.set_label(vlabel("oxygen_saturation"), loc="left")

    ax.set_xlabel(vlabel("absolute_salinity"))
    ax.set_ylabel(vlabel("conservative_temperature"))
    hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_stability_fig(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_TWOTHIRDS,
) -> plt.Figure | None:
    """Return downcast profiles of buoyancy frequency squared (N²) and the Turner angle.

    Parameters
    ----------
    ds : xarray.Dataset
        Per-cast dataset with ``pressure`` and the T/S channels; CT, SA and σ₀
        are derived here (TEOS-10) and the downcast is selected.
    cfg : ReportConfig
        Report configuration; ``clean_spines`` sets the despine.
    width_in : float, default ``W_TWOTHIRDS``
        Figure width in inches (two-thirds slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when the downcast has fewer than three levels.
    """
    ds_teos = add_teos10(ds)
    ds_down, _ = split_cast(ds_teos)
    p = ds_down["pressure"].values.astype(float)
    sa = ds_down["absolute_salinity"].values.astype(float)
    ct = ds_down["conservative_temperature"].values.astype(float)
    lat = float(np.nanmedian(ds["latitude"].values))

    if len(p) < 3:
        return None

    # gsw.Nsquared warns when consecutive pressure values are equal (dp=0),
    # which occurs in 1-second CTD data when the instrument is stationary.
    # The computation still produces correct values where dp != 0.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        n2, p_n2 = gsw.Nsquared(sa, ct, p, lat=lat)
        tu, _, p_tu = gsw.Turner_Rsubrho(sa, ct, p, axis=0)

    fig, axes = plt.subplots(
        1, 2, figsize=(width_in, width_in * 5.5 / _W_TWOTHIRDS), sharey=True
    )
    ax_n2, ax_tu = axes

    ax_n2.plot(n2, p_n2, color="k")
    ax_n2.axvline(0, color="0.6", lw=pen("thinner"), ls="--")
    ax_n2.set_ylim(float(np.nanmax(p_n2)), 0)
    ax_n2.set_xlabel(vlabel("N2"))
    ax_n2.set_ylabel(vlabel("pressure"))
    ax_n2.grid(True)

    ax_tu.axvspan(-90, -45, color="#f4a582", alpha=0.35, label="salt fingering")
    ax_tu.axvspan(45, 90, color="#92c5de", alpha=0.35, label="diffusive conv.")
    ax_tu.axvspan(-45, 45, color="0.88", alpha=0.5, label="doubly stable")
    ax_tu.axvline(-45, color="k", lw=pen("thinner"), ls="--")
    ax_tu.axvline(45, color="k", lw=pen("thinner"), ls="--")
    ax_tu.plot(tu, p_tu, color="#333333")
    ax_tu.set_xlim(-90, 90)
    ax_tu.set_xlabel(vlabel("Turner"))
    ax_tu.legend(loc="lower right")
    ax_tu.grid(True)
    hide_outer_spines(ax_n2, ax_tu, clean=cfg.clean_spines)

    return fig


def draw_aux_profiles_fig(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_FULL,
) -> plt.Figure | None:
    """Return side-by-side profiles of oxygen saturation, fluorescence and turbidity.

    Parameters
    ----------
    ds : xarray.Dataset
        Per-cast dataset; each of ``oxygen_saturation``, ``ctd_fluor`` and
        ``ctd_turbidity`` (or their old names) found in it gets a panel.
    cfg : ReportConfig
        Report configuration; ``clean_spines`` sets the despine.
    width_in : float, default ``W_FULL``
        Figure width in inches (full slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when none of the three variables is present.
    """
    vars_labels = [
        (
            next((v for v in ("oxygen_saturation", "oxsat_1") if v in ds), None),
            vlabel("oxygen_saturation"),
        ),
        (
            next((v for v in ("ctd_fluor", "fluorescence") if v in ds), None),
            vlabel("ctd_fluor"),
        ),
        (
            next((v for v in ("ctd_turbidity", "turbidity") if v in ds), None),
            vlabel("ctd_turbidity"),
        ),
    ]
    available = [(v, lbl) for v, lbl in vars_labels if v is not None]
    if not available:
        return None
    ds_down, ds_up = split_cast(ds)

    fig, axes = plt.subplots(
        1, len(available), figsize=(width_in, width_in * 5.5 / _W_FULL), sharey=True
    )
    if len(available) == 1:
        axes = [axes]

    p_down = ds_down["pressure"].values
    max_p = float(np.nanmax(p_down))
    for ax, (var, label) in zip(axes, available, strict=True):
        color = VAR_COLORS.get(var, "#000000")
        ax.plot(ds_down[var].values, p_down, color=color, label="downcast")
        if var in ds_up and len(ds_up["pressure"]) > 2:
            ax.plot(
                ds_up[var].values,
                ds_up["pressure"].values,
                color=_UPCAST_COLOR,
                alpha=0.6,
                label="upcast",
            )
        ax.set_xlabel(label)
        ax.grid(True)

    axes[0].set_ylabel(vlabel("pressure"))
    axes[0].set_ylim(max_p, 0)
    axes[0].legend(loc="center left")
    hide_outer_spines(*axes, clean=cfg.clean_spines)
    return fig


def draw_ct_sa_sigma0_fig(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_FULL,
) -> plt.Figure | None:
    """Return side-by-side CT, SA and σ₀ profiles (downcast, with the upcast in grey).

    Parameters
    ----------
    ds : xarray.Dataset
        Per-cast dataset with ``pressure`` and the T/S channels; CT, SA and σ₀
        are derived here (TEOS-10) and the downcast is selected.
    cfg : ReportConfig
        Report configuration; ``clean_spines`` sets the despine.
    width_in : float, default ``W_FULL``
        Figure width in inches (full slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when none of CT, SA, σ₀ is available.
    """
    ds_teos = add_teos10(ds)
    ds_down, ds_up = split_cast(ds_teos)

    vars_labels = [
        ("conservative_temperature", vlabel("conservative_temperature")),
        ("absolute_salinity", vlabel("absolute_salinity")),
        ("sigma0", vlabel("sigma0")),
    ]
    available = [(v, lbl) for v, lbl in vars_labels if v in ds_down]
    if not available:
        return None

    fig, axes = plt.subplots(
        1, len(available), figsize=(width_in, width_in * 5.5 / _W_FULL), sharey=True
    )
    if len(available) == 1:
        axes = [axes]

    p_down = ds_down["pressure"].values
    max_p = float(np.nanmax(p_down))

    for ax, (var, label) in zip(axes, available, strict=True):
        color = VAR_COLORS.get(var, "#000000")
        d_vals = ds_down[var].values
        d_fin = d_vals[np.isfinite(d_vals)]
        ax.plot(d_vals, p_down, color=color, label="downcast")
        if var in ds_up and len(ds_up["pressure"]) > 2:
            ax.plot(
                ds_up[var].values,
                ds_up["pressure"].values,
                color=_UPCAST_COLOR,
                alpha=0.6,
                label="upcast",
            )
        ax.set_xlabel(label)
        ax.grid(True)
        # Lock x-axis to downcast 1–99th percentile so upcast outliers don't stretch the scale
        if len(d_fin) > 1:
            p1, p99 = (
                float(np.percentile(d_fin, 1)),
                float(np.percentile(d_fin, 99)),
            )
            pad = max((p99 - p1) * 0.05, 1e-6)
            ax.set_xlim(p1 - pad, p99 + pad)

    axes[0].set_ylabel(vlabel("pressure"))
    axes[0].set_ylim(max_p, 0)
    axes[0].legend(loc="center left")
    hide_outer_spines(*axes, clean=cfg.clean_spines)
    return fig


def draw_ts_updown_fig(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_TWO_FIFTHS,
) -> plt.Figure | None:
    """Return a T–S diagram Figure overlaying the downcast and the upcast.

    Parameters
    ----------
    ds : xarray.Dataset
        Per-cast dataset with ``pressure`` and the T/S channels; CT, SA and σ₀
        are derived here (TEOS-10) and the downcast is selected.
    cfg : ReportConfig
        Report configuration; ``clean_spines`` sets the despine.
    width_in : float, default ``W_TWO_FIFTHS``
        Figure width in inches (two-fifths slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when the downcast has no valid CT/SA pair.
    """
    ds_teos = add_teos10(ds)
    ds_down, ds_up = split_cast(ds_teos)

    sa_d = ds_down["absolute_salinity"].values
    ct_d = ds_down["conservative_temperature"].values
    sa_u = ds_up["absolute_salinity"].values
    ct_u = ds_up["conservative_temperature"].values

    mask_d = np.isfinite(sa_d) & np.isfinite(ct_d)
    mask_u = np.isfinite(sa_u) & np.isfinite(ct_u)
    if not mask_d.any():
        return None

    # Axis limits from downcast only — matches _make_ts_density_b64's auto-scale
    # (matplotlib default margin = 5 % of data range on each side).
    sa_lo = float(np.nanmin(sa_d[mask_d]))
    sa_hi = float(np.nanmax(sa_d[mask_d]))
    ct_lo = float(np.nanmin(ct_d[mask_d]))
    ct_hi = float(np.nanmax(ct_d[mask_d]))
    sa_pad = 0.05 * (sa_hi - sa_lo) if sa_hi > sa_lo else 0.05
    ct_pad = 0.05 * (ct_hi - ct_lo) if ct_hi > ct_lo else 0.05

    # σ₀ contour grid — extend beyond axis limits to avoid edge artefacts
    sa_g = np.linspace(sa_lo - sa_pad - 0.1, sa_hi + sa_pad + 0.1, 80)
    ct_g = np.linspace(ct_lo - ct_pad - 0.2, ct_hi + ct_pad + 0.2, 80)
    SA_g, CT_g = np.meshgrid(sa_g, ct_g)
    sig0_g = gsw.sigma0(SA_g, CT_g)

    fig, ax = plt.subplots(figsize=(width_in, width_in))
    cs = ax.contour(
        SA_g, CT_g, sig0_g, levels=8, colors=_SIGMA0_CONTOUR_COLOR, linewidths=0.6
    )
    ax.clabel(cs, fmt="%.1f", fontsize=CLABEL_FS)
    ax.scatter(
        sa_d[mask_d],
        ct_d[mask_d],
        s=6,
        color="#1f77b4",
        alpha=0.7,
        label="down",
    )
    if mask_u.any():
        ax.scatter(
            sa_u[mask_u],
            ct_u[mask_u],
            s=4,
            color="#d62728",
            alpha=0.5,
            label="up",
        )
    ax.set_xlim(sa_lo - sa_pad, sa_hi + sa_pad)
    ax.set_ylim(ct_lo - ct_pad, ct_hi + ct_pad)
    ax.set_xlabel(vlabel("absolute_salinity"))
    ax.set_ylabel(vlabel("conservative_temperature"))
    ax.legend(loc="best", markerscale=2)
    ax.grid(False)
    hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_qc_histogram_fig(
    nc_path: Path,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_FULL,
) -> plt.Figure | None:
    """Return a per-variable data-value distribution Figure, or None.

    One histogram panel per science variable that carries a ``{var}_qc``
    companion.  Grey bars are all finite data; coloured bars are the **good** data
    (QARTOD pass, flag 1 only — so suspect, fail and missing all show as grey
    above the colour), on **shared bin edges** so the two are directly comparable.
    The gross-range suspect and fail thresholds recorded on the ``_qc`` companion
    are drawn as dashed/dotted lines when they fall within the plotted range.
    Reads *nc_path* directly, so the distribution
    is the file's own — untrimmed — data and flags.  Ports the logic of
    oceanarray's ``draw_data_histogram``.

    Parameters
    ----------
    nc_path:
        Path to a per-cast stage file (stage 2 or 3, i.e. one carrying ``_qc``).
    cfg:
        The frozen report configuration; ``clean_spines`` drives the despine.
    width_in:
        Figure width in inches; each panel row's height scales with it.
    """
    with xr.open_dataset(nc_path, engine="netcdf4", decode_timedelta=False) as ds:
        ds.load()
        panels = [
            v
            for v in sorted(ds.data_vars)
            if not str(v).endswith("_qc")
            and f"{v}_qc" in ds
            and ds[v].dims == ds[f"{v}_qc"].dims
            and np.isfinite(ds[v].values.astype(float)).any()
        ]
        if not panels:
            return None

        ncols = min(3, len(panels))
        nrows = math.ceil(len(panels) / ncols)
        fig, axs_grid = plt.subplots(
            nrows,
            ncols,
            figsize=(width_in, width_in * 2.4 / _W_FULL * nrows),
            squeeze=False,
            sharey=True,
        )
        axs = axs_grid.ravel()
        for k in range(len(panels), len(axs)):
            axs[k].set_visible(False)

        for ax, vname in zip(axs, panels, strict=False):
            data = ds[vname].values.astype(float).ravel()
            flags = ds[f"{vname}_qc"].values.astype(int).ravel()
            all_mask = np.isfinite(data)
            good_mask = all_mask & (flags == 1)  # QARTOD pass only
            all_data = data[all_mask]
            if all_data.size == 0:
                ax.set_visible(False)
                continue

            # Grey = all finite data; colour = only the good (pass) data, on the
            # SAME bin edges (computed once from all data) so they overlay exactly.
            # Grey showing above the colour is data flagged for any reason — a
            # gross-range suspect cluster or a mis-set threshold is then visible.
            bin_edges = np.histogram_bin_edges(all_data, bins=60)
            ax.hist(all_data, bins=bin_edges, color="#aaaaaa", alpha=0.6, label="all")
            good = data[good_mask]
            if good.size:
                ax.hist(
                    good,
                    bins=bin_edges,
                    color=VAR_COLORS.get(vname, "#2c7fb8"),
                    alpha=0.85,
                    label="good",
                )
            ax.set_yscale("log")
            ax.set_xlabel(vlabel(vname))
            if ax.get_subplotspec().is_first_col():
                ax.set_ylabel(r"$\log_{10}$(count)")

            all_lo, all_hi = float(all_data.min()), float(all_data.max())
            pad = max(0.03 * (all_hi - all_lo), 1e-6)
            xlim_lo, xlim_hi = all_lo - pad, all_hi + pad
            ax.set_xlim(xlim_lo, xlim_hi)

            # Gross-range bounds: suspect orange dashed, fail red dotted, labelled,
            # drawn only when they fall within the plotted range (a far-off bound
            # would just clip).  Spike thresholds are on the difference metric, not
            # the value, so they are not drawn here.
            qattrs = ds[f"{vname}_qc"].attrs
            handles, labels = [], []
            for key, tag, color, ls in (
                ("qc_gross_range_suspect_min", "suspect min", "#f39c12", "--"),
                ("qc_gross_range_suspect_max", "suspect max", "#f39c12", "--"),
                ("qc_gross_range_fail_min", "fail min", "#e74c3c", ":"),
                ("qc_gross_range_fail_max", "fail max", "#e74c3c", ":"),
            ):
                bound = qattrs.get(key)
                if bound is not None and xlim_lo <= float(bound) <= xlim_hi:
                    line = ax.axvline(
                        float(bound),
                        color=color,
                        linestyle=ls,
                        linewidth=pen("thin"),
                    )
                    handles.append(line)
                    labels.append(f"{tag} ({bound})")
            if handles:
                ax.legend(handles, labels, loc="upper left")

            ax.grid(True)
            hide_outer_spines(ax, clean=cfg.clean_spines)

            n_flagged = int(all_mask.sum()) - int(good_mask.sum())
            if n_flagged:
                ax.text(
                    0.97,
                    0.95,
                    f"{n_flagged} flagged",
                    transform=ax.transAxes,
                    ha="right",
                    va="top",
                    color="#e74c3c",
                )
        return fig
