"""Vendored netCDF inventory tables — pure builders over an open ``xr.Dataset``.

Each builder takes an **open** dataset (the caller opens and closes; never a path) and
returns ``(rows, source)``, where *source* is the ``"<module>.py:<function>"`` caption
string from :func:`figure_png.source_for` — so a report can show which function built a
table under the same toggle the per-figure caption uses.

Package-neutral by construction: this module names no package and knows nothing about
casts, dives or moorings.  It is vendored byte-identical across ctdcast, oceanarray and
glidertest (ctdcast ``main`` the source of truth; see ``MANIFEST.txt``), which the
import-purity test guards — it may import only the standard library, numpy, xarray and its
vendored siblings.

The per-package rules live in each package's owned ``reports/design.py`` and are passed in:
``is_qc(name, ds)`` (the QC-companion rule), ``is_sensor(name)``, the ``extras`` that add a
package's own globals to the canonical :data:`ATTR_GROUPS`, and (for sensors) a ``read_record``
reader.  Nothing package-specific is hard-coded here.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

import numpy as np

from .figure_png import source_for

if TYPE_CHECKING:
    import xarray as xr

#: Attribute names shown as their own table columns, so omitted from the per-variable
#: attribute disclosure list.
_COLUMNED = frozenset({"units", "standard_name", "long_name"})

#: Canonical global-attribute groups, holding **only** names a named convention defines
#: (ACDD 1.3, CF, and the mandatory globals OceanSITES / OG1 / CCHDO share) — each annotated
#: with its convention so the file is checkable against the published lists and never carries
#: an invented name.  A package adds its own vocabulary to these same titles through the
#: ``extras`` argument of :func:`globals_rows` (from its owned ``reports/design.py``); a
#: package may add a group but not rename one.  Whatever is named by neither falls into
#: :data:`OTHER_GROUP`.
ATTR_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Identity & discovery",
        (
            "title",  # ACDD
            "summary",  # ACDD
            "id",  # ACDD
            "naming_authority",  # ACDD
            "project",  # ACDD
            "program",  # ACDD
            "platform",  # OG1
            "platform_vocabulary",  # OG1
            "platform_code",  # OceanSITES
            "site_code",  # OceanSITES
            "references",  # CF / ACDD
            "standard_name_vocabulary",  # ACDD
        ),
    ),
    (
        "Spatiotemporal coverage",
        (
            "geospatial_lat_min",  # ACDD
            "geospatial_lat_max",  # ACDD
            "geospatial_lat_units",  # ACDD
            "geospatial_lon_min",  # ACDD
            "geospatial_lon_max",  # ACDD
            "geospatial_lon_units",  # ACDD
            "geospatial_vertical_min",  # ACDD
            "geospatial_vertical_max",  # ACDD
            "geospatial_vertical_units",  # ACDD
            "geospatial_vertical_positive",  # ACDD
            "time_coverage_start",  # ACDD
            "time_coverage_end",  # ACDD
            "time_coverage_duration",  # ACDD
            "time_coverage_resolution",  # ACDD
        ),
    ),
    (
        "People & institutions",
        (
            "creator_name",  # ACDD
            "creator_email",  # ACDD
            "creator_type",  # ACDD
            "creator_url",  # ACDD
            "creator_id",  # ACDD
            "contributor_name",  # ACDD
            "contributor_role",  # ACDD
            "contributing_institutions",  # OG1
            "institution",  # CF / ACDD
            "publisher_name",  # ACDD
            "publisher_email",  # ACDD
            "publisher_url",  # ACDD
        ),
    ),
    (
        "Rights & access",
        (
            "acknowledgement",  # ACDD
            "license",  # ACDD
            "citation",  # ACDD
        ),
    ),
    (
        "Provenance & processing",
        (
            "date_created",  # ACDD
            "date_modified",  # ACDD
            "source",  # CF / ACDD
            "history",  # CF / ACDD
            "comment",  # CF / ACDD
            "processing_level",  # ACDD / OceanSITES
            "data_mode",  # OceanSITES
            "QC_indicator",  # OceanSITES
            "Conventions",  # CF / ACDD
            "featureType",  # CF
            "cdm_data_type",  # ACDD
            "tracking_id",  # OceanSITES / ACDD
        ),
    ),
)

#: Title for attributes named by no group (never dropped).
OTHER_GROUP = "Other"


def _readable_dtype(dtype: np.dtype) -> str:
    """Return a readable dtype label: the precision for numbers, a word for the rest."""
    kind = dtype.kind
    if kind in "US":
        return "string"
    if kind == "O":
        return "object"
    if kind == "M":
        return "datetime"
    if kind == "m":
        return "timedelta"
    return str(dtype)  # float64 / float32 / int32 — keep the precision visible


def _fmt_minmax(v: float) -> str:
    """Format a numeric min/max compactly: ``0``, scientific for extremes, else 4 s.f."""
    if v == 0.0:
        return "0"
    if abs(v) < 1e-3 or abs(v) >= 1e5:
        return f"{v:.3g}"
    return f"{v:.4g}"


def _attr_type_name(value: Any) -> str:  # noqa: ANN401  # any global-attribute value
    """Return a readable type name for a global-attribute value.

    Read straight off the stored value's dtype through :func:`_readable_dtype`, the one
    type vocabulary shared with the variable tables — so text reads ``string`` (never
    ``str`` or a raw numpy dtype), the signal a reviewer uses to catch a position written
    ``"65 43.913"`` where a decimal degree was meant, or a count stored as a string.
    """
    arr = np.asarray(value)
    if arr.ndim:
        return f"{_readable_dtype(arr.dtype)}[{arr.size}]"
    return _readable_dtype(arr.dtype)


def _fmt_scalar(x: Any) -> str:  # noqa: ANN401  # any 0-d value the caller decided to show
    """Format a scalar value for the Value column, truncating long strings."""
    if isinstance(x, (float, np.floating)):
        return "—" if not np.isfinite(x) else _fmt_minmax(float(x))
    if isinstance(x, (int, np.integer)):
        return str(int(x))
    return str(x)[:120]


def _numeric_minmax(v: xr.DataArray) -> tuple[float | None, float | None, int]:
    """Return ``(min, max, n_valid)`` over the finite values, or ``(None, None, 0)``."""
    vals = np.asarray(v.values).ravel()
    finite = np.isfinite(vals)
    n_valid = int(finite.sum())
    if not n_valid:
        return None, None, 0
    good = vals[finite]
    return float(good.min()), float(good.max()), n_valid


def _datetime_minmax(v: xr.DataArray) -> tuple[str | None, str | None, int]:
    """Return ISO ``(min, max, n_valid)`` for a datetime array, NaT excluded."""
    vals = np.asarray(v.values).ravel()
    good = vals[~np.isnat(vals)]
    if not good.size:
        return None, None, 0
    lo = np.datetime64(good.min(), "s")
    hi = np.datetime64(good.max(), "s")
    return str(lo).replace("T", " "), str(hi).replace("T", " "), int(good.size)


def _scalar_value(v: xr.DataArray) -> str:
    """Return a 0-d value as a display string, CF-decoding an encoded time.

    A numeric scalar carrying ``units`` like ``"seconds since ..."`` is decoded through
    xarray so an epoch reads as a date, never a raw count.  Everything else is formatted
    plainly.
    """
    if v.dtype.kind == "M":
        lo, _hi, n = _datetime_minmax(v)
        return lo if n else "—"
    item = v.values.item() if v.size else None
    if item is None:
        return "—"
    units = str(v.attrs.get("units", ""))
    if (
        isinstance(item, (int, float, np.number))
        and np.isfinite(item)
        and "since" in units
    ):
        try:
            import xarray.coding.times as _xtimes

            decoded = _xtimes.decode_cf_datetime(
                np.asarray(item), units, v.attrs.get("calendar", "standard")
            )
            return str(np.datetime64(decoded.ravel()[0], "s")).replace("T", " ")
        except Exception:  # noqa: BLE001  # undecodable → show the raw value, never crash
            pass
    return _fmt_scalar(item)


def _attr_disclosure(v: xr.DataArray) -> dict[str, str]:
    """Return the variable's attributes minus the ones shown as columns, stringified."""
    return {
        str(k): _fmt_scalar(val)
        for k, val in v.attrs.items()
        if str(k) not in _COLUMNED
    }


