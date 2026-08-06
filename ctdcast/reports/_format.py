"""Display-formatting helpers for report pages (dates, etc.).

Internal to ``reports/``; parallels oceanarray's ``report/_html_helpers.py``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import xarray as xr


def profile_cast_suffixes(ds: xr.Dataset) -> np.ndarray:
    """Return the per-profile cast letter suffix as a string array.

    Reads the ``cast_suffix`` variable when present; falls back to all-empty
    (every cast treated as plain) for a ``profiles.nc`` written before the
    variable existed, so older files still load.
    """
    if "cast_suffix" in ds:
        return ds["cast_suffix"].values.astype(str)
    return np.full(ds.sizes["N_PROF"], "", dtype="<U1")


def _fmt_utc(t: Any) -> str:
    """Format a numpy datetime64 scalar as 'YYYY-MM-DD HH:MM UTC'.

    Returns '—' on any error.
    """
    try:
        return str(np.datetime_as_string(t, unit="m")).replace("T", " ") + " UTC"
    except Exception:  # noqa: BLE001
        return "—"
