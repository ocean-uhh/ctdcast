"""CF-compliant netCDF writer for per-cast Datasets.

Augments the variable attributes produced by seasenselib with proper CF
metadata from ``ctdcast.config.parameters.VARIABLES`` and writes QARTOD flag
variables with the CF flag_values / flag_meanings convention.  Writes
atomically via a ``.nc.tmp`` intermediary.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from pathlib import Path

import numpy as np
import xarray as xr

from ctdcast.config.global_attrs import data_mode_with_meaning, order_attrs
from ctdcast.config.parameters import VARIABLES

_QARTOD_FLAG_VALUES = np.array([1, 2, 3, 4, 9], dtype=np.int8)
_QARTOD_FLAG_MEANINGS = (
    "pass not_evaluated suspect_or_of_high_interest fail missing_data"
)


def write(ds: xr.Dataset, path: Path, *, encoding: dict | None = None) -> None:
    """Write *ds* to *path* with CF-1.13 attributes and QARTOD flag metadata.

    For each variable present in both *ds* and ``VARIABLES`` — including
    coordinate variables such as ``latitude``/``longitude`` — applies
    ``units``, ``long_name``, ``standard_name``, and ``label_units`` (when
    defined).  For each ``{var}_qc`` variable, generates complete CF flag
    attributes.  Sets ``Conventions = "CF-1.13"`` unless the caller already
    declared one (a richer value such as ``"CF-1.13, ACDD-1.3"`` is preserved).

    Writes atomically: writes to ``path.with_suffix(".nc.tmp")`` then
    replaces *path* so a failed write never leaves a partial file.

    Parameters
    ----------
    ds:
        Dataset to write (per-cast, dim=time, or profiles N_PROF×pressure).
    path:
        Output netCDF path.
    encoding:
        Optional xarray encoding dict passed through to ``to_netcdf``.
    """
    ds = ds.copy()

    # Apply CF metadata from VARIABLES for each known variable.
    for var, meta in VARIABLES.items():
        if var not in ds:
            continue
        existing = dict(ds[var].attrs)
        if meta.get("long_name"):
            existing.setdefault("long_name", meta["long_name"])
        if meta.get("units"):
            existing["units"] = meta["units"]  # always override — CF canonical form
        if meta.get("standard_name"):
            existing.setdefault("standard_name", meta["standard_name"])
        if meta.get("label_units"):
            # Unicode display form for figure axes (e.g. "S m⁻¹"); complements the
            # CF-canonical ASCII ``units``.  Kept if the file already carries one.
            existing.setdefault("label_units", meta["label_units"])
        ds[var].attrs = existing

    # Apply CF flag metadata for QARTOD _qc variables.
    for var in list(ds.data_vars):
        if not var.endswith("_qc"):
            continue
        base = var[:-3]  # strip "_qc"
        standard_name = None
        if base in VARIABLES and VARIABLES[base].get("standard_name"):
            standard_name = f"{VARIABLES[base]['standard_name']} status_flag"

        attrs = dict(ds[var].attrs)
        attrs["flag_values"] = _QARTOD_FLAG_VALUES
        attrs["flag_meanings"] = _QARTOD_FLAG_MEANINGS
        attrs.setdefault("conventions", "QARTOD")
        attrs.setdefault("long_name", f"Quality flag for {base}")
        attrs["valid_min"] = np.int8(1)
        attrs["valid_max"] = np.int8(9)
        if standard_name:
            attrs["standard_name"] = standard_name
        ds[var].attrs = attrs

    global_attrs = dict(ds.attrs)
    # Default to CF-1.13, but let a caller that has already declared a richer
    # conformance (e.g. the compiled profiles builder writes "CF-1.13, ACDD-1.3")
    # keep it rather than being silently downgraded here.
    global_attrs.setdefault("Conventions", "CF-1.13")
    # A fresh identity on *every* write (ACDD/OceanSITES ``tracking_id``, UUID4). This
    # answers "which instance of this file is this" — NOT "did the content change": a
    # content hash would answer a different question (and netCDF embeds write-time detail,
    # so it would churn anyway).  Stability would be the bug — a stable id cannot detect a
    # rewrite.  Written here, the single ``to_netcdf`` seam, so every stage file, the
    # compiled ``profiles.nc`` and the LADCP files get one without per-module edits.  A
    # writer overwrites any inbound ``tracking_id``; a stage that wants lineage must have
    # already copied the file-it-read's id into ``source_tracking_id`` before calling write.
    global_attrs["tracking_id"] = str(uuid.uuid4())
    # ``date_modified`` moves on every write; ``date_created`` is set once (first write) and
    # preserved on re-runs — a stage-3 rewrite records when it was rewritten without resetting
    # the creation time. Same UTC form as ``global_attrs.provenance_attrs``.
    _stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    global_attrs["date_modified"] = _stamp
    global_attrs.setdefault("date_created", _stamp)
    # Every file carries a ``data_mode`` (OceanSITES reference table 4), so a consumer
    # that reads a per-cast stage file via ``select_best_available`` — caldip does — can
    # read its reference's mode without opening ``profiles.nc``.  Stage 1/2/3 files fall to
    # ``P`` (provisional) here; the compiled builders and a declared ``D`` set the value on
    # ``ds.attrs`` before calling write and keep it.  The mode and its meaning come from one
    # helper so the pair can never drift, whoever set the mode (no warning at this last seam —
    # an invalid mode was already warned about where it was declared).
    global_attrs["data_mode"], global_attrs["data_mode_meaning"] = (
        data_mode_with_meaning(global_attrs.get("data_mode"), warn=False)
    )
    # Write the global attributes in the canonical order (identity → platform →
    # coverage → people → rights → provenance); unnamed attrs keep their order and
    # follow.  One source of truth with the inventory page's grouping.
    ds.attrs = order_attrs(global_attrs)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".nc.tmp")

    # Give every datetime variable an explicit CF time encoding.  Without it
    # xarray guesses ``units="days since <first timestamp>"`` as int64, which
    # cannot hold sub-day (second-resolution) cast times, so it warns and falls
    # back to seconds.  Pinning a fixed epoch in float64 seconds is the CF-standard
    # encoding, is faithful to sub-second precision, and silences the warning.
    # (CF always stores time as a numeric count since an epoch; it decodes back to
    # real datetimes on read — this is not "time as an integer".)
    enc: dict = dict(encoding or {})
    for name, var in ds.variables.items():
        if np.issubdtype(var.dtype, np.datetime64) and name not in enc:
            enc[name] = {
                "units": "seconds since 1970-01-01T00:00:00",
                "dtype": "float64",
                "calendar": "proleptic_gregorian",
                # A NaT (e.g. an incomplete cast) would otherwise write as a bare
                # NaN a strict CF reader cannot flag as missing; declare it.
                "_FillValue": np.nan,
            }

    kw: dict = {"encoding": enc} if enc else {}
    ds.to_netcdf(str(tmp), **kw)
    tmp.replace(path)