def _row_base(ds: xr.Dataset, name: str) -> dict[str, Any]:
    """Return the fields shared by coordinate, variable and scalar rows."""
    v = ds[name]
    return {
        "name": name,
        "dtype": _readable_dtype(v.dtype),
        "units": str(v.attrs.get("units", "")),
        "standard_name": str(v.attrs.get("standard_name", "")),
        "long_name": str(v.attrs.get("long_name", "")),
        # Float is the kind CF expects a unit for; an integer flag/index/channel or a string
        # legitimately has none, so only a float missing its units is a defect (units_cell).
        "is_numeric": v.dtype.kind == "f",
        "attrs": _attr_disclosure(v),
    }


def _value_row(ds: xr.Dataset, name: str) -> dict[str, Any]:
    """Return a row with the full min/max/valid block for a dimensioned variable/coord."""
    v = ds[name]
    row = _row_base(ds, name)
    n = int(np.prod(v.shape)) if v.shape else 1
    v_min_raw: float | None = None
    v_min = v_max = "—"
    n_valid = n
    if v.dtype.kind == "M":
        lo, hi, n_valid = _datetime_minmax(v)
        v_min, v_max = (lo or "—"), (hi or "—")
    elif v.dtype.kind in "fiu":
        lo_f, hi_f, n_valid = _numeric_minmax(v)
        if lo_f is not None:
            v_min_raw = lo_f
            v_min, v_max = _fmt_minmax(lo_f), _fmt_minmax(hi_f)  # type: ignore[arg-type]
    row.update(
        n=n,
        n_valid=n_valid,
        valid_pct=round(100.0 * n_valid / n, 1) if n else 0.0,
        v_min=v_min,
        v_max=v_max,
        v_min_raw=v_min_raw,
    )
    return row


