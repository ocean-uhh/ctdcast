"""Layer-1 ``ax``-taking primitives that draw into a provided axes and create no Figure."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import gsw
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from mpl_toolkits.axes_grid1 import make_axes_locatable
from mpl_toolkits.axes_grid1.axes_size import Fixed

from ctdcast.config.parameters import (
    VAR_COLORS,
)
from ctdcast.reports._vendored.design_tokens import (
    ANNOT_FS,
    CAST_LABEL_FS,
    CBAR_PAD_IN,
    CBAR_WIDTH_IN,
    CLABEL_FS,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.cm import ScalarMappable
    from matplotlib.colorbar import Colorbar
    from matplotlib.colors import Colormap, Normalize
    from matplotlib.figure import Figure


def sigma0_isopycnals(
    ax: Axes, x: np.ndarray, y: np.ndarray, data2d: np.ndarray
) -> None:
    """Overlay the 27.7 and 27.8 σ₀ isopycnal contours (labelled) on *ax*, swallowing contour failures."""
    try:
        _iso = ax.contour(
            x,
            y,
            data2d.T,
            levels=[27.7, 27.8],
            colors="k",
            linewidths=0.4,
            linestyles="solid",
        )
        ax.clabel(_iso, fmt="%.1f", fontsize=CLABEL_FS)
    except Exception:  # noqa: BLE001
        pass


def nice_colorbar_ticks(vmin: float, vmax: float, *, max_ticks: int = 6) -> np.ndarray:
    """Return at most *max_ticks* nicely-rounded tick positions in ``[vmin, vmax]``.

    Decoupled from the colorbar's colour discretisation: a 20-level ``BoundaryNorm``
    bar can still show ~6 round labels (e.g. 34.8, 34.9, … 35.2) instead of one label
    per boundary.  Uses :class:`~matplotlib.ticker.MaxNLocator` with round step
    multiples so labels land on clean values.

    Parameters
    ----------
    vmin, vmax : float
        Data range of the colorbar.
    max_ticks : int
        Maximum number of ticks (approximate; the locator may return a few fewer).

    Returns
    -------
    numpy.ndarray
        Tick positions, clipped to ``[vmin, vmax]``.

    """
    lo, hi = (vmin, vmax) if vmin <= vmax else (vmax, vmin)
    ticks = mticker.MaxNLocator(nbins=max_ticks, steps=[1, 2, 2.5, 5, 10]).tick_values(
        lo, hi
    )
    ticks = ticks[(ticks >= lo) & (ticks <= hi)]
    # A near-degenerate range can leave every rounded tick outside [lo, hi]; fall
    # back to the endpoints so the colorbar never renders with zero labels.
    return ticks if len(ticks) else np.array([lo, hi])


def unit_colorbar(
    target: Axes,
    mappable: ScalarMappable,
    *,
    unit: str = "",
    ticks: np.ndarray | None = None,
    extend: str = "neither",
    reserve: bool = False,
    title_loc: str = "center",
) -> Colorbar:
    """Draw the report-standard colorbar with the unit as a title on top.

    One entry point, two placement strategies so the *appearance* (bar width, gap,
    tick choice, unit-on-top) is set in a single place regardless of how the axes
    was laid out.

    Parameters
    ----------
    target : matplotlib Axes
        When *reserve* is False, a colorbar axes already reserved by a hand layout.
        When *reserve* is True, the *host* plot axes, into which a fixed-inch cax is
        appended — allowed **only for free-aspect axes** (see :func:`mesh_field`).
    mappable : matplotlib ScalarMappable
        The artist to map (``pcolormesh``, ``contourf`` set, ...).
    unit : str
        Text placed above the bar (``cax.set_title``) rather than as a rotated
        side label — reads cleanly and, unlike a side label, does not widen the
        figure.  A unit (``"m/s"``) or a full label (``"CT (°C)"``); empty
        renders no title.
    ticks : numpy.ndarray, optional
        Explicit tick positions (e.g. from :func:`nice_colorbar_ticks`).
    extend : str
        ``"neither"``/``"both"``/``"min"``/``"max"`` — pointed ends for out-of-range.
    reserve : bool
        Append a fixed-inch cax to *target* instead of treating it as the cax.
    title_loc : str
        Horizontal anchor for the on-top title — ``"center"`` (default),
        ``"left"`` or ``"right"``.  ``"left"`` anchors the title at the thin bar's
        left edge so it extends right into the margin, clear of a figure's
        top-left annotations (e.g. the cast-marker strip on field figures);
        centering it over the thin bar would instead overhang the plot.

    Returns
    -------
    matplotlib.colorbar.Colorbar

    """
    if reserve:
        cax = make_axes_locatable(target).append_axes(
            "right", size=Fixed(CBAR_WIDTH_IN), pad=Fixed(CBAR_PAD_IN)
        )
    else:
        cax = target
    cb = cax.figure.colorbar(mappable, cax=cax, ticks=ticks, extend=extend)
    if unit:
        cax.set_title(unit, fontsize=ANNOT_FS, loc=title_loc)
    return cb


def mesh_field(
    ax: Axes,
    fig: Figure,  # noqa: ARG001 — kept for signature stability; colorbar uses cax.figure
    x: np.ndarray,
    y: np.ndarray,
    data2d: np.ndarray,
    *,
    cmap: Colormap,
    norm: Normalize,
    cmap_name: str,
    bounds: np.ndarray,
    style: str,
    cbar_label: str = "",
) -> Colorbar:
    """Draw a pcolormesh/contourf field with a matched discrete colorbar into *ax*; return the colorbar.

    The colorbar has a *fixed inch width* (not a fraction of the host axes), so its
    thickness and the resulting right margin are identical on every field figure
    regardless of slot width, and its labels are ~6 round values
    (:func:`nice_colorbar_ticks`) rather than one per discretisation boundary, with
    *cbar_label* written as a title on top (:func:`unit_colorbar`) so it does not
    widen the figure.

    ``make_axes_locatable`` (via ``unit_colorbar(reserve=True)``) is used **only
    because this axes is free-aspect**.  It attaches the colorbar to the divider of
    the axes' box *at layout time*; if something resizes that box afterwards —
    ``set_aspect("equal", adjustable="box")``, or a hand-placed map layout — the cax
    tracks the pre-resize box and ends up the wrong size.  The rule: ``make_axes_locatable``
    for free-aspect axes; hand-reserved inches whenever the aspect is locked or the
    axes are hand-placed.  Do not add ``set_aspect("equal")`` to a figure that
    colorbars through here without switching to the reserved-inches path.
    """
    if style == "contourf":
        X, Y = np.meshgrid(x, y)
        Z = np.ma.masked_invalid(data2d.T)
        mappable = ax.contourf(X, Y, Z, levels=bounds, cmap=cmap_name, extend="both")
    else:
        mappable = ax.pcolormesh(
            x, y, data2d.T, cmap=cmap, norm=norm, shading="nearest"
        )
    return unit_colorbar(
        ax,
        mappable,
        unit=cbar_label,
        ticks=nice_colorbar_ticks(float(bounds[0]), float(bounds[-1])),
        extend="both",
        reserve=True,
        title_loc="left",
    )


# ---------------------------------------------------------------------------
# Shared figure helpers (used by more than one figure module)
# ---------------------------------------------------------------------------


# Derived aliases used throughout this module.
_TS_COLORS = [
    VAR_COLORS["conservative_temperature"],
    VAR_COLORS["absolute_salinity"],
    VAR_COLORS["sigma0"],
]

# Upcast trace color (dark grey).  Downcast uses the native per-variable color.
_UPCAST_COLOR: str = "#666666"

# Grey level for σ₀ density contours on T–S diagrams.
_SIGMA0_CONTOUR_COLOR: str = "0.4"


def hide_outer_spines(*axes: Axes, clean: bool) -> None:
    """Hide the top and right spines of each axes when *clean* is True.

    Parameters
    ----------
    *axes : matplotlib.axes.Axes
        The axes to despine.
    clean : bool
        Despine only when True (``ReportConfig.clean_spines``); otherwise a no-op.
    """
    if not clean:
        return
    for ax in axes:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)


def nice_colorbar_bounds(
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

    Parameters
    ----------
    vmin, vmax : float
        Data range to cover.
    n : int, default 20
        Approximate number of colour levels.
    hard_min, hard_max : float or None, optional
        Exact limits to clip to and include as end bounds.

    Returns
    -------
    numpy.ndarray
        Monotonic level boundaries, for ``BoundaryNorm`` and the colorbar ticks.
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


def _cast_markers(ax: Axes, x_vals: np.ndarray, cast_labels: list) -> None:
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
    cmap_name = var_cmaps.get(var)
    if cmap_name is None:
        # Not in the resolved table (a registry gap): resolve through the one
        # resolver, which warns naming the variable and falls back to viridis —
        # a gap should not stop a report (a bad name in a config is rejected at
        # load instead, where cmap_for is called without a default).
        from ctdcast.reports.design import cmap_for

        cmap_name = cmap_for(var, default="viridis")
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
        bounds = nice_colorbar_bounds(v0, v1, n=n, hard_min=vmin, hard_max=vmax)
    cmap = plt.get_cmap(cmap_name, len(bounds) - 1)
    norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)
    return cmap, norm, bounds, cmap_name


def _sigma0_backdrop(ax: Axes, n: int = 80) -> None:
    """Draw σ₀ density contours over the current axes extent, behind the data.

    Call this **after** the data has been plotted so the σ₀ grid spans the same
    salinity/temperature range the axes ended up with.  Gridding on the data
    percentiles (the previous behaviour) fell short of an outlier-driven axis
    limit, leaving the contours not filling the panel.  Contours are drawn at
    zorder 0 (behind the data); the axes limits are restored afterwards because
    contouring can nudge them.
    """
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    sa_g = np.linspace(xlim[0], xlim[1], n)
    ct_g = np.linspace(ylim[0], ylim[1], n)
    SA_g, CT_g = np.meshgrid(sa_g, ct_g)
    sig0_g = gsw.sigma0(SA_g, CT_g)
    cs = ax.contour(
        SA_g,
        CT_g,
        sig0_g,
        levels=8,
        colors=_SIGMA0_CONTOUR_COLOR,
        linewidths=0.6,
        zorder=0,
    )
    ax.clabel(cs, fmt="%.1f", fontsize=CLABEL_FS)
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
