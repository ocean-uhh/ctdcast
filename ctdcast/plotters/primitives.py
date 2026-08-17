"""Layer-1 ``ax``-taking primitives that draw into a provided axes and create no Figure."""

from __future__ import annotations

from typing import Any

import matplotlib.ticker as mticker
import numpy as np
from mpl_toolkits.axes_grid1 import make_axes_locatable
from mpl_toolkits.axes_grid1.axes_size import Fixed

from ctdcast.config.report_tokens import (
    ANNOT_FS,
    CBAR_PAD_IN,
    CBAR_WIDTH_IN,
    CLABEL_FS,
)



def sigma0_isopycnals(
    ax: Any, x: np.ndarray, y: np.ndarray, data2d: np.ndarray
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


def nice_colorbar_ticks(
    vmin: float, vmax: float, *, max_ticks: int = 6
) -> np.ndarray:
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
    ticks = mticker.MaxNLocator(
        nbins=max_ticks, steps=[1, 2, 2.5, 5, 10]
    ).tick_values(vmin, vmax)
    return ticks[(ticks >= vmin) & (ticks <= vmax)]


def unit_colorbar(
    target: Any,
    mappable: Any,
    *,
    unit: str = "",
    ticks: np.ndarray | None = None,
    extend: str = "neither",
    reserve: bool = False,
    title_loc: str = "center",
) -> Any:
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
        figure.  A unit (``"m s⁻¹"``) or a full label (``"CT (°C)"``); empty
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
    ax: Any,
    fig: Any,  # noqa: ARG001 — kept for signature stability; colorbar uses cax.figure
    x: np.ndarray,
    y: np.ndarray,
    data2d: np.ndarray,
    *,
    cmap: Any,
    norm: Any,
    cmap_name: str,
    bounds: np.ndarray,
    style: str,
    cbar_label: str = "",
) -> Any:
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
    tracks the pre-resize box and ends up the wrong size.  The rule (see
    ``.claude/notes/2026-08-14-consistent-cruise-maps.md``): ``make_axes_locatable``
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
