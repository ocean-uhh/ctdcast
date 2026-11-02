"""Products: files made from the stage-3 file by further steps, such as a 1 dbar downcast.

Sea-Bird processing usually runs one sequence of steps and then branches: the same corrected scans
become a 1 s time series, a 1 dbar downcast and a 1 dbar upcast, each with its own Loop Edit and
Bin Average.  ``data_processing.products`` lists these branches; each has a ``name`` and its own
``steps``, run on the stage-3 data (every scan, already through ``data_processing.steps``)::

    data_processing:
      steps: [...]                       # the stage-3 file
      products:
        - name: 1dbar_down
          steps:
            - split: down
            - loopedit: {min_velocity: 0.25}
            - binavg: {bin: decibars, size: 1}
        - name: 1sec
          steps:
            - binavg: {bin: seconds, size: 1}

A product may use any step; ``split`` and ``binavg`` are product-only, because the stage-3 file
keeps every scan, and ``binavg`` comes last.  Each product is written to
``<ctd_root>/products/<name>/<cast>_<name>.nc``; the stage-3 file is unchanged.

**Bin Average** (``binavg``) uses :func:`seabirdscientific.processing.bin_average`.  Bins are
``decibars`` (on ``pressure``), ``seconds`` (from the first scan) or ``scans``.  A value is left
out of its bin when its ``_qc`` is 4 (fail) or 9 (missing) — so Wild Edit's marks, stage 2's soak
and deck flags and a failed gross-range test leave out that one value, not its whole scan — and,
with ``exclude_flagged``, the scans Loop Edit marked are left out entirely, as SBE Data Processing
does.  Salinity is re-derived from the binned conductivity, temperature and pressure.  Bins of a
pressure product run down then up unless a ``split`` chose one leg.
"""

from __future__ import annotations

import re
import warnings

import numpy as np
import pandas as pd
import xarray as xr
from seabirdscientific import processing as sbs_processing

from ctdcast.analysis.derive import derive_salinity
from ctdcast.processors.corrections import _number, _version
from ctdcast.processors.history import append_history

#: Bin types, and the variable each bins on.
BIN_TYPES = {"decibars": "pressure", "seconds": "elapsed_seconds", "scans": "nScan"}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def check_split(params: object) -> str:
    """Return the leg a ``split`` step keeps: ``"down"`` or ``"up"``.

    Parameters
    ----------
    params : str or dict
        ``down`` / ``up``, or ``{leg: down}``.

    Returns
    -------
    str
        ``"down"`` or ``"up"``.

    Raises
    ------
    ValueError
        On anything else.
    """
    leg = params.get("leg") if isinstance(params, dict) else params
    if leg not in ("down", "up"):
        raise ValueError(f"split: expected down or up, got {params!r}")
    return leg


def check_binavg(params: object) -> dict:
    """Return the resolved parameters of a ``binavg`` step.

    Parameters
    ----------
    params : dict
        ``bin`` (``decibars``, ``seconds``, ``scans``), ``size``, and optionally
        ``exclude_flagged`` (default true), ``min_scans`` (1), ``max_scans``, ``skip_over`` (scans
        dropped at the start, 0), ``omit`` (at the end, 0), ``surface_bin``
        (``{min, max, value}`` or null) and ``interpolate`` (false).

    Returns
    -------
    dict
        The parameters with defaults filled in.

    Raises
    ------
    ValueError
        On an unknown key or a value of the wrong kind.
    """
    if not isinstance(params, dict):
        raise ValueError(f"binavg: expected a mapping, got {params!r}")
    unknown = set(params) - {
        "bin",
        "size",
        "exclude_flagged",
        "min_scans",
        "max_scans",
        "skip_over",
        "omit",
        "surface_bin",
        "interpolate",
    }
    if unknown:
        raise ValueError(f"binavg: unknown key(s) {sorted(unknown)}")
    kind = params.get("bin")
    if kind not in BIN_TYPES:
        raise ValueError(f"binavg.bin: expected one of {list(BIN_TYPES)}, got {kind!r}")
    size = _number(params.get("size"), "binavg.size")
    if size <= 0:
        raise ValueError(f"binavg.size: must be positive, got {size!r}")
    out = {"bin": kind, "size": size}
    for key, default in (
        ("min_scans", 1),
        ("max_scans", 2147483647),
        ("skip_over", 0),
        ("omit", 0),
    ):
        value = params.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"binavg.{key}: expected a whole number, got {value!r}")
        out[key] = value
    for key, default in (("exclude_flagged", True), ("interpolate", False)):
        value = params.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"binavg.{key}: expected true or false, got {value!r}")
        out[key] = value
    surface = params.get("surface_bin")
    if surface is not None:
        if not isinstance(surface, dict) or set(surface) - {"min", "max", "value"}:
            raise ValueError(
                f"binavg.surface_bin: expected {{min, max, value}} or null, got {surface!r}"
            )
        surface = {
            k: _number(surface.get(k, d), f"binavg.surface_bin.{k}")
            for k, d in (("min", 0.0), ("max", 5.0), ("value", 2.5))
        }
    out["surface_bin"] = surface
    return out


