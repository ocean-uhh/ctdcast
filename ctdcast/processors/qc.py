"""Stage QC — gross-range flagging.

Sets QARTOD flag 3 (suspect) on any record outside the configured
physical range.  Operates on per-cast Datasets (dim=time); call after
``apply_stage2`` so the flag arrays already exist.
"""

from __future__ import annotations

import datetime

import numpy as np
import xarray as xr

# Physical plausibility bounds by internal variable name.
# These are deliberately generous — they catch instrument malfunction,
# not oceanographic anomalies.  Per-cruise tightening goes in config.yaml
# under qc.gross_range.<variable>.
GROSS_RANGE_DEFAULTS: dict[str, tuple[float, float]] = {
    "temperature_1": (-2.5, 40.0),
    "temperature_2": (-2.5, 40.0),
    "temperature": (-2.5, 40.0),
    "conductivity_1": (0.0, 7.0),
    "conductivity_2": (0.0, 7.0),
    "salinity_1": (2.0, 42.0),
    "salinity_2": (2.0, 42.0),
    "oxygen_1": (0.0, 450.0),
    "oxsat_1": (0.0, 200.0),
    "fluorescence": (0.0, 50.0),
    "turbidity": (0.0, 50.0),
}


def apply_gross_range(
    ds: xr.Dataset,
    thresholds: dict[str, tuple[float, float]] | None = None,
) -> xr.Dataset:
    """Set QARTOD flag 3 on records outside gross-range bounds.

    Creates ``{var}_qc`` arrays (int8, initialised 1=pass) if they do not
    already exist.  Merges ``GROSS_RANGE_DEFAULTS`` with any caller-supplied
    ``thresholds``; caller wins per variable.  Records each threshold used in
    ``ds.attrs["history"]``.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time).  Modified variables are those present
        in both ``ds`` and the merged threshold dict.
    thresholds:
        Per-variable overrides: ``{"salinity_1": (30.0, 40.0)}``.
        Caller-supplied values replace the defaults for that variable.

    Returns
    -------
    xr.Dataset
        New Dataset; input is not mutated.
    """
    merged: dict[str, tuple[float, float]] = {**GROSS_RANGE_DEFAULTS}
    if thresholds:
        merged.update(thresholds)

    ds = ds.copy()
    applied: list[str] = []

    for var, (vmin, vmax) in merged.items():
        if var not in ds:
            continue
        qc_name = f"{var}_qc"
        if qc_name not in ds:
            dim = ds[var].dims[0]
            n = ds.sizes[dim]
            ds[qc_name] = xr.DataArray(
                np.ones(n, dtype=np.int8),
                dims=[dim],
                attrs=_qc_attrs(var, ds[var].attrs.get("standard_name")),
            )
        vals = ds[var].values
        out_of_range = ~np.isnan(vals) & ((vals < vmin) | (vals > vmax))
        if out_of_range.any():
            qc = ds[qc_name].values.copy()
            qc[out_of_range] = np.int8(3)
            ds[qc_name] = xr.DataArray(
                qc,
                dims=ds[qc_name].dims,
                attrs=ds[qc_name].attrs,
            )
        applied.append(f"{var}:[{vmin},{vmax}]")

    if applied:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        entry = f"{stamp} ctdcast apply_gross_range: {', '.join(applied)}"
        prev = ds.attrs.get("history", "")
        ds.attrs["history"] = f"{prev}\n{entry}".lstrip("\n")

    return ds


def _qc_attrs(var: str, standard_name: str | None) -> dict:
    """Return CF-compliant flag attributes for a QC variable."""
    attrs: dict = {
        "long_name": f"Quality flag for {var}",
        "flag_values": np.array([1, 2, 3, 4, 9], dtype=np.int8),
        "flag_meanings": "pass not_evaluated suspect_or_of_high_interest fail missing_data",
        "valid_min": np.int8(1),
        "valid_max": np.int8(9),
        "conventions": "QARTOD",
    }
    if standard_name:
        attrs["standard_name"] = f"{standard_name} status_flag"
    return attrs
