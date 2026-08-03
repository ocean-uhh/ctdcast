"""``ctdreport run`` — convert profiles and generate HTML reports in one step."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdreport run``."""
    _epilog = """
Equivalent to running ``ctdreport convert`` then ``ctdreport report`` in sequence.
The convert step builds (or skips) profiles.nc; the report step generates HTML.

Examples:
  # Full smart update (profiles if stale, then reports if stale):
  ctdreport run config.yaml

  # Rebuild everything:
  ctdreport run config.yaml --force

  # Include CNV → nc conversion (requires an external backend):
  ctdreport run config.yaml --ctd

  # Regenerate one cast page without rebuilding profiles:
  ctdreport run config.yaml --cast 42
"""
    kwargs: dict = {
        "description": "Convert profiles and generate HTML reports in one step.",
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": _epilog,
    }
    if subparsers is not None:
        parser = subparsers.add_parser(
            "run",
            help="Convert profiles then generate HTML reports (convert + report).",
            **kwargs,
        )
        parser.set_defaults(func=run)
    else:
        parser = argparse.ArgumentParser(prog="ctdreport run", **kwargs)

    parser.add_argument("config", type=Path, help="Path to config YAML file.")

    parser.add_argument(
        "--ctd",
        action="store_true",
        default=False,
        help="Also run CNV → netCDF conversion before building profiles (requires data.cnv_dir).",
    )
    parser.add_argument(
        "--cast",
        type=int,
        metavar="N",
        default=None,
        help="Process only cast N: rebuild its station page (skips the profiles step).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force regeneration of all outputs regardless of mtime.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=False,
        help="Skip any page whose HTML already exists, regardless of source mtime.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be done without writing any files.",
    )

    return parser


def run(args: argparse.Namespace) -> int:
    """Execute ``ctdreport run``."""
    cfg_path: Path = args.config
    if not cfg_path.exists():
        print(f"Config file not found: {cfg_path}", file=sys.stderr)
        return 1

    cast_filter: int | None = args.cast

    # ------------------------------------------------------------------ convert
    # Skip the convert step entirely when targeting a single cast — profiles.nc
    # rebuild would be expensive and pointless for a per-cast station-page check.
    if cast_filter is None:
        from . import convert as _convert

        # When --ctd is given, pass ctd=True and profiles=True so that convert's
        # explicit-flag branch runs both steps in sequence.
        # Without --ctd, pass both False so convert uses its default branch, which
        # runs profiles only when data.profiles_nc is configured in the config.
        convert_ns = argparse.Namespace(
            config=cfg_path,
            ctd=args.ctd,
            profiles=args.ctd,
            ladcp=False,
            backend="seasenselib",
            cast=None,
            force=args.force,
            dry_run=args.dry_run,
        )

        print("=== convert ===")
        rc = _convert.run(convert_ns)
        if rc != 0:
            return rc

    # ------------------------------------------------------------------ report
    from . import report as _report

    report_ns = argparse.Namespace(
        config=cfg_path,
        stations=False,
        sections=False,
        timeseries=False,
        index=False,
        map=False,
        cast=cast_filter,
        force=args.force,
        skip_existing=args.skip_existing,
        dry_run=args.dry_run,
    )

    print("=== report ===")
    return _report.run(report_ns)
