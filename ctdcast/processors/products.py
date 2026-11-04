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
from collections.abc import Callable

import numpy as np
import pandas as pd
import xarray as xr
from seabirdscientific import processing as sbs_processing

from ctdcast.analysis.derive import derive_salinity
from ctdcast.processors.corrections import _number, _version
from ctdcast.processors.history import append_history
from ctdcast.processors.qc import usable_pressure

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
    if not out["exclude_flagged"]:
        raise ValueError(
            "binavg.exclude_flagged: false is not supported: a value flagged fail (4) or "
            "missing (9), Loop Edit's scans among them, never enters a ctdcast bin, as in "
            "profiles.nc; remove the key"
        )
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


def _leg_slice(ds: xr.Dataset, leg: str) -> slice:
    """Return the scans of one leg: to the deepest scan (inclusive), or from it."""
    # A scan with a failed pressure has no depth: it cannot be the bottom of the cast.
    deepest = int(np.nanargmax(usable_pressure(ds)))
    return slice(0, deepest + 1) if leg == "down" else slice(deepest, None)


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
    sel = _leg_slice(ds, leg)
    p = ds["pressure"].values
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
    bad_of: dict[str, np.ndarray] = {}
    for v in names:
        x = np.asarray(ds[v].values, dtype=float).copy()
        qc = f"{v}_qc"
        if qc in ds:
            bad_of[v] = np.isin(ds[qc].values, (4, 9))
            x[bad_of[v]] = np.nan
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
    # The bin variable's own values are never left out singly: a scan without one has no bin.
    control = BIN_TYPES[p["bin"]]
    if control == "pressure":
        # A scan whose pressure failed has no bin: it is left out whole.
        columns["pressure"] = usable_pressure(ds)
    keep = (
        np.isfinite(columns[control])
        if control in columns
        else np.ones(t.size, dtype=bool)
    )
    if p["bin"] == "decibars":
        cast = {
            "down": sbs_processing.CastType.DOWNCAST,
            "up": sbs_processing.CastType.UPCAST,
        }.get(leg, sbs_processing.CastType.BOTH)
    else:
        cast = sbs_processing.CastType.NONE
    surface = p["surface_bin"]

    def run(cols: dict[str, np.ndarray]) -> xr.Dataset:
        frame = xr.Dataset({k: ("scan", v[keep]) for k, v in cols.items()})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return sbs_processing.bin_average(
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

    binned = run(columns)
    partial, by_var = _sea_bird_would_drop(
        run, columns, bad_of, int(binned["nbin"].sum()), skip=control
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
    out.attrs["bin_average_partly_flagged_scans"] = int(partial)
    out.attrs["bin_average_partly_flagged"] = _partly_flagged_text(partial, by_var)
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


def _sea_bird_would_drop(
    run: Callable[[dict[str, np.ndarray]], xr.Dataset],
    columns: dict[str, np.ndarray],
    bad_of: dict[str, np.ndarray],
    binned_scans: int,
    *,
    skip: str,
) -> tuple[int, dict[str, int]]:
    """Count the scans seabirdscientific's ``bin_average`` would drop that ctdcast keeps in part.

    seabirdscientific drops the whole scan when any value in it holds its bad flag; ctdcast
    leaves out only that value.  The count is seabirdscientific's own answer: the same binning
    run again with the per-value flags written as its bad flag, so every rule of the step
    (trims, the leg, ``min_scans``, ``max_scans``) applies to both.  A scan flagged in every
    variable that has a ``_qc``, pressure aside (the stage-2 soak and deck) is a whole-scan flag, not a
    per-value one, and is left out of the comparison; so are salinity (re-derived from the
    binned values) and the bin variable (*skip*).  Also returned: what each variable's flags
    alone would cost.
    """
    # Stage 2 never flags pressure (it places the scan), so a whole-scan flag is one on every
    # other variable that has a _qc.
    judged = [m for v, m in bad_of.items() if v != "pressure"]
    if not judged:
        return 0, {}
    whole = np.logical_and.reduce(judged)
    per_value = {
        v: m & ~whole
        for v, m in bad_of.items()
        if v != skip and not v.startswith("ctd_salinity") and (m & ~whole).any()
    }
    if not per_value:
        return 0, {}

    def lost(marks: dict[str, np.ndarray]) -> int:
        cols = dict(columns)
        for v, m in marks.items():
            x = cols[v].copy()
            x[m] = sbs_processing.FLAG_VALUE
            cols[v] = x
        try:
            return binned_scans - int(run(cols)["nbin"].sum())
        except (ValueError, KeyError, IndexError):  # every scan dropped: no bins at all
            return binned_scans

    total = lost(per_value)
    by_var = {v: lost({v: m}) for v, m in per_value.items()} if total else {}
    return total, {v: n for v, n in by_var.items() if n}


def _partly_flagged_text(n: int, by_var: dict[str, int]) -> str:
    """Return the one-line record of :func:`_sea_bird_would_drop`, for the product attributes."""
    if not n:
        return (
            "none: no scan with a value flagged fail or missing would be dropped whole"
        )
    parts = ", ".join(
        f"{v} {k}" for v, k in sorted(by_var.items(), key=lambda t: -t[1])
    )
    return (
        f"{n} scan(s) kept their other values here but would be dropped whole if these "
        f"flags were treated as seabirdscientific's bin_average treats its bad flag (each "
        f"variable's flags alone: {parts}); ctdcast left out only the flagged values."
    )


def make_product(
    ds: xr.Dataset,
    product: dict,
    *,
    cast_number: int | None,
    cast_label: str,
    marked: dict[str, np.ndarray] | None = None,
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
    marked : dict of str to numpy.ndarray, optional
        ``{variable: mask}`` of the values stage 3's Wild Edit marked, which a filter in the
        product steps over as at stage 3.  Without it (a product made later from the file),
        every value flagged fail or missing outside Loop Edit's scans is stepped over: the file
        keeps the flag, not which step raised it.

    Returns
    -------
    xarray.Dataset
        The product; ``product_name`` and ``data_processing_steps`` attributes say what it is.
    """
    from ctdcast.processors.steps import STEPS, StepContext, iter_steps

    ctx = StepContext(cast_number=cast_number, cast_label=cast_label)
    if "loop_edit_flag" in ds:
        ctx.excluded = ds["loop_edit_flag"].values.astype(bool)
    # A filter here steps over what stage 3's Wild Edit marked, as it does at stage 3.
    ctx.marked = (
        {k: np.asarray(v, dtype=bool) for k, v in marked.items()}
        if marked is not None
        else _failed_values(ds, ctx.excluded)
    )
    out = ds.copy()
    out.attrs["product_name"] = product["name"]
    ran = []
    for name, params in iter_steps({"steps": product["steps"]}):
        if name == "split":
            sl = _leg_slice(out, check_split(params))
            ctx.marked = {k: v[sl] for k, v in ctx.marked.items()}
            out = split_leg(out, check_split(params))
            ctx.excluded = (
                out["loop_edit_flag"].values.astype(bool)
                if "loop_edit_flag" in out
                else None
            )
        elif name == "binavg":
            out = bin_average(out, params)
            n = int(out.attrs.get("bin_average_partly_flagged_scans", 0))
            if n:
                warnings.warn(
                    f"cast {cast_label}, product {product['name']}: "
                    + out.attrs["bin_average_partly_flagged"],
                    stacklevel=2,
                )
        else:
            out = STEPS[name].apply(out, params, ctx)
        ran.append(name)
    if "binavg" not in ran and any(
        v.startswith(("conductivity", "ctd_temperature")) or v == "pressure"
        for v in ctx.changed
    ):
        # Salinity is always derived: re-derived whenever a step changed C, T or P.
        out = derive_salinity(out)
        append_history(out.attrs, "salinity re-derived", stage="stage3")
    out.attrs["product_steps"] = "; ".join(ran)
    return out


def _failed_values(
    ds: xr.Dataset, excluded: np.ndarray | None
) -> dict[str, np.ndarray]:
    """Return ``{variable: mask}`` of each variable's fail (4) and missing (9) values, Loop Edit's scans out."""
    keep_out = (
        np.asarray(excluded, dtype=bool)
        if excluded is not None
        else np.zeros(ds.sizes["time"], dtype=bool)
    )
    return {
        v[: -len("_qc")]: np.isin(ds[v].values, (4, 9)) & ~keep_out
        for v in ds.data_vars
        if v.endswith("_qc") and v[: -len("_qc")] in ds and ds[v].dims == ("time",)
    }
