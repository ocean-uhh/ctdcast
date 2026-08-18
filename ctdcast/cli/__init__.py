"""CLI entry point for ctdcast."""

from __future__ import annotations

import argparse
import sys

from ctdcast._version import __version__

from . import convert as _convert
from . import draft as _draft
from . import init as _init
from . import inspect as _inspect
from . import process as _process
from . import report as _report
from . import run as _run
from . import validate as _validate

_EPILOG = """
Typical mid-cruise workflow:
  ctdcast init                                  write a template config.yaml
  ctdcast validate config.yaml                  check paths and data
  ctdcast process config.yaml --stage 1         CNV → per-cast netCDF
  ctdcast process config.yaml --stage 2 3       soak/deck flags, QC + calibration
  ctdcast process config.yaml --stage profiles  compile profiles.nc
  ctdcast report config.yaml                    generate HTML reports
  ctdcast run config.yaml                       profiles + all HTML in one step

Run 'ctdcast <command> --help' for command-specific options.
"""


def main() -> None:
    """Run the ctdcast command-line interface."""
    parser = argparse.ArgumentParser(
        prog="ctdcast",
        description=(
            "Generate self-contained HTML reports from shipboard CTD and LADCP data."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EPILOG,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        metavar="<command>",
    )
    subparsers.required = True

    _draft.build_parser(subparsers)
    _init.build_parser(subparsers)
    _convert.build_parser(subparsers)
    _process.build_parser(subparsers)
    _report.build_parser(subparsers)
    _run.build_parser(subparsers)
    _validate.build_parser(subparsers)
    _inspect.build_parser(subparsers)

    args = parser.parse_args()
    sys.exit(args.func(args))
