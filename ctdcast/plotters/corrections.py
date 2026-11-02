"""Figures for the corrections page: alignment and cell thermal mass fits over a cruise.

Each draw function takes the ``fits.nc`` dataset written by ``ctdcast fit`` and the slot width,
and returns a Figure at a fixed aspect.  Primary is drawn with circles and solid lines,
secondary with triangles and dashed lines, throughout.  Downcast blue, upcast vermillion
(Okabe–Ito, colour-blind safe).
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from ctdcast.analysis import fits as F
from ctdcast.processors.fit import summarise
from ctdcast.reports._vendored.design_tokens import W_FULL as _W_FULL
from ctdcast.reports._vendored.design_tokens import pen

DOWN = "#0072B2"
UP = "#D55E00"
TAU_COLOUR = "#CC79A7"
LINE_STYLE = {1: ("o", "-", "primary"), 2: ("^", "--", "secondary")}


def _xticks(ax: plt.Axes, labels: list[str]) -> None:
    step = max(1, len(labels) // 15)
    idx = np.arange(0, len(labels), step)
    ax.set_xticks(idx)
    ax.set_xticklabels([labels[i] for i in idx], rotation=90)


def per_cast_alignment(fits: xr.Dataset, li: int) -> np.ndarray:
    """Return each cast's residual advance at the minimum of its down+up cost.

    NaN where the cast has no alignment cost, or where the minimum is at either end of the search
    (the cost still falling there: no minimum inside the search, so no estimate).

    Parameters
    ----------
    fits : xarray.Dataset
        The ``fits.nc`` dataset.
    li : int
        Line index (0 primary, 1 secondary).

    Returns
    -------
    numpy.ndarray
        One value per cast, seconds.
    """
    res = fits["residual"].values.astype(np.float64)
    out = np.full(fits.sizes["cast"], np.nan)
    for i, a in enumerate(fits["alignment_cost"].values[:, li]):
        total = np.nansum(a, axis=0)
        if np.isfinite(a).any() and np.isfinite(total).any():
            j = int(np.nanargmin(np.where(np.isfinite(a).any(axis=0), total, np.nan)))
            out[i] = res[j] if 0 < j < res.size - 1 else np.nan
    return out


def alignment_at_edge(fits: xr.Dataset, li: int) -> np.ndarray:
    """Return a mask of the casts whose alignment minimum is at an end of the search.

    Parameters
    ----------
    fits : xarray.Dataset
        The ``fits.nc`` dataset.
    li : int
        Line index (0 primary, 1 secondary).

    Returns
    -------
    numpy.ndarray of bool
        True where the cast has a cost but its minimum is the first or last residual.
    """
    n = fits.sizes["residual"]
    out = np.zeros(fits.sizes["cast"], bool)
    for i, a in enumerate(fits["alignment_cost"].values[:, li]):
        total = np.where(np.isfinite(a).any(axis=0), np.nansum(a, axis=0), np.nan)
        if np.isfinite(total).any():
            out[i] = int(np.nanargmin(total)) in (0, n - 1)
    return out


def per_cast_one_parameter(fits: xr.Dataset, li: int) -> tuple[np.ndarray, np.ndarray]:
    """Return each cast's alpha at tau = 7 s and tau at alpha = 0.03 (NaN where not fitted).

    Parameters
    ----------
    fits : xarray.Dataset
        The ``fits.nc`` dataset.
    li : int
        Line index (0 primary, 1 secondary).

    Returns
    -------
    tuple of numpy.ndarray
        ``(alpha, tau)``, one value per cast.
    """
    al = fits["alpha"].values.astype(np.float64)
    ta = fits["tau"].values.astype(np.float64)
    a = np.full(fits.sizes["cast"], np.nan)
    t = a.copy()
    for i, m in enumerate(fits["ctm_cost"].values[:, li]):
        n = F.normalise(m.astype(np.float64), (0, 0))
        if n is not None:
            a[i], t[i] = F.one_parameter_fits(n, al, ta)
    return a, t


def draw_alignment_fig(
    fits: xr.Dataset, *, width_in: float = _W_FULL
) -> plt.Figure | None:
    """Return per-cast total conductivity advance, primary and secondary, with their medians.

    The total is the deck unit's advance plus the residual at each cast's minimum.  A solid line
    marks the primary median and a dashed line the secondary, each with its value printed.

    Parameters
    ----------
    fits : xarray.Dataset
        The ``fits.nc`` dataset.
    width_in : float, default ``W_FULL``
        Figure width in inches; the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        None when no cast has an alignment fit.
    """
    labels = [str(c) for c in fits["cast_id"].values]
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(width_in, width_in * 0.38))
    drawn = False
    deck = (
        fits["deck_advance"].values
        if "deck_advance" in fits
        else np.zeros(fits.sizes["line"])
    )
    for li, line in enumerate(fits["line"].values):
        marker, ls, name = LINE_STYLE[int(line)]
        base = float(deck[li]) if np.isfinite(deck[li]) else 0.0
        y = per_cast_alignment(fits, li) + base
        if not np.isfinite(y).any():
            continue
        drawn = True
        colour = "k" if line == 1 else "0.4"
        ax.plot(
            x,
            y,
            marker,
            ms=3.5,
            color=colour,
            mfc=colour if line == 1 else "none",
            ls="none",
            label=name,
        )
        med = float(np.nanmedian(y))
        ax.axhline(med, color=colour, ls=ls, lw=pen("thin"))
        ax.annotate(f"{name} {med:.3f} s", (1.0, med), xycoords=("axes fraction", "data"), xytext=(4, 0),
                    textcoords="offset points", va="center", color=colour)  # fmt: skip
    if not drawn:
        plt.close(fig)
        return None
    # Casts with no minimum inside the search: a tick along the top, not a value.
    edge_any = np.zeros(len(x), bool)
    for li in range(fits.sizes["line"]):
        edge_any |= alignment_at_edge(fits, li)
    if edge_any.any():
        ax.plot(x[edge_any], np.full(edge_any.sum(), 0.97), "|", color="0.55", ms=8,
                transform=ax.get_xaxis_transform(), label=f"no minimum in the search ({int(edge_any.sum())})")  # fmt: skip
    if np.isfinite(deck).any():
        ax.axhline(float(np.nanmax(deck)), color="0.75", lw=pen("thinner"))
    ax.set_ylabel("total conductivity advance (s)")
    _xticks(ax, labels)
    ax.legend(loc="lower left")
    fig.tight_layout()
    return fig


def draw_ctm_casts_fig(
    fits: xr.Dataset, *, width_in: float = _W_FULL
) -> plt.Figure | None:
    """Return the three-panel cell thermal mass figure, x = cast.

    (1) |ΔT| between the bottom and the top of the window, downcast and upcast; (2) maximum
    pressure, with the window marked for casts that were fitted; (3) one-parameter fits, alpha at
    tau = 7 s (black, left) and tau at alpha = 0.03 (right), filled where the cast's |ΔT| is above
    the cruise median and open below.

    Parameters
    ----------
    fits : xarray.Dataset
        The ``fits.nc`` dataset.
    width_in : float, default ``W_FULL``
        Figure width in inches; the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        None when no cast has a cell thermal mass fit.
    """
    if not np.isfinite(fits["ctm_cost"].values).any():
        return None
    labels = [str(c) for c in fits["cast_id"].values]
    x = np.arange(len(labels))
    pmin = float(fits.attrs.get("ctm_pmin_dbar", F.DEFAULT_CTM_PMIN))
    dt = fits["delta_t"].values.astype(np.float64)
    pmax = fits["pmax"].values.astype(np.float64)
    fig, (a0, a1, a2) = plt.subplots(
        3, 1, figsize=(width_in, width_in * 0.95), sharex=True
    )
    a0.plot(x, dt[:, 0], "-", color=DOWN, lw=pen("thin"), marker=".", label="downcast")
    a0.plot(x, dt[:, 1], "-", color=UP, lw=pen("thin"), marker=".", label="upcast")
    a0.set_ylabel(f"|ΔT| bottom − {pmin:g} dbar (°C)")
    a0.legend(loc="upper right")
    fitted = np.isfinite(fits["ctm_cost"].values).any(axis=(1, 2, 3))
    a1.plot(x, pmax, "k.")
    for i in np.flatnonzero(fitted):
        a1.plot([i, i], [pmin, pmax[i]], color="0.6", lw=2)
    a1.invert_yaxis()
    a1.set_ylabel("max pressure (dbar)")
    mag = np.nanmax(np.where(np.isfinite(dt), dt, -np.inf), axis=1)
    strong = (
        mag > np.nanmedian(mag[np.isfinite(mag)])
        if np.isfinite(mag).any()
        else np.zeros(len(x), bool)
    )
    a2b = a2.twinx()
    for li, line in enumerate(fits["line"].values):
        marker, _ls, _name = LINE_STYLE[int(line)]
        a, t = per_cast_one_parameter(fits, li)
        for sel, filled in ((strong, True), (~strong, False)):
            a2.plot(
                x[sel],
                a[sel],
                marker,
                ms=4,
                color="k",
                mfc="k" if filled else "none",
                ls="none",
            )
            a2b.plot(
                x[sel],
                t[sel],
                marker,
                ms=4,
                color=TAU_COLOUR,
                mfc=TAU_COLOUR if filled else "none",
                ls="none",
            )
    a2.axhline(F.DEFAULT_ALPHA_SBE, color="k", lw=pen("thinner"), ls=":")
    a2b.axhline(F.DEFAULT_TAU_SBE, color=TAU_COLOUR, lw=pen("thinner"), ls=":")
    a2.set_ylabel("α at τ = 7 s")
    a2b.set_ylabel("τ at α = 0.03 (s)", color=TAU_COLOUR)
    _xticks(a2, labels)
    fig.tight_layout()
    return fig


def draw_ctm_surface_fig(
    fits: xr.Dataset, *, width_in: float = _W_FULL
) -> plt.Figure | None:
    """Return the cruise cell thermal mass cost surface per line, as labelled line contours.

    The surface is the |ΔT|-weighted mean of each cast's cost divided by its cost with no
    correction; contours are labelled as multiples of the minimum, the region within 5% of the
    minimum is shaded, and Sea-Bird's (0.03, 7 s) is marked with a cross.

    Parameters
    ----------
    fits : xarray.Dataset
        The ``fits.nc`` dataset.
    width_in : float, default ``W_FULL``
        Figure width in inches; the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        None when no line has a cell thermal mass fit.
    """
    al = fits["alpha"].values.astype(np.float64)
    ta = fits["tau"].values.astype(np.float64)
    panels = []
    for li, line in enumerate(fits["line"].values):
        costs, weights = [], []
        for m, dt in zip(
            fits["ctm_cost"].values[:, li], fits["delta_t"].values, strict=True
        ):
            n = F.normalise(m.astype(np.float64), (0, 0))
            if n is not None:
                costs.append(n)
                weights.append(float(np.nanmax(dt)) if np.isfinite(dt).any() else 0.0)
        fit = F.cruise_surface(costs, weights)
        if fit is not None:
            panels.append((int(line), fit))
    if not panels:
        return None
    fig, axs = plt.subplots(
        1, len(panels), figsize=(width_in, width_in * 0.42), sharey=True, squeeze=False
    )
    for ax, (line, fit) in zip(axs[0], panels, strict=True):
        s, (i, j) = fit.surface, fit.index
        smin = s[i, j]
        levels = smin * np.array([1.02, 1.05, 1.1, 1.2, 1.4, 1.7, 2.0, 3.0, 5.0])
        ax.contourf(
            ta, al, s, levels=[0.0, smin * (1 + F.VALLEY_FRACTION)], colors=["#fde3c8"]
        )
        cs = ax.contour(
            ta, al, s, levels=levels, colors="0.45", linewidths=pen("thinner")
        )
        ax.clabel(cs, fmt=lambda v, m=smin: f"{v / m:.2f}")
        ax.plot(ta[j], al[i], "o", color=UP)
        ax.plot(F.DEFAULT_TAU_SBE, F.DEFAULT_ALPHA_SBE, "x", color="k", mew=2)
        ax.set_title(
            f"{LINE_STYLE[line][2]}: minimum ({al[i]:g}, {ta[j]:g} s), n = {fit.n_casts}"
        )
        ax.set_xlabel("τ (s)")
    axs[0][0].set_ylabel("α")
    fig.tight_layout()
    return fig


def draw_blocks_fig(
    fits: xr.Dataset, *, width_in: float = _W_FULL
) -> plt.Figure | None:
    """Return the fits for blocks of consecutive casts: advance, alpha at 7 s, tau at 0.03.

    Parameters
    ----------
    fits : xarray.Dataset
        The ``fits.nc`` dataset; its ``block`` attribute sets the casts per block.
    width_in : float, default ``W_FULL``
        Figure width in inches; the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        None when the cruise has fewer than two blocks.
    """
    n = fits.sizes["cast"]
    size = int(fits.attrs.get("block", 10))
    starts = list(range(0, n, size))
    if len(starts) < 2:
        return None
    labels = [str(c) for c in fits["cast_id"].values]
    deck = (
        fits["deck_advance"].values
        if "deck_advance" in fits
        else np.zeros(fits.sizes["line"])
    )
    rows: dict[int, list] = {1: [], 2: []}
    for b0 in starts:
        for s in summarise(fits, casts=slice(b0, b0 + size)):
            rows[s.line].append((b0 + (min(size, n - b0) - 1) / 2, s))
    fig, (a0, a1, a2) = plt.subplots(
        3, 1, figsize=(width_in, width_in * 0.8), sharex=True
    )
    for line, pts in rows.items():
        if not pts:
            continue
        marker, ls, name = LINE_STYLE[line]
        xs = [p[0] for p in pts]
        base = float(deck[line - 1]) if np.isfinite(deck[line - 1]) else 0.0
        kw = {
            "color": "k",
            "mfc": "k" if line == 1 else "none",
            "ls": ls,
            "marker": marker,
        }
        a0.plot(xs, [p[1].residual + base for p in pts], label=name, **kw)
        a1.plot(xs, [p[1].alpha_at_tau for p in pts], **kw)
        a2.plot(xs, [p[1].tau_at_alpha for p in pts], **kw)
    a0.set_ylabel("advance (s)")
    a0.legend(loc="best")
    a1.axhline(F.DEFAULT_ALPHA_SBE, color="0.6", ls=":", lw=pen("thinner"))
    a2.axhline(F.DEFAULT_TAU_SBE, color="0.6", ls=":", lw=pen("thinner"))
    a1.set_ylabel("α at τ = 7 s")
    a2.set_ylabel("τ at α = 0.03 (s)")
    _xticks(a2, labels)
    fig.tight_layout()
    return fig
