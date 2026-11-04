"""Optimal storage-dtype selection for netCDF output.

Package-local data-saving utility — **not** part of the vendored report design
system (which is about producing identical *reports*, not identical *data*).  The
two functions are ported from oceanarray and may diverge as ctdcast's on-disk
conventions require; keep them in sync by choice, not by vendoring discipline.

:func:`find_best_dtype` picks a variable's storage dtype from its name and current
dtype; :func:`cast_output_dtypes` applies that across a whole dataset (coordinates
included) at the one write seam, shrinking file size (float64 → float32, int64 → int32,
QC → int8) without touching time, position or provenance.  :func:`widen_floats` is the
reverse for a stage that reads a file to compute on it: storage is float32, arithmetic is
float64.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

#: Position variables keep float64 by rule, whether they are coordinates or data.
_POSITION = frozenset({"latitude", "longitude", "lat", "lon"})


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

    - String / datetime / timedelta / object variables: unchanged.
    - ``time`` in name: unchanged (preserve datetime64 / float encoding).
    - ``latitude`` / ``longitude`` (and ``lat`` / ``lon``): ``float64``, as everywhere in
      the family; they compress to almost nothing, so float32 would save no space.
    - ``*_qc`` suffix or ``flag`` in name: ``int8``.
    - ``serial_number`` or ``serial``: ``int32``.
    - Integer input: downsize to ``int32`` if stored as ``int64``, else unchanged.
    - ``float64`` input: ``float32`` (about 10⁻⁷ relative, two to three orders of
      magnitude below the CTD sensors' resolution).
    - Anything else: unchanged.

    """
    input_dtype = da.dtype.type
    if da.dtype.kind in ("U", "S", "O", "M", "m"):
        return input_dtype
    if "time" in var_name.lower():
        return input_dtype
    if var_name in _POSITION:
        return np.float64 if da.dtype.kind == "f" else input_dtype
    if var_name.endswith("_qc") or "flag" in var_name:
        return np.int8
    if var_name in ("serial_number", "serial"):
        return np.int32
    if da.dtype.kind in ("i", "u") and da.dtype.itemsize == 8:
        return np.int32
    if input_dtype == np.float64:
        return np.float32
    return input_dtype


def cast_output_dtypes(ds: xr.Dataset) -> xr.Dataset:
    """Cast every variable in *ds* to its optimal storage dtype.

    Calls :func:`find_best_dtype` per variable, coordinates included, and rebuilds only
    those that change.  Attributes are preserved.  The input dataset is not modified.
    A float variable cast to an integer has NaN written as 9 (QARTOD missing) for a flag;
    ctdcast has no other float-to-integer case (serial numbers are text), and the ``0``
    fill kept for one is oceanarray's rule, copied unchanged.

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
    for vname in ds.variables:
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
    out = ds.copy()
    for vname, var in updates.items():
        if vname in out.coords:
            out = out.assign_coords({vname: var})
        else:
            out[vname] = var
    return out


def widen_floats(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with every float32 variable as float64, for computation.

    Files are stored as float32 (:func:`cast_output_dtypes`); a stage that reads one and
    computes on it (filters, recursive corrections, TEOS-10) does so in float64, so the
    float32 rounding happens once, at the write, and never compounds.

    Parameters
    ----------
    ds : xr.Dataset
        A dataset read from a ctdcast file.

    Returns
    -------
    xr.Dataset
        A new dataset; float32 variables (coordinates included) are float64.  The input is
        not modified.
    """
    narrow = [v for v, var in ds.variables.items() if var.dtype == np.float32]
    if not narrow:
        return ds
    out = ds.copy()
    for vname in narrow:
        var = ds.variables[vname]
        wide = xr.Variable(var.dims, var.values.astype(np.float64), attrs=var.attrs)
        if vname in out.coords:
            out = out.assign_coords({vname: wide})
        else:
            out[vname] = wide
    return out
