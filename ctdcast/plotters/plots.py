"""Figure builders: each ``draw_*_fig`` returns a matplotlib Figure or None.

Encoding to base64 PNG for embedding in a page is done separately by the
``_make_*_b64`` wrappers in :mod:`ctdcast.reports._plots`.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import gsw
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MultipleLocator
import numpy as np
import xarray as xr

from ctdcast.analysis.bathymetry import (
    load_gebco,
)
from ctdcast.analysis.derive import derive_teos10 as add_teos10
from ctdcast.config.parameters import (
    VAR_COLORS,
    vlabel,
)
from ctdcast.config.report_config import DEFAULT_REPORT_CONFIG, ReportConfig
from ctdcast.config.report_tokens import (
    ANNOT_FS,
    CAST_LABEL_FS,
    CLABEL_FS,
    pen,
    MAX_SECTION_H as _MAX_SECTION_H,
    MIN_SECTION_H as _MIN_SECTION_H,
    SECTION_STRETCH as _SECTION_STRETCH,
    W_FULL as _W_FULL,
    W_HALF as _W_HALF,
    W_THIRD as _W_THIRD,
    W_THREE_FIFTHS as _W_THREE_FIFTHS,
    W_TWO_FIFTHS as _W_TWO_FIFTHS,
    W_TWOTHIRDS as _W_TWOTHIRDS,
)
from ctdcast.plotters.primitives import (
    mesh_field,
    nice_colorbar_ticks,
    sigma0_isopycnals,
    unit_colorbar,
)
from ctdcast.processors.stage2 import split_cast
from ctdcast.readers.ladcp import read_ladcp

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Extra margin (degrees) added when loading GEBCO for map rendering.
# Ensures downsampled pcolormesh edge-cells extend past the axis limits,
# eliminating white-gap artefacts at map borders.
_GEBCO_RENDER_PAD: float = 0.5


# Derived aliases used throughout this module.
_TS_COLORS = [
    VAR_COLORS["conservative_temperature"],
    VAR_COLORS["absolute_salinity"],
    VAR_COLORS["sigma0"],
]
_LADCP_U_COLOR: str = VAR_COLORS["U"]
_LADCP_V_COLOR: str = VAR_COLORS["V"]


# Upcast trace color (dark grey).  Downcast uses the native per-variable color.
_UPCAST_COLOR: str = "#666666"

# Grey level for σ₀ density contours on T–S diagrams.
_SIGMA0_CONTOUR_COLOR: str = "0.4"


def _map_lim(
    lat_lo: float,
    lat_hi: float,
    lon_lo: float,
    lon_hi: float,
    margin: float,
    bounds: tuple[float | None, float | None, float | None, float | None],
) -> tuple[float, float, float, float]:
    """Return (lat_lo, lat_hi, lon_lo, lon_hi) with *bounds* overrides applied."""
    lat_min, lat_max, lon_min, lon_max = bounds
    return (
        lat_min if lat_min is not None else lat_lo - margin,
        lat_max if lat_max is not None else lat_hi + margin,
        lon_min if lon_min is not None else lon_lo - margin,
        lon_max if lon_max is not None else lon_hi + margin,
    )


def _square_map_limits(
    yl0: float,
    yl1: float,
    xl0: float,
    xl1: float,
    cos_lat: float,
) -> tuple[float, float, float, float]:
    """Widen longitude so the map is ~square in Mercator proportion.

    Mercator-equivalent width is ``lon_span * cos(lat)``; if the map would be
    taller than wide, longitude is expanded symmetrically to make it roughly
    square.  Shared aspect principle for all cruise maps.
    """
    lon_span = xl1 - xl0
    lat_span = yl1 - yl0
    x_width = lon_span * cos_lat
    if lat_span > x_width:
        lon_span_sq = lat_span / cos_lat
        extra = (lon_span_sq - lon_span) / 2
        xl0, xl1 = xl0 - extra, xl1 + extra
    return yl0, yl1, xl0, xl1


def _hide_outer_spines(*axes: Any, clean: bool) -> None:
    """Hide top and right spines on *axes* when *clean* is True."""
    if not clean:
        return
    for ax in axes:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)


# ---------------------------------------------------------------------------
# Internal utilities (rendering helpers, no external science dependencies)
# ---------------------------------------------------------------------------


def _nice_colorbar_bounds(
    vmin: float,
    vmax: float,
    n: int = 20,
    hard_min: float | None = None,
    hard_max: float | None = None,
) -> np.ndarray:
    """Return a boundary array for a discrete colorbar with approximately *n* levels.

    Steps are chosen from the "nice" ladder [1, 2, 2.5, 5, 10] scaled to the
    appropriate decade, so ticks land on clean values (e.g. 1.0 rather than 0.8,
    0.5 rather than 0.4). The range is centred on the midpoint of [vmin, vmax].

    If *hard_min* or *hard_max* are given, the returned bounds are clipped to
    those values so user-specified colormap limits are honoured exactly.
    """
    span = vmax - vmin
    if span <= 0:
        return np.linspace(vmin - 1, vmin + 1, n + 1)
    raw_step = span / n
    mag = 10.0 ** math.floor(math.log10(raw_step))
    normalized = raw_step / mag  # in [1, 10)
    # Pick the smallest nice multiplier >= normalized
    nice_step = 10.0 * mag  # fallback
    for factor in (1.0, 2.0, 2.5, 5.0, 10.0):
        if factor >= normalized:
            nice_step = factor * mag
            break
    mid = (vmin + vmax) / 2
    mid_aligned = round(mid / nice_step) * nice_step
    lo = mid_aligned - (n / 2) * nice_step
    bounds = np.array([lo + i * nice_step for i in range(n + 1)])
    if hard_min is not None or hard_max is not None:
        lo_clip = hard_min if hard_min is not None else bounds[0]
        hi_clip = hard_max if hard_max is not None else bounds[-1]
        bounds = bounds[(bounds >= lo_clip) & (bounds <= hi_clip)]
        if len(bounds) < 2:
            bounds = np.linspace(lo_clip, hi_clip, n + 1)
        if bounds[0] > lo_clip:
            bounds = np.concatenate([[lo_clip], bounds])
        if bounds[-1] < hi_clip:
            bounds = np.concatenate([bounds, [hi_clip]])
    return bounds


def _downsample_gebco_for_map(
    lons: np.ndarray,
    lats: np.ndarray,
    depth: np.ndarray,
    max_pts: int = 400,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Subsample GEBCO arrays to at most *max_pts* per dimension for map rendering.

    Only for use in pcolormesh map backgrounds — not for section bathymetry extraction.
    """
    stride = max(1, max(len(lons) // max_pts, len(lats) // max_pts))
    return lons[::stride], lats[::stride], depth[::stride, ::stride]


# ---------------------------------------------------------------------------
# Shared drawing helpers (internal)
# ---------------------------------------------------------------------------


# Fixed inch reservations for the deterministic map layout (independent of figure
# width): y-tick labels on the left; gap + bar + tick/label text for the east depth
# colorbar; x-tick labels and each south legend row at the bottom.
_MAP_LEFT_IN: float = 0.55
_MAP_CBAR_GAP_IN: float = 0.12
_MAP_CBAR_W_IN: float = 0.16
_MAP_CBAR_TXT_IN: float = 0.42
_MAP_TOP_IN: float = 0.30  # room for the depth colorbar's "m" title above the bar
_MAP_XTICK_IN: float = 0.30
_MAP_LEGEND_ROW_IN: float = 0.24
_MAP_MARKER_S: float = 18.0  # scatter marker area (pt^2) — every map cast marker
_MAP_MARKER_MS: float = 4.5  # plot marker size (pt), visually matched to _MAP_MARKER_S


def _map_layout(
    fig_w: float,
    xl0: float,
    xl1: float,
    yl0: float,
    yl1: float,
    cos_lat: float,
    *,
    legend_rows: int = 0,
) -> tuple[Any, Any, Any, float]:
    """Lay a cruise map out deterministically; return ``(fig, ax, cax, legend_top)``.

    ``legend_top`` is the figure-fraction y at the top of the reserved south legend
    strip, so a caller can anchor a bottom legend snug under the x-ticks.

    Width is fixed to the display slot (``fig_w`` inches).  Fixed inch margins are
    reserved for the y-tick labels, the east depth colorbar (gap + bar + text), the
    x-tick labels, and any south legend rows.  The map fills the remaining width and its
    height is computed from the (already-framed) extent so it is undistorted — the axes
    and colorbar are then placed by hand, so every map lays out identically regardless of
    legend/colorbar rather than letting matplotlib renegotiate and shrink the map.
    """
    lon_span = max(xl1 - xl0, 1e-6)
    lat_span = max(yl1 - yl0, 1e-6)
    right_in = _MAP_CBAR_GAP_IN + _MAP_CBAR_W_IN + _MAP_CBAR_TXT_IN
    bottom_in = _MAP_XTICK_IN + legend_rows * _MAP_LEGEND_ROW_IN
    map_w_in = max(fig_w - _MAP_LEFT_IN - right_in, 1.0)
    map_h_in = map_w_in * lat_span / (lon_span * cos_lat)  # undistorted
    fig_h = _MAP_TOP_IN + map_h_in + bottom_in
    fig = plt.figure(figsize=(fig_w, fig_h))
    # Explicit add_axes layout — tell the encoder to skip tight_layout (which would
    # both warn and fight these hand-placed axes).
    fig._manual_layout = True
    ax = fig.add_axes(
        [_MAP_LEFT_IN / fig_w, bottom_in / fig_h, map_w_in / fig_w, map_h_in / fig_h]
    )
    cax = fig.add_axes(
        [
            (_MAP_LEFT_IN + map_w_in + _MAP_CBAR_GAP_IN) / fig_w,
            bottom_in / fig_h,
            _MAP_CBAR_W_IN / fig_w,
            map_h_in / fig_h,
        ]
    )
    legend_top = (legend_rows * _MAP_LEGEND_ROW_IN) / fig_h
    return fig, ax, cax, legend_top


def map_panel(
    ax: Any,
    cax: Any,
    xl0: float,
    xl1: float,
    yl0: float,
    yl1: float,
    *,
    cfg: ReportConfig,
) -> None:
    """Draw the GEBCO depth field into *ax* and its 'Depth (m)' colorbar into *cax*.

    *cax* is a pre-placed colorbar axes from :func:`_map_layout`; when there is no GEBCO
    to draw it is hidden so no empty box remains.
    """
    gebco = load_gebco(
        yl0, yl1, xl0, xl1, margin=_GEBCO_RENDER_PAD, path=cfg.gebco_path
    )
    if gebco is None:
        cax.set_visible(False)
        return
    lons_b, lats_b, depth_b = gebco
    lons_b, lats_b, depth_b = _downsample_gebco_for_map(lons_b, lats_b, depth_b)
    d_fin = depth_b[depth_b > 0]
    if not len(d_fin):
        cax.set_visible(False)
        return
    bounds_b = _nice_colorbar_bounds(
        float(d_fin.min()), float(np.percentile(d_fin, 98)), n=12, hard_min=0.0
    )
    cmap_b = plt.get_cmap("Blues", len(bounds_b) - 1)
    norm_b = mcolors.BoundaryNorm(bounds_b, ncolors=cmap_b.N)
    LON2, LAT2 = np.meshgrid(lons_b, lats_b)
    bathy_pc = ax.pcolormesh(
        LON2,
        LAT2,
        depth_b,
        cmap=cmap_b,
        norm=norm_b,
        shading="nearest",
        rasterized=True,
    )
    cb = ax.get_figure().colorbar(bathy_pc, cax=cax, ticks=bounds_b[::2])
    cb.ax.set_title("m", fontsize=ANNOT_FS)  # depth units, above the bar (saves width)
    cb.ax.invert_yaxis()


def _fmt_lon(x: float, _pos: Any) -> str:
    """Format a longitude tick as degrees East/West (no negative °E)."""
    return f"{abs(x):g}°W" if x < 0 else f"{x:g}°E"


def _fmt_lat(y: float, _pos: Any) -> str:
    """Format a latitude tick as degrees North/South."""
    return f"{abs(y):g}°S" if y < 0 else f"{y:g}°N"


def _deg_tick_step(lo: float, hi: float, max_ticks: int = 6) -> float:
    """Return a 'nice' degree step (>= 0.1) giving 2..*max_ticks* ticks within [lo, hi].

    Counts ticks that actually land inside the range (not just span/step), so a coarse
    step whose multiples fall only once in-range is rejected — there are always at least
    two ticks.  Prefers the finest step that fits the width cap; if none does, falls back
    to the coarsest step that still yields two ticks.
    """
    max_ticks = max(2, max_ticks)
    steps = (0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0)

    def _count(step: float) -> int:
        return math.floor(hi / step + 1e-9) - math.ceil(lo / step - 1e-9) + 1

    for step in steps:
        if 2 <= _count(step) <= max_ticks:
            return step
    best = steps[0]
    for step in steps:
        if _count(step) >= 2:
            best = step
        else:
            break
    return best


def _finish_map_axes(
    ax: Any,
    xl0: float,
    xl1: float,
    yl0: float,
    yl1: float,
    title: str = "",
) -> None:
    """Set hemisphere-formatted lon/lat ticks, limits, grid (no axis labels needed).

    The ``°W``/``°N`` tick suffixes carry the axis meaning, so no x/y label is set.
    """
    ax.xaxis.set_major_formatter(FuncFormatter(_fmt_lon))
    ax.yaxis.set_major_formatter(FuncFormatter(_fmt_lat))
    # Tick at "nice" degree multiples no finer than 0.1° (one decimal max), and cap the
    # count to what physically fits: a wide "45.2°W" label clobbers on a narrow (1/3-width)
    # map, so scale the max tick count by the axes' actual inch size.
    fig_w_in, fig_h_in = ax.get_figure().get_size_inches()
    pos = ax.get_position()
    max_x = max(2, int(pos.width * fig_w_in / 0.62))  # ~0.62 in per lon label
    max_y = max(2, int(pos.height * fig_h_in / 0.30))  # ~0.30 in per lat label
    ax.xaxis.set_major_locator(MultipleLocator(_deg_tick_step(xl0, xl1, max_x)))
    ax.yaxis.set_major_locator(MultipleLocator(_deg_tick_step(yl0, yl1, max_y)))
    ax.set_xlim(xl0, xl1)
    ax.set_ylim(yl0, yl1)
    if title:
        ax.set_title(title)
    ax.grid(True)


def _cast_markers(ax: Any, x_vals: np.ndarray, cast_labels: list) -> None:
    """Draw ▼ cast markers and sparse numeric labels along the top edge of *ax*."""
    trans = ax.get_xaxis_transform()
    ax.plot(
        x_vals,
        [1.03] * len(x_vals),
        marker="v",
        ls="none",
        ms=5,
        mfc="none",
        mec="black",
        mew=0.7,
        transform=trans,
        clip_on=False,
        zorder=6,
    )
    n_lab = len(cast_labels)
    label_step = max(1, n_lab // 20)
    for i in range(0, n_lab, label_step):
        ax.text(
            float(x_vals[i]),
            1.05,
            str(cast_labels[i]),
            transform=trans,
            ha="center",
            va="bottom",
            fontsize=CAST_LABEL_FS,
            rotation=0,
        )


def _discrete_norm(
    d_fin: np.ndarray,
    var: str,
    vmin: float | None,
    vmax: float | None,
    n: int = 20,
    *,
    var_cmaps: Mapping[str, str],
) -> tuple[Any, Any, np.ndarray, str]:
    """Return ``(cmap, norm, bounds, cmap_name)`` for a discrete colorbar.

    Percentile limits (2nd–98th) are computed from *d_fin* (finite data values)
    unless overridden by *vmin*/*vmax*.  Includes the oxygen-specific fixed step
    and a guard against degenerate ranges.  The fourth return value is the
    colormap name string, needed when calling ``ax.contourf`` which accepts a
    name rather than a ``Colormap`` object.
    """
    cmap_name = var_cmaps.get(var, "viridis")
    v0 = vmin if vmin is not None else float(np.percentile(d_fin, 2))
    v1 = vmax if vmax is not None else float(np.percentile(d_fin, 98))
    if v0 >= v1:
        v0, v1 = float(np.percentile(d_fin, 2)), float(np.percentile(d_fin, 98))
    if var in ("oxsat_1", "oxygen_saturation"):
        _o2_step = 2.5
        _o2_lo = math.floor(v0 / _o2_step) * _o2_step
        _o2_hi = math.ceil(v1 / _o2_step) * _o2_step
        bounds = np.arange(_o2_lo, _o2_hi + _o2_step * 0.5, _o2_step)
    else:
        bounds = _nice_colorbar_bounds(v0, v1, n=n, hard_min=vmin, hard_max=vmax)
    cmap = plt.get_cmap(cmap_name, len(bounds) - 1)
    norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)
    return cmap, norm, bounds, cmap_name


def _sigma0_backdrop(ax: Any, sa: np.ndarray, ct: np.ndarray, n: int = 80) -> None:
    """Draw σ₀ density contours as a grey backdrop on a T–S axes."""
    sa_lo = float(np.nanpercentile(sa, 0.5))
    sa_hi = float(np.nanpercentile(sa, 99.5))
    ct_lo = float(np.nanpercentile(ct, 0.5))
    ct_hi = float(np.nanpercentile(ct, 99.5))
    sa_g = np.linspace(sa_lo - 0.05, sa_hi + 0.05, n)
    ct_g = np.linspace(ct_lo - 0.1, ct_hi + 0.1, n)
    SA_g, CT_g = np.meshgrid(sa_g, ct_g)
    sig0_g = gsw.sigma0(SA_g, CT_g)
    cs = ax.contour(
        SA_g, CT_g, sig0_g, levels=8, colors=_SIGMA0_CONTOUR_COLOR, linewidths=0.6
    )
    ax.clabel(cs, fmt="%.1f", fontsize=CLABEL_FS)


# ---------------------------------------------------------------------------
# draw_*_fig — individual figure builders (return a Figure or None)
# ---------------------------------------------------------------------------


def draw_ts_density_fig(
    ds: xr.Dataset,
    ladcp_path: Path | None = None,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> plt.Figure | None:
    """Return a CT/SA/σ₀ profiles Figure, optionally alongside LADCP U/V."""
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
        ax_ladcp.set_xlabel("Velocity (m s⁻¹)")
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
    _hide_outer_spines(ax_ladcp, clean=cfg.clean_spines)

    ax_ctd.set_ylim(float(np.nanmax(p)), 0)
    return fig


def draw_ts_diagram_fig(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> plt.Figure | None:
    """Return a T-S diagram Figure colored by O₂ saturation."""
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

    fig, ax = plt.subplots(figsize=(_W_THIRD, 3.8))

    _sigma0_backdrop(ax, sa, ct)

    sc = ax.scatter(sa, ct, c=o2, cmap=cmap, norm=norm, s=6, alpha=0.8)
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
    cb.set_label(vlabel("oxygen_saturation"))

    ax.set_xlabel(vlabel("absolute_salinity"))
    ax.set_ylabel(vlabel("conservative_temperature"))
    _hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_stability_fig(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> plt.Figure | None:
    """Return a N² and Turner angle (2-panel) Figure."""
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

    fig, axes = plt.subplots(1, 2, figsize=(_W_TWOTHIRDS, 5.5), sharey=True)
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
    _hide_outer_spines(ax_n2, ax_tu, clean=cfg.clean_spines)

    return fig


def draw_aux_profiles_fig(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> plt.Figure | None:
    """Return a O₂ sat, fluorescence, turbidity profiles Figure (downcast + pale upcast)."""
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

    fig, axes = plt.subplots(1, len(available), figsize=(_W_FULL, 5.5), sharey=True)
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
    _hide_outer_spines(*axes, clean=cfg.clean_spines)
    return fig


def draw_ct_sa_sigma0_fig(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> plt.Figure | None:
    """Return a CT, SA, σ₀ profiles side-by-side Figure (downcast + grey upcast)."""
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

    fig, axes = plt.subplots(1, len(available), figsize=(_W_FULL, 5.5), sharey=True)
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
    _hide_outer_spines(*axes, clean=cfg.clean_spines)
    return fig


def draw_ts_updown_fig(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> plt.Figure | None:
    """Return a CT–SA scatter Figure: downcast in blue, upcast in red, σ₀ contours."""
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

    fig, ax = plt.subplots(figsize=(_W_TWO_FIFTHS, _W_TWO_FIFTHS))
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
    _hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_station_map_fig(
    lat: float,
    lon: float,
    all_meta: list[dict],
    target_h: float = 4.5,  # noqa: ARG001
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> plt.Figure | None:
    """Return a GEBCO map Figure with all casts and this cast highlighted."""
    all_lats = [m["lat"] for m in all_meta if np.isfinite(m.get("lat", np.nan))]
    all_lons = [m["lon"] for m in all_meta if np.isfinite(m.get("lon", np.nan))]

    if not all_lats:
        return None

    lat_lo, lat_hi = min(all_lats), max(all_lats)
    lon_lo, lon_hi = min(all_lons), max(all_lons)
    margin = max(0.05, (lat_hi - lat_lo) * 0.1)
    mean_lat = 0.5 * (lat_lo + lat_hi)
    cos_lat = float(np.cos(np.deg2rad(mean_lat)))
    yl0, yl1, xl0, xl1 = _map_lim(
        lat_lo, lat_hi, lon_lo, lon_hi, margin, bounds=cfg.map_bounds
    )
    yl0, yl1, xl0, xl1 = _square_map_limits(yl0, yl1, xl0, xl1, cos_lat)

    fig, ax, cax, _ = _map_layout(_W_TWO_FIFTHS, xl0, xl1, yl0, yl1, cos_lat)

    map_panel(ax, cax, xl0, xl1, yl0, yl1, cfg=cfg)

    ax.scatter(
        all_lons,
        all_lats,
        s=_MAP_MARKER_S,
        facecolors="white",
        edgecolors="black",
        linewidths=pen("thinnest"),
        zorder=3,
        label="all casts",
    )
    ax.scatter(
        [lon],
        [lat],
        s=_MAP_MARKER_S,
        facecolors="#ff2a2a",
        edgecolors="black",
        linewidths=pen("thinnest"),
        zorder=5,
        label="this cast",
    )
    _finish_map_axes(ax, xl0, xl1, yl0, yl1)
    return fig


def draw_cruise_map_fig(
    all_meta: list[dict],
    *,
    target_h: float = 4.0,  # noqa: ARG001
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> plt.Figure | None:
    """Return a Figure of all cast positions (no single-cast highlight)."""
    lats = [m["lat"] for m in all_meta if np.isfinite(m.get("lat", np.nan))]
    lons = [m["lon"] for m in all_meta if np.isfinite(m.get("lon", np.nan))]
    nums = [
        m["cast_num"]
        for m in all_meta
        if np.isfinite(m.get("lat", np.nan)) and np.isfinite(m.get("lon", np.nan))
    ]
    if not lats:
        return None

    lat_lo, lat_hi = min(lats), max(lats)
    lon_lo, lon_hi = min(lons), max(lons)
    margin = max(0.05, max(lat_hi - lat_lo, lon_hi - lon_lo) * 0.12)
    mean_lat = 0.5 * (lat_lo + lat_hi)
    cos_lat = float(np.cos(np.deg2rad(mean_lat)))
    yl0, yl1, xl0, xl1 = _map_lim(
        lat_lo, lat_hi, lon_lo, lon_hi, margin, bounds=cfg.map_bounds
    )
    yl0, yl1, xl0, xl1 = _square_map_limits(yl0, yl1, xl0, xl1, cos_lat)

    fig, ax, cax, _ = _map_layout(_W_HALF, xl0, xl1, yl0, yl1, cos_lat)

    map_panel(ax, cax, xl0, xl1, yl0, yl1, cfg=cfg)

    ax.scatter(
        lons,
        lats,
        s=_MAP_MARKER_S,
        facecolors="white",
        edgecolors="black",
        linewidths=pen("thinnest"),
        zorder=3,
    )
    n = len(nums)
    # Label the first and last cast plus every cast number divisible by 10.
    label_idx = sorted(
        set([0, n - 1] + [i for i, cn in enumerate(nums) if int(cn) % 10 == 0])
    )
    for i in label_idx:
        ax.annotate(
            str(nums[i]),
            (lons[i], lats[i]),
            fontsize=CAST_LABEL_FS,
            xytext=(3, 3),
            textcoords="offset points",
        )

    _finish_map_axes(ax, xl0, xl1, yl0, yl1)
    return fig


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
    label: str,
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
    """Return a Figure of *var* vs pressure × *x_vals*."""
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
        cbar_label=label,
    )

    if bathy_depths is not None:
        bx = (
            bathy_x
            if (bathy_x is not None and len(bathy_x) == len(bathy_depths))
            else x_vals
        )
        if len(bathy_depths) == len(bx):
            step = "mid" if bathy_x is None else None
            ax.fill_between(bx, bathy_depths, y_bottom, color="black", step=step, lw=0)

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
) -> plt.Figure | None:
    """Return a Figure of per-cast CT–SA profiles coloured by along-track distance."""
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
    bounds = _nice_colorbar_bounds(x_lo, x_hi, n=12)
    cmap = plt.get_cmap("plasma", len(bounds) - 1)
    norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

    fig, ax = plt.subplots(figsize=(_W_THIRD, 3.8))
    _sigma0_backdrop(ax, sa_fin, ct_fin)

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
    cb.set_label("Along-track distance (km)")

    ax.set_xlim(sa_lo, sa_hi)
    ax.set_ylim(ct_lo, ct_hi)
    ax.set_xlabel(vlabel("absolute_salinity"))
    ax.set_ylabel(vlabel("conservative_temperature"))
    ax.grid(False)
    _hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_ts_diagram_timeseries_fig(
    ds_ts: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> plt.Figure | None:
    """Return a CT–SA diagram Figure for all timeseries profiles, coloured by time."""
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
    bounds = _nice_colorbar_bounds(t_lo, t_hi, n=12)
    cmap = plt.get_cmap("plasma", len(bounds) - 1)
    norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

    fig, ax = plt.subplots(figsize=(_W_THIRD, 3.8))
    _sigma0_backdrop(ax, sa_fin, ct_fin)

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
    cb.set_label("Hours since start")

    ax.set_xlim(sa_lo, sa_hi)
    ax.set_ylim(ct_lo, ct_hi)
    ax.set_xlabel(vlabel("absolute_salinity"))
    ax.set_ylabel(vlabel("conservative_temperature"))
    ax.grid(False)
    _hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_section_ts_histogram_fig(
    ds_prof: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> plt.Figure | None:
    """Return a CT–SA 2-D count histogram Figure (log₁₀ colour) for section profiles."""
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
    bounds_c = _nice_colorbar_bounds(float(c_fin.min()), float(c_fin.max()), n=12)
    cmap_c = plt.cm.YlOrRd.copy()
    cmap_c.set_bad("white")
    norm_c = mcolors.BoundaryNorm(bounds_c, ncolors=256)

    fig, ax = plt.subplots(figsize=(_W_THIRD, 3.8))
    _sigma0_backdrop(ax, sa, ct)
    pc = ax.pcolormesh(sa_c, ct_c, counts_log, cmap=cmap_c, norm=norm_c)
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
    cb.set_label("log₁₀(count)")

    ax.set_xlim(sa_lo, sa_hi)
    ax.set_ylim(ct_lo, ct_hi)
    ax.set_xlabel(vlabel("absolute_salinity"))
    ax.set_ylabel(vlabel("conservative_temperature"))
    ax.grid(False)
    _hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_section_ts_o2_fig(
    ds_prof: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> plt.Figure | None:
    """Return a CT–SA histogram Figure coloured by median O₂ saturation per bin."""
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

    bounds_o = _nice_colorbar_bounds(
        float(np.nanpercentile(o2_fin, 2)),
        float(np.nanpercentile(o2_fin, 98)),
        n=16,
    )
    cmap_o = plt.get_cmap("RdYlGn", len(bounds_o) - 1)
    norm_o = mcolors.BoundaryNorm(bounds_o, ncolors=cmap_o.N)

    fig, ax = plt.subplots(figsize=(_W_THIRD, 3.8))
    _sigma0_backdrop(ax, sa, ct)
    pc = ax.pcolormesh(sa_c, ct_c, o2_grid, cmap=cmap_o, norm=norm_o)
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
    cb.set_label("Median O₂ saturation (%)")

    ax.set_xlim(sa_lo, sa_hi)
    ax.set_ylim(ct_lo, ct_hi)
    ax.set_xlabel(vlabel("absolute_salinity"))
    ax.set_ylabel(vlabel("conservative_temperature"))
    ax.grid(False)
    _hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_section_map_fig(
    lats: list[float],
    lons: list[float],
    cast_nums: list[int],
    title: str = "",  # noqa: ARG001  (no longer drawn on the map; kept for callers)
    min_margin: float = 0.03,
    min_margin_lon: float | None = None,
    *,
    fig_w: float = _W_HALF,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> plt.Figure | None:
    """Return a GEBCO map Figure with the section track."""
    lats_arr = np.array(lats)
    lons_arr = np.array(lons)
    mask = np.isfinite(lats_arr) & np.isfinite(lons_arr)
    if not mask.any():
        return None
    lats_arr, lons_arr = lats_arr[mask], lons_arr[mask]

    lat_lo, lat_hi = lats_arr.min(), lats_arr.max()
    lon_lo, lon_hi = lons_arr.min(), lons_arr.max()
    mean_lat = 0.5 * (lat_lo + lat_hi)
    cos_lat = float(np.cos(np.deg2rad(mean_lat)))

    if min_margin_lon is not None:
        # Independent lat/lon margins — used for co-located clusters.
        # N-S guard not applied; caller is responsible for aspect.
        data_extent = max(lat_hi - lat_lo, lon_hi - lon_lo)
        margin_lat = max(min_margin, data_extent * 0.30)
        margin_lon = max(min_margin_lon, data_extent * 0.30)
        map_lat_min, map_lat_max, map_lon_min, map_lon_max = cfg.map_bounds
        yl0 = map_lat_min if map_lat_min is not None else lat_lo - margin_lat
        yl1 = map_lat_max if map_lat_max is not None else lat_hi + margin_lat
        xl0 = map_lon_min if map_lon_min is not None else lon_lo - margin_lon
        xl1 = map_lon_max if map_lon_max is not None else lon_hi + margin_lon
        # A single-location region is so small its ticks would need 0.01° (2 decimals,
        # which overflow the axis).  Enforce a minimum LATITUDE span, then square the
        # extent so longitude is expanded to match (Mercator) — done here, before the
        # layout, so the aspect is computed from the final limits.
        _min_lat_span = 0.2
        if yl1 - yl0 < _min_lat_span:
            _cy = 0.5 * (yl0 + yl1)
            yl0, yl1 = _cy - _min_lat_span / 2, _cy + _min_lat_span / 2
        yl0, yl1, xl0, xl1 = _square_map_limits(yl0, yl1, xl0, xl1, cos_lat)
    else:
        margin = max(min_margin, max(lat_hi - lat_lo, lon_hi - lon_lo) * 0.15)
        yl0, yl1, xl0, xl1 = _map_lim(
            lat_lo, lat_hi, lon_lo, lon_hi, margin, bounds=cfg.map_bounds
        )
        yl0, yl1, xl0, xl1 = _square_map_limits(yl0, yl1, xl0, xl1, cos_lat)

    fig, ax, cax, _ = _map_layout(fig_w, xl0, xl1, yl0, yl1, cos_lat)

    map_panel(ax, cax, xl0, xl1, yl0, yl1, cfg=cfg)

    ax.plot(lons_arr, lats_arr, "-", color="white", lw=pen("thick"), zorder=3)
    ax.scatter(
        lons_arr,
        lats_arr,
        s=_MAP_MARKER_S,
        facecolors="white",
        edgecolors="black",
        linewidths=pen("thinnest"),
        zorder=4,
    )
    # A single-location timeseries stacks every cast on one point — label only the
    # first and last so the numbers don't overwrite each other.
    _pts = list(zip(lons_arr, lats_arr, cast_nums, strict=True))
    _show = {0, len(_pts) - 1} if min_margin_lon is not None else set(range(len(_pts)))
    for i, (x, y, n) in enumerate(_pts):
        if i not in _show:
            continue
        ax.annotate(
            str(n),
            (x, y),
            fontsize=CAST_LABEL_FS,
            color="black",
            xytext=(3, 3),
            textcoords="offset points",
        )

    _finish_map_axes(ax, xl0, xl1, yl0, yl1)
    return fig


def draw_overview_panel_fig(
    ds_prof: xr.Dataset,
    var: str,
    label: str,
    bathy_depths: np.ndarray | None = None,
    style: str = "pcolormesh",
    vmin: float | None = None,
    vmax: float | None = None,
    cast_groups: dict[str, list[int]] | None = None,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> plt.Figure | None:
    """Return a Figure of *var* vs pressure × cast number (cruise overview panel)."""
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

    fig, ax = plt.subplots(figsize=cfg.overview_figsize)

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
        cbar_label=label,
    )

    if bathy_depths is not None:
        ax.fill_between(x_pos, bathy_depths, y_bottom, color="black", step="mid", lw=0)

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


def draw_all_sections_map_fig(
    sections_data: list[dict[str, Any]],
    all_lats: list[float],
    all_lons: list[float],
    legend_outside: bool = False,  # noqa: ARG001  (kept for call-site compatibility)
    *,
    target_h: float = 4.5,  # noqa: ARG001
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> plt.Figure | None:
    """Return a Figure showing all section tracks coloured by section."""
    if not sections_data:
        return None
    all_s_lats = [y for s in sections_data for y in s["lats"]] + list(all_lats)
    all_s_lons = [x for s in sections_data for x in s["lons"]] + list(all_lons)
    finite_lats = [v for v in all_s_lats if np.isfinite(v)]
    finite_lons = [v for v in all_s_lons if np.isfinite(v)]
    if not finite_lats:
        return None

    lat_lo, lat_hi = min(finite_lats), max(finite_lats)
    lon_lo, lon_hi = min(finite_lons), max(finite_lons)
    margin = max(0.05, max(lat_hi - lat_lo, lon_hi - lon_lo) * 0.12)
    mean_lat = 0.5 * (lat_lo + lat_hi)
    cos_lat = float(np.cos(np.deg2rad(mean_lat)))
    yl0, yl1, xl0, xl1 = _map_lim(
        lat_lo, lat_hi, lon_lo, lon_hi, margin, bounds=cfg.map_bounds
    )
    yl0, yl1, xl0, xl1 = _square_map_limits(yl0, yl1, xl0, xl1, cos_lat)

    ncol = min(len(sections_data), 3)
    legend_rows = math.ceil(len(sections_data) / ncol)
    fig, ax, cax, legend_top = _map_layout(
        _W_HALF, xl0, xl1, yl0, yl1, cos_lat, legend_rows=legend_rows
    )

    map_panel(ax, cax, xl0, xl1, yl0, yl1, cfg=cfg)

    if all_lats:
        fin = [
            np.isfinite(y) and np.isfinite(x)
            for y, x in zip(all_lats, all_lons, strict=True)
        ]
        ax.scatter(
            [x for x, f in zip(all_lons, fin, strict=True) if f],
            [y for y, f in zip(all_lats, fin, strict=True) if f],
            s=_MAP_MARKER_S,
            facecolors="white",
            edgecolors="black",
            linewidths=pen("thinnest"),
            zorder=2,
        )

    for sec in sections_data:
        slats = np.array(sec["lats"])
        slons = np.array(sec["lons"])
        color = sec.get("color", "#555555")
        ax.plot(
            slons,
            slats,
            "-o",
            color=color,
            lw=pen("thicker"),
            ms=_MAP_MARKER_MS,
            markeredgecolor="black",
            markeredgewidth=pen("thinnest"),
            zorder=4,
            label=sec["name"],
        )

    _finish_map_axes(ax, xl0, xl1, yl0, yl1)
    # Legend sits in the reserved south strip (figure coords), full width — never over
    # the map, and the same strip on every all-sections map.
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        ncol=ncol,
        framealpha=0.9,
        bbox_to_anchor=(0.5, legend_top),
    )
    return fig


def draw_timeseries_fig(
    ds_prof: xr.Dataset,
    var: str,
    label: str,
    style: str = "pcolormesh",
    vmin: float | None = None,
    vmax: float | None = None,
    figw: float | None = None,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> plt.Figure | None:
    """Return a Figure of *var* vs cast time × pressure, both down and upcast."""
    import matplotlib.dates as mdates

    if var not in ds_prof or "time_start" not in ds_prof:
        return None
    pressure = ds_prof["pressure"].values
    data = ds_prof[var].values
    times_start = ds_prof["time_start"].values
    cast_types = (
        ds_prof["cast_type"].values
        if "cast_type" in ds_prof
        else np.full(len(times_start), "down")
    )
    cast_numbers = ds_prof["cast_number"].values if "cast_number" in ds_prof else None

    if not len(times_start):
        return None

    # Use profile midpoint time so down/up pairs of the same deployment
    # are spread apart rather than stacked at the same time_start.
    if "time_end" in ds_prof:
        times_end = ds_prof["time_end"].values
        times = times_start + (times_end - times_start) // 2
    else:
        times = times_start

    order = np.argsort(times)
    data = data[order]
    times = times[order]
    cast_types = cast_types[order]
    if cast_numbers is not None:
        cast_numbers = cast_numbers[order]

    # Trim to deepest pressure level that has any valid data across all profiles
    valid_cols = np.where(np.any(np.isfinite(data), axis=0))[0]
    if not len(valid_cols):
        return None
    p_trim = pressure[: valid_cols[-1] + 1]
    data_trim = data[:, : valid_cols[-1] + 1]

    d_fin = data_trim[np.isfinite(data_trim)]
    if not len(d_fin):
        return None

    cmap, norm, bounds, _ = _discrete_norm(
        d_fin, var, vmin, vmax, var_cmaps=cfg.var_cmaps
    )

    t_mpl = mdates.date2num(times.astype("datetime64[ms]").astype("O"))
    n_prof = len(t_mpl)
    fw = figw
    if fw is None:
        # Mirror the step function in timeseries.py so standalone callers
        # get a slot-consistent width even without the Tier-2 caller.
        fw = _W_FULL if n_prof >= 30 else _W_HALF if n_prof >= 15 else _W_THIRD
    fig_h = float(np.clip(float(p_trim[-1]) / 250.0 + 2.5, 3.0, _MAX_SECTION_H))

    fig, ax = plt.subplots(figsize=(fw, fig_h))
    x_for_contour: np.ndarray
    if style == "contourf":
        t_idx = np.arange(n_prof, dtype=float)
        pc = ax.contourf(
            t_idx,
            p_trim,
            data_trim.T,
            levels=bounds,
            cmap=cmap,
            norm=norm,
            extend="both",
        )
        x_for_contour = t_idx
        _max_ticks = max(4, round(fw * 1.4))
        _tick_step = max(1, n_prof // _max_ticks)
        ax.set_xticks(t_idx[::_tick_step])
        ax.set_xticklabels(
            [mdates.num2date(t).strftime("%d %b\n%H:%M") for t in t_mpl[::_tick_step]],
            rotation=30,
            ha="right",
        )
    else:
        pc = ax.pcolormesh(
            t_mpl, p_trim, data_trim.T, cmap=cmap, norm=norm, shading="nearest"
        )
        x_for_contour = t_mpl
        ax.xaxis_date()
        locator = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")

    unit_colorbar(
        ax,
        pc,
        unit=label,
        ticks=nice_colorbar_ticks(float(bounds[0]), float(bounds[-1])),
        extend="both",
        reserve=True,
        title_loc="left",
    )

    if var == "sigma0":
        sigma0_isopycnals(ax, x_for_contour, p_trim, data_trim)

    # ▼ for downcast, △ for upcast floating above axes; cast number above each downcast
    trans = ax.get_xaxis_transform()
    n_down = sum(1 for ct in cast_types if ct == "down")
    label_step = max(1, n_down // 20)
    down_count = 0
    for i, (t_val, ctype) in enumerate(zip(t_mpl, cast_types, strict=True)):
        marker, color = ("v", "#1f77b4") if ctype == "down" else ("^", _UPCAST_COLOR)
        ax.plot(
            t_val,
            1.03,
            marker=marker,
            ls="none",
            ms=5,
            mfc="none",
            mec=color,
            mew=0.7,
            clip_on=False,
            transform=trans,
        )
        if ctype == "down" and cast_numbers is not None:
            if down_count % label_step == 0:
                ax.text(
                    t_val,
                    1.05,
                    str(int(cast_numbers[i])),
                    transform=trans,
                    ha="center",
                    va="bottom",
                    fontsize=CAST_LABEL_FS,
                    rotation=0,
                )
            down_count += 1

    ax.set_ylim(float(p_trim[-1]), float(p_trim[0]))
    ax.set_ylabel(vlabel("pressure"))
    return fig


def draw_sensor_diff_fig(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> plt.Figure | None:
    """Return a primary minus secondary sensor difference profiles Figure."""
    p = ds["pressure"].values
    _t1 = next((v for v in ("ctd_temperature_1", "temperature_1") if v in ds), None)
    _t2 = next((v for v in ("ctd_temperature_2", "temperature_2") if v in ds), None)
    _s1 = next((v for v in ("ctd_salinity_1", "salinity_1") if v in ds), None)
    _s2 = next((v for v in ("ctd_salinity_2", "salinity_2") if v in ds), None)
    has_t = _t1 is not None and _t2 is not None
    has_s = _s1 is not None and _s2 is not None
    if not has_t and not has_s:
        return None

    n_panels = int(has_t) + int(has_s)
    fig, axes = plt.subplots(1, n_panels, figsize=(_W_TWOTHIRDS, 5.5), sharey=True)
    if n_panels == 1:
        axes = [axes]

    max_p = float(np.nanmax(p))
    idx = 0
    if has_t:
        dt = ds[_t1].values - ds[_t2].values
        axes[idx].plot(
            dt,
            p,
            ".",
            color=VAR_COLORS["conservative_temperature"],
            markersize=1.5,
            linewidth=0,
        )
        axes[idx].axvline(0, color="0.6", linewidth=pen("thinner"), linestyle="--")
        axes[idx].set_xlabel("T₁ − T₂ (°C)")
        axes[idx].set_xlim(-0.01, 0.01)
        axes[idx].grid(True)
        idx += 1
    if has_s:
        ds_diff = ds[_s1].values - ds[_s2].values
        axes[idx].plot(
            ds_diff,
            p,
            ".",
            color=VAR_COLORS["absolute_salinity"],
            markersize=1.5,
            linewidth=0,
        )
        axes[idx].axvline(0, color="0.6", linewidth=pen("thinner"), linestyle="--")
        axes[idx].set_xlabel("S₁ − S₂ (PSU)")
        axes[idx].set_xlim(-0.01, 0.01)
        axes[idx].grid(True)

    axes[0].set_ylabel(vlabel("pressure"))
    axes[0].set_ylim(max_p, 0)
    _hide_outer_spines(*axes, clean=cfg.clean_spines)
    return fig


def draw_pressure_time_fig(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> plt.Figure | None:
    """Return a pressure vs elapsed time Figure (cast trajectory + bottle stops)."""
    p = ds["pressure"].values
    t_raw = ds["time"].values

    if np.issubdtype(t_raw.dtype, np.datetime64):
        elapsed_min = (t_raw - t_raw[0]) / np.timedelta64(1, "s") / 60.0
    else:
        elapsed_min = (t_raw.astype(float) - float(t_raw[0])) / 60.0

    fig, ax = plt.subplots(figsize=(_W_THIRD, 3.7))
    ax.plot(elapsed_min, p, color="k", linewidth=pen("thin"))
    max_p = float(np.nanmax(p))
    ax.set_ylim(max_p, 0)
    ax.set_xlabel("Elapsed time (min)")
    ax.set_ylabel(vlabel("pressure"))
    ax.grid(True)
    _hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_updown_diff_fig(
    ds: xr.Dataset, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
) -> plt.Figure | None:
    """Return a downcast minus upcast profiles Figure: ΔCT, ΔSA, Δσ₀."""
    ds_teos = add_teos10(ds)
    ds_down, ds_up = split_cast(ds_teos)

    if len(ds_down["pressure"]) < 5 or len(ds_up["pressure"]) < 5:
        return None

    p_down = ds_down["pressure"].values
    p_up = ds_up["pressure"].values
    p_lo = max(float(np.nanmin(p_down)), float(np.nanmin(p_up)))
    p_hi = min(float(np.nanmax(p_down)), float(np.nanmax(p_up)))
    if p_hi - p_lo < 10:
        return None

    p_grid = np.arange(p_lo, p_hi + 1, 1.0)

    # Sort each cast by pressure so np.interp receives monotonically increasing x
    sort_d = np.argsort(p_down)
    sort_u = np.argsort(p_up)
    p_d_s, p_u_s = p_down[sort_d], p_up[sort_u]

    diffs, labels, colors = [], [], []
    for var, label, color in zip(
        ("conservative_temperature", "absolute_salinity", "sigma0"),
        (
            vlabel(v, prefix="Δ")
            for v in ("conservative_temperature", "absolute_salinity", "sigma0")
        ),
        _TS_COLORS,
        strict=True,
    ):
        if var not in ds_down or var not in ds_up:
            continue
        v_d = np.interp(p_grid, p_d_s, ds_down[var].values[sort_d])
        v_u = np.interp(p_grid, p_u_s, ds_up[var].values[sort_u])
        diffs.append(v_d - v_u)
        labels.append(label)
        colors.append(color)

    if not diffs:
        return None

    fig, axes = plt.subplots(1, len(diffs), figsize=(_W_FULL, 5.5), sharey=True)
    if len(diffs) == 1:
        axes = [axes]
    for ax, diff, label, color in zip(axes, diffs, labels, colors, strict=True):
        ax.plot(diff, p_grid, color=color, linewidth=pen("thin"))
        ax.axvline(0, color="0.6", linewidth=pen("thinner"), linestyle="--")
        ax.set_xlabel(label)
        ax.grid(True)
    axes[0].set_ylabel(vlabel("pressure"))
    axes[0].set_ylim(float(p_grid[-1]), float(p_grid[0]))
    _hide_outer_spines(*axes, clean=cfg.clean_spines)
    return fig


def draw_ladcp_bottomtrack_fig(
    ladcp_path: Path | None, *, cfg: ReportConfig = DEFAULT_REPORT_CONFIG
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

    fig, axes = plt.subplots(1, 2, sharey=True, figsize=(_W_THIRD, 1.8))

    for ax, vel, xlabel, color in zip(
        axes,
        [u, v],
        ["U (m s⁻¹)\nEast +", "V (m s⁻¹)\nNorth +"],
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
    _hide_outer_spines(*axes, clean=cfg.clean_spines)
    return fig
