"""QC flag summary and thresholds, read back from a per-cast stage file.

The report shows what QC the pipeline applied — the flag-count breakdown per
variable and the gross-range thresholds recorded on each ``{var}_qc`` companion.
Both read the file's own ``flag_values``/``flag_meanings``, so the table is
correct for whatever convention the file declares (ctdcast writes QARTOD), and
stays correct for a file written by an older version.

Read the **best-available per-cast stage file**, not ``profiles.nc``: the
compiled product deliberately drops ``_qc`` companions (per-scan integer flags
are not griddable), so the flags only exist on the per-cast files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

#: ctdcast-local display colours for the QARTOD flag values it declares.  A file
#: states its flag *values and meanings*; colour is the one thing it does not
#: carry, so it is chosen here — semantically: pass green, suspect amber, fail
#: red, missing grey.  Unlisted flags fall back to :data:`_DEFAULT_COLOR`.
QC_FLAG_COLORS: dict[int, str] = {
    1: "#27ae60",
    2: "#a8e6cf",
    3: "#f39c12",
    4: "#e74c3c",
    9: "#bdc3c7",
}
_DEFAULT_COLOR = "#999999"

#: Short display glosses of the QARTOD ``flag_meanings`` tokens ctdcast writes.
#: Keyed by the meaning token so the label follows the file, not a fixed value.
_GLOSS: dict[str, str] = {
    "pass": "pass",
    "not_evaluated": "not eval",
    "suspect_or_of_high_interest": "suspect",
    "fail": "fail",
    "missing_data": "missing",
}

#: Fallback flag vocabulary when a ``_qc`` variable declares none (should not
#: happen for a ctdcast file, but keeps the reader robust).
_FALLBACK_VALUES = (1, 2, 3, 4, 9)


def _flag_vocab(qc_var: xr.DataArray) -> list[tuple[int, str]]:
    """Return ``[(value, label), …]`` from the qc variable's own attributes.

    Reads ``flag_values`` and ``flag_meanings`` (positionally paired, the CF
    convention) and glosses each meaning to a short label.  Falls back to the
    QARTOD values ctdcast declares when the file states none.
    """
    values = qc_var.attrs.get("flag_values")
    meanings = str(qc_var.attrs.get("flag_meanings", "")).split()
    if values is None or len(values) == 0:
        return [(v, _GLOSS.get("", str(v))) for v in _FALLBACK_VALUES]
    vocab: list[tuple[int, str]] = []
    for i, val in enumerate(np.asarray(values).ravel().tolist()):
        meaning = meanings[i] if i < len(meanings) else str(val)
        vocab.append((int(val), _GLOSS.get(meaning, meaning.replace("_", " "))))
    return vocab


def qc_summary(nc_path: Path) -> list[dict[str, Any]]:
    """Return the per-variable QC flag-count breakdown for a per-cast file.

    One row per ``{var}`` that has a ``{var}_qc`` companion and exists as a data
    variable: ``{var, total, flags: [{flag, label, color, n, pct}, …]}``, with
    one entry per flag value the qc variable declares.  Returns ``[]`` on any
    read error (a missing or unreadable file is not a report-time failure).
    """
    try:
        with xr.open_dataset(nc_path, engine="netcdf4", decode_timedelta=False) as ds:
            rows: list[dict[str, Any]] = []
            for v in sorted(ds.data_vars):
                if not v.endswith("_qc"):
                    continue
                base = v[:-3]
                if base not in ds.data_vars:
                    continue
                flags = ds[v].values.astype(int).ravel()
                total = int(flags.size)
                if total == 0:
                    continue
                flag_rows = [
                    {
                        "flag": val,
                        "label": label,
                        "color": QC_FLAG_COLORS.get(val, _DEFAULT_COLOR),
                        "n": int(np.sum(flags == val)),
                        "pct": round(100.0 * int(np.sum(flags == val)) / total, 1),
                    }
                    for val, label in _flag_vocab(ds[v])
                ]
                rows.append({"var": base, "total": total, "flags": flag_rows})
            return rows
    except (OSError, ValueError, KeyError):
        return []


def qc_thresholds(nc_path: Path) -> list[dict[str, Any]]:
    """Return the gross-range thresholds recorded on each ``{var}_qc`` companion.

    Reads the ``qc_gross_range_suspect_min``/``…_max`` attrs that
    :func:`ctdcast.processors.qc.apply_gross_range` stamps on the qc variable, so
    the table reflects the values actually applied to the file (defaults, config,
    or per-cast overrides) without parsing the ``history`` prose.  One row per
    ``(variable, test)``.  Returns ``[]`` on any read error.
    """
    try:
        with xr.open_dataset(nc_path, engine="netcdf4", decode_timedelta=False) as ds:
            rows: list[dict[str, Any]] = []
            for v in sorted(ds.data_vars):
                if not v.endswith("_qc"):
                    continue
                base = v[:-3]
                if base not in ds.data_vars:
                    continue
                a = ds[v].attrs
                smin = a.get("qc_gross_range_suspect_min")
                smax = a.get("qc_gross_range_suspect_max")
                if smin is not None and smax is not None:
                    rows.append(
                        {
                            "var": base,
                            "test": "gross-range",
                            "suspect": f"[{smin}, {smax}]",
                        }
                    )
            return rows
    except (OSError, ValueError, KeyError):
        return []