def check_products(products: object) -> list[dict]:
    """Return ``data_processing.products``, checked.

    Parameters
    ----------
    products : list or None
        Each entry ``{name, steps}``.

    Returns
    -------
    list of dict
        The products.

    Raises
    ------
    ValueError
        On a missing or unsafe name, a repeated name, a step not allowed here, ``binavg`` before
        the last step, or more than one ``split``.
    """
    from ctdcast.processors.steps import STEPS, iter_steps

    if products is None:
        return []
    if not isinstance(products, list):
        raise ValueError(f"data_processing.products: expected a list, got {products!r}")
    seen = set()
    for i, prod in enumerate(products):
        where = f"data_processing.products[{i}]"
        if not isinstance(prod, dict) or set(prod) - {"name", "steps"}:
            raise ValueError(f"{where}: expected {{name, steps}}, got {prod!r}")
        name = prod.get("name")
        if not isinstance(name, str) or not _SAFE_NAME.match(name):
            raise ValueError(
                f"{where}.name: letters, digits, '_', '-', '.' only, got {name!r}"
            )
        if name in seen:
            raise ValueError(f"{where}.name: {name!r} is used twice")
        seen.add(name)
        steps = iter_steps({"steps": prod.get("steps")})
        if not steps:
            raise ValueError(f"{where}: no steps")
        names = [n for n, _ in steps]
        if "binavg" in names[:-1]:
            raise ValueError(f"{where}: binavg must be the last step")
        if names.count("split") > 1:
            raise ValueError(f"{where}: split may appear once")
        for j, (step, params) in enumerate(steps):
            try:
                STEPS[step].check(params, None)
            except ValueError as exc:
                raise ValueError(f"{where}.steps[{j}] {step}: {exc}") from exc
    return products


def split_leg(ds: xr.Dataset, leg: str) -> xr.Dataset:
    """Return the downcast (to the deepest scan, inclusive) or the upcast (from it).

    Parameters
    ----------
    ds : xarray.Dataset
        A cast at its native scan rate, with ``pressure``.
    leg : str
        ``"down"`` or ``"up"``.

    Returns
    -------
    xarray.Dataset
        The scans of that leg; the dataset's ``product_leg`` attribute names it.
    """
    p = np.asarray(ds["pressure"].values, dtype=float)
    deepest = int(np.nanargmax(p))
    sel = slice(0, deepest + 1) if leg == "down" else slice(deepest, None)
    out = ds.isel(time=sel).copy()
    out.attrs = dict(ds.attrs)  # isel shares the attributes; the input must not change
    out.attrs["product_leg"] = leg
    append_history(
        out.attrs,
        f"split: {leg}cast, scans {sel.start or 0}–{(sel.stop or p.size) - 1} of {p.size}",
        stage="stage3",
    )
    return out


def _binnable(ds: xr.Dataset) -> list[str]:
    return [
        v
        for v, da in ds.data_vars.items()
        if da.dims == ("time",)
        and da.dtype.kind == "f"
        and not v.endswith("_qc")
        and not v.startswith("SENSOR_")
    ]


