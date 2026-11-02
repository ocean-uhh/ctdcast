"""Fit conductivity alignment and cell thermal mass parameters from a cruise's casts.

Two cost functions on one cast at its native scan rate, and the arithmetic that combines them
over many casts.  They suggest the ``processing.alignctd`` and ``processing.celltm`` values that
stage 3 applies; they never change data.

- **Alignment** (:func:`alignment_cost`): the mean square of high-passed practical salinity in the
  thermocline, as a function of the conductivity advance on top of what the data already carry
  (the deck unit's).  A misalignment makes salinity spike where temperature changes fast; too
  much advance reverses the spikes, so the cost has a minimum.  Down and up are scored separately
  and should agree.
- **Cell thermal mass** (:func:`ctm_cost`): the down–up difference of practical salinity in
  temperature bins below a window top (default 200 dbar), each bin weighted towards the time the
  two legs passed it, as a function of ``(alpha, tau)``.  Each grid point is scored through
  seabirdscientific's ``cell_thermal_mass``, the correction stage 3 applies.

Over a cruise (:func:`cruise_surface`), each cast's cost is divided by its value with no
correction and the casts are averaged: the cruise optimum is the minimum of that average, not the
average of per-cast optima.  ``alpha`` and ``tau`` trade off along a valley, so
:func:`one_parameter_fits` also fits one with the other held at Sea-Bird's default, the stable
quantity for comparing casts and blocks of casts.

Original author of the cell thermal mass cost (down/up salinity in temperature bins, grid search
through Sea-Bird's ``cell_thermal_mass``): Joel Bracamontes Ramirez, ctdproc
``processing.find_opt_alp_tat_fast``.  The alignment cost, the time weighting, the window and the
cruise aggregation are not from ctdproc.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import gsw
import numpy as np
from scipy.ndimage import median_filter
from seabirdscientific import processing as sbs_processing

#: Residual conductivity advance searched by :func:`alignment_cost`, seconds on top of the data's.
DEFAULT_RESIDUALS = np.round(np.arange(-0.10, 0.15 + 1e-9, 0.005), 4)
#: Cell thermal mass grid searched by :func:`ctm_cost`, around Sea-Bird's (0.03, 7 s).
DEFAULT_ALPHA = np.round(np.arange(0.0, 0.08 + 1e-9, 0.0025), 4)
DEFAULT_TAU = np.round(np.arange(1.0, 16.0 + 1e-9, 0.5), 2)
#: Sea-Bird's defaults for a TC duct and 3000-rpm pump (SBE manual p.92).
DEFAULT_ALPHA_SBE = 0.03
DEFAULT_TAU_SBE = 7.0
#: Thermocline threshold for the alignment cost: |dT/dp| in °C per dbar, on 2-dbar bins.
DEFAULT_GRADIENT = 0.02
#: Top of the cell thermal mass window (dbar): the near-surface water changes between legs.
DEFAULT_CTM_PMIN = 200.0
#: Time scale (s) of the down/up weighting: weight = 1 / (gap + this).
DEFAULT_GAP_SCALE = 300.0
#: Temperature bins in the cell thermal mass cost.
DEFAULT_TEMPERATURE_BINS = 40
#: A cast's down/up difference within this fraction of the cruise minimum is "in the valley".
VALLEY_FRACTION = 0.05


@dataclass(frozen=True)
class Cast:
    """One cast's native-rate arrays for one conductivity line.

    Attributes
    ----------
    pressure : numpy.ndarray
        Pressure (dbar); NaN where a scan is not usable.
    temperature : numpy.ndarray
        ITS-90 temperature (°C) of the line.
    conductivity : numpy.ndarray
        Conductivity (mS/cm) of the line, as stage 2 carries it.
    interval : float
        Time between scans (s).
    """

    pressure: np.ndarray
    temperature: np.ndarray
    conductivity: np.ndarray
    interval: float

    @property
    def turnaround(self) -> int:
        """Index of the last scan within 2 dbar of the cast's maximum pressure."""
        p = self.pressure
        pmax = np.nanmax(p)
        return int(np.flatnonzero(p >= pmax - 2.0)[-1])

    @property
    def pmax(self) -> float:
        """The cast's maximum pressure (dbar)."""
        return float(np.nanmax(self.pressure))


