"""Convert SeaBird CNV files to netCDF using seasenselib.

One netCDF file is written per CNV cast.  Output filenames mirror the input
stems (e.g. mixsed2_004.cnv → mixsed2_004.nc).

Usage
-----
    python cnv_to_nc.py                        # defaults below
    python cnv_to_nc.py --in-dir /path/cnv --out-dir /path/cnv_nc
    python cnv_to_nc.py --force                # overwrite existing nc files
"""

import argparse
import contextlib
import io
import logging
import sys
from pathlib import Path

# Must call basicConfig BEFORE importing seasenselib/pycnv so that pycnv's
# module-level basicConfig(level=INFO) call becomes a no-op (already set up).
logging.basicConfig(level=logging.ERROR)
logging.getLogger("pycnv").setLevel(logging.ERROR)
logging.getLogger("seasenselib").setLevel(logging.ERROR)

import seasenselib as ssl  # noqa: E402

CNV_DIR = Path("/Volumes/T9ifmeo/odb2026/CTD/cnv")
NC_DIR  = Path("/Volumes/T9ifmeo/odb2026/CTD/cnv_nc")


def convert_one(cnv_path: Path, out_dir: Path, force: bool) -> bool:
    """Read one CNV file and write netCDF; return True on success."""
    out_path = out_dir / (cnv_path.stem + ".nc")
    if out_path.exists() and not force:
        print(f"  skip (exists): {out_path.name}")
        return True
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ds = ssl.read(str(cnv_path))
        ssl.write(ds, str(out_path), sanitize_names=True)
        print(f"  ok: {cnv_path.name} → {out_path.name}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED: {cnv_path.name}  ({type(exc).__name__}: {exc})", file=sys.stderr)
        return False


def main() -> None:
    """Run CNV → netCDF batch conversion."""
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in-dir",  type=Path, default=CNV_DIR)
    parser.add_argument("--out-dir", type=Path, default=NC_DIR)
    parser.add_argument("--force",   action="store_true",
                        help="overwrite existing netCDF files")
    args = parser.parse_args()

    cnv_files = sorted(args.in_dir.glob("*.cnv"))
    if not cnv_files:
        print(f"No .cnv files found in {args.in_dir}", file=sys.stderr)
        sys.exit(1)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Converting {len(cnv_files)} CNV files")
    print(f"  in:  {args.in_dir}")
    print(f"  out: {args.out_dir}\n")

    n_ok = sum(convert_one(f, args.out_dir, args.force) for f in cnv_files)
    n_fail = len(cnv_files) - n_ok
    print(f"\nDone: {n_ok} ok, {n_fail} failed")
    if n_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
