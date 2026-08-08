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
from ctdcast.processors import qc
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
    nc_dir: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    cast_tags: set[str] | None = None,
    **kw: object,
) -> int:
    """Apply stage3 (QC + calibration) to NC files in *nc_dir*.

    Reads each ``*.nc`` file, applies :func:`stage3`, and writes the result
    back in place using :func:`ctdcast.writers.netcdf.write`.  Called by
    :func:`ctdcast.processors.process` with ``stage=3`` or
    ``stage="stage3"``.

    Parameters
    ----------
    nc_dir:
        Directory of per-cast netCDF files (read and written in place).
    force:
        Reprocess files that already carry QC flag variables.  Without
        ``force``, already-QC'd files are skipped.
    dry_run:
        Print which files would be processed without writing any output.
    cast_tags:
        If given, process only files whose stem contains one of the zero-padded
        3-digit cast numbers (e.g. ``{"042", "043"}``).
    **kw:
        Passed to :func:`stage3` (e.g. ``cruise_cfg``).

    Returns
    -------
    int
        Number of files written (0 for dry_run).

    Raises
    ------
    FileNotFoundError
        If *nc_dir* does not exist or is not a directory.
    """
    if not nc_dir.is_dir():
        raise FileNotFoundError(f"nc_dir not found: {nc_dir}")

    cruise_cfg: dict | None = kw.get("cruise_cfg")  # type: ignore[assignment]

    nc_files = sorted(nc_dir.glob("*.nc"))
    if cast_tags is not None:
        nc_files = [p for p in nc_files if any(t in p.stem for t in cast_tags)]

    n = n_skipped = n_failed = 0
    for nc_path in nc_files:
        if dry_run:
            print(f"  [dry-run] stage 3 would process: {nc_path.name}")
            continue
        ds = None
        try:
            ds = xr.open_dataset(nc_path, engine="netcdf4").load()
            already_qcd = any(v.endswith("_qc") for v in ds.data_vars)
            if already_qcd and not force:
                print(f"  skip (already QC'd): {nc_path.name}")
                n_skipped += 1
                continue
            ds_out = stage3(ds, cruise_cfg=cruise_cfg)
            _write_nc(ds_out, nc_path)
            print(f"  ok: {nc_path.name}")
            n += 1
        except Exception as exc:  # noqa: BLE001
            print(
                f"  FAILED: {nc_path.name}  ({type(exc).__name__}: {exc})",
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
