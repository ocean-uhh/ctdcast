"""``ctdcast run`` — convert profiles and generate HTML reports in one step."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ctdcast.cli._deprecate import DeprecatedAlias, warn_deprecated
from ctdcast.cli.process import _STAGE_METAVAR, _stage_token


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdcast run``."""
    _epilog = """
Equivalent to running ``ctdcast process`` then ``ctdcast report`` in sequence.
By default runs every stage (1 2 3 profiles) across every configured source,
then generates HTML. Narrow with --stage; both steps are mtime-smart.

Examples:
  # Full pipeline (all stages, all sources) then reports:
  ctdcast run config.yaml

  # Compile profiles from existing per-cast files, then report (skip raw ingest):
  ctdcast run config.yaml --stage profiles

  # Ingest + compile, skipping QC:
  ctdcast run config.yaml --stage 1 profiles

  # Rebuild everything:
  ctdcast run config.yaml --force

  # Regenerate one cast page (cast-scope stages only, profiles skipped):
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
        "--stage",
        nargs="+",
        type=_stage_token,
        metavar=_STAGE_METAVAR,
        default=None,
        help="Processing stage(s) to run before reporting, across every configured"
        " source (default: all — 1 2 3 profiles). E.g. --stage profiles to only"
        " compile and report.",
    )
    parser.add_argument(
        "--ctd",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,  # deprecated: `run` now ingests raw by default
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

    if args.ctd:
        print(
            "NOTE: 'ctdcast run --ctd' is deprecated; run now ingests raw by default."
            " Use '--stage 1 profiles' to skip QC, or '--stage profiles' to skip"
            " ingest.",
            file=sys.stderr,
        )

    # ------------------------------------------------------------------ process
    # Run the pipeline stages across every configured source (CTD + LADCP): a
    # stage ingests/compiles both when both are configured, so there is no
    # separate LADCP step here.
    import yaml

    from ctdcast.config.parameters import CAST_TAG_WIDTH
    from ctdcast.config.sensors import SensorOverrides
    from ctdcast.processors import process as _process
    from ctdcast.processors import stages_for

    with open(cfg_path) as _f:
        _cfg = yaml.safe_load(_f) or {}
    _data = _cfg.get("data") or {}
    _processing = _cfg.get("processing") or {}
    # --only/--cast use nargs='+', so cast_filter is a list or None.
    _cast_tags = (
        {f"{c:0{CAST_TAG_WIDTH}d}" for c in cast_filter} if cast_filter else None
    )

    # Default (no --stage) runs every stage; --stage narrows.  With --only we
    # process just those casts, so cruise-scope stages (profiles) are skipped —
    # a single-cast profile compile is not meaningful.
    _stages = stages_for(args.stage)
    if cast_filter is not None:
        _stages = tuple(s for s in _stages if s.scope == "cast")
    stages = [s.name for s in _stages]

    if stages:
        print("=== process ===")
        try:
            _process(
                stage=stages,
                cnv_dir=_data.get("cnv_dir"),
                # Roots first; the legacy keys follow and `process` applies the
                # same precedence as StagePaths.from_config.
                ctd_root=_data.get("ctd_root"),
                ladcp_root=_data.get("ladcp_root"),
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
                profiles_dbar=int(_processing.get("profiles_dbar", 1)),
                sensor_overrides=SensorOverrides.from_cruise_config(_cfg),
                cruise_info=_cfg.get("cruise_info") or {},
            )
        except (ValueError, OSError, ImportError, NotImplementedError) as exc:
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
