"""CLI entry point for ctdreport."""

from __future__ import annotations

import argparse
import sys

from ctdreport._version import __version__

from . import convert as _convert
from . import init as _init
from . import report as _report
from . import run as _run
from . import validate as _validate

_EPILOG = """
Typical mid-cruise workflow:
  ctdreport init                           write a template config.yaml in the current dir
  ctdreport validate config.yaml           check paths and data before the first run
  ctdreport run config.yaml                build profiles.nc then generate all HTML pages
  ctdreport run config.yaml --cast 42      quickly check a single new cast
  ctdreport run config.yaml --force        rebuild everything (e.g. end of cruise)

Or as separate steps:
  ctdreport convert config.yaml            build profiles.nc (without generating HTML)
  ctdreport report config.yaml             generate HTML from existing profiles.nc

Run 'ctdreport <command> --help' for command-specific options.
"""


def main() -> None:
    """Run the ctdreport command-line interface."""
    parser = argparse.ArgumentParser(
        prog="ctdreport",
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

    _init.build_parser(subparsers)
    _convert.build_parser(subparsers)
    _report.build_parser(subparsers)
    _run.build_parser(subparsers)
    _validate.build_parser(subparsers)

    args = parser.parse_args()
    sys.exit(args.func(args))
