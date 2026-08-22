"""Stage 3 — QC, calibration, and derived-variable orchestrator.

Stage3 is iterative: re-run it as calibration improves.  Each run applies
gross-range QC, then any conductivity calibration present in the cruise
config, then re-derives salinity from the calibrated conductivity.

Sea-Bird processing-chain calibration (hex-level, frequency coefficients) is
Phase 5 scope; this module covers only the post-conversion treatment.
"""

from __future__ import annotations

import sys
from pathlib import Path

import xarray as xr

from ctdcast.analysis.derive import derive_salinity
from ctdcast.identity import format_cast_id
from ctdcast.processors import qc
from ctdcast.processors.stage_layout import (
    group_by_cast,
    matches_tags,
    parse_stage,
    stage_path,
)
from ctdcast.writers.netcdf import write as _write_nc


def stage3(
    ds: xr.Dataset,
    cruise_cfg: dict | None = None,
) -> xr.Dataset:
    """Apply QC and calibration to a per-cast Dataset.

    Applies the following in order:

    1. Gross-range QC (``qc.apply_gross_range``), using ``GROSS_RANGE_DEFAULTS``
       merged with any overrides from ``cruise_cfg["qc"]["gross_range"]``.
    2. Conductivity calibration slope, if ``cruise_cfg["calibration"]["conductivity_slope"]``
       is present.  Multiplies ``conductivity_1`` (and ``conductivity_2`` if
       present) by the slope and records it in the variable's attributes.
    3. Re-derives ``salinity_1`` (and ``salinity_2``) from the calibrated
       conductivity using ``derive_salinity()`` — only when a conductivity
       calibration was applied.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time), already through stage1 and stage2.
    cruise_cfg:
        Optional dict with sub-keys ``qc`` and ``calibration``.  Pass
        ``cfg.get("processing")`` or the full cruise config dict.

    Returns
    -------
    xr.Dataset
        New Dataset; input is not mutated.
    """
    cfg = cruise_cfg or {}

    # Step 1: gross-range QC
    thresholds = cfg.get("qc", {}).get("gross_range") or {}
    ds = qc.apply_gross_range(ds, thresholds or None)

    # Step 2: conductivity calibration
    slope_raw = cfg.get("calibration", {}).get("conductivity_slope")
    if slope_raw is not None:
        slope = float(slope_raw)
        ds = _apply_conductivity_slope(ds, slope)
        # Step 3: re-derive salinity from calibrated conductivity
        ds = derive_salinity(ds)

    return ds


def _apply_conductivity_slope(ds: xr.Dataset, slope: float) -> xr.Dataset:
    """Multiply conductivity variables by *slope* and record in attributes.

    Parameters
    ----------
    ds:
        Per-cast Dataset containing ``conductivity_1`` (and optionally
        ``conductivity_2``).
    slope:
        Multiplicative calibration factor (e.g. 1.0002).

    Returns
    -------
    xr.Dataset
        New Dataset with calibrated conductivity; input is not mutated.
    """
    import numpy as np

    ds = ds.copy()
    for var in ("conductivity_1", "conductivity_2"):
        if var not in ds:
            continue
        calibrated = (ds[var].values.astype(np.float64) * slope).astype(np.float32)
        new_attrs = dict(ds[var].attrs)
        new_attrs["calibration_slope"] = slope
        new_attrs["calibration_note"] = f"conductivity multiplied by {slope}"
        dim = ds[var].dims[0]
        ds[var] = xr.DataArray(calibrated, dims=[dim], attrs=new_attrs)
    return ds


def run(
    root: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    cast_tags: set[str] | None = None,
    **kw: object,
) -> int:
    """Apply stage 3 (QC + calibration) across the casts under *root*.

    Reads each cast's **stage-2** file, applies :func:`stage3`, and writes a new
    ``stage3/<stem>_stage3.nc`` — never in place.  Reads are strict: a cast with
    no stage-2 file is skipped with a warning (its soak/deck flags were never
    applied, so QC'ing it would manufacture a product whose filename lies).
    Called by :func:`ctdcast.processors.process` with ``stage=3``.

    Parameters
    ----------
    root:
        The CTD stage root (``ctd_root``).  Stage files live under
        ``root/stage2/`` … ``root/stage3/``.
    force:
        Rewrite the stage-3 file even when it already exists.  Without ``force``,
        a cast whose ``stage3/<stem>_stage3.nc`` exists is skipped.
    dry_run:
        Print what would be processed without writing any output.
    cast_tags:
        If given, process only casts selected by these zero-padded tags
        (e.g. ``{"042"}``), matched on the parsed cast identity.
    **kw:
        Passed to :func:`stage3` (e.g. ``cruise_cfg``).

    Returns
    -------
    int
        Number of stage-3 files written (0 for dry_run).

    Raises
    ------
    FileNotFoundError
        If *root* does not exist or is not a directory.
    """
    if not root.is_dir():
        raise FileNotFoundError(f"stage root not found: {root}")

    cruise_cfg: dict | None = kw.get("cruise_cfg")  # type: ignore[assignment]

    groups = group_by_cast(root)
    n = n_skipped = n_failed = 0
    for cast_id in sorted(groups):
        if cast_tags is not None and not matches_tags(cast_id, cast_tags):
            continue
        input_path = groups[cast_id].get(2)  # strict: stage 3 reads stage 2
        if input_path is None:
            num, suffix = cast_id
            print(
                f"  skip (no stage 2): cast {format_cast_id(num, suffix)}",
                file=sys.stderr,
            )
            n_skipped += 1
            continue
        parsed = parse_stage(input_path)
        stem = parsed[0] if parsed else input_path.stem
        target = stage_path(root, stem, 3)
        if target.exists() and not force:
            print(f"  skip (stage 3 exists): {target.name}")
            n_skipped += 1
            continue
        if dry_run:
            print(
                f"  [dry-run] stage 3 would process: {input_path.name} -> {target.name}"
            )
            continue
        ds = None
        try:
            ds = xr.open_dataset(input_path, engine="netcdf4").load()
            ds_out = stage3(ds, cruise_cfg=cruise_cfg)
            ds.close()
            ds = None  # prevent double-close in finally; file released before write
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_nc(ds_out, target)
            print(f"  ok: {target.name}")
            n += 1
        except Exception as exc:  # noqa: BLE001
            print(
                f"  FAILED: {input_path.name}  ({type(exc).__name__}: {exc})",
                file=sys.stderr,
            )
            n_failed += 1
        finally:
            if ds is not None:
                ds.close()
    if not dry_run:
        parts = [f"{n} written", f"{n_skipped} skipped"]
        if n_failed:
            parts.append(f"{n_failed} FAILED")
        print(f"stage 3: {', '.join(parts)}.")
    return n
