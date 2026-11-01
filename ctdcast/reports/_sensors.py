"""Tier-2: the "SBE sensors" page — which sensor did what, on which casts.

Reads the sensor catalog and per-profile linkage that
:func:`ctdcast.processors.profiles.build_profiles` writes into ``profiles.nc``
(the dimensionless ``SENSOR_<TYPE>_<SERIAL>`` variables and the
``sensor_<role>`` / ``sensor_channel_<role>`` variables) and renders, in order: the
sensor configuration by run of casts, the preferred T/C pair and oxygen per run (where a
cast carries two), the device inventory with its datcnv slope/offset, the rewiring log
(same device moved to a different acquisition channel), and the sensor-variable tables
themselves.  One self-contained HTML page, generated beside the netCDF inventory pages.

:func:`read_sensor_tables` extracts the tables as plain data;
:func:`generate_sensors_page` renders them to HTML.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from ctdcast._version import __version__ as _VERSION
from ctdcast.config.cnv_header import cal_value_nondefault
from ctdcast.config.sensors import ROLE_ORDER, is_sensor_catalog_var
from ctdcast.config.sensors import role_label as _role_label
from ctdcast.config.sensors import role_sort_key as _role_sort_key
from ctdcast.reports._env import get_template
from ctdcast.reports._format import report_generated_at
from ctdcast.reports._navs import nav_for
from ctdcast.reports.dataset import sensor_variable_tables
from ctdcast.reports.design import _JS_TOP_LINKS, SHARED_CSS


def _linkage_roles(names: list[str]) -> list[str]:
    """Return the roles that have a ``sensor_<role>`` linkage variable among *names*.

    Selected by inclusion: ``<role>`` is a known role (:data:`ROLE_ORDER`) or has a
    ``sensor_channel_<role>`` twin.  Anything else with a ``sensor_`` prefix — the
    ``sensor_<role>_preferred`` choice, the channel variables themselves — is not a role.
    """
    present = set(names)
    roles = {
        n[len("sensor_") :]
        for n in names
        if n.startswith("sensor_") and not n.startswith("sensor_channel_")
    }
    return sorted(
        (r for r in roles if r in ROLE_ORDER or f"sensor_channel_{r}" in present),
        key=_role_sort_key,
    )


def _cast_range(start: int, end: int) -> str:
    """Format a run of casts as ``011`` or ``011–014``."""
    return f"{start:03d}" if start == end else f"{start:03d}–{end:03d}"


#: How the preferred-choice table names a cast with no choice to make, or one it was not given.
_SINGLE = "single sensor"
_NOT_DECLARED = "not declared"
_OXYGEN_NOT_DECLARED = "line 1 shown (not declared)"
_NO_CATALOG = "no sensor catalog"


def _preferred_runs(
    ds: xr.Dataset,
    downs: list[int],
    cast_num: np.ndarray,
    dev_by_role: dict[str, np.ndarray],
    serial_of: Callable[[str], str],
) -> list[dict[str, Any]]:
    """Return the per-cast preferred T/C pair and oxygen, collapsed into runs of casts.

    One row per run of consecutive casts with the same choice and serials.  A dual T/C
    cast shows its declared ``primary``/``secondary`` pair and that pair's serials, or
    ``not declared``; a dual-oxygen cast likewise, except an undeclared one shows line 1,
    which is what the figures draw.  A single-sensor cast has no choice.  A cast compiled
    from a stage-1 or stage-2 file (``source_stage``) has not had its choice resolved yet
    and reads ``not resolved yet (stage N)``; a cast with no sensor catalog reads
    ``no sensor catalog``.  Each run carries ``undeclared`` (either group has a choice the
    config did not make; an unresolved or catalog-less cast is not counted).  Returns ``[]``
    when no cast has a second T/C pair or a second oxygen sensor.
    """
    empty = np.array([""] * len(cast_num))

    def _link(role: str) -> np.ndarray:
        return dev_by_role.get(role, empty)

    def _var(name: str) -> np.ndarray:
        return ds[name].values.astype(str) if name in ds.variables else empty

    pair_word, oxy_word = _var("preferred_pair"), _var("preferred_oxygen")
    t_pref, c_pref = (
        _var("sensor_temperature_preferred"),
        _var("sensor_conductivity_preferred"),
    )
    o_pref = _var("sensor_oxygen_preferred")
    t1, c1, t2 = _link("temperature_1"), _link("conductivity_1"), _link("temperature_2")
    o1, o2 = _link("oxygen_1"), _link("oxygen_2")
    if not any(t2[i] or o2[i] for i in downs):
        return []

    stage = (
        ds["source_stage"].values
        if "source_stage" in ds.variables
        else np.zeros(len(cast_num), dtype=int)
    )
    runs: list[dict[str, Any]] = []
    prev: tuple[str, ...] | None = None
    for i in downs:
        unresolved = (
            f"not resolved yet (stage {int(stage[i])})"
            if int(stage[i]) in (1, 2)
            else None
        )
        if not any(dev[i] for dev in dev_by_role.values()):
            pair, pair_serials, oxygen, oxygen_serial = _NO_CATALOG, "", "", ""
        elif not t2[i]:
            pair, pair_serials = _SINGLE, f"{serial_of(t1[i])} / {serial_of(c1[i])}"
        elif pair_word[i]:
            pair = str(pair_word[i])
            pair_serials = f"{serial_of(t_pref[i])} / {serial_of(c_pref[i])}"
        else:
            pair, pair_serials = unresolved or _NOT_DECLARED, ""
        if pair == _NO_CATALOG:
            pass
        elif not o1[i]:
            oxygen, oxygen_serial = "", ""
        elif not o2[i]:
            oxygen, oxygen_serial = _SINGLE, serial_of(o1[i])
        elif oxy_word[i]:
            oxygen, oxygen_serial = str(oxy_word[i]), serial_of(o_pref[i])
        else:
            oxygen, oxygen_serial = unresolved or _OXYGEN_NOT_DECLARED, serial_of(o1[i])
        row = (pair, pair_serials, oxygen, oxygen_serial)
        cast = int(cast_num[i])
        if row == prev:
            runs[-1]["cast_end"] = cast
            continue
        prev = row
        runs.append(
            dict(
                zip(
                    ("pair", "pair_serials", "oxygen", "oxygen_serial"),
                    row,
                    strict=True,
                )
            )
            | {"cast_start": cast, "cast_end": cast}
        )
    for r in runs:
        r["range"] = _cast_range(r["cast_start"], r["cast_end"])
        r["undeclared"] = (
            r["pair"] == _NOT_DECLARED or r["oxygen"] == _OXYGEN_NOT_DECLARED
        )
    return runs


def read_sensor_tables(profiles_path: Path) -> dict[str, Any]:
    """Read the sensor tables of *profiles_path* as plain data.

    Parameters
    ----------
    profiles_path : pathlib.Path
        A compiled ``profiles.nc``.

    Returns
    -------
    dict
        ``filename``, ``has_catalog``, ``has_channel``, ``n_casts``, ``n_devices``,
        ``n_changes``, ``any_calibrated`` (some device has slope ≠ 1 or offset ≠ 0),
        ``role_cols`` and ``blocks`` (the configuration table), ``preferred`` (the
        preferred-sensor runs, ``[]`` when no cast carries two sensors), ``catalog``
        (one row per device, with ``slope``/``offset`` as recorded and
        ``slope_nondefault``/``offset_nondefault``), ``changes`` (hardware swaps in cast
        order), ``rewiring`` (same device, moved channel) and ``sensor_vars`` (the
        sensor-variable tables, :func:`ctdcast.reports.dataset.sensor_variable_tables`).
        On a read error ``{"filename", "error"}``; on a file that predates the sensor
        catalog, empty tables with ``has_catalog=False``.
    """
    try:
        ds = xr.open_dataset(profiles_path, engine="netcdf4", decode_timedelta=False)
    except Exception as exc:  # noqa: BLE001 — surface any backend error on the page
        return {"filename": profiles_path.name, "error": str(exc)}

    with ds:
        catalog_names = sorted(str(v) for v in ds.variables if is_sensor_catalog_var(v))
        roles = _linkage_roles([str(v) for v in ds.variables])
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
            slope = a.get("sensor_calibration_slope", "")
            offset = a.get("sensor_calibration_offset", "")
            catalog.append(
                {
                    "slope": slope,
                    "offset": offset,
                    "slope_nondefault": bool(slope)
                    and cal_value_nondefault(slope, 1.0),
                    "offset_nondefault": bool(offset)
                    and cal_value_nondefault(offset, 0.0),
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
            b["range"] = _cast_range(b["cast_start"], b["cast_end"])

        preferred = _preferred_runs(
            ds, downs, cast_num, dev_by_role, lambda name: ms.get(name, ("", ""))[1]
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
            "any_calibrated": any(
                r["slope_nondefault"] or r["offset_nondefault"] for r in catalog
            ),
            "role_cols": role_cols,
            "blocks": blocks,
            "preferred": preferred,
            "catalog": catalog,
            "changes": changes,
            "rewiring": rewiring,
            "sensor_vars": sensor_variable_tables(ds),
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
    generated_at: str | None = None,
    inventory_href: str | None = None,
) -> Path:
    """Render the SBE sensors page for *profiles_path* to *out_path*.

    Parameters
    ----------
    profiles_path : pathlib.Path
        A compiled ``profiles.nc``.
    out_path : pathlib.Path
        The HTML file to write; parent directories are created.
    cruise : str, optional
        Cruise identifier for the title and footer.
    nav_prefix : str, optional
        Relative path to the report root for the page-nav links.
    show_nav : bool, default True
        Render the report page-nav.
    inventory_pills : list of dict, optional
        ``{"label", "href"}`` entries for the compiled-file inventory pages, rendered as a
        cross-navigation pill bar.
    current_href : str, default ``"sbe_sensors.html"``
        This page's own pill, rendered as the non-link active one.
    generated_at : str, optional
        Page build stamp; ``None`` uses the current UTC time.  Threaded from
        :func:`ctdcast.report` so one build stamps every page identically.
    inventory_href : str, optional
        The file's netCDF inventory page.  The page ends with the sensor-variable tables
        (``SENSOR_*``, ``sensor_<role>``, ``sensor_channel_<role>``), and this links them
        back to the inventory, which points here instead of repeating them.

    Returns
    -------
    pathlib.Path
        The written *out_path*.
    """
    meta = read_sensor_tables(profiles_path)
    sensor_vars = meta.get("sensor_vars") if meta.get("has_catalog") else None
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
    html = get_template("sensors.html").render(
        meta=meta,
        sensor_vars=sensor_vars,
        inventory_href=inventory_href,
        page_title=f"SBE sensors — {cruise}" if cruise else "SBE sensors",
        cruise=cruise,
        css=SHARED_CSS,
        js_top_links=_JS_TOP_LINKS,
        nav_prefix=nav_prefix,
        nav=nav,
        masthead_role="component",
        version=_VERSION,
        generated_at=report_generated_at(generated_at),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
