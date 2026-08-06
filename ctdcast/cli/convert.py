"""``ctdcast convert`` — convert raw CTD data to netCDF report inputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdcast convert``."""
    _epilog = """
Default (no step flag): runs --profiles only if data.profiles_nc is configured.
  --ctd must be requested explicitly; it requires an external backend.
  --ladcp is not yet implemented.

Examples:
  # Build profiles.nc from existing per-cast netCDF files (most common):
  ctdcast convert config.yaml

  # Same, explicit:
  ctdcast convert config.yaml --profiles

  # CNV → per-cast netCDF using seasenselib (default backend), then profiles:
  ctdcast convert config.yaml --ctd
  ctdcast convert config.yaml --profiles

  # Force reprocess a single cast:
  ctdcast convert config.yaml --ctd --cast 42 --force

  # Convert only 1 Hz files (skip 24 Hz variants):
  ctdcast convert config.yaml --ctd --pattern "msm*1sec.cnv"
"""
    kwargs: dict = {
        "description": "Convert raw CTD (CNV) files to netCDF inputs for ctdcast report.",
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": _epilog,
    }
    if subparsers is not None:
        parser = subparsers.add_parser(
            "convert",
            help="Convert raw CTD (CNV) files to netCDF.",
            **kwargs,
        )
        parser.set_defaults(func=run)
    else:
        parser = argparse.ArgumentParser(prog="ctdcast convert", **kwargs)

    parser.add_argument("config", type=Path, help="Path to config YAML file.")

    # Step selection
    steps = parser.add_argument_group("step selection")
    steps.add_argument(
        "--ctd",
        action="store_true",
        default=False,
        help="Convert per-cast CNV files to netCDF (requires data.cnv_dir in config).",
    )
    steps.add_argument(
        "--profiles",
        action="store_true",
        default=False,
        help="Compile per-cast netCDF files into profiles.nc (requires data.profiles_nc in config).",
    )
    steps.add_argument(
        "--ladcp",
        action="store_true",
        default=False,
        help="Convert LADCP data (not yet implemented).",
    )

    # Backend (applies only to --ctd)
    parser.add_argument(
        "--backend",
        choices=["seasenselib"],
        default="seasenselib",
        metavar="NAME",
        help="CTD conversion backend for --ctd (currently only 'seasenselib').",
    )

    # Per-cast targeting
    parser.add_argument(
        "--cast",
        type=int,
        metavar="N",
        default=None,
        help="Convert only the CNV file for cast N (implies --ctd).",
    )
    parser.add_argument(
        "--pattern",
        metavar="GLOB",
        default="*.cnv",
        help="Filename glob pattern for CNV files (default: '*.cnv'). Applies to --ctd only.",
    )

    # Run behaviour
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing output files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be converted without writing any files.",
    )

    return parser


def run(args: argparse.Namespace) -> int:
    """Execute ``ctdcast convert``."""
    cfg_path: Path = args.config
    if not cfg_path.exists():
        print(f"Config file not found: {cfg_path}", file=sys.stderr)
        return 1

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    data = cfg.get("data") or {}

    nc_dir_raw = data.get("nc_dir")
    if not nc_dir_raw:
        print("Config error: data.nc_dir is required.", file=sys.stderr)
        return 1
    nc_dir = Path(nc_dir_raw)

    cnv_dir_raw = data.get("cnv_dir")
    # If cnv_dir contains a wildcard (e.g. "/path/msm*1sec.cnv"), split into
    # parent directory and pattern so that older configs keep working.
    if cnv_dir_raw and ("*" in cnv_dir_raw or "?" in cnv_dir_raw):
        _cnv_path = Path(cnv_dir_raw)
        if not _cnv_path.is_dir():
            if args.pattern == "*.cnv":
                args.pattern = _cnv_path.name
            cnv_dir_raw = str(_cnv_path.parent)
    # data.cnv_pattern overrides the CLI default ('*.cnv') but is itself overridden
    # when the user passes an explicit --pattern on the command line.
    cfg_pattern: str = data.get("cnv_pattern") or "*.cnv"
    if args.pattern == "*.cnv":
        args.pattern = cfg_pattern
    profiles_nc_raw = data.get("profiles_nc")
    profiles_path = Path(profiles_nc_raw) if profiles_nc_raw else None

    # Resolve which steps to run
    if args.cast is not None:
        run_ctd, run_profiles, run_ladcp = True, False, False
    elif any([args.ctd, args.profiles, args.ladcp]):
        run_ctd, run_profiles, run_ladcp = args.ctd, args.profiles, args.ladcp
    else:
        # Default: only build profiles — CTD conversion requires explicit --ctd
        # (it needs an external backend and is not the common case).
        run_ctd = False
        run_profiles = bool(profiles_nc_raw)
        run_ladcp = False

    if run_ladcp:
        print("--ladcp is not yet implemented.", file=sys.stderr)
        return 1

    if run_ctd and not cnv_dir_raw:
        print(
            "Config error: data.cnv_dir is required for --ctd. "
            "Add it to config.yaml and point it at your raw CNV directory.",
            file=sys.stderr,
        )
        return 1

    if run_profiles and not profiles_nc_raw:
        print(
            "Config error: data.profiles_nc is required for --profiles.",
            file=sys.stderr,
        )
        return 1

    cnv_dir = Path(cnv_dir_raw) if cnv_dir_raw else None

    if args.dry_run:
        print(f"[dry-run] config:    {cfg_path}")
        if run_ctd:
            print(
                f"[dry-run] --ctd:     {cnv_dir} → {nc_dir}  "
                f"(backend={args.backend}, pattern={args.pattern})"
            )
        if run_profiles:
            print(f"[dry-run] --profiles: {nc_dir} → {profiles_path}")
        if args.cast is not None:
            print(f"[dry-run] --cast {args.cast}: single-cast only")
        print(f"[dry-run] force={args.force}")
        return 0

    from ctdcast.converters import build_profiles, convert_ctd_files

    if run_ctd:
        assert cnv_dir is not None
        try:
            n = convert_ctd_files(
                cnv_dir,
                nc_dir,
                backend=args.backend,
                force=args.force,
                cast_filter=args.cast,
                pattern=args.pattern,
            )
        except (NotImplementedError, ImportError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Converted {n} cast(s).")

    if run_profiles:
        assert profiles_path is not None
        try:
            written = build_profiles(nc_dir, profiles_path, force=args.force)
        except NotImplementedError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        if written:
            print(f"Built profiles.nc → {profiles_path}")
        else:
            print("Skipped (profiles.nc already exists; use --force to rebuild).")

    return 0
