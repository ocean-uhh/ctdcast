"""Stage-3 filters at the native scan rate: Sea-Bird's Filter and Window Filter.

- **Filter** (``filter`` step): Sea-Bird's low-pass filter, a single-pole filter run forward and
  backward so it adds no lag, with one time constant (SBE Data Processing manual, Filter).  Sea-Bird's
  module applies two time constants, A and B, to two lists of variables in one run; in
  ``data_processing.steps`` that is two ``filter`` entries.  Applied with
  :func:`seabirdscientific.processing.low_pass_filter`.
- **Window Filter** (``window_filter`` step): a boxcar, cosine, triangle, gaussian or median window
  of ``width`` scans, with :func:`seabirdscientific.processing.window_filter`.

Both change values; the parameters are recorded on each variable (``filters``, one entry per
filter, in order) and in ``history``.  Values an earlier Wild Edit marked are left out of the
filter, as SBE Data Processing leaves out its bad flags: the filter runs across them on values
interpolated from their neighbours, and the marked values themselves are kept as they were.  On
OdB cast 050, Filter on ``.hex`` data matches the cruise's CNV to its rounding for pressure
(0.15 s) and fluorescence (0.03 s).

Configuration, steps in ``data_processing.steps``::

    - filter: {time_constant: 0.15, variables: [pressure]}
    - window_filter: {type: median, width: 10, variables: [pressure, ctd_fluor],
                      exclude_flagged: true}     # gaussian also takes half_width, offset
"""

from __future__ import annotations

import numpy as np
import xarray as xr
from seabirdscientific import processing as sbs_processing

from ctdcast.processors.corrections import (
    _number,
    _version,
    native_interval,
)
from ctdcast.processors.history import append_history

WINDOW_TYPES = ("boxcar", "cosine", "triangle", "gaussian", "median")


def _variables(params: dict, step: str) -> list[str]:
    variables = params.get("variables")
    if (
        not variables
        or isinstance(variables, str)
        or not all(isinstance(v, str) for v in variables)
    ):
        raise ValueError(
            f"{step}.variables: expected a list of variable names, got {variables!r}"
        )
    return list(variables)


def check_filter(params: object) -> tuple[float, list[str]]:
    """Return ``(time_constant, variables)`` from a ``filter`` step's parameters.

    Parameters
    ----------
    params : dict
        The step's parameters.

    Returns
    -------
    tuple of (float, list of str)
        The time constant in seconds and the variables to filter.

    Raises
    ------
    ValueError
        On an unknown key, a missing or non-positive time constant, or no variables.
    """
    if not isinstance(params, dict):
        raise ValueError(f"filter: expected a mapping, got {params!r}")
    unknown = set(params) - {"time_constant", "variables"}
    if unknown:
        raise ValueError(f"filter: unknown key(s) {sorted(unknown)}")
    if "time_constant" not in params:
        raise ValueError("filter: needs time_constant (seconds)")
    tc = _number(params["time_constant"], "filter.time_constant")
    if tc <= 0:
        raise ValueError(f"filter.time_constant: must be positive, got {tc!r}")
    return tc, _variables(params, "filter")


def check_window_filter(params: object) -> dict:
    """Return the resolved parameters of a ``window_filter`` step.

    Parameters
    ----------
    params : dict
        The step's parameters: ``type``, ``width`` (scans), ``variables``, and optionally
        ``exclude_flagged`` and, for a gaussian, ``half_width`` and ``offset`` (seconds).

    Returns
    -------
    dict
        ``type``, ``width``, ``variables``, ``exclude_flagged``, ``half_width``, ``offset``.

    Raises
    ------
    ValueError
        On an unknown key or type, or a width under 2.
    """
    if not isinstance(params, dict):
        raise ValueError(f"window_filter: expected a mapping, got {params!r}")
    unknown = set(params) - {
        "type",
        "width",
        "variables",
        "exclude_flagged",
        "half_width",
        "offset",
    }
    if unknown:
        raise ValueError(f"window_filter: unknown key(s) {sorted(unknown)}")
    kind = params.get("type")
    if kind not in WINDOW_TYPES:
        raise ValueError(
            f"window_filter.type: expected one of {list(WINDOW_TYPES)}, got {kind!r}"
        )
    width = params.get("width")
    if isinstance(width, bool) or not isinstance(width, int) or width < 2:
        raise ValueError(
            f"window_filter.width: expected a whole number of scans, at least 2, got {width!r}"
        )
    excl = params.get("exclude_flagged", True)
    if not isinstance(excl, bool):
        raise ValueError(
            f"window_filter.exclude_flagged: expected true or false, got {excl!r}"
        )
    return {
        "type": kind,
        "width": width,
        "variables": _variables(params, "window_filter"),
        "exclude_flagged": excl,
        "half_width": _number(
            params.get("half_width", 1.0), "window_filter.half_width"
        ),
        "offset": _number(params.get("offset", 0.0), "window_filter.offset"),
    }


def _bridged(x: np.ndarray, gaps: np.ndarray) -> np.ndarray:
    """*x* with the scans in *gaps* (and NaN) replaced by linear interpolation from neighbours."""
    bad = gaps | ~np.isfinite(x)
    if not bad.any() or bad.all():
        return x
    idx = np.arange(x.size)
    out = x.copy()
    out[bad] = np.interp(idx[bad], idx[~bad], x[~bad])
    return out


