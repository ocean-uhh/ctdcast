"""``ctdcast run`` — convert profiles and generate HTML reports in one step."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ctdcast.cli._deprecate import DeprecatedAlias, warn_deprecated


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
  ctdcast run config.yaml --only 42
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
        "--only",
        dest="only",
        type=int,
        nargs="+",
        metavar="N",
        default=None,
        help="Process only these cast(s): rebuild their pages (skips the profiles step). "
        "Example: --only 42  or  --only 42 43 44",
    )
    parser.add_argument(
        "--cast",
        dest="only",
        type=int,
        nargs="+",
        metavar="N",
        action=DeprecatedAlias,
        help=argparse.SUPPRESS,
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
    warn_deprecated(args)
    cfg_path: Path = args.config
    if not cfg_path.exists():
        print(f"Config file not found: {cfg_path}", file=sys.stderr)
        return 1

    cast_filter: list[int] | None = args.only

    # ------------------------------------------------------------------ process
    # Run the pipeline stages across every configured source (CTD + LADCP): a
    # stage ingests/compiles both when both are configured, so there is no
    # separate LADCP step here.
    import yaml

    from ctdcast.config.parameters import CAST_TAG_WIDTH
    from ctdcast.processors import process as _process

    with open(cfg_path) as _f:
        _data = (yaml.safe_load(_f) or {}).get("data") or {}
    # cast_filter may be a single int (from --cast) or a list (from --only).
    _cast_nums = (
        [cast_filter]
        if isinstance(cast_filter, int)
        else list(cast_filter)
        if cast_filter
        else []
    )
    _cast_tags = {f"{c:0{CAST_TAG_WIDTH}d}" for c in _cast_nums} or None

    if cast_filter is not None and args.ctd:
        # Single-cast + --ctd: re-ingest that one cast only, skip the cruise compile.
        stages: list[str] = ["stage1"]
    elif cast_filter is None:
        # Full run: compile products, ingesting raw first when --ctd is set.
        stages = ["stage1", "profiles"] if args.ctd else ["profiles"]
    else:
        # Single cast, no --ctd: skip processing, just regenerate the HTML.
        stages = []

    if stages:
        print("=== process ===")
        try:
            _process(
                stage=stages,
                cnv_dir=_data.get("cnv_dir"),
                nc_dir=_data.get("nc_dir"),
                profiles_path=_data.get("profiles_nc"),
                ladcp_dir=_data.get("ladcp_dir"),
                ladcp_nc_dir=_data.get("ladcp_nc"),
                ladcp_profiles_path=_data.get("ladcp_profiles_nc"),
                force=args.force,
                dry_run=args.dry_run,
                cast_tags=_cast_tags,
                pattern=_data.get("cnv_pattern") or "*.cnv",
                ladcp_pattern=_data.get("ladcp_pattern"),
            )
        except (ValueError, OSError, ImportError) as exc:
            print(f"process error: {exc}", file=sys.stderr)
            return 1

    # ------------------------------------------------------------------ report
    from . import report as _report

    report_ns = argparse.Namespace(
        config=cfg_path,
        casts=False,
        sections=False,
        timeseries=False,
        index=False,
        map=False,
        all_pages=False,
        only=cast_filter,
        force=args.force,
        skip_existing=args.skip_existing,
        dry_run=args.dry_run,
        sal=None,
        trim_soak=args.trim_soak,
        dbar_step=1,
        # run is the everyday verb: keep failed figures loud (visible stubs).
        # Opt into dropping them with the granular `report --drop-stub`.
        drop_stub=False,
    )

    print("=== report ===")
    return _report.run(report_ns)