def despike_pressure(
    pressure: np.ndarray, *, window: int = 49, limit: float = 5.0
) -> np.ndarray:
    """Return *pressure* with spikes and impossible values set NaN.

    A scan is a spike when it departs from the running median of *window* scans by more than
    *limit* dbar, or lies outside −5…7000 dbar.  The 911plus occasionally records single-scan
    pressure spikes of thousands of dbar, which would otherwise set the cast's maximum.

    Parameters
    ----------
    pressure : numpy.ndarray
        Pressure (dbar).
    window : int, optional
        Running-median length, in scans.
    limit : float, optional
        Departure from the running median (dbar) that marks a spike.

    Returns
    -------
    numpy.ndarray
        A float64 copy with spikes as NaN.
    """
    p = np.asarray(pressure, dtype=np.float64).copy()
    bad = ~np.isfinite(p) | (p > 7000.0) | (p < -5.0)
    fill = np.where(bad, np.nanmedian(p[~bad]) if (~bad).any() else 0.0, p)
    bad |= np.abs(p - median_filter(fill, size=window)) > limit
    p[bad] = np.nan
    return p


def _fill(x: np.ndarray) -> np.ndarray:
    """Linear interpolation across NaN, so a recursive filter can run through a short gap."""
    x = np.asarray(x, dtype=np.float64)
    ok = np.isfinite(x)
    if ok.all() or not ok.any():
        return x
    idx = np.arange(x.size)
    return np.interp(idx, idx[ok], x[ok])


