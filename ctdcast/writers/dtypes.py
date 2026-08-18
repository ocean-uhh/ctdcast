"""Optimal storage-dtype selection for netCDF output.

Package-local data-saving utility — **not** part of the vendored report design
system (which is about producing identical *reports*, not identical *data*).  The
two functions are ported from oceanarray and may diverge as ctdcast's on-disk
conventions require; keep them in sync by choice, not by vendoring discipline.

:func:`find_best_dtype` picks a variable's storage dtype from its name and current
dtype; :func:`cast_output_dtypes` applies that across a whole dataset before write,
shrinking file size (float64 → float32, int64 → int32, QC → int8) without touching
coordinates or provenance.
"""

from __future__ import annotations

import numpy as np
import xarray as xr


def find_best_dtype(var_name: str, da: xr.DataArray) -> type:
    """Determine the optimal storage dtype for a variable.

    Parameters
    ----------
    var_name : str
        Variable name.
    da : xr.DataArray
        Data array to inspect.

    Returns
    -------
    type
        Recommended numpy dtype.

    Notes
    -----
    Rules applied in order:

    - String / datetime / object variables: unchanged.
    - ``time`` in name: unchanged (preserve datetime64 / float encoding).
    - ``*_qc`` suffix or ``flag`` in name: ``int8``.
    - ``serial_number`` or ``serial``: ``int32``.
    - ``latitude`` / ``longitude`` in name: ``float64``.
    - Integer input: downsize to ``int32`` if stored as ``int64``, else unchanged.
    - ``float64`` input: ``float32``.
    - Anything else: unchanged.

    """
    input_dtype = da.dtype.type
    if da.dtype.kind in ("U", "S", "O", "M"):
        return input_dtype
    if "time" in var_name.lower():
        return input_dtype
    if var_name.endswith("_qc") or "flag" in var_name:
        return np.int8
    if var_name in ("serial_number", "serial"):
        return np.int32
    if "latitude" in var_name.lower() or "longitude" in var_name.lower():
        return np.float64
    if da.dtype.kind in ("i", "u") and da.dtype.itemsize == 8:
        return np.int32
    if input_dtype == np.float64:
        return np.float32
    return input_dtype


def cast_output_dtypes(ds: xr.Dataset) -> xr.Dataset:
    """Cast every variable in *ds* to its optimal storage dtype.

    Calls :func:`find_best_dtype` per variable and rebuilds only those that
    change.  Attributes are preserved.  The input dataset is not modified.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset to cast.

    Returns
    -------
    xr.Dataset
        New dataset with optimised dtypes, ready for NetCDF output.

    """
    updates: dict[str, xr.Variable] = {}
    for vname in ds.data_vars:
        var = ds[vname]
        target = find_best_dtype(vname, var)
        if np.dtype(target) != var.dtype:
            if np.issubdtype(np.dtype(target), np.integer) and np.issubdtype(
                var.dtype, np.floating
            ):
                # NaN cannot be represented as an integer; replace before cast.
                # QC variables use 9 (CF "missing value"); other integer vars use 0.
                fill_val = 9 if (vname.endswith("_qc") or "flag" in vname) else 0
                safe_vals = np.where(np.isfinite(var.values), var.values, fill_val)
                updates[vname] = xr.Variable(
                    var.dims, safe_vals.astype(target), attrs=var.attrs
                )
            else:
                updates[vname] = xr.Variable(
                    var.dims, var.values.astype(target), attrs=var.attrs
                )
    if not updates:
        return ds
    return ds.assign(updates)
