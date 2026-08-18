"""``ctdcast process`` — run CTD processing pipeline stages."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from ctdcast.cli._deprecate import DeprecatedAlias, warn_deprecated

from ctdcast.config.parameters import CAST_TAG_WIDTH
from ctdcast.processors import STAGES, resolve_stage

# Derived from STAGES — single source of truth for the valid stage set and run order.
_STAGE_CHOICES: tuple[str, ...] = tuple(
    str(s.number) if s.number is not None else s.name for s in STAGES
)


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdcast process``."""
    _epilog = """
Processing stages:
  Stage 1: convert CNV files to per-cast netCDF  (reads data.cnv_dir)
  Stage 2: flag pre-soak and post-recovery records with QARTOD flag 4
  Stage 3: gross-range QC and conductivity calibration (reads processing: config)
  profiles: bin per-cast netCDF to profiles.nc on a 1-dbar grid

Paths (nc_dir, cnv_dir, profiles_nc) are read from the config YAML.

Examples:
  ctdcast process config.yaml --stage 1
  ctdcast process config.yaml --stage 2 3
  ctdcast process config.yaml --stage 1 2 3 profiles
  ctdcast process config.yaml --stage profiles
  ctdcast process config.yaml --stage 2 --near-surface-dbar 5
  ctdcast process config.yaml --stage 1 --only 42 --force
  ctdcast process config.yaml --stage profiles --gebco /data/GEBCO_2025.nc
"""
    kwargs: dict = {
        "description": "Run one or more CTD processing pipeline stages.",
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": _epilog,
    }
    if subparsers is not None:
        parser = subparsers.add_parser(
            "process",
            help="Run processing pipeline stages (CNV→NC, QC, calibration, profiles).",
            **kwargs,
        )
        parser.set_defaults(func=run)
    else:
        parser = argparse.ArgumentParser(prog="ctdcast process", **kwargs)

    parser.add_argument("config", type=Path, help="Path to config YAML file.")
    parser.add_argument(
        "--stage",
        nargs="+",
        choices=_STAGE_CHOICES,
        metavar="{1,2,3,profiles}",
        required=True,
        help=(
            "Stage(s) to run. Multiple values run in canonical order (1→2→3→profiles)."
            " Example: --stage 1 2 3 profiles"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing output files.",
    )
    parser.add_argument(
        "--only",
        dest="only",
        type=int,
        nargs="+",
        metavar="N",
        default=None,
        help="Process only these cast number(s). Applies to stages 1–3."
        " Example: --only 42  or  --only 42 43 44",
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
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be done without modifying any files.",
    )

    # Stage 1 options
    s1 = parser.add_argument_group("stage 1 options")
    s1.add_argument(
        "--backend",
        choices=["seasenselib"],
        default="seasenselib",
        metavar="NAME",
        help="CTD conversion backend (default: seasenselib).",
    )
    s1.add_argument(
        "--pattern",
        metavar="GLOB",
        default=None,
        help="Filename glob for CNV files (default: from config or '*.cnv').",
    )

    # Stage 2 tuning — CLI values override config processing.trim.*
    s2 = parser.add_argument_group("stage 2 trim tuning (override config defaults)")
    s2.add_argument(
        "--near-surface-dbar",
        type=float,
        default=None,
        metavar="N",
        help="Pressure threshold for last near-surface crossing (default: 10 dbar).",
    )
    s2.add_argument(
        "--search-seconds",
        type=float,
        default=None,
        metavar="S",
        help="Backward-crawl window for pre-descent surface minimum (default: 20 s).",
    )
    s2.add_argument(
        "--deck-window-seconds",
        type=float,
        default=None,
        metavar="S",
        help="Tail window for on-deck reference pressure estimate (default: 20 s).",
    )
    s2.add_argument(
        "--margin-dbar",
        type=float,
        default=None,
        metavar="N",
        help="Added to on-deck median to form the cut threshold (default: 0.5 dbar).",
    )
    s2.add_argument(
        "--max-deck-dbar",
        type=float,
        default=None,
        metavar="N",
        help="If on-deck median exceeds this, no end-trim is applied (default: 20 dbar).",
    )

    # Profiles options
    sp = parser.add_argument_group("profiles options")
    sp.add_argument(
        "--gebco",
        type=Path,
        default=None,
        metavar="NC",
        help="Path to GEBCO_2025.nc for bathymetry depth at each cast position.",
    )

    return parser


def run(args: argparse.Namespace) -> int:
    """Execute ``ctdcast process``."""
    warn_deprecated(args)
    cfg_path: Path = args.config
    if not cfg_path.exists():
        print(f"Config not found: {cfg_path}", file=sys.stderr)
        return 1

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f) or {}
    data = cfg.get("data") or {}
    processing_cfg = cfg.get("processing") or {}
    trim_cfg = processing_cfg.get("trim") or {}

    nc_dir_raw = data.get("nc_dir")
    if not nc_dir_raw:
        print("Config error: data.nc_dir is required.", file=sys.stderr)
        return 1
    nc_dir = Path(nc_dir_raw)
    cnv_dir = Path(data["cnv_dir"]) if data.get("cnv_dir") else None
    profiles_path = Path(data["profiles_nc"]) if data.get("profiles_nc") else None
    ladcp_dir = Path(data["ladcp_dir"]) if data.get("ladcp_dir") else None
    ladcp_nc_dir = Path(data["ladcp_nc"]) if data.get("ladcp_nc") else None
    ladcp_profiles_path = (
        Path(data["ladcp_profiles_nc"]) if data.get("ladcp_profiles_nc") else None
    )

    # Deduplicate and force canonical order
    requested = [s for s in _STAGE_CHOICES if s in args.stage]

    # Cast filter: set of zero-padded tags, or None for all
    cast_tags: set[str] | None = (
        {f"{c:0{CAST_TAG_WIDTH}d}" for c in args.only} if args.only else None
    )

    # Pre-flight checks
    if "1" in requested:
        if not cnv_dir:
            print("Config error: data.cnv_dir required for stage 1.", file=sys.stderr)
            return 1
        if not cnv_dir.exists():
            print(f"cnv_dir not found: {cnv_dir}", file=sys.stderr)
            return 1
    if "profiles" in requested and not profiles_path:
        print(
            "Config error: data.profiles_nc required for stage 'profiles'.",
            file=sys.stderr,
        )
        return 1
    if "ladcp" in requested and not (ladcp_dir and ladcp_nc_dir):
        print(
            "Config error: data.ladcp_dir and data.ladcp_nc required for stage 'ladcp'.",
            file=sys.stderr,
        )
        return 1
    if "ladcp-profiles" in requested and not (ladcp_nc_dir and ladcp_profiles_path):
        print(
            "Config error: data.ladcp_nc and data.ladcp_profiles_nc required for "
            "stage 'ladcp-profiles'.",
            file=sys.stderr,
        )
        return 1

    # Per-stage path and tuning kwargs
    stage_kw: dict[str, dict] = {
        "stage1": {
            "cnv_dir": cnv_dir,
            "nc_dir": nc_dir,
            "backend": args.backend,
            "pattern": args.pattern or data.get("cnv_pattern") or "*.cnv",
        },
        "stage2": {
            "nc_dir": nc_dir,
            "near_surface_dbar": (
                args.near_surface_dbar
                if args.near_surface_dbar is not None
                else trim_cfg.get("near_surface_dbar", 10.0)
            ),
            "search_seconds": (
                args.search_seconds
                if args.search_seconds is not None
                else trim_cfg.get("search_seconds", 20.0)
            ),
            "deck_window_seconds": (
                args.deck_window_seconds
                if args.deck_window_seconds is not None
                else trim_cfg.get("deck_window_seconds", 20.0)
            ),
            "margin_dbar": (
                args.margin_dbar
                if args.margin_dbar is not None
                else trim_cfg.get("margin_dbar", 0.5)
            ),
            "max_deck_dbar": (
                args.max_deck_dbar
                if args.max_deck_dbar is not None
                else trim_cfg.get("max_deck_dbar", 20.0)
            ),
        },
        "stage3": {"nc_dir": nc_dir, "cruise_cfg": processing_cfg},
        "profiles": {
            "nc_dir": nc_dir,
            "profiles_path": profiles_path,
            "gebco_path": args.gebco,
        },
        "ladcp": {
            "ladcp_dir": ladcp_dir,
            "ladcp_nc_dir": ladcp_nc_dir,
            "ladcp_pattern": data.get("ladcp_pattern"),
        },
        "ladcp-profiles": {
            "ladcp_nc_dir": ladcp_nc_dir,
            "ladcp_profiles_path": ladcp_profiles_path,
        },
    }

    rc = 0
    for stage_token in requested:
        s = resolve_stage(stage_token)
        try:
            _result = s.run(
                force=args.force,
                dry_run=args.dry_run,
                cast_tags=cast_tags,
                **stage_kw[s.name],
            )
        except (ImportError, NotImplementedError) as exc:
            print(f"{s.name} error: {exc}", file=sys.stderr)
            rc = 1
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"{s.name} error: {type(exc).__name__}: {exc}", file=sys.stderr)
            rc = 1
            continue
        # All summary printing happens inside each stage's run() — nothing to do here.
    return rc
