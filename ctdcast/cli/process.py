"""``ctdcast process`` — run CTD processing pipeline stages."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from ctdcast.processors import STAGES

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
  ctdcast process config.yaml --stage 1 --cast 42 --force
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
        "--cast",
        type=int,
        nargs="+",
        metavar="N",
        default=None,
        help="Process only these cast number(s). Applies to stages 1–3."
        " Example: --cast 42  or  --cast 42 43 44",
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
    cfg_path: Path = args.config
    if not cfg_path.exists():
        print(f"Config not found: {cfg_path}", file=sys.stderr)
        return 1

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f) or {}
    data = cfg.get("data") or {}
    processing_cfg = cfg.get("processing") or {}

    nc_dir_raw = data.get("nc_dir")
    if not nc_dir_raw:
        print("Config error: data.nc_dir is required.", file=sys.stderr)
        return 1
    nc_dir = Path(nc_dir_raw)

    cnv_dir = Path(data["cnv_dir"]) if data.get("cnv_dir") else None
    profiles_path = Path(data["profiles_nc"]) if data.get("profiles_nc") else None

    # Deduplicate and force canonical order
    requested = [s for s in _STAGE_CHOICES if s in args.stage]

    # Cast filter: set of zero-padded 3-digit tags, or None for all
    cast_tags: set[str] | None = {f"{c:03d}" for c in args.cast} if args.cast else None

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

    rc = 0
    for stage in requested:
        if stage == "1":
            rc |= _run_stage1(args, cnv_dir, nc_dir, cast_tags, data, processing_cfg)
        elif stage == "2":
            rc |= _run_stage2(args, nc_dir, processing_cfg, cast_tags)
        elif stage == "3":
            rc |= _run_stage3(args, nc_dir, processing_cfg, cast_tags)
        elif stage == "profiles":
            rc |= _run_profiles(args, nc_dir, profiles_path)
    return rc


def _run_stage1(
    args: argparse.Namespace,
    cnv_dir: Path,
    nc_dir: Path,
    cast_tags: set[str] | None,
    data: dict,
    processing_cfg: dict,  # noqa: ARG001
) -> int:
    """Stage 1: CNV → per-cast netCDF."""
    from ctdcast.processors.stage1 import stage1

    cfg_pattern: str = data.get("cnv_pattern") or "*.cnv"
    pattern = args.pattern or cfg_pattern

    # cast_tags → cast_filter int if exactly one cast requested, else list
    cast_filter = None
    if cast_tags is not None:
        cast_filter = [int(t) for t in cast_tags]
        if len(cast_filter) == 1:
            cast_filter = cast_filter[0]

    if args.dry_run:
        print(
            f"[dry-run] stage 1: {cnv_dir} → {nc_dir}"
            f"  (backend={args.backend}, pattern={pattern})"
        )
        return 0

    try:
        n = stage1(
            cnv_dir,
            nc_dir,
            backend=args.backend,
            force=args.force,
            cast_filter=cast_filter,
            pattern=pattern,
        )
    except (NotImplementedError, ImportError) as exc:
        print(f"stage 1 error: {exc}", file=sys.stderr)
        return 1
    print(f"stage 1: converted {n} cast(s).")
    return 0


def _run_stage2(
    args: argparse.Namespace,
    nc_dir: Path,
    processing_cfg: dict,
    cast_tags: set[str] | None,
) -> int:
    """Stage 2: flag pre-soak and post-recovery records."""
    import xarray as xr

    from ctdcast.processors.stage2 import apply_stage2
    from ctdcast.writers.netcdf import write

    if not nc_dir.exists():
        print(f"nc_dir not found: {nc_dir}", file=sys.stderr)
        return 1

    # Build stage-2 kwargs: CLI overrides > config > processor defaults
    trim_cfg = processing_cfg.get("trim") or {}
    kw: dict = {
        "near_surface_dbar": args.near_surface_dbar
        or trim_cfg.get("near_surface_dbar", 10.0),
        "search_seconds": args.search_seconds or trim_cfg.get("search_seconds", 20.0),
        "deck_window_seconds": args.deck_window_seconds
        or trim_cfg.get("deck_window_seconds", 20.0),
        "margin_dbar": args.margin_dbar or trim_cfg.get("margin_dbar", 0.5),
        "max_deck_dbar": args.max_deck_dbar or trim_cfg.get("max_deck_dbar", 20.0),
    }

    nc_files = _filter_nc_files(nc_dir, cast_tags)
    if not nc_files:
        print("stage 2: no netCDF files matched.", file=sys.stderr)
        return 1

    n = 0
    for nc_path in nc_files:
        if args.dry_run:
            print(f"  [dry-run] stage 2 would flag: {nc_path.name}")
            continue
        try:
            ds = xr.open_dataset(nc_path, engine="netcdf4").load()
            already_flagged = any(v.endswith("_qc") for v in ds.data_vars)
            if already_flagged and not args.force:
                print(f"  skip (already flagged): {nc_path.name}")
                ds.close()
                continue
            ds_out = apply_stage2(ds, **kw)
            ds.close()
            write(ds_out, nc_path)
            print(f"  ok: {nc_path.name}")
            n += 1
        except Exception as exc:  # noqa: BLE001
            print(
                f"  FAILED: {nc_path.name}  ({type(exc).__name__}: {exc})",
                file=sys.stderr,
            )
    if not args.dry_run:
        print(f"stage 2: {n}/{len(nc_files)} file(s) updated.")
    return 0


def _run_stage3(
    args: argparse.Namespace,
    nc_dir: Path,
    processing_cfg: dict,
    cast_tags: set[str] | None,
) -> int:
    """Stage 3: gross-range QC and conductivity calibration."""
    import xarray as xr

    from ctdcast.processors.stage3 import stage3
    from ctdcast.writers.netcdf import write

    if not nc_dir.exists():
        print(f"nc_dir not found: {nc_dir}", file=sys.stderr)
        return 1

    nc_files = _filter_nc_files(nc_dir, cast_tags)
    if not nc_files:
        print("stage 3: no netCDF files matched.", file=sys.stderr)
        return 1

    n = 0
    for nc_path in nc_files:
        if args.dry_run:
            print(f"  [dry-run] stage 3 would process: {nc_path.name}")
            continue
        try:
            ds = xr.open_dataset(nc_path, engine="netcdf4").load()
            ds_out = stage3(ds, cruise_cfg=processing_cfg)
            ds.close()
            write(ds_out, nc_path)
            print(f"  ok: {nc_path.name}")
            n += 1
        except Exception as exc:  # noqa: BLE001
            print(
                f"  FAILED: {nc_path.name}  ({type(exc).__name__}: {exc})",
                file=sys.stderr,
            )
    if not args.dry_run:
        print(f"stage 3: {n}/{len(nc_files)} file(s) updated.")
    return 0


def _run_profiles(
    args: argparse.Namespace,
    nc_dir: Path,
    profiles_path: Path,
) -> int:
    """Stage profiles: bin per-cast netCDF to profiles.nc."""
    from ctdcast.processors.profiles import build_profiles

    if args.dry_run:
        print(f"[dry-run] profiles: {nc_dir} → {profiles_path}")
        return 0

    try:
        wrote = build_profiles(
            nc_dir, profiles_path, force=args.force, gebco_path=args.gebco
        )
    except ValueError as exc:
        print(f"profiles error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"profiles error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if wrote:
        print(f"profiles: wrote {profiles_path}")
    else:
        print(
            f"profiles: skipped (already exists; use --force to overwrite): {profiles_path}"
        )
    return 0


def _filter_nc_files(nc_dir: Path, cast_tags: set[str] | None) -> list[Path]:
    """Return sorted .nc files in *nc_dir*, optionally filtered by *cast_tags*."""
    files = sorted(nc_dir.glob("*.nc"))
    if cast_tags is not None:
        files = [p for p in files if any(t in p.stem for t in cast_tags)]
    return files
