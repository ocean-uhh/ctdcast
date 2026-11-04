r"""Compare a ctdcast file made from the ``.hex`` with Sea-Bird's CNV of the same cast.

Use it to check one SBE Data Processing step, or a whole set of steps. Run the ``.hex`` through
ctdcast with the steps from the CNV's own header, then compare the two files. The steps can
come from ``ctdcast inspect <file>.cnv``, pasted into ``data_processing:``. Two cases are
handled:

- **Scan by scan.** A stage-3 file (or stage 1 or 2) is compared with a CNV at the same scan
  rate, e.g. ``cnv_24Hz``. Values either side flags are left out: Wild Edit's bad-flag value
  and Loop Edit's scan flag in the CNV, and ``{var}_qc`` 3 or 4 in ctdcast's file. The flags
  are counted against each other.
- **Bin by bin.** A product (``<ctd_root>/products/<name>/<cast>_<name>.nc``) is compared
  with a bin-averaged CNV, e.g. ``cnv_cal`` at 1 dbar. Bins are matched on their pressure,
  rounded to the bin size.

It prints a table: per variable, the median, rms and largest difference (ctdcast minus CNV),
with the flag counts. With ``-o`` it also saves a figure of the differences against
pressure, one panel per variable, downcast and upcast.

Usage::

    venv/bin/python scripts/compare_hex_cnv.py STAGE3.nc CAST.cnv
    venv/bin/python scripts/compare_hex_cnv.py STAGE3.nc CAST.cnv -o diff.png \
        --vars conductivity_1 ctd_temperature_1 ctd_salinity_1 pressure
    venv/bin/python scripts/compare_hex_cnv.py PRODUCT_1dbar_down.nc CAST_cal.cnv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import xarray as xr

from ctdcast.analysis.sbe_compare import compare, comparison_table, read_reference


def _on_pressure(ds: xr.Dataset, dim: str, step: float) -> xr.Dataset:
    """Index *ds* by its pressure rounded to *step*, as a ``time`` dimension."""
    p = np.round(ds["pressure"].values.astype(float) / step) * step
    keep = np.isfinite(p)
    ds = ds.isel({dim: keep})
    key = p[keep]
    _, first = np.unique(key, return_index=True)
    ds = ds.isel({dim: np.sort(first)})
    key = np.round(ds["pressure"].values.astype(float) / step) * step
    ds = ds.drop_vars([c for c in ds.coords if dim in ds[c].dims])
    ds = ds.assign_coords(bin_pressure=(dim, key)).swap_dims({dim: "bin_pressure"})
    # A bin's mean time is a variable, not the index; it would clash with the new dimension.
    return ds.drop_vars("time", errors="ignore")


def _match_bins(
    ours: xr.Dataset, ref: xr.Dataset
) -> tuple[xr.Dataset, xr.Dataset, float]:
    """Return both datasets on their shared bin pressures, along ``time``."""
    step = ref.attrs.get("sample_interval_dbar")
    if step is None:
        p = np.sort(ref["pressure"].values.astype(float))
        step = float(np.nanmedian(np.diff(p)))
    step = float(step)
    dim = "bin" if "bin" in ours.dims else "time"
    a = _on_pressure(ours, dim, step)
    b = _on_pressure(ref, "time", step)
    shared = np.intersect1d(a["bin_pressure"].values, b["bin_pressure"].values)
    a = a.sel(bin_pressure=shared).rename({"bin_pressure": "time"})
    b = b.sel(bin_pressure=shared).rename({"bin_pressure": "time"})
    return a, b, step


def main(argv: list[str] | None = None) -> int:
    """Run the comparison from the command line."""
    parser = argparse.ArgumentParser(
        description="Compare a ctdcast file from the .hex with the cast's Sea-Bird CNV."
    )
    parser.add_argument(
        "ours", type=Path, help="ctdcast netCDF (stage file or product)"
    )
    parser.add_argument("cnv", type=Path, help="Sea-Bird CNV of the same cast")
    parser.add_argument(
        "--vars", nargs="+", help="variables to compare (default: all shared)"
    )
    parser.add_argument(
        "-o", "--output", type=Path, help="save a difference figure (PNG)"
    )
    args = parser.parse_args(argv)

    with xr.open_dataset(args.ours, engine="netcdf4") as ds:
        ours = ds.load()
    ref = read_reference(args.cnv)

    binned = "bin" in ours.dims or ref.attrs.get("sample_interval_kind") == "decibars"
    if binned:
        ours, ref, step = _match_bins(ours, ref)
        print(f"bin by bin: {ours.sizes['time']} shared bins at {step:g} dbar")
    else:
        print(f"scan by scan: {ours.sizes['time']} scans")
    try:
        rows = compare(ours, ref, args.vars)
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(f"ctdcast: {args.ours.name}\nCNV:     {args.cnv.name}")
    steps = ours.attrs.get("data_processing_steps")
    if steps:
        print(f"ctdcast steps: {steps}")
    print()
    print(comparison_table(rows))

    if args.output:
        import matplotlib

        matplotlib.use("Agg")
        from ctdcast.plotters.sbe_compare import draw_sbe_compare_fig

        names = [r.name for r in rows if r.n_compared]
        fig = draw_sbe_compare_fig(
            ours, ref, names, title=f"{args.ours.stem} minus {args.cnv.stem}"
        )
        if fig is None:
            print("no figure: nothing to compare", file=sys.stderr)
        else:
            fig.savefig(args.output, dpi=150)
            print(f"\nfigure: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
