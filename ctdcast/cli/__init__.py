"""CLI entry point for ctdcast."""

from __future__ import annotations

import argparse
import sys

from ctdcast._version import __version__

from . import clock as _clock
from . import convert as _convert
from . import draft as _draft
from . import fit as _fit
from . import init as _init
from . import inspect as _inspect
from . import list as _list
from . import process as _process
from . import report as _report
from . import run as _run
from . import validate as _validate

_EPILOG = """
Typical mid-cruise workflow:
  ctdcast init                                  write a template config.yaml
  ctdcast validate config.yaml                  check the config before a run
  ctdcast process config.yaml --stage 1         raw → per-cast netCDF (CTD + LADCP)
  ctdcast process config.yaml --stage 2 3       soak/deck flags, QC + calibration
  ctdcast process config.yaml --stage profiles  compile profiles.nc (+ ladcp_profiles.nc)
  ctdcast report config.yaml                    generate HTML reports
  ctdcast run config.yaml                       every stage, then the HTML

Run 'ctdcast <command> --help' for command-specific options.
"""


def main() -> None:
    """Run the ctdcast command-line interface."""
    parser = argparse.ArgumentParser(
        prog="ctdcast",
        description=(
            "Process and report shipboard CTD and LADCP data: from raw files to QC'd netCDF to self-contained HTML."
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
    _clock.build_parser(subparsers)
    _fit.build_parser(subparsers)
    _list.build_parser(subparsers)

    args = parser.parse_args()
    from ctdcast.config.loader import ConfigError

    try:
        sys.exit(args.func(args))
    except ConfigError as exc:
        # A config that cannot be used as written: say where and why, without a traceback.
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)
