"""Stage 2 — trim.

Downcast/upcast splitting and soak / back-on-deck detection.  This is processing,
not analysis: it decides which scans belong to the real cast.

``apply_stage2()`` is the pipeline entry point: it sets QARTOD flag 4 on soak
and post-recovery deck records and records the parameters used in
``ds.attrs["history"]``.  ``find_soak_end`` and ``find_cast_end`` are kept public
because ``reports._cast`` calls them directly for report-time plot trimming (that
coupling will be removed in a later phase when reports read flags from the files).

The turnaround convention (last pressure within 2 dbar of the maximum) and the
soak/deck algorithms are deliberate — see the individual docstrings.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import numpy as np
import xarray as xr

from ctdcast.processors.qc import _qc_attrs
from ctdcast.writers.netcdf import write as _write_nc

# _SKIP_STAGE2_QC: variables that are coordinates or administrative — not physical
# measurements, so they do not get a _qc flag from stage2.
_SKIP_STAGE2_QC: frozenset[str] = frozenset(
    {"pressure", "latitude", "longitude", "time", "timeJ", "timeS"}
)

# Keyword arguments accepted by apply_stage2(); others in **kw are dropped.
_STAGE2_KWARGS: frozenset[str] = frozenset(
    {
        "near_surface_dbar",
        "search_seconds",
        "deck_window_seconds",
        "margin_dbar",
        "max_deck_dbar",
    }
)


def apply_stage2(
    ds: xr.Dataset,
    *,
    near_surface_dbar: float = 10.0,
    search_seconds: float = 20.0,
    deck_window_seconds: float = 20.0,
    margin_dbar: float = 0.5,
    max_deck_dbar: float = 20.0,
) -> xr.Dataset:
    """Apply QARTOD flag 4 to soak and post-recovery deck records.

    Creates ``{var}_qc`` arrays (int8, flag 1=pass) for each physical data
    variable, then sets flag 4 (fail) on the pre-descent soak window and
    the post-recovery on-deck window.  Records the parameters used in
    ``ds.attrs["history"]`` so the treatment is reproducible from the output
    file alone.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time).
    near_surface_dbar:
        Passed to ``find_soak_end`` — pressure threshold for last near-surface
        crossing before the real descent.
    search_seconds:
        Passed to ``find_soak_end`` — backward-crawl window width.
    deck_window_seconds:
        Passed to ``find_cast_end`` — tail window for on-deck reference pressure.
    margin_dbar:
        Passed to ``find_cast_end`` — added to on-deck median to form the cut.
    max_deck_dbar:
        Passed to ``find_cast_end`` — if on-deck median exceeds this, no trim.

    Returns
    -------
    xr.Dataset
        New Dataset; input is not mutated.
    """
    ds = ds.copy()
    pressure = ds["pressure"].values
    times = ds["time"].values
    dim = ds["pressure"].dims[0]
    n = ds.sizes[dim]

    i_soak = find_soak_end(
        pressure,
        times,
        near_surface_dbar=near_surface_dbar,
        search_seconds=search_seconds,
    )
    i_deck = find_cast_end(
        pressure,
        times,
        deck_window_seconds=deck_window_seconds,
        margin_dbar=margin_dbar,
        max_deck_dbar=max_deck_dbar,
    )

    for var in list(ds.data_vars):
        if var in _SKIP_STAGE2_QC or var.endswith("_qc"):
            continue
        qc_name = f"{var}_qc"
        if qc_name not in ds:
            sname = ds[var].attrs.get("standard_name")
            ds[qc_name] = xr.DataArray(
                np.ones(n, dtype=np.int8),
                dims=[dim],
                attrs=_qc_attrs(var, sname),
            )
        qc = ds[qc_name].values.copy()
        if i_soak > 0:
            qc[:i_soak] = np.int8(4)
        if i_deck < n:
            qc[i_deck:] = np.int8(4)
        ds[qc_name] = xr.DataArray(qc, dims=[dim], attrs=ds[qc_name].attrs)

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = (
        f"near_surface_dbar={near_surface_dbar}, search_seconds={search_seconds}, "
        f"deck_window_seconds={deck_window_seconds}, margin_dbar={margin_dbar}, "
        f"max_deck_dbar={max_deck_dbar}"
    )
    entry = f"{stamp} ctdcast apply_stage2: soak_end_idx={i_soak}, deck_start_idx={i_deck}; {params}"
    prev = ds.attrs.get("history", "")
    ds.attrs["history"] = f"{prev}\n{entry}".lstrip("\n")

    return ds


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


def run(
    nc_dir: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    cast_tags: set[str] | None = None,
    **kw: object,
) -> int:
    """Apply stage2 (soak/deck flagging) to NC files in *nc_dir*.

    Reads each ``*.nc`` file, applies :func:`apply_stage2`, and writes the
    result back in place using :func:`ctdcast.writers.netcdf.write`.  Called
    by :func:`ctdcast.processors.process` with ``stage=2`` or
    ``stage="stage2"``.

    Parameters
    ----------
    nc_dir:
        Directory of per-cast netCDF files (read and written in place).
    force:
        Reprocess files that already carry ``_qc`` flag variables.  Without
        ``force``, already-flagged files are skipped.
    dry_run:
        Print which files would be processed without writing any output.
    cast_tags:
        If given, process only files whose stem contains one of the zero-padded
        3-digit cast numbers (e.g. ``{"042", "043"}``).
    **kw:
        Passed to :func:`apply_stage2` (e.g. ``near_surface_dbar``).

    Returns
    -------
    int
        Number of files written (0 for dry_run).

    Raises
    ------
    FileNotFoundError
        If *nc_dir* does not exist or is not a directory.
    """
    if not nc_dir.is_dir():
        raise FileNotFoundError(f"nc_dir not found: {nc_dir}")

    stage2_kw = {k: v for k, v in kw.items() if k in _STAGE2_KWARGS}

    nc_files = sorted(nc_dir.glob("*.nc"))
    if cast_tags is not None:
        nc_files = [p for p in nc_files if any(t in p.stem for t in cast_tags)]

    n = n_skipped = n_failed = 0
    for nc_path in nc_files:
        if dry_run:
            print(f"  [dry-run] stage 2 would flag: {nc_path.name}")
            continue
        ds = None
        try:
            ds = xr.open_dataset(nc_path, engine="netcdf4").load()
            already_flagged = any(v.endswith("_qc") for v in ds.data_vars)
            if already_flagged and not force:
                print(f"  skip (already flagged): {nc_path.name}")
                n_skipped += 1
                continue
            ds_out = apply_stage2(ds, **stage2_kw)
            ds.close()
            ds = None  # prevent double-close in finally; file released before write
            _write_nc(ds_out, nc_path)
            print(f"  ok: {nc_path.name}")
            n += 1
        except Exception as exc:  # noqa: BLE001
            print(
                f"  FAILED: {nc_path.name}  ({type(exc).__name__}: {exc})",
                file=sys.stderr,
            )
            n_failed += 1
        finally:
            if ds is not None:
                ds.close()
    if not dry_run:
        parts = [f"{n} written", f"{n_skipped} skipped"]
        if n_failed:
            parts.append(f"{n_failed} FAILED")
        print(f"stage 2: {', '.join(parts)}.")
    return n