def _record(ds: xr.Dataset, var: str, text: str, method: str) -> None:
    attrs = dict(ds[var].attrs)
    previous = str(attrs.get("filters", ""))
    attrs["filters"] = f"{previous}; {text}" if previous else text
    attrs["filters_method"] = method
    ds[var].attrs = attrs


def apply_filter(
    ds: xr.Dataset,
    params: dict,
    *,
    marked: dict[str, np.ndarray] | None = None,
) -> tuple[xr.Dataset, list[str]]:
    """Apply one ``filter`` step: Sea-Bird's low-pass filter, forward and backward.

    Parameters
    ----------
    ds : xarray.Dataset
        A stage-2 dataset at its native scan rate.
    params : dict
        The step's ``time_constant`` and ``variables``.
    marked : dict of str to numpy.ndarray, optional
        ``{variable: mask}`` of values an earlier Wild Edit marked; filtered across, kept.

    Returns
    -------
    tuple of (xarray.Dataset, list of str)
        A new dataset (the input is not mutated) and the variables filtered.

    Raises
    ------
    ValueError
        On malformed parameters, or a dataset not at its native scan rate.
    """
    tc, variables = check_filter(params)
    interval, reason = native_interval(ds)
    if interval is None:
        raise ValueError(f"filter: {reason}")
    ds = ds.copy()
    method = f"seabirdscientific {_version()} processing.low_pass_filter"
    done, absent = [], []
    for var in variables:
        if var not in ds.data_vars or ds[var].dims != ("time",):
            absent.append(var)
            continue
        x = ds[var].values.astype(float)
        keep = (marked or {}).get(var, np.zeros(x.size, dtype=bool)) | ~np.isfinite(x)
        y = sbs_processing.low_pass_filter(_bridged(x, keep), tc, interval)
        y[keep] = x[keep]
        ds[var] = (ds[var].dims, y.astype(ds[var].dtype, copy=False), ds[var].attrs)
        _record(ds, var, f"low-pass {tc:g} s", method)
        done.append(var)
    note = f"filter: low-pass time constant {tc:g} s on {', '.join(done) or 'nothing'}"
    if absent:
        note += f"; not in this cast: {', '.join(absent)}"
    append_history(ds.attrs, note, stage="stage3")
    return ds, done


def apply_window_filter(
    ds: xr.Dataset,
    params: dict,
    *,
    marked: dict[str, np.ndarray] | None = None,
    excluded: np.ndarray | None = None,
) -> tuple[xr.Dataset, list[str]]:
    """Apply one ``window_filter`` step.

    Parameters
    ----------
    ds : xarray.Dataset
        A stage-2 dataset at its native scan rate.
    params : dict
        The step's parameters (see :func:`check_window_filter`).
    marked : dict of str to numpy.ndarray, optional
        ``{variable: mask}`` of values an earlier Wild Edit marked; left out of the window.
    excluded : numpy.ndarray, optional
        Scans an earlier Loop Edit marked; left out of the window when ``exclude_flagged``.

    Returns
    -------
    tuple of (xarray.Dataset, list of str)
        A new dataset (the input is not mutated) and the variables filtered.

    Raises
    ------
    ValueError
        On malformed parameters, or a dataset not at its native scan rate.
    """
    p = check_window_filter(params)
    interval, reason = native_interval(ds)
    if interval is None:
        raise ValueError(f"window_filter: {reason}")
    ds = ds.copy()
    method = f"seabirdscientific {_version()} processing.window_filter"
    flag = sbs_processing.FLAG_VALUE
    done, absent = [], []
    for var in p["variables"]:
        if var not in ds.data_vars or ds[var].dims != ("time",):
            absent.append(var)
            continue
        x = ds[var].values.astype(float)
        keep = (marked or {}).get(var, np.zeros(x.size, dtype=bool)) | ~np.isfinite(x)
        data = np.where(keep, flag, x)
        flags = np.zeros(x.size)
        if excluded is not None and p["exclude_flagged"]:
            flags[np.asarray(excluded, dtype=bool)] = flag
        y = np.asarray(
            sbs_processing.window_filter(
                data,
                flags,
                p["type"],
                p["width"],
                interval,
                half_width=p["half_width"],
                offset=p["offset"],
                exclude_flags=p["exclude_flagged"],
            ),
            dtype=float,
        )
        y[keep] = x[keep]
        ds[var] = (ds[var].dims, y.astype(ds[var].dtype, copy=False), ds[var].attrs)
        text = f"window {p['type']} {p['width']} scans"
        if p["type"] == "gaussian":
            text += f" (half_width {p['half_width']:g} s, offset {p['offset']:g} s)"
        _record(ds, var, text, method)
        done.append(var)
    note = f"window_filter: {p['type']} {p['width']} scans on {', '.join(done) or 'nothing'}"
    if absent:
        note += f"; not in this cast: {', '.join(absent)}"
    append_history(ds.attrs, note, stage="stage3")
    return ds, done
