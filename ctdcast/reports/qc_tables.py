"""ctdcast-owned QC table post-processing.

The QC flag-count and threshold *tables* are built by the vendored
:mod:`ctdcast.reports._vendored.nc_tables` (:func:`~ctdcast.reports._vendored.nc_tables.qc_flag_rows`
and :func:`~ctdcast.reports._vendored.nc_tables.qc_threshold_rows`) and rendered by its macros,
file-driven from each ``{var}_qc`` companion's own ``flag_values`` / ``flag_meanings``.  This
module keeps the two ctdcast-specific pieces: collapsing dual-sensor threshold rows that share
identical bounds, and the explanatory note shown with the flag-count table.
"""

from __future__ import annotations

import re
from typing import Any

#: Trailing sensor number (``conductivity_1`` → family ``conductivity``).
_SENSOR_SUFFIX = re.compile(r"_\d+$")

#: Explanatory caption shown with the flag-count table: flag 4 is not solely the variable's own
#: gross-range / spike test — stage 2's whole-cast soak / on-deck trim sets flag 4 on the same
#: scans of *every* variable, so a variable can show flagged samples its own thresholds never
#: raised.  Owned here (it describes ctdcast's stage-2 behaviour, not a vendored table rule).
QC_FLAG_NOTE = (
    "Flag 4 (fail) combines two independent exclusions: this variable’s own gross-range "
    "and spike tests, and the whole-cast soak / on-deck trim, which flags the same pre-descent "
    "and post-recovery scans on every variable. A variable can therefore show flagged samples "
    "that its own thresholds did not raise."
)


def collapse_sibling_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge dual-sensor threshold rows that share identical thresholds.

    ``conductivity_1`` and ``conductivity_2`` with the same bounds are one row, labelled
    ``conductivity_*`` — the thresholds are per-family, so repeating a row per sensor is noise.
    Siblings whose thresholds differ (e.g. a per-sensor config override) stay separate.
    First-seen order is preserved.
    """
    grouped: dict[tuple, dict[str, Any]] = {}
    order: list[tuple] = []
    for r in rows:
        family = _SENSOR_SUFFIX.sub("", r["var"])
        key = (family, r["test"], r["suspect"], r["fail"])
        if key not in grouped:
            grouped[key] = {**r, "_names": [r["var"]]}
            order.append(key)
        else:
            grouped[key]["_names"].append(r["var"])
    out: list[dict[str, Any]] = []
    for key in order:
        g = grouped[key]
        names = g.pop("_names")
        g["var"] = f"{key[0]}_*" if len(names) > 1 else names[0]
        out.append(g)
    return out
