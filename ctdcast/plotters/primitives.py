"""Layer-1 ``ax``-taking primitives that draw into a provided axes and create no Figure."""

from __future__ import annotations

from typing import Any

import numpy as np

from ctdcast.config.report_tokens import CLABEL_FS


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
    except Exception:  # noqa: BLE001, S110
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
    """Draw a pcolormesh/contourf field with a matched discrete colorbar into *ax*; return the colorbar."""
    if style == "contourf":
        X, Y = np.meshgrid(x, y)
        Z = np.ma.masked_invalid(data2d.T)
        cf = ax.contourf(X, Y, Z, levels=bounds, cmap=cmap_name, extend="both")
        cb = fig.colorbar(cf, ax=ax, ticks=bounds[::2], pad=0.02, extend="both")
    else:
        pc = ax.pcolormesh(x, y, data2d.T, cmap=cmap, norm=norm, shading="nearest")
        cb = fig.colorbar(pc, ax=ax, ticks=bounds[::2], pad=0.02, extend="both")
    return cb
