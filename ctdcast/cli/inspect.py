"""``ctdcast inspect`` — render a netCDF data-inventory page, or show a CNV's SBE Data Processing steps."""

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

A Sea-Bird .cnv is read for its SBE Data Processing steps instead: the
equivalent data_processing: block is printed, ready to paste into the
config.  With -o, it is written as a page with a copy button and the
header's own fields for each module.

  ctdcast inspect /data/cnv_24Hz/mixsed2_017.cnv
  ctdcast inspect /data/cnv_24Hz/mixsed2_017.cnv -o mixsed2_017_processing.html
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
        help="The netCDF file to inventory, or a Sea-Bird .cnv to read the SBE processing steps of.",
    )
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        metavar="HTML",
        default=None,
        help=(
            "Output HTML path (default for netCDF: <stem>_inventory.html beside the file; "
            "for a .cnv: print to the screen only)."
        ),
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
    from ctdcast.reports.dataset import generate_dataset_page

    nc_file: Path = args.nc_file
    if not nc_file.exists():
        print(f"Error: file not found: {nc_file}", file=sys.stderr)
        return 1

    if nc_file.suffix.lower() == ".cnv":
        return _run_cnv(nc_file, args.out, args.title)

    out_path: Path = args.out or nc_file.with_name(f"{nc_file.stem}_inventory.html")
    generate_dataset_page(nc_file, out_path, title=args.title)
    print(f"Wrote {out_path}")
    return 0


def _run_cnv(cnv_file: Path, out: Path | None, title: str | None) -> int:
    """Print a CNV's SBE Data Processing steps as ``data_processing:`` YAML; write a page with ``-o``."""
    from ctdcast.config.sbe_steps import header_text_of, processing_yaml

    print(processing_yaml(header_text_of(cnv_file)), end="")
    if out is not None:
        from ctdcast.reports.sbe_processing import generate_sbe_processing_page

        generate_sbe_processing_page(cnv_file, out, title=title)
        print(f"Wrote {out}", file=sys.stderr)
    return 0
