"""Display-formatting helpers for report pages (dates, etc.).

Internal to ``reports/``; parallels oceanarray's ``report/_html_helpers.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import xarray as xr

#: The display form of the "Generated"/build timestamp shown on every report page.
GENERATED_AT_FMT = "%Y-%m-%d %H:%M UTC"


def report_generated_at(generated_at: str | None = None) -> str:
    """Return the page build stamp: *generated_at* if given, else the current UTC time.

    Threaded from :func:`ctdcast.report` so one build stamps every page with the same
    value and a caller (the demo) can pin a fixed, reproducible date; ``None`` falls
    back to the current time, the normal run.  Parallels the injectable ``now`` of
    :func:`ctdcast.config.global_attrs.provenance_attrs`.
    """
    return generated_at or datetime.now(timezone.utc).strftime(GENERATED_AT_FMT)


def profile_cast_suffixes(ds: xr.Dataset) -> np.ndarray:
    """Return the per-profile cast letter suffix as a string array.

    Reads the ``cast_suffix`` variable when present; falls back to all-empty
    (every cast treated as plain) for a ``profiles.nc`` written before the
    variable existed, so older files still load.
    """
    if "cast_suffix" in ds:
        return ds["cast_suffix"].values.astype(str)
    return np.full(ds.sizes["N_PROF"], "", dtype="<U1")


def _fmt_utc(t: np.datetime64) -> str:
    """Format a numpy datetime64 scalar as 'YYYY-MM-DD HH:MM UTC'.

    Returns '—' on any error.
    """
    try:
        return str(np.datetime_as_string(t, unit="m")).replace("T", " ") + " UTC"
    except Exception:  # noqa: BLE001
        return "—"
