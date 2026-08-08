"""Stage 3 — QC, calibration, and derived-variable orchestrator.

Stage3 is iterative: re-run it as calibration improves.  Each run applies
gross-range QC, then any conductivity calibration present in the cruise
config, then re-derives salinity from the calibrated conductivity.

Sea-Bird processing-chain calibration (hex-level, frequency coefficients) is
Phase 5 scope; this module covers only the post-conversion treatment.
"""

from __future__ import annotations

from pathlib import Path

import xarray as xr

from ctdcast.analysis.derive import derive_salinity
from ctdcast.processors import qc


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
    proc_dir: Path,
    *,
    force: bool = False,  # noqa: ARG001
    cruise_cfg: dict | None = None,
) -> int:
    """Apply stage3 (QC + calibration) to all NC files in ``proc_dir/nc/``.

    Reads each ``*.nc`` file, applies :func:`stage3`, and writes the result
    back in place using :func:`ctdcast.writers.netcdf.write`.  Called by
    :func:`ctdcast.processors.process` with ``stage=3`` or
    ``stage="stage3"``.

    Parameters
    ----------
    proc_dir:
        Base processing directory.  NC files are read from and written back
        to ``proc_dir/nc/``.
    force:
        Accepted for API consistency but ignored — stage3 always rewrites.
    cruise_cfg:
        Passed to :func:`stage3`.

    Returns
    -------
    int
        Number of files processed.
    """
    import xarray as xr

    from ctdcast.writers.netcdf import write

    nc_dir = proc_dir / "nc"
    n = 0
    for nc_path in sorted(nc_dir.glob("*.nc")):
        ds = xr.open_dataset(nc_path, engine="netcdf4").load()
        ds_out = stage3(ds, cruise_cfg=cruise_cfg)
        write(ds_out, nc_path)
        n += 1
    return n
