"""Figure for a ctdcast-versus-Sea-Bird comparison: the difference in each variable against pressure.

One panel per variable, ctdcast minus the CNV at every scan neither side flags, downcast blue and
upcast vermillion (Okabe–Ito), with zero drawn.  A step reproduced exactly is a vertical line at
zero; a step missing or different shows as structure where the profile changes fastest.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from ctdcast.analysis.sbe_compare import FLAGGED_QC
from ctdcast.reports._vendored.design_tokens import W_FULL as _W_FULL
from ctdcast.reports._vendored.design_tokens import pen

DOWN = "#0072B2"
UP = "#D55E00"


def draw_sbe_compare_fig(
    ours: xr.Dataset,
    ref: xr.Dataset,
    variables: list[str],
    *,
    title: str | None = None,
    width_in: float = _W_FULL,
) -> plt.Figure | None:
    """Return ctdcast minus Sea-Bird against pressure, one panel per variable.

    Parameters
    ----------
    ours : xarray.Dataset
        A ctdcast stage file read from the ``.hex``.
    ref : xarray.Dataset
        The same cast's CNV, from :func:`ctdcast.analysis.sbe_compare.read_reference`.
    variables : list of str
        The variables to draw, each present in both.
    title : str, optional
        A figure title, e.g. the cast and the step compared.
    width_in : float, default ``W_FULL``
        Figure width in inches; the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        None when no variable has a scan to compare or the scan counts differ.
    """
    variables = [v for v in variables if v in ours and v in ref]
    n = ours.sizes["time"]
    if not variables or ref.sizes["time"] != n or "pressure" not in ref:
        return None
    p = ref["pressure"].values.astype(float)
    turn = int(np.nanargmax(p))
    down = np.arange(n) <= turn
    ncol = min(4, len(variables))
    nrow = -(-len(variables) // ncol)
    fig, axs = plt.subplots(
        nrow,
        ncol,
        figsize=(width_in, width_in * 0.42 * nrow),
        squeeze=False,
        sharey=True,
    )
    drawn = False
    for ax, name in zip(axs.flat, variables, strict=False):
        a = ours[name].values.astype(float)
        b = ref[name].values.astype(float)
        ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(p)
        if f"{name}_sbe_flagged" in ref:
            ok &= ~ref[f"{name}_sbe_flagged"].values
        if f"{name}_qc" in ours:
            ok &= ~np.isin(ours[f"{name}_qc"].values, FLAGGED_QC)
        d = a - b
        for sel, colour, label in ((down, DOWN, "down"), (~down, UP, "up")):
            m = ok & sel
            if m.any():
                drawn = True
                ax.plot(
                    d[m], p[m], ".", ms=1.0, color=colour, label=label, rasterized=True
                )
        ax.axvline(0.0, color="k", lw=pen("thinner"))
        units = ours[name].attrs.get("units", "")
        ax.set_xlabel(f"{name} ({units})" if units else name)
        if ok.any():
            lim = float(np.nanpercentile(np.abs(d[ok]), 99.5)) or 1e-6
            ax.set_xlim(-1.2 * lim, 1.2 * lim)
    for ax in list(axs.flat)[len(variables) :]:
        ax.set_visible(False)
    if not drawn:
        plt.close(fig)
        return None
    axs[0][0].invert_yaxis()
    for row in axs:
        row[0].set_ylabel("pressure (dbar)")
    axs[0][0].legend(loc="lower left", markerscale=6)
    if title:
        fig.suptitle(title)
    fig.tight_layout()
    return fig