def _qc_parent(name: str) -> str:
    """Return a QC companion's parent variable name (a trailing ``_qc`` removed).

    Case-insensitive so it serves both conventions in the family — ``_qc`` (ctdcast) and
    ``_QC`` (OceanSITES / OG1).
    """
    return re.sub(r"_qc$", "", name, flags=re.IGNORECASE)


def coords_rows(ds: xr.Dataset) -> tuple[list[dict[str, Any]], str]:
    """Return ``(rows, source)`` for the coordinate variables.

    Parameters
    ----------
    ds : xarray.Dataset
        An open dataset.

    Returns
    -------
    rows : list of dict
        One :func:`_value_row` per coordinate (sorted by name), each carrying an extra
        ``length`` field (the coordinate's size).
    source : str
        The caption string for this builder.
    """
    rows = []
    for name in sorted(ds.coords):
        row = _value_row(ds, name)
        row["length"] = int(ds[name].size)
        rows.append(row)
    return rows, source_for(coords_rows)


def variables_rows(
    ds: xr.Dataset,
    *,
    is_qc: Callable[[str, xr.Dataset], bool],
    is_sensor: Callable[[str], bool] | None = None,
    group_by_dims: bool = True,
) -> tuple[list[tuple[str, list[dict[str, Any]]]], str]:
    """Return ``([(group_title, rows)], source)`` for the dimensioned data variables.

    QC companion variables (``is_qc`` true) are **not** listed; instead their parent row
    carries ``has_qc=True`` so the template can show an inline ``(_QC)`` marker.  Sensor
    variables (``is_sensor`` true) are excluded — the sensor catalog is its own table.

    Parameters
    ----------
    ds : xarray.Dataset
        An open dataset.
    is_qc : callable
        ``is_qc(name, ds) -> bool`` — the package's QC-companion rule.
    is_sensor : callable, optional
        ``is_sensor(name) -> bool`` — excludes sensor-catalog variables.
    group_by_dims : bool, default True
        Group variables by their dimension tuple, one group per tuple; the per-group sample
        count goes in the title.  When ``False`` a single ``""``-titled group holds all rows.

    Returns
    -------
    groups : list of (str, list of dict)
        ``(group_title, rows)`` in order of first appearance; ``group_title`` reads e.g.
        ``"N_PROF × pressure (236 × 2,001 = 472,236 samples)"``.
    source : str
        The caption string for this builder.
    """
    sensor = is_sensor or (lambda _n: False)
    qc_names = {n for n in ds.data_vars if is_qc(n, ds)}
    parents_with_qc = {_qc_parent(n) for n in qc_names}

    candidates = [
        n
        for n in sorted(ds.data_vars)
        if ds[n].ndim >= 1 and n not in qc_names and not sensor(n)
    ]

    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    order: list[tuple[str, ...]] = []
    for name in candidates:
        dims = tuple(str(d) for d in ds[name].dims) if group_by_dims else ()
        if dims not in groups:
            groups[dims] = []
            order.append(dims)
        row = _value_row(ds, name)
        row["has_qc"] = name in parents_with_qc
        groups[dims].append(row)

    out = [(_dims_heading(ds, dims), groups[dims]) for dims in order]
    return out, source_for(variables_rows)


