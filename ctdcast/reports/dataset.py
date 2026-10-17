"""Tier-2: a per-file netCDF *data inventory* page.

Unlike the figure report pages, this one answers "what is actually in this file?"
for a developer or data reviewer: every coordinate and variable with its dtype,
units, CF names, value range and validity, the sensor catalog, and the global
attributes grouped into their canonical sections.  One page per file, generated
for ``profiles.nc``, a per-cast cast NC, or any other ctdcast product.

The tables themselves are built by the package-neutral
:mod:`ctdcast.reports._vendored.nc_tables` builders (coordinates, variables grouped
by dimension, scalars, the sensor catalog, grouped globals) and rendered by the
vendored ``_nc_tables.html`` macros.  What stays owned here is ctdcast-specific: the
QC-exclusion and variable-renaming tables, the sensor linkage/channel tables, and the
coverage check that recomputes ``geospatial_*`` / ``time_coverage_*`` from the data.

:func:`read_dataset_meta` extracts the inventory as plain data;
:func:`generate_dataset_page` renders it to a self-contained HTML file.
:func:`data_ranges_markup` renders the cast page's data-ranges appendix through the same
vendored ``variables_tables`` macro, so it reads identically to the inventory page.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from ctdcast._version import __version__ as _VERSION
from ctdcast.readers.metadata import source_to_canonical
from ctdcast.reports import design
from ctdcast.reports._env import _env, get_template
from ctdcast.reports._format import report_generated_at
from ctdcast.reports._navs import nav_for
from ctdcast.reports._vendored import nc_tables

__all__ = ["data_ranges_markup", "generate_dataset_page", "read_dataset_meta"]


def _fmt_val(x: Any) -> str:  # noqa: ANN401  # scalar min/max of caller-decided type (None/float/numpy scalar/str)
    """Format a scalar min/max value compactly for the table."""
    if x is None:
        return "—"
    if isinstance(x, (float, np.floating)):
        if not np.isfinite(x):
            return "—"
        return f"{x:.4g}"
    return str(x)[:40]


# The sensor-provenance variables are split out of the science-variable inventory.
# ``SENSOR_*`` is the catalog (its own table); the lowercase ``sensor_*`` family is the
# per-profile linkage (which catalog variable fills each role) and the ``sensor_channel_*``
# raw acquisition channels — both owned CTD-specific tables.  ``_is_sensor_var`` is the
# broad predicate (decision: exclude every ``SENSOR_*`` / ``sensor_*`` name) used to keep
# all of them out of the science-variable and scalar tables; ``design.is_sensor`` stays
# narrow (``SENSOR_*``) for the catalog itself.  A future lowercase ``sensor_``-named
# *science* variable would be excluded here — rename it or widen this rule when that happens.
def _is_channel(name: str) -> bool:
    """Return whether *name* is a per-profile raw-channel variable."""
    return name.startswith("sensor_channel_")


def _is_linkage(name: str) -> bool:
    """Return whether *name* is a per-profile sensor-linkage variable."""
    return name.startswith("sensor_") and not _is_channel(name)


def _is_sensor_var(name: str) -> bool:
    """Return whether *name* is any sensor-provenance variable (catalog, linkage, channel)."""
    return name.startswith(("SENSOR_", "sensor_"))


def _qc_exclusion_rows(ds: xr.Dataset) -> list[dict[str, Any]]:
    """Return the per-variable QC-exclusion summary rows.

    How many finite input samples each science variable carried and how many were
    dropped (QARTOD suspect/fail) before binning.  The denominator is pre-binning
    samples, so the fraction is not confounded by binning's own reduction in point
    count.  Only variables that recorded the counts (a compiled profiles file)
    contribute a row.
    """
    rows: list[dict[str, Any]] = []
    for name in sorted(ds.data_vars):
        if _is_sensor_var(name):
            continue
        attrs = ds[name].attrs
        if "qc_input_samples" not in attrs or "qc_excluded_samples" not in attrs:
            continue
        n_in = int(attrs["qc_input_samples"])
        n_drop = int(attrs["qc_excluded_samples"])
        rows.append(
            {
                "name": name,
                "n_input": n_in,
                "n_excluded": n_drop,
                "pct": (100.0 * n_drop / n_in) if n_in else 0.0,
            }
        )
    return rows


def _finite_min_max(ds: xr.Dataset, name: str) -> tuple[float | None, float | None]:
    """Return the finite ``(min, max)`` of a variable, or ``(None, None)`` when absent/empty."""
    if name not in ds.variables:
        return None, None
    vals = np.asarray(ds[name].values, dtype="float64").ravel()
    vals = vals[np.isfinite(vals)]
    if not vals.size:
        return None, None
    return float(vals.min()), float(vals.max())


def _datetime_extreme(
    ds: xr.Dataset, name: str, reduce: Callable[[np.ndarray], np.datetime64]
) -> np.datetime64 | None:
    """Return ``reduce`` of a datetime variable to the second, or ``None`` when absent/empty."""
    if name not in ds.variables:
        return None
    vals = np.asarray(ds[name].values).ravel()
    if vals.dtype.kind != "M":
        return None
    vals = vals[~np.isnat(vals)]
    if not vals.size:
        return None
    return np.datetime64(reduce(vals), "s")


def _time_bounds(ds: xr.Dataset) -> tuple[np.datetime64 | None, np.datetime64 | None]:
    """Return the data's ``(start, end)`` to the second, or ``(None, None)``.

    The start is the earliest ``time_start`` and the end the latest ``time_end`` —
    the two extremes the writer states, each from its own variable, so a correct
    file shows ``diff = 0`` and an amber flag means the metadata genuinely disagrees
    with the data.  A file with only a single ``time`` coordinate uses it for both.
    NaT is dropped.
    """
    start_var = "time_start" if "time_start" in ds.variables else "time"
    end_var = "time_end" if "time_end" in ds.variables else "time"
    return (
        _datetime_extreme(ds, start_var, np.min),
        _datetime_extreme(ds, end_var, np.max),
    )


def _fmt_diff(diff: float) -> str:
    """Format a coverage difference, collapsing a negligible value to a bare ``0``."""
    if abs(diff) < 5e-5:
        return "0"
    return f"{diff:+.3g}"


def _parse_iso_second(text: str) -> np.datetime64 | None:
    """Parse a written ISO timestamp (trailing ``Z`` allowed) to second precision."""
    try:
        return np.datetime64(text.rstrip("Z"), "s")
    except (ValueError, TypeError):
        return None


def _coverage_note() -> str:
    """Return the caption stating the amber-flag tolerances for the coverage table."""
    tol = design.COVERAGE_TOLERANCE
    latlon = (
        f"latitude/longitude {tol['lat']:g}°"
        if tol["lat"] == tol["lon"]
        else f"latitude {tol['lat']:g}°, longitude {tol['lon']:g}°"
    )
    return (
        "Computed values are recomputed from the data in this file. Diff is File − Computed; "
        "a cell is amber when |Diff| exceeds the tolerance "
        f"({latlon}, vertical {tol['vertical']:g} dbar, time {tol['time']:g} s)."
    )


def _coverage_computed(ds: xr.Dataset) -> dict[str, dict[str, Any]]:
    """Return the coverage check: ``{attr: {"value", "diff", "over"}}``.

    Recomputes the ``geospatial_*`` and ``time_coverage_*`` bounds from the data and
    compares each against the file's stated value.  ``over`` marks a disagreement
    larger than the per-axis tolerance in :data:`ctdcast.reports.design.COVERAGE_TOLERANCE`.
    An attribute the file does not state, or a value that cannot be recomputed, is
    omitted rather than guessed.
    """
    attrs = ds.attrs
    tol = design.COVERAGE_TOLERANCE
    out: dict[str, dict[str, Any]] = {}

    lat_lo, lat_hi = _finite_min_max(ds, "latitude")
    lon_lo, lon_hi = _finite_min_max(ds, "longitude")
    # The vertical axis is pressure on a CTD file and depth on the LADCP product; pick the
    # one present so the vertical bound is actually checked instead of silently skipped.
    ver_var = next((v for v in ("pressure", "depth") if v in ds.variables), None)
    ver_lo, ver_hi = _finite_min_max(ds, ver_var) if ver_var else (None, None)
    numeric: tuple[tuple[str, float | None, float], ...] = (
        ("geospatial_lat_min", lat_lo, tol["lat"]),
        ("geospatial_lat_max", lat_hi, tol["lat"]),
        ("geospatial_lon_min", lon_lo, tol["lon"]),
        ("geospatial_lon_max", lon_hi, tol["lon"]),
        ("geospatial_vertical_min", ver_lo, tol["vertical"]),
        ("geospatial_vertical_max", ver_hi, tol["vertical"]),
    )
    for key, computed, axis_tol in numeric:
        if key not in attrs:
            continue
        if computed is None:
            # A stated bound we cannot recompute. For the vertical bounds, say so rather than
            # omitting the row — an omitted row is indistinguishable from "not stated", which
            # is the thing this column exists to distinguish.
            if key.startswith("geospatial_vertical") and ver_var is None:
                out[key] = {
                    "value": "not computed (no pressure or depth variable)",
                    "diff": "",
                    "over": False,
                }
            continue
        try:
            stated = float(attrs[key])
        except (TypeError, ValueError):
            continue
        # Diff is File − Computed (the file's error), matching the table caption.
        diff = stated - computed
        out[key] = {
            "value": _fmt_val(computed),
            "diff": _fmt_diff(diff),
            "over": abs(diff) > axis_tol,
        }

    t_start, t_end = _time_bounds(ds)
    for key, computed_t in (
        ("time_coverage_start", t_start),
        ("time_coverage_end", t_end),
    ):
        if key not in attrs or computed_t is None:
            continue
        stated_t = _parse_iso_second(str(attrs[key]))
        if stated_t is None:
            continue
        delta_s = int((stated_t - computed_t) / np.timedelta64(1, "s"))
        out[key] = {
            "value": nc_tables.fmt_datetime(computed_t),
            "diff": "0 s" if delta_s == 0 else f"{delta_s:+d} s",
            "over": abs(delta_s) > tol["time"],
        }
    return out


# The inventory "Data variables" table rendered on its own, for the cast page's data-ranges
# appendix — the same vendored macro the full inventory page uses, so the two never diverge.
_VARIABLES_FRAGMENT = _env.from_string(
    "{% import '_nc_tables.html' as nc with context %}"
    "{{ nc.variables_tables(groups, source=source) }}"
)


def data_ranges_markup(nc_path: Path) -> str | None:
    """Return the cast page's netCDF data-ranges table as markup, or None when empty.

    Built from the same vendored ``variables_rows`` builder and ``variables_tables`` macro as
    the inventory page's "Data variables" section, so the per-cast appendix renders in the same
    form: variables grouped by dimension, ``_qc`` companions folded into their parent, and the
    full attribute set (including ``processing_level``) behind each row's disclosure.  Every
    ``SENSOR_*``/``sensor_*`` variable is excluded (``_is_sensor_var``) — a per-cast file carries
    the sensor catalog, not the per-profile linkage/channel the inventory page tables separately.
    Rendered to markup here because the cast template embeds it with ``|safe``.

    Parameters
    ----------
    nc_path : pathlib.Path
        The netCDF file to read.

    Returns
    -------
    str or None
        The table markup, or None if the file cannot be read or has no dimensioned variables.
    """
    try:
        ds = xr.open_dataset(nc_path, decode_timedelta=False, engine="netcdf4")
    except Exception:  # noqa: BLE001 — a bad file yields no appendix, never a crash
        return None
    with ds:
        groups, source = nc_tables.variables_rows(
            ds,
            is_qc=design.is_qc,
            is_sensor=_is_sensor_var,
            original_name_attrs=design.ORIGINAL_NAME_ATTRS,
        )
    if not groups:
        return None
    return _VARIABLES_FRAGMENT.render(groups=groups, source=source)


def read_dataset_meta(nc_path: Path) -> dict[str, Any]:
    """Read *nc_path* into a plain-data inventory for the netCDF inventory page.

    Opens the file once and runs the vendored
    :mod:`~ctdcast.reports._vendored.nc_tables` builders (coordinates, variables grouped
    by dimension, scalars, the sensor catalog, grouped globals), keeping the owned
    ctdcast tables (QC exclusions, variable renaming, sensor linkage/channel) and the
    coverage check alongside them.  A renamed variable's source name also rides each row
    as ``original_name`` (the in-context ``original → name`` cell).

    Returns a dict with ``filename``, ``filesize``, ``dims``, ``summary`` (the headline
    counts), ``coords`` / ``variables`` / ``scalars`` / ``sensor_catalog`` / ``globals``
    (each ``{"rows"|"groups", "source"}``), ``sensor_linkage`` / ``sensor_channel``
    (``{"groups", "source"}`` from :func:`~ctdcast.reports._vendored.nc_tables.variables_rows`
    with an including predicate), ``coverage`` (the recomputed-bounds check), ``qc_exclusion``
    and ``rename_map``.  On any read error returns ``{"filename", "error"}`` so the page
    can report it rather than failing to generate.

    Parameters
    ----------
    nc_path : pathlib.Path
        The netCDF file to inventory.

    Returns
    -------
    dict
        The inventory, or an error dict on a read failure.
    """
    try:
        ds = xr.open_dataset(nc_path, decode_timedelta=False, engine="netcdf4")
    except Exception as exc:  # noqa: BLE001 — surface any backend error on the page
        return {"filename": nc_path.name, "error": str(exc)}
    with ds:
        coord_rows, coord_src = nc_tables.coords_rows(
            ds, original_name_attrs=design.ORIGINAL_NAME_ATTRS
        )
        var_groups, var_src = nc_tables.variables_rows(
            ds,
            is_qc=design.is_qc,
            is_sensor=_is_sensor_var,
            original_name_attrs=design.ORIGINAL_NAME_ATTRS,
        )
        scalar_rows, scalar_src = nc_tables.scalars_rows(
            ds, exclude=_is_sensor_var, original_name_attrs=design.ORIGINAL_NAME_ATTRS
        )
        catalog_rows, catalog_src = nc_tables.sensor_rows(ds)
        global_groups, global_src = nc_tables.globals_rows(
            ds, extras=design.ATTR_GROUP_EXTRAS
        )
        summary = nc_tables.summary_counts(
            ds, is_qc=design.is_qc, is_sensor=design.is_sensor, exclude=_is_sensor_var
        )
        # Linkage and channel are per-profile sensor variables, kept out of the science
        # tables (decision) but shown in their own sections. Build them through the same
        # vendored variables_rows builder with an *including* predicate, so they render
        # through nc.variables_tables with the Length/Valid/Valid %/type columns the
        # science table has — owned code chooses the rows, the vendored macro owns the cells.
        linkage_groups, linkage_src = nc_tables.variables_rows(
            ds,
            is_qc=design.is_qc,
            include=_is_linkage,
            original_name_attrs=design.ORIGINAL_NAME_ATTRS,
        )
        channel_groups, channel_src = nc_tables.variables_rows(
            ds,
            is_qc=design.is_qc,
            include=_is_channel,
            original_name_attrs=design.ORIGINAL_NAME_ATTRS,
        )
        # Source → canonical rename table, reconstructed from each variable's recorded
        # source name; sorted by canonical name.  source_to_canonical already drops
        # identity entries (source == canonical).  Kept alongside the per-row arrow: the
        # section is the at-a-glance rename overview, the arrow the in-context detail.
        rename_map = dict(sorted(source_to_canonical(ds).items(), key=lambda kv: kv[1]))
        return {
            "filename": nc_path.name,
            "filesize": nc_path.stat().st_size if nc_path.exists() else 0,
            "dims": dict(ds.sizes),
            "summary": summary,
            "coords": {"rows": coord_rows, "source": coord_src},
            "variables": {"groups": var_groups, "source": var_src},
            "scalars": {"rows": scalar_rows, "source": scalar_src},
            "sensor_catalog": {"rows": catalog_rows, "source": catalog_src},
            "sensor_linkage": {"groups": linkage_groups, "source": linkage_src},
            "sensor_channel": {"groups": channel_groups, "source": channel_src},
            "globals": {"groups": global_groups, "source": global_src},
            "coverage": _coverage_computed(ds),
            "coverage_note": _coverage_note(),
            "qc_exclusion": _qc_exclusion_rows(ds),
            "rename_map": rename_map,
        }


def generate_dataset_page(
    nc_path: Path,
    out_path: Path,
    *,
    title: str | None = None,
    cruise: str = "",
    nav_prefix: str = "",
    show_nav: bool = False,
    inventory_pills: list[dict[str, str]] | None = None,
    current_href: str = "",
    generated_at: str | None = None,
) -> Path:
    """Render the netCDF inventory of *nc_path* to a self-contained HTML *out_path*.

    Parameters
    ----------
    nc_path:
        The netCDF file to inventory.
    out_path:
        Destination HTML path (parent directories are created).
    title:
        Page title; defaults to the file name.
    cruise:
        Cruise identifier shown in the footer; empty for a standalone inspection.
    nav_prefix:
        Relative path prefix to the report root for the page-nav links (``""``
        when the page sits beside ``index.html``).
    show_nav:
        Render the full report page-nav when ``True`` (the in-report cruise
        inventory page).  Standalone inspections leave it ``False`` so the nav's
        report-relative links are not shown for an arbitrary file.
    inventory_pills:
        ``{"label", "href"}`` entries for the compiled-file inventory pages
        (profiles/ladcp/sensors), rendered as a cross-navigation pill bar.
    current_href:
        The href of this page, rendered as the non-link active pill.
    generated_at:
        Page build stamp; ``None`` uses the current UTC time.  Threaded from
        :func:`ctdcast.report` so one build stamps every page identically.

    Returns
    -------
    Path
        The written *out_path*.
    """
    meta = read_dataset_meta(nc_path)
    nav = (
        nav_for(
            None,
            prefix=nav_prefix,
            inventory=inventory_pills or (),
            inventory_current=current_href,
        )
        if show_nav
        else None
    )
    html = get_template("dataset.html").render(
        meta=meta,
        page_title=title or nc_path.name,
        cruise=cruise,
        css=design.SHARED_CSS,
        js_top_links=design._JS_TOP_LINKS,
        nav_prefix=nav_prefix,
        nav=nav,
        masthead_role="component",
        version=_VERSION,
        generated_at=report_generated_at(generated_at),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