def bin_average(ds: xr.Dataset, params: dict) -> xr.Dataset:
    """Bin-average a cast with :func:`seabirdscientific.processing.bin_average`.

    Parameters
    ----------
    ds : xarray.Dataset
        A cast at its native scan rate (dim ``time``), possibly one leg from :func:`split_leg`.
    params : dict
        The ``binavg`` step's parameters (see :func:`check_binavg`).

    Returns
    -------
    xarray.Dataset
        Dim ``bin``: each binned variable, ``nbin`` (scans in the bin), and ``time`` (the bin's
        mean time).  Salinity is re-derived from the binned values.
    """
    p = check_binavg(params)
    leg = ds.attrs.get("product_leg")
    names = _binnable(ds)
    flag = sbs_processing.FLAG_VALUE
    columns: dict[str, np.ndarray] = {}
    for v in names:
        x = np.asarray(ds[v].values, dtype=float).copy()
        qc = f"{v}_qc"
        if qc in ds:
            x[np.isin(ds[qc].values, (4, 9))] = np.nan
        columns[v] = x
    t = pd.to_datetime(ds["time"].values)
    columns["elapsed_seconds"] = np.asarray((t - t[0]).total_seconds(), dtype=float)
    columns["flag"] = np.where(
        np.asarray(
            ds.get("loop_edit_flag", xr.zeros_like(ds["time"], dtype=np.int8)).values
        )
        == 1,
        flag,
        0.0,
    )
    # The bin variable itself is never left out: a scan without one has no bin.
    control = BIN_TYPES[p["bin"]]
    if control == "pressure":
        columns["pressure"] = np.asarray(ds["pressure"].values, dtype=float)
    keep = (
        np.isfinite(columns[control])
        if control in columns
        else np.ones(t.size, dtype=bool)
    )
    frame = xr.Dataset({k: ("scan", v[keep]) for k, v in columns.items()})
    if p["bin"] == "decibars":
        cast = {
            "down": sbs_processing.CastType.DOWNCAST,
            "up": sbs_processing.CastType.UPCAST,
        }.get(leg, sbs_processing.CastType.BOTH)
    else:
        cast = sbs_processing.CastType.NONE
    surface = p["surface_bin"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        binned = sbs_processing.bin_average(
            frame,
            control,
            p["size"],
            include_scan_count=True,
            min_scans=p["min_scans"],
            max_scans=p["max_scans"],
            exclude_bad_scans=p["exclude_flagged"],
            interpolate=p["interpolate"],
            cast_type=cast,
            trim_start=p["skip_over"],
            trim_end=p["omit"],
            include_surface_bin=surface is not None,
            surface_bin_min=(surface or {}).get("min", 0.0),
            surface_bin_max=(surface or {}).get("max", 5.0),
            surface_bin_value=(surface or {}).get("value", 2.5),
        )
    binned = (
        binned.rename({"bin_number": "bin"}) if "bin_number" in binned.dims else binned
    )
    out = xr.Dataset(attrs=dict(ds.attrs))
    for v in names:
        if v in binned:
            out[v] = ("bin", binned[v].values, dict(ds[v].attrs))
    out["nbin"] = (
        "bin",
        binned["nbin"].values.astype(np.int32),
        {"long_name": "Number of scans in the bin"},
    )
    out["time"] = (
        "bin",
        (t[0] + pd.to_timedelta(binned["elapsed_seconds"].values, unit="s")).values,
        {"long_name": "Mean time of the scans in the bin"},
    )
    for coord in ("latitude", "longitude"):
        if coord in ds.variables and ds[coord].ndim == 0:
            out[coord] = ds[coord]
    out = out.drop_vars(
        [v for v in out.data_vars if v.startswith(("ctd_salinity", "sbe_"))]
    )
    out = derive_salinity(out) if "pressure" in out else out
    desc = (
        f"bin {p['bin']} size {p['size']:g}, exclude_flagged="
        f"{'yes' if p['exclude_flagged'] else 'no'}, min_scans {p['min_scans']}, "
        f"skip_over {p['skip_over']}, omit {p['omit']}"
        + (f", surface bin {surface}" if surface else "")
        + (f", {leg}cast" if leg else "")
    )
    out.attrs["bin_average"] = desc
    out.attrs["bin_average_method"] = (
        f"seabirdscientific {_version()} processing.bin_average; a value with _qc 4 or 9 "
        "left out of its own bin"
    )
    append_history(
        out.attrs,
        f"binavg: {desc}; {out.sizes['bin']} bins; salinity re-derived",
        stage="stage3",
    )
    return out


def make_product(
    ds: xr.Dataset, product: dict, *, cast_number: int | None, cast_label: str
) -> xr.Dataset:
    """Run one product's steps on a finished stage-3 dataset.

    Parameters
    ----------
    ds : xarray.Dataset
        The stage-3 dataset (every scan).
    product : dict
        ``{name, steps}`` from ``data_processing.products``.
    cast_number : int or None
        For per-cast-range values in the product's steps.
    cast_label : str
        How the cast is named in warnings.

    Returns
    -------
    xarray.Dataset
        The product; ``product_name`` and ``data_processing_steps`` attributes say what it is.
    """
    from ctdcast.processors.steps import STEPS, StepContext, iter_steps

    ctx = StepContext(cast_number=cast_number, cast_label=cast_label)
    if "loop_edit_flag" in ds:
        ctx.excluded = ds["loop_edit_flag"].values.astype(bool)
    out = ds.copy()
    out.attrs["product_name"] = product["name"]
    ran = []
    for name, params in iter_steps({"steps": product["steps"]}):
        if name == "split":
            out = split_leg(out, check_split(params))
            ctx.excluded = (
                out["loop_edit_flag"].values.astype(bool)
                if "loop_edit_flag" in out
                else None
            )
        elif name == "binavg":
            out = bin_average(out, params)
        else:
            out = STEPS[name].apply(out, params, ctx)
        ran.append(name)
    out.attrs["product_steps"] = "; ".join(ran)
    return out