def _bin_mean(
    key: np.ndarray, value: np.ndarray, edges: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Mean of *value* in bins of *key*, and the count per bin."""
    i = np.digitize(key, edges) - 1
    ok = (i >= 0) & (i < len(edges) - 1) & np.isfinite(value) & np.isfinite(key)
    n = np.bincount(i[ok], minlength=len(edges) - 1).astype(np.float64)
    s = np.bincount(i[ok], value[ok], minlength=len(edges) - 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return s / n, n


def window_delta_t(cast: Cast, pmin: float = DEFAULT_CTM_PMIN) -> tuple[float, float]:
    """Return |T(bottom) − T(pmin)| on the downcast and the upcast.

    The temperature change across the cell thermal mass window: where it is small the window
    carries no gradient and the fit learns nothing from the cast.

    Parameters
    ----------
    cast : Cast
        The cast.
    pmin : float, optional
        Top of the window (dbar).

    Returns
    -------
    tuple of float
        ``(down, up)`` in °C; NaN when the cast does not reach 60 dbar below *pmin*.
    """
    if cast.pmax < pmin + 60.0:
        return np.nan, np.nan
    k = cast.turnaround
    edges = np.arange(0.0, cast.pmax + 4.0, 2.0)
    out = []
    for sl in (slice(0, k + 1), slice(k, None)):
        m, _ = _bin_mean(cast.pressure[sl], cast.temperature[sl], edges)
        pc = 0.5 * (edges[1:] + edges[:-1])
        ok = np.isfinite(m)
        if ok.sum() < 4:
            out.append(np.nan)
            continue
        out.append(
            abs(
                float(
                    np.interp(cast.pmax - 5.0, pc[ok], m[ok])
                    - np.interp(pmin, pc[ok], m[ok])
                )
            )
        )
    return out[0], out[1]


def alignment_cost(
    cast: Cast,
    residuals: np.ndarray = DEFAULT_RESIDUALS,
    *,
    gradient: float = DEFAULT_GRADIENT,
) -> np.ndarray | None:
    """Return the salinity spike cost of each residual advance, downcast and upcast.

    For each advance, conductivity is advanced with seabirdscientific's ``align_ctd``, practical
    salinity is derived, and the cost is the mean square of salinity minus its 1-s running mean,
    over scans in 2-dbar bins whose downcast |dT/dp| exceeds *gradient*.  Every advance is scored
    on the same scans (those usable for all of them), so shifting data off the ends of the record
    cannot change the cost.

    Parameters
    ----------
    cast : Cast
        The cast, at its native scan rate.
    residuals : numpy.ndarray, optional
        Advances (s) to try, on top of whatever the data already carry.
    gradient : float, optional
        Thermocline threshold, °C per dbar.

    Returns
    -------
    numpy.ndarray or None
        Shape ``(2, len(residuals))``: row 0 the downcast, row 1 the upcast; NaN where a leg has
        under 200 thermocline scans.  None when the cast has no thermocline at all.
    """
    p, T = cast.pressure, cast.temperature
    k = cast.turnaround
    edges = np.arange(0.0, cast.pmax + 4.0, 2.0)
    tm, _ = _bin_mean(p[: k + 1], T[: k + 1], edges)
    pc = 0.5 * (edges[1:] + edges[:-1])
    with np.errstate(invalid="ignore"):
        steep = np.abs(np.gradient(tm, pc)) > gradient
    if steep.sum() < 5:
        return None
    b = np.digitize(p, edges) - 1
    in_tc = np.zeros(p.size, bool)
    ok_b = (b >= 0) & (b < steep.size)
    in_tc[ok_b] = steep[b[ok_b]]
    usable = in_tc & np.isfinite(p) & np.isfinite(T) & np.isfinite(cast.conductivity)
    c = _fill(cast.conductivity)
    p_f = _fill(p)
    n_avg = max(3, round(1.0 / cast.interval))
    kernel = np.ones(n_avg) / n_avg
    hps = []
    for r in residuals:
        ca = sbs_processing.align_ctd(
            c.copy(), float(r), cast.interval, flag_value=np.nan
        )
        s = gsw.SP_from_C(ca, T, p_f)
        hps.append(
            s
            - np.convolve(
                np.nan_to_num(s, nan=float(np.nanmean(s))), kernel, mode="same"
            )
        )
    hp = np.vstack(hps)
    # Every advance is scored on the same scans: a scan pushed off either end by any advance in
    # the search is dropped for all of them, so the cost cannot fall just because bad scans at an
    # end of the record leave it as the advance grows.  The 1-s running mean is unreliable within
    # a second of a NaN, so that margin goes too.
    common = usable & np.isfinite(hp).all(axis=0)
    common &= np.convolve((~common).astype(float), kernel, mode="same") == 0
    out = np.full((2, len(residuals)), np.nan)
    for leg, sl in enumerate((slice(0, k + 1), slice(k, None))):
        m = common[sl]
        if m.sum() >= 200:
            out[leg] = np.mean(hp[:, sl][:, m] ** 2, axis=1)
    return out


def ctm_cost(
    cast: Cast,
    alpha: np.ndarray = DEFAULT_ALPHA,
    tau: np.ndarray = DEFAULT_TAU,
    *,
    pmin: float = DEFAULT_CTM_PMIN,
    n_bins: int = DEFAULT_TEMPERATURE_BINS,
    gap_scale: float = DEFAULT_GAP_SCALE,
) -> np.ndarray | None:
    """Return the down/up salinity mismatch below *pmin* for each ``(alpha, tau)``.

    Conductivity is corrected over the whole cast (the filter needs the history), then practical
    salinity below *pmin* is averaged in *n_bins* temperature bins on each leg.  The cost is the
    weighted mean of (down − up)², each bin weighted by ``1 / (gap + gap_scale)`` where *gap* is the
    time between the two legs passing it, so the bottom of the cast, where the water has had least
    time to change, counts most.

    Parameters
    ----------
    cast : Cast
        The cast, at its native scan rate, conductivity already aligned.
    alpha, tau : numpy.ndarray, optional
        The grid (``tau`` in seconds).
    pmin : float, optional
        Top of the window (dbar).
    n_bins : int, optional
        Temperature bins across the 1st–99th percentile of the window.
    gap_scale : float, optional
        Weighting time scale (s).

    Returns
    -------
    numpy.ndarray or None
        Shape ``(len(alpha), len(tau))``; ``alpha == 0`` is no correction.  None when the cast
        does not reach 60 dbar below *pmin*, has under 98% finite scans, spans under 0.1 °C in
        the window, or has fewer than 5 bins seen by both legs.
    """
    if cast.pmax < pmin + 60.0:
        return None
    T0, C0 = cast.temperature, cast.conductivity
    if (np.isfinite(T0) & np.isfinite(C0)).mean() < 0.98:
        return None
    T, C, p = _fill(T0), _fill(C0), cast.pressure
    k = cast.turnaround
    t_s = np.arange(T.size) * cast.interval
    deep = np.isfinite(p) & (p > pmin)
    tlo, thi = np.nanpercentile(T[deep], [1, 99])
    if thi - tlo < 0.1:
        return None
    edges = np.linspace(tlo, thi, n_bins + 1)
    legs = (slice(0, k + 1), slice(k, None))
    sel = [np.flatnonzero(deep[sl]) + (sl.start or 0) for sl in legs]
    t_dn, n_dn = _bin_mean(T[sel[0]], t_s[sel[0]], edges)
    t_up, n_up = _bin_mean(T[sel[1]], t_s[sel[1]], edges)
    min_n = round(
        1.0 / cast.interval
    )  # at least a second of scans in a bin on each leg
    w = np.where(
        (n_dn >= min_n) & (n_up >= min_n), 1.0 / (np.abs(t_up - t_dn) + gap_scale), 0.0
    )
    w = np.nan_to_num(w)
    if (w > 0).sum() < 5:
        return None
    idx = np.concatenate(sel)
    p_w, T_w = p[idx], T[idx]
    n0 = sel[0].size
    out = np.full((len(alpha), len(tau)), np.nan)
    for i, a in enumerate(alpha):
        for j, tc in enumerate(tau):
            cc = (
                C
                if a == 0.0
                else sbs_processing.cell_thermal_mass(
                    T, C / 10.0, float(a), float(tc), cast.interval
                )
                * 10.0
            )
            s = gsw.SP_from_C(cc[idx], T_w, p_w)
            s_dn, _ = _bin_mean(T_w[:n0], s[:n0], edges)
            s_up, _ = _bin_mean(T_w[n0:], s[n0:], edges)
            d2 = (s_dn - s_up) ** 2
            ok = np.isfinite(d2) & (w > 0)
            out[i, j] = (
                float(np.sum(w[ok] * d2[ok]) / np.sum(w[ok])) if ok.any() else np.nan
            )
            if a == 0.0:
                out[i, :] = out[i, j]
                break
    return out


def has_interior_minimum(cost: np.ndarray) -> bool:
    """Return whether a 1-D cost has its minimum strictly inside the search.

    A cost whose minimum is its first or last value is still falling at the end of the search:
    it gives no estimate, and averaged with other casts it would pull the result to that end.

    Parameters
    ----------
    cost : numpy.ndarray
        One cast's cost over the searched values.

    Returns
    -------
    bool
        True when the minimum is neither the first nor the last finite-searched value.
    """
    if not np.isfinite(cost).any():
        return False
    j = int(np.nanargmin(cost))
    return 0 < j < cost.size - 1


def normalise(cost: np.ndarray, reference: tuple[int, ...]) -> np.ndarray | None:
    """Divide *cost* by its value at *reference* (no correction), or None if that is not usable.

    Parameters
    ----------
    cost : numpy.ndarray
        A cost array from :func:`alignment_cost` (summed over legs) or :func:`ctm_cost`.
    reference : tuple of int
        The index of the no-correction value.

    Returns
    -------
    numpy.ndarray or None
        The normalised cost, or None when the reference is NaN or not positive.
    """
    ref = cost[reference]
    if not np.isfinite(ref) or ref <= 0:
        return None
    return cost / ref


@dataclass(frozen=True)
class CruiseFit:
    """The cruise-average cost and where it is lowest.

    Attributes
    ----------
    surface : numpy.ndarray
        The average of the casts' normalised costs.
    index : tuple of int
        Index of the minimum.
    valley : numpy.ndarray
        Boolean mask of the points within :data:`VALLEY_FRACTION` of the minimum.
    n_casts : int
        How many casts went into the average.
    """

    surface: np.ndarray
    index: tuple[int, ...]
    valley: np.ndarray
    n_casts: int


def cruise_surface(
    costs: Sequence[np.ndarray], weights: Sequence[float] | None = None
) -> CruiseFit | None:
    """Average normalised per-cast costs and find the minimum and the valley.

    Parameters
    ----------
    costs : sequence of numpy.ndarray
        Normalised costs (from :func:`normalise`), all the same shape.
    weights : sequence of float, optional
        A weight per cast (e.g. its |ΔT| over the window); equal when omitted.

    Returns
    -------
    CruiseFit or None
        None when *costs* is empty.
    """
    if not costs:
        return None
    stack = np.stack(costs)
    wts = (
        np.ones(len(costs))
        if weights is None
        else np.asarray(weights, dtype=np.float64)
    )
    wts = np.where(np.isfinite(wts) & (wts > 0), wts, 0.0)
    if wts.sum() == 0:
        return None
    w = wts.reshape((-1,) + (1,) * (stack.ndim - 1)) * np.isfinite(stack)
    with np.errstate(invalid="ignore"):
        surface = np.nansum(stack * w, axis=0) / w.sum(axis=0)
    index = np.unravel_index(int(np.nanargmin(surface)), surface.shape)
    valley = surface <= surface[index] * (1.0 + VALLEY_FRACTION)
    return CruiseFit(
        surface, tuple(int(i) for i in index), valley, int((wts > 0).sum())
    )


def one_parameter_fits(
    surface: np.ndarray,
    alpha: np.ndarray = DEFAULT_ALPHA,
    tau: np.ndarray = DEFAULT_TAU,
    *,
    alpha_fixed: float = DEFAULT_ALPHA_SBE,
    tau_fixed: float = DEFAULT_TAU_SBE,
) -> tuple[float, float]:
    """Return alpha with tau held at *tau_fixed*, and tau with alpha held at *alpha_fixed*.

    ``alpha`` and ``tau`` trade off along a valley, so the two-parameter minimum of one cast or a
    few casts wanders; with one held at Sea-Bird's default the other is well defined.

    Parameters
    ----------
    surface : numpy.ndarray
        A cost surface on the ``(alpha, tau)`` grid.
    alpha, tau : numpy.ndarray, optional
        The grid.
    alpha_fixed, tau_fixed : float, optional
        The values held fixed.

    Returns
    -------
    tuple of float
        ``(alpha at tau_fixed, tau at alpha_fixed)``; NaN where the row or column is all NaN.
    """
    jt = int(np.argmin(np.abs(np.asarray(tau) - tau_fixed)))
    ia = int(np.argmin(np.abs(np.asarray(alpha) - alpha_fixed)))
    col, row = surface[:, jt], surface[ia, :]
    a = float(alpha[int(np.nanargmin(col))]) if np.isfinite(col).any() else np.nan
    t = float(tau[int(np.nanargmin(row))]) if np.isfinite(row).any() else np.nan
    return a, t
