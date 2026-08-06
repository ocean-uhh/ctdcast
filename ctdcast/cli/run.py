"""``ctdcast run`` — convert profiles and generate HTML reports in one step."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdcast run``."""
    _epilog = """
Equivalent to running ``ctdcast convert`` then ``ctdcast report`` in sequence.
The convert step builds (or skips) profiles.nc; the report step generates HTML.

Examples:
  # Full smart update (profiles if stale, then reports if stale):
  ctdcast run config.yaml

  # Rebuild everything:
  ctdcast run config.yaml --force

  # Include CNV → nc conversion (requires an external backend):
  ctdcast run config.yaml --ctd

  # Regenerate one cast page without rebuilding profiles:
  ctdcast run config.yaml --cast 42
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
        parser = argparse.ArgumentParser(prog="ctdcast run", **kwargs)

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
        nargs="+",
        metavar="N",
        default=None,
        help="Process only these cast(s): rebuild their station pages (skips the profiles step). "
        "Example: --cast 42  or  --cast 42 43 44",
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
    parser.add_argument(
        "--trim-soak",
        action="store_true",
        default=False,
        dest="trim_soak",
        help=(
            "Remove pre-soak records from each cast before plotting. "
            "Detects the last near-surface point before the main descent and trims everything prior."
        ),
    )

    return parser


def run(args: argparse.Namespace) -> int:
    """Execute ``ctdcast run``."""
    cfg_path: Path = args.config
    if not cfg_path.exists():
        print(f"Config file not found: {cfg_path}", file=sys.stderr)
        return 1

    cast_filter: list[int] | None = args.cast

    # ------------------------------------------------------------------ convert
    from . import convert as _convert

    if cast_filter is not None and args.ctd:
        # Single-cast + --ctd: convert that one CNV file, skip profiles rebuild.
        convert_ns = argparse.Namespace(
            config=cfg_path,
            ctd=True,
            profiles=False,
            ladcp=False,
            backend="seasenselib",
            cast=cast_filter,
            pattern="*.cnv",
            force=args.force,
            dry_run=args.dry_run,
        )
        print("=== convert ===")
        rc = _convert.run(convert_ns)
        if rc != 0:
            return rc
    elif cast_filter is None:
        # Full run: build profiles (and optionally CTD-convert first if --ctd).
        # Without --ctd, the default branch in convert runs profiles only.
        convert_ns = argparse.Namespace(
            config=cfg_path,
            ctd=args.ctd,
            profiles=args.ctd,
            ladcp=False,
            backend="seasenselib",
            cast=None,
            pattern="*.cnv",
            force=args.force,
            dry_run=args.dry_run,
        )
        print("=== convert ===")
        rc = _convert.run(convert_ns)
        if rc != 0:
            return rc
    # cast_filter set but no --ctd: skip convert entirely (just regenerate the HTML).

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
        sal=None,
        trim_soak=args.trim_soak,
        dbar_step=1,
    )

    print("=== report ===")
    return _report.run(report_ns)