def _dims_heading(ds: xr.Dataset, dims: tuple[str, ...]) -> str:
    """Return a group title with the per-group sample count, thousands-separated."""
    if not dims:
        return ""
    sizes = [int(ds.sizes[d]) for d in dims]
    n = int(np.prod(sizes)) if sizes else 0
    label = " × ".join(dims)
    if len(dims) > 1:
        factors = " × ".join(f"{s:,}" for s in sizes)
        return f"{label} ({factors} = {n:,} samples)"
    return f"{label} ({n:,} samples)"


def scalars_rows(
    ds: xr.Dataset, *, exclude: Callable[[str], bool] | None = None
) -> tuple[list[dict[str, Any]], str]:
    """Return ``(rows, source)`` for the 0-d (scalar) variables.

    Parameters
    ----------
    ds : xarray.Dataset
        An open dataset.
    exclude : callable, optional
        ``exclude(name) -> bool`` — drop a scalar from the table (ctdcast excludes
        ``SENSOR_*``, which has its own catalog).

    Returns
    -------
    rows : list of dict
        One row per scalar (sorted by name), each a :func:`_row_base` plus a ``value``
        field (CF-decoded when it is an encoded time).
    source : str
        The caption string for this builder.
    """
    drop = exclude or (lambda _n: False)
    rows = []
    for name in sorted(ds.data_vars):
        if ds[name].ndim != 0 or drop(name):
            continue
        row = _row_base(ds, name)
        row["value"] = _scalar_value(ds[name])
        rows.append(row)
    return rows, source_for(scalars_rows)


def _merge_groups(
    groups: tuple[tuple[str, tuple[str, ...]], ...],
    extras: dict[str, Iterable[str]] | None,
) -> list[tuple[str, tuple[str, ...]]]:
    """Return *groups* with each title's ``extras`` names appended (order preserved)."""
    extra = {k: tuple(v) for k, v in (extras or {}).items()}
    merged = [(title, names + extra.get(title, ())) for title, names in groups]
    # A title that appears only in extras (a package-added group) is kept, trailing.
    seen = {title for title, _ in groups}
    merged += [(t, tuple(v)) for t, v in extra.items() if t not in seen]
    return merged


def globals_rows(
    ds: xr.Dataset,
    *,
    groups: tuple[tuple[str, tuple[str, ...]], ...] = ATTR_GROUPS,
    extras: dict[str, Iterable[str]] | None = None,
) -> tuple[list[tuple[str, list[tuple[str, str]]]], str]:
    """Return ``([(group_title, [(attr, value), ...])], source)`` for the global attributes.

    Groups appear in *groups* order with the package's *extras* merged into each title;
    within a group the attributes keep the file's own order so the page can be checked
    against the spec.  Attributes named by no group fall into a trailing
    :data:`OTHER_GROUP`.  Empty groups are omitted.

    Parameters
    ----------
    ds : xarray.Dataset
        An open dataset.
    groups : tuple, default :data:`ATTR_GROUPS`
        The canonical group definitions.
    extras : dict, optional
        ``{group_title: (attr_name, ...)}`` — a package's own global-attribute names added
        to the canonical groups (from its owned ``reports/design.py``).

    Returns
    -------
    grouped : list of (str, list of (str, str, str))
        ``(group_title, rows)`` with each row an ``(attribute, type, value)`` triple; the
        *type* is the stored value's type name (:func:`_attr_type_name`).
    source : str
        The caption string for this builder.
    """
    merged = _merge_groups(groups, extras)
    group_of = {name: title for title, names in merged for name in names}
    buckets: dict[str, list[tuple[str, str, str]]] = {title: [] for title, _ in merged}
    buckets[OTHER_GROUP] = []
    for key, value in ds.attrs.items():
        buckets.setdefault(group_of.get(str(key), OTHER_GROUP), []).append(
            (str(key), _attr_type_name(value), str(value))
        )
    titles = [title for title, _ in merged] + [OTHER_GROUP]
    return [(t, buckets[t]) for t in titles if buckets[t]], source_for(globals_rows)


