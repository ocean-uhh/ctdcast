"""Tier-2: a per-file netCDF *data inventory* page.

Unlike the figure report pages, this one answers "what is actually in this file?"
for a developer or data reviewer: every dimension, coordinate, and variable with
its dtype, units, CF names, value range and validity, plus the full per-variable
attribute set (revealed on demand) and the global attributes.  One page per file,
generated for ``profiles.nc``, a per-cast cast NC, or any other ctdcast product.

:func:`read_dataset_meta` extracts the inventory as plain data;
:func:`generate_dataset_page` renders it to a self-contained HTML file.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from ctdcast._version import __version__ as _VERSION
from ctdcast.config.global_attrs import group_attrs
from ctdcast.config.parameters import VARIABLES
from ctdcast.config.report_tokens import ROLE_ACCENT
from ctdcast.readers.metadata import source_to_canonical
from ctdcast.reports._report_css import _JS_TOP_LINKS, SHARED_CSS
from ctdcast.reports._env import get_template


def _fmt_val(x: Any) -> str:
    """Format a scalar min/max value compactly for the table."""
    if x is None:
        return "—"
    if isinstance(x, (float, np.floating)):
        if not np.isfinite(x):
            return "—"
        return f"{x:.4g}"
    return str(x)[:40]


def _var_meta(name: str, v: xr.DataArray) -> dict[str, Any]:
    """Return the inventory row for one variable or coordinate."""
    # Attributes already shown as their own table columns are omitted from the
    # expandable set (units, standard_name, long_name); label_units and everything
    # else remain.
    _columned = {"units", "standard_name", "long_name"}
    attrs = {
        str(k): _fmt_val(val) if isinstance(val, (int, float, np.number)) else str(val)
        for k, val in v.attrs.items()
        if k not in _columned
    }
    n = int(np.prod(v.shape)) if v.shape else 1
    v_min = v_max = None
    n_valid = n
    if v.dtype.kind in "fiu" and n:
        vals = np.asarray(v.values)
        finite = np.isfinite(vals)
        n_valid = int(finite.sum())
        if n_valid:
            v_min = vals[finite].min().item()
            v_max = vals[finite].max().item()
    # label_units is the Unicode display form used on figure axes (e.g. "S m⁻¹",
    # "°C").  Prefer the file's attr; fall back to the VARIABLES registry by
    # canonical name so it shows even before the writer records it on disk.
    label_units = v.attrs.get("label_units") or VARIABLES.get(name, {}).get(
        "label_units", ""
    )
    return {
        "name": name,
        "dims": ", ".join(str(d) for d in v.dims) or "()",
        "dtype": str(v.dtype),
        "units": v.attrs.get("units", ""),
        "label_units": label_units,
        "standard_name": v.attrs.get("standard_name", ""),
        "long_name": v.attrs.get("long_name", ""),
        "n": n,
        "n_valid": n_valid,
        "v_min": _fmt_val(v_min),
        "v_max": _fmt_val(v_max),
        "processing_level": v.attrs.get("processing_level", ""),
        "attrs": attrs,
    }


def read_dataset_meta(nc_path: Path) -> dict[str, Any]:
    """Read *nc_path* into a plain-data inventory (dims, coords, vars, attrs).

    Returns a dict with ``filename``, ``filesize``, ``dims``, ``coords``,
    ``data_vars`` (each a :func:`_var_meta` row), ``qc_exclusion`` (per-variable
    QC drop counts, from the ``qc_input_samples``/``qc_excluded_samples`` attrs a
    compiled profiles file carries), and ``global_attrs``.  On any read error
    returns ``{"error": <message>, ...}`` so the page can report it rather than
    failing to generate.
    """
    try:
        ds = xr.open_dataset(nc_path, decode_timedelta=False, engine="netcdf4")
    except Exception as exc:  # noqa: BLE001 — surface any backend error on the page
        return {"filename": nc_path.name, "error": str(exc)}
    with ds:
        coords = [_var_meta(n, ds[n]) for n in sorted(ds.coords)]
        all_vars = [_var_meta(n, ds[n]) for n in sorted(ds.data_vars)]

        # Split the sensor-provenance variables into their own inventory tables:
        # the catalog carries no numeric data (attributes only), the linkage is a
        # string per profile, and the channel is an integer per profile — each
        # wants a different column set from the science variables.
        def _is_catalog(n: str) -> bool:
            return n.startswith("SENSOR_")

        def _is_channel(n: str) -> bool:
            return n.startswith("sensor_channel_")

        def _is_linkage(n: str) -> bool:
            return n.startswith("sensor_") and not _is_channel(n)

        sensor_catalog = [v for v in all_vars if _is_catalog(v["name"])]
        sensor_channel = [v for v in all_vars if _is_channel(v["name"])]
        sensor_linkage = [v for v in all_vars if _is_linkage(v["name"])]
        data_vars = [
            v
            for v in all_vars
            if not (
                _is_catalog(v["name"])
                or _is_channel(v["name"])
                or _is_linkage(v["name"])
            )
        ]
        # QC-exclusion summary: how many finite input samples each science
        # variable carried and how many were dropped (QARTOD suspect/fail) before
        # binning.  The denominator is pre-binning samples, so the fraction is not
        # confounded by binning's own reduction in point count.  Only variables
        # that recorded the counts (a compiled profiles file) contribute a row.
        qc_exclusion = []
        for v in data_vars:
            name = v["name"]
            attrs = ds[name].attrs
            if "qc_input_samples" not in attrs or "qc_excluded_samples" not in attrs:
                continue
            n_in = int(attrs["qc_input_samples"])
            n_drop = int(attrs["qc_excluded_samples"])
            qc_exclusion.append(
                {
                    "name": name,
                    "n_input": n_in,
                    "n_excluded": n_drop,
                    "pct": (100.0 * n_drop / n_in) if n_in else 0.0,
                }
            )

        # The source→canonical rename table the reader applied, reconstructed from each
        # variable's recorded source name.
        rename_map = source_to_canonical(ds)
        # Show global attributes in full: this page exists to display the file's
        # provenance, and people/licence/institution strings routinely exceed a
        # couple hundred characters — truncating them hides the very metadata the
        # inventory is meant to surface.  The HTML wraps long values.  Values are
        # shown in the file's own order, split into the canonical groups so the
        # page can be checked against the specification.
        global_attrs = {str(k): str(v) for k, v in ds.attrs.items()}
        return {
            "filename": nc_path.name,
            "filesize": nc_path.stat().st_size if nc_path.exists() else 0,
            "dims": dict(ds.sizes),
            "coords": coords,
            "data_vars": data_vars,
            "qc_exclusion": qc_exclusion,
            "sensor_catalog": sensor_catalog,
            "sensor_linkage": sensor_linkage,
            "sensor_channel": sensor_channel,
            "rename_map": dict(sorted(rename_map.items(), key=lambda kv: kv[1])),
            "global_attrs": global_attrs,
            "global_attr_groups": group_attrs(global_attrs),
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

    Returns
    -------
    Path
        The written *out_path*.
    """
    meta = read_dataset_meta(nc_path)
    html = get_template("dataset.html").render(
        meta=meta,
        page_title=title or nc_path.name,
        cruise=cruise,
        css=SHARED_CSS,
        js_top_links=_JS_TOP_LINKS,
        nav_prefix=nav_prefix,
        nav_current="inventory",
        show_nav=show_nav,
        inventory_pills=inventory_pills or [],
        current_href=current_href,
        masthead_bg=ROLE_ACCENT.get("component", ""),
        version=_VERSION,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
