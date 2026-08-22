"""Tier-2: the "SBE sensors" page — sensor inventory and change log.

Reads the sensor catalog and per-profile linkage that
:func:`ctdcast.processors.profiles.build_profiles` writes into ``profiles.nc``
(the dimensionless ``SENSOR_<TYPE>_<SERIAL>`` variables and the
``sensor_<role>`` / ``sensor_channel_<role>`` variables) and renders three
things: the catalog of distinct devices used, the hardware-change log (which
sensor changed on which cast), and the rewiring log (same device moved to a
different acquisition channel).  One self-contained HTML page, generated beside
the netCDF inventory pages.

:func:`read_sensor_tables` extracts the tables as plain data;
:func:`generate_sensors_page` renders them to HTML.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from ctdcast._version import __version__ as _VERSION
from ctdcast.config.report_tokens import ROLE_ACCENT
from ctdcast.config.sensors import role_label as _role_label
from ctdcast.config.sensors import role_sort_key as _role_sort_key
from ctdcast.reports._env import get_template
from ctdcast.reports._report_css import _JS_TOP_LINKS, SHARED_CSS


def read_sensor_tables(profiles_path: Path) -> dict[str, Any]:
    """Read the sensor catalog and change/rewiring logs from *profiles_path*.

    Returns a plain-data dict with ``filename``, ``n_casts``, ``n_devices``,
    ``catalog`` (one row per distinct device), ``changes`` (hardware swaps in
    cast order) and ``rewiring`` (same device, moved channel).  On a read error
    returns ``{"filename": ..., "error": ...}``; on a file that predates the
    sensor catalog returns empty tables with ``has_catalog=False``.
    """
    try:
        ds = xr.open_dataset(profiles_path, engine="netcdf4", decode_timedelta=False)
    except Exception as exc:  # noqa: BLE001 — surface any backend error on the page
        return {"filename": profiles_path.name, "error": str(exc)}

    with ds:
        catalog_names = sorted(v for v in ds.variables if str(v).startswith("SENSOR_"))
        roles = sorted(
            (
                str(v)[len("sensor_") :]
                for v in ds.variables
                if str(v).startswith("sensor_")
                and not str(v).startswith("sensor_channel_")
            ),
            key=_role_sort_key,
        )
        cast_num = (
            ds["cast_number"].values if "cast_number" in ds.variables else np.array([])
        )
        n_casts = int(len({int(c) for c in cast_num})) if cast_num.size else 0

        if not catalog_names:
            return {
                "filename": profiles_path.name,
                "has_catalog": False,
                "n_casts": n_casts,
                "n_devices": 0,
                "catalog": [],
                "changes": [],
                "rewiring": [],
            }

        # Which roles did each catalog device serve (across all profiles)?
        served: dict[str, set[str]] = {n: set() for n in catalog_names}
        for role in roles:
            for v in set(ds[f"sensor_{role}"].values.astype(str)):
                if v in served:
                    served[v].add(role)

        catalog = []
        for name in catalog_names:
            a = {str(k): str(val) for k, val in ds[name].attrs.items()}
            catalog.append(
                {
                    "sensor_type": a.get("sensor_type", ""),
                    "model": a.get("sensor_model", ""),
                    "serial": a.get("sensor_serial_number", ""),
                    "calibration_date": a.get("sensor_calibration_date", ""),
                    "maker": a.get("sensor_maker", ""),
                    "model_source": a.get("model_source", ""),
                    "roles": [
                        _role_label(r) for r in sorted(served[name], key=_role_sort_key)
                    ],
                    "_name": name,
                }
            )
        catalog.sort(key=lambda r: (r["sensor_type"], r["serial"]))

        # Model/serial lookup, keyed by catalog variable name, for the change log.
        ms = {r["_name"]: (r["model"], r["serial"]) for r in catalog}
        has_channel = any(str(v).startswith("sensor_channel_") for v in ds.variables)

        dev_by_role = {r: ds[f"sensor_{r}"].values.astype(str) for r in roles}

        changes: list[dict[str, Any]] = []
        rewiring: list[dict[str, Any]] = []
        downs = list(range(0, len(cast_num), 2))  # downcast profile of each cast
        for role in roles:
            dev = dev_by_role[role]
            ch = (
                ds[f"sensor_channel_{role}"].values
                if has_channel and f"sensor_channel_{role}" in ds.variables
                else None
            )
            prev: tuple[str, int | None] | None = None
            for i in downs:
                d = dev[i]
                if not d:
                    continue
                c = int(ch[i]) if ch is not None else None
                cast = int(cast_num[i])
                if prev is not None:
                    pd, pc = prev
                    if d != pd:
                        om, osn = ms.get(pd, ("?", "?"))
                        nm, nsn = ms.get(d, ("?", "?"))
                        changes.append(
                            {
                                "cast": cast,
                                "role": _role_label(role),
                                "was": f"{om} {osn}".strip(),
                                "now": f"{nm} {nsn}".strip(),
                            }
                        )
                    elif c is not None and pc is not None and c != pc:
                        rewiring.append(
                            {
                                "cast": cast,
                                "role": _role_label(role),
                                "serial": ms.get(d, ("", ""))[1],
                                "from_ch": pc,
                                "to_ch": c,
                            }
                        )
                prev = (d, c)

        # Configuration blocks: consecutive casts sharing the same set of
        # device serials across all roles collapse to one row — "which sensor was
        # used on which cast".  Rewiring (channel-only) does not start a new block.
        def _serial(role: str, i: int) -> str:
            return ms.get(dev_by_role[role][i], ("", ""))[1]

        blocks: list[dict[str, Any]] = []
        prev_cfg: tuple[str, ...] | None = None
        for i in downs:
            cast = int(cast_num[i])
            cfg = tuple(_serial(r, i) for r in roles)
            if cfg != prev_cfg:
                blocks.append(
                    {
                        "cast_start": cast,
                        "cast_end": cast,
                        "cells": {r: cfg[j] for j, r in enumerate(roles)},
                    }
                )
                prev_cfg = cfg
            else:
                blocks[-1]["cast_end"] = cast
        for b in blocks:
            b["range"] = (
                f"{b['cast_start']:03d}"
                if b["cast_start"] == b["cast_end"]
                else f"{b['cast_start']:03d}–{b['cast_end']:03d}"
            )

        role_cols = [{"key": r, "label": _role_label(r)} for r in roles]

        for row in catalog:
            del row["_name"]
        changes.sort(key=lambda r: (r["cast"], _role_sort_key(r["role"].lower())))
        rewiring.sort(key=lambda r: (r["cast"], _role_sort_key(r["role"].lower())))

        return {
            "filename": profiles_path.name,
            "has_catalog": True,
            "has_channel": has_channel,
            "n_casts": n_casts,
            "n_devices": len(catalog),
            "n_changes": len(changes),
            "role_cols": role_cols,
            "blocks": blocks,
            "catalog": catalog,
            "changes": changes,
            "rewiring": rewiring,
        }


def generate_sensors_page(
    profiles_path: Path,
    out_path: Path,
    *,
    cruise: str = "",
    nav_prefix: str = "",
    show_nav: bool = True,
    inventory_pills: list[dict[str, str]] | None = None,
    current_href: str = "sbe_sensors.html",
) -> Path:
    """Render the SBE sensors page for *profiles_path* to *out_path*.

    Reads the sensor catalog and change log with :func:`read_sensor_tables` and
    writes a self-contained HTML file.  Returns the written *out_path*.
    ``inventory_pills`` (``{"label", "href"}`` entries) render a cross-navigation
    pill bar to the other compiled-file inventory pages; ``current_href`` marks
    this page's own pill as the non-link active one.
    """
    meta = read_sensor_tables(profiles_path)
    html = get_template("sensors.html").render(
        meta=meta,
        page_title=f"SBE sensors — {cruise}" if cruise else "SBE sensors",
        cruise=cruise,
        css=SHARED_CSS,
        js_top_links=_JS_TOP_LINKS,
        nav_prefix=nav_prefix,
        nav_current="sensors",
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
