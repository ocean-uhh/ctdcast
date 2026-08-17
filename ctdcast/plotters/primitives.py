"""Layer-1 ``ax``-taking primitives that draw into a provided axes and create no Figure."""

from __future__ import annotations

from typing import Any

import numpy as np
from mpl_toolkits.axes_grid1 import make_axes_locatable
from mpl_toolkits.axes_grid1.axes_size import Fixed

from ctdcast.config.report_tokens import CBAR_PAD_IN, CBAR_WIDTH_IN, CLABEL_FS


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


def mesh_field(
    ax: Any,
    fig: Any,
    x: np.ndarray,
    y: np.ndarray,
    data2d: np.ndarray,
    *,
    cmap: Any,
    norm: Any,
    cmap_name: str,
    bounds: np.ndarray,
    style: str,
) -> Any:
    """Draw a pcolormesh/contourf field with a matched discrete colorbar into *ax*; return the colorbar.

    The colorbar is placed in a divider axes of *fixed inch width* (not a fraction
    of the host axes), so its thickness and the resulting right margin are identical
    on every field figure regardless of slot width.

    ``make_axes_locatable`` is used **only because this axes is free-aspect**.  It
    attaches the colorbar to the divider of the axes' box *at layout time*; if
    something resizes that box afterwards — ``set_aspect("equal", adjustable="box")``,
    or a hand-placed map layout — the cax tracks the pre-resize box and ends up the
    wrong size.  The rule (see ``.claude/notes/2026-08-14-consistent-cruise-maps.md``):
    ``make_axes_locatable`` for free-aspect axes; hand-reserved inches whenever the
    aspect is locked or the axes are hand-placed.  Do not add ``set_aspect("equal")``
    to a figure that colorbars through here without switching to the reserved-inches path.
    """
    if style == "contourf":
        X, Y = np.meshgrid(x, y)
        Z = np.ma.masked_invalid(data2d.T)
        mappable = ax.contourf(X, Y, Z, levels=bounds, cmap=cmap_name, extend="both")
    else:
        mappable = ax.pcolormesh(
            x, y, data2d.T, cmap=cmap, norm=norm, shading="nearest"
        )
    cax = make_axes_locatable(ax).append_axes(
        "right", size=Fixed(CBAR_WIDTH_IN), pad=Fixed(CBAR_PAD_IN)
    )
    return fig.colorbar(mappable, cax=cax, ticks=bounds[::2], extend="both")
