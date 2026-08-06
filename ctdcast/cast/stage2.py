"""Stage 2 — trim.

Downcast/upcast splitting and soak / back-on-deck detection.  This is processing,
not analysis: it decides which scans belong to the real cast.  In the target
pipeline stage2 flags rather than deletes (architecture plan §3); for now these
functions return indices the callers slice on.

The turnaround convention (last pressure within 2 dbar of the maximum) and the
soak/deck algorithms are deliberate — see the individual docstrings.
"""

from __future__ import annotations

import numpy as np
import xarray as xr


def split_cast(ds: xr.Dataset) -> tuple[xr.Dataset, xr.Dataset]:
    """Split *ds* (individual cast file, dim=time) into (downcast, upcast).

    Uses the turnaround convention: last index where pressure is within 2 dbar
    of its maximum.
    """
    p = ds["pressure"].values
    p_max = float(np.nanmax(p))
    near = np.where(p >= p_max - 2)[0]
    i_turn = int(near[-1]) if len(near) else len(p) // 2
    return ds.isel(time=slice(0, i_turn + 1)), ds.isel(time=slice(i_turn, None))


def find_soak_end(
    pressure: np.ndarray,
    times: np.ndarray,
    near_surface_dbar: float = 10.0,
    search_seconds: float = 20.0,
) -> int:
    """Return the index at which the real downcast begins (exclusive end of soak).

    Algorithm (three steps):

    1. Find ``i_max``, the index of the global pressure maximum (deepest point
       of the cast).  Searching only in ``pressure[0:i_max+1]`` keeps the
       upcast recovery — when the CTD returns to the surface at the end of the
       cast — from being confused with the pre-soak position.
    2. Within ``pressure[0:i_max+1]``, find the **last** index where
       ``pressure < near_surface_dbar``.  For a typical MSM-style cast this
       falls on the early real descent, just as the CTD passes
       ``near_surface_dbar`` going downward.
    3. Crawl **backward** from that index within ``search_seconds`` to find the
       **minimum pressure** — the shallowest point (closest to the surface) just
       before the real descent began.  Return the index immediately after that
       minimum as the start of the real downcast.

    In bad-weather conditions where the CTD soaks at depth and is never raised
    back to the surface, step 3 finds the minimum within the soak window and
    removes only the first ``search_seconds`` of the soak.  The operator-
    visible effect is a truncation of the pre-soak data, not a clean removal.

    Parameters
    ----------
    pressure:
        Pressure array in dbar (1-D, same length as *times*).
    times:
        Time coordinate array.  May be ``numpy.datetime64`` or numeric seconds;
        elapsed time is computed relative to ``times[0]``.
    near_surface_dbar:
        Pressure threshold used to find the last near-surface crossing before
        the main descent.  Default is 10 dbar (≈10 m), safely below the
        typical soak depth of 8–10 m.
    search_seconds:
        Width of the backward-crawl window (seconds) used to find the
        pre-descent surface minimum.  Default is 20 s.

    Returns
    -------
    int
        Index of the first record to keep; slice with
        ``ds.isel(time=slice(idx, None))``.  Returns 0 if the cast never
        reaches below ``near_surface_dbar`` (no trim applied).

    """
    n = len(pressure)
    if n == 0:
        return 0

    p_arr = np.asarray(pressure, dtype=float)
    times_arr = np.asarray(times)
    if np.issubdtype(times_arr.dtype, np.datetime64):
        elapsed = (times_arr - times_arr[0]) / np.timedelta64(1, "s")
    else:
        elapsed = times_arr.astype(float) - float(times_arr[0])

    # Step 1: deepest point (also limits search to downcast only)
    i_max = int(np.nanargmax(p_arr))

    # Step 2: last near-surface crossing before the deepest point
    pre_max_mask = p_arr[: i_max + 1] < near_surface_dbar
    near_indices = np.where(pre_max_mask)[0]
    if len(near_indices) == 0:
        return 0  # cast never came within near_surface_dbar of the surface

    i_last_near = int(near_indices[-1])

    # Step 3: within search_seconds before i_last_near, find the pressure minimum
    t_last = float(elapsed[i_last_near])
    i_win_start = int(np.searchsorted(elapsed, t_last - search_seconds))
    i_win_start = max(0, i_win_start)
    window_p = p_arr[i_win_start : i_last_near + 1]
    if len(window_p) == 0:
        return i_last_near + 1

    i_min_local = int(np.nanargmin(window_p))
    i_min = i_win_start + i_min_local

    return i_min + 1


def find_cast_end(
    pressure: np.ndarray,
    times: np.ndarray,
    deck_window_seconds: float = 20.0,
    margin_dbar: float = 0.5,
    max_deck_dbar: float = 20.0,
) -> int:
    """Return the exclusive end index, trimming post-recovery deck records.

    Algorithm:

    1. Take the median pressure of the last *deck_window_seconds* seconds as
       the on-deck reference pressure.  Using a median handles sensor offset
       (the pressure sensor may not read exactly 0 dbar when the CTD is in
       the air) and is robust to brief oscillations on deck.
    2. Find the **first** index after the pressure maximum where pressure falls
       at or below ``p_deck_median + margin_dbar``.  Trim from that index
       onward.

    Returns ``len(pressure)`` (no trim) if:
    - the record is empty or the CTD never returned near the surface
      (``p_deck_median > max_deck_dbar``), or
    - pressure never drops to the threshold on the upcast.

    Parameters
    ----------
    pressure:
        Pressure array in dbar.
    times:
        Time coordinate array (``numpy.datetime64`` or numeric seconds).
    deck_window_seconds:
        Duration of the tail window used to estimate on-deck pressure.
    margin_dbar:
        Added to the on-deck median to form the cut threshold.
    max_deck_dbar:
        If the on-deck median exceeds this value the CTD is considered not to
        have returned to the surface and no trim is applied.

    Returns
    -------
    int
        Exclusive end index; slice with ``ds.isel(time=slice(None, idx))``.

    """
    n = len(pressure)
    if n == 0:
        return n

    p_arr = np.asarray(pressure, dtype=float)
    times_arr = np.asarray(times)
    if np.issubdtype(times_arr.dtype, np.datetime64):
        elapsed = (times_arr - times_arr[0]) / np.timedelta64(1, "s")
    else:
        elapsed = times_arr.astype(float) - float(times_arr[0])

    i_max = int(np.nanargmax(p_arr))

    # On-deck reference: median of final deck_window_seconds.
    t_end = float(elapsed[-1])
    i_win_start = int(np.searchsorted(elapsed, t_end - deck_window_seconds))
    i_win_start = max(i_max + 1, i_win_start)
    if i_win_start >= n:
        return n

    p_deck = float(np.nanmedian(p_arr[i_win_start:]))
    if p_deck > max_deck_dbar:
        return n

    threshold = p_deck + margin_dbar

    upcast = p_arr[i_max:]
    below = np.where(upcast <= threshold)[0]
    if len(below) == 0:
        return n

    return i_max + int(below[0])