def summary_counts(
    ds: xr.Dataset,
    *,
    is_qc: Callable[[str, xr.Dataset], bool],
    is_sensor: Callable[[str], bool] | None = None,
    exclude: Callable[[str], bool] | None = None,
) -> dict[str, int]:
    """Return the one-line inventory summary counts.

    Parameters
    ----------
    ds : xarray.Dataset
        An open dataset.
    is_qc : callable
        ``is_qc(name, ds) -> bool``.
    is_sensor : callable, optional
        ``is_sensor(name) -> bool`` — the sensor-catalog predicate, counted as ``sensors``.
    exclude : callable, optional
        ``exclude(name) -> bool`` — a package's data variables shown in their own tables, not
        in the main variable table (e.g. ctdcast's per-profile linkage/channel).  Counted as
        ``excluded`` and removed from ``data_variables`` so that count stays honest.

    Returns
    -------
    dict
        ``{"data_variables", "sensors", "qc_companions", "coordinates", "excluded"}``.
    """
    sensor = is_sensor or (lambda _n: False)
    excl = exclude or (lambda _n: False)
    sensors = [n for n in ds.data_vars if sensor(n)]
    qc = [n for n in ds.data_vars if is_qc(n, ds)]
    accounted = set(sensors) | set(qc)
    # Excluded: named by the package's own predicate but not already a sensor or QC companion.
    excluded = [n for n in ds.data_vars if excl(n) and n not in accounted]
    data = [n for n in ds.data_vars if n not in accounted | set(excluded)]
    return {
        "data_variables": len(data),
        "sensors": len(sensors),
        "qc_companions": len(qc),
        "coordinates": len(ds.coords),
        "excluded": len(excluded),
    }


#: Attribute names the default OG1 sensor reader consumes into columns.
_SENSOR_COLUMNED = frozenset(
    {
        "sensor_model",
        "sensor_serial_number",
        "serial_number",
        "sensor_calibration_date",
        "calibration_date",
        "model_source",
        "standard_name",
        "long_name",
    }
)


def _sensor_field(attrs: dict[str, Any], primary: str, legacy: str) -> tuple[str, bool]:
    """Return ``(value, used_legacy)`` preferring *primary*, falling back to *legacy*."""
    if attrs.get(primary) not in (None, ""):
        return str(attrs[primary]), False
    if attrs.get(legacy) not in (None, ""):
        return str(attrs[legacy]), True
    return "", False


def _og1_sensor_record(ds: xr.Dataset, name: str) -> dict[str, Any]:
    """Read one ``SENSOR_*`` variable into a catalog row (OG1 attribute names)."""
    a = dict(ds[name].attrs)
    serial, serial_legacy = _sensor_field(a, "sensor_serial_number", "serial_number")
    cal, cal_legacy = _sensor_field(a, "sensor_calibration_date", "calibration_date")
    return {
        "name": name,
        "model": str(a.get("sensor_model", "")),
        "model_assumed": str(a.get("model_source", "")) == "assumed",
        "serial": serial,
        "serial_legacy": serial_legacy,
        "calibration": cal,
        "calibration_legacy": cal_legacy,
        "standard_name": str(a.get("standard_name", "")),
        "long_name": str(a.get("long_name", "")),
        "attrs": {
            str(k): _fmt_scalar(v)
            for k, v in a.items()
            if str(k) not in _SENSOR_COLUMNED
        },
    }


def sensor_rows(
    ds: xr.Dataset,
    *,
    names: Iterable[str] | None = None,
    read_record: Callable[[xr.Dataset, str], dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Return ``(rows, source)`` for the sensor catalog.

    Parameters
    ----------
    ds : xarray.Dataset
        An open dataset.
    names : iterable of str, optional
        The sensor variable names; defaults to the ``SENSOR_*`` variables (the OG1 / ctdcast
        convention), sorted.
    read_record : callable, optional
        ``read_record(ds, name) -> dict`` building one catalog row; defaults to the OG1
        ``SENSOR_*`` reader (model, serial, calibration date, with legacy fallbacks, an
        ``model_assumed`` flag, and the remaining attributes).  oceanarray passes its own.

    Returns
    -------
    rows : list of dict
        One catalog row per sensor.
    source : str
        The caption string for this builder.
    """
    reader = read_record or _og1_sensor_record
    if names is None:
        names = sorted(n for n in ds.data_vars if str(n).startswith("SENSOR_"))
    return [reader(ds, n) for n in names], source_for(sensor_rows)
