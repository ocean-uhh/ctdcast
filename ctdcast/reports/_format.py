"""Display-formatting helpers for report pages (dates, etc.).

Internal to ``reports/``; parallels oceanarray's ``report/_html_helpers.py``.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def _fmt_utc(t: Any) -> str:
    """Format a numpy datetime64 scalar as 'YYYY-MM-DD HH:MM UTC'.

    Returns '—' on any error.
    """
    try:
        return str(np.datetime_as_string(t, unit="m")).replace("T", " ") + " UTC"
    except Exception:  # noqa: BLE001
        return "—"
