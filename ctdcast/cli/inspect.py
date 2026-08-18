"""``ctdcast inspect`` — render a netCDF data-inventory page for any file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdcast inspect``."""
    _epilog = """
Reads any ctdcast netCDF product (a per-cast file, profiles.nc, or
ladcp_profiles.nc) and writes a self-contained HTML inventory page: every
dimension, coordinate, and variable with its dtype, units, CF names, value
range and valid count, the source-to-canonical variable renaming, and the
global attributes.  No figures — this answers "what is in this file?".

Examples:
  # Inspect a compiled profiles file (writes profiles_inventory.html beside it):
  ctdcast inspect /data/profiles.nc

  # Inspect a single cast, choosing the output path:
  ctdcast inspect /data/nc/cast_012.nc -o /tmp/cast_012_inventory.html
"""
    kwargs: dict = {
        "description": "Render a netCDF data-inventory page for a single file.",
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": _epilog,
    }
    if subparsers is not None:
        parser = subparsers.add_parser(
            "inspect",
            help="Render a netCDF data-inventory page for a single file.",
            **kwargs,
        )
        parser.set_defaults(func=run)
    else:
        parser = argparse.ArgumentParser(prog="ctdcast inspect", **kwargs)

    parser.add_argument(
        "nc_file",
        type=Path,
        help="The netCDF file to inventory.",
    )
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        metavar="HTML",
        default=None,
        help="Output HTML path (default: <nc_file stem>_inventory.html beside the file).",
    )
    parser.add_argument(
        "--title",
        metavar="TEXT",
        default=None,
        help="Page title (default: the file name).",
    )

    return parser


def run(args: argparse.Namespace) -> int:
    """Execute ``ctdcast inspect``."""
    from ctdcast.reports._dataset import generate_dataset_page

    nc_file: Path = args.nc_file
    if not nc_file.exists():
        print(f"Error: file not found: {nc_file}", file=sys.stderr)
        return 1

    out_path: Path = args.out or nc_file.with_name(f"{nc_file.stem}_inventory.html")
    generate_dataset_page(nc_file, out_path, title=args.title)
    print(f"Wrote {out_path}")
    return 0
