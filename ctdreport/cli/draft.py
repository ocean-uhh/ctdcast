"""``ctdreport draft`` — quick-look CNV → HTML pipeline with no config file required."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdreport draft``."""
    _epilog = """
Converts raw CNV files to netCDF via seasenselib, then generates station pages,
an index page, and a Leaflet map — all in one step with no config.yaml required.
Sections and time-series pages are skipped (they need a compiled profiles.nc).

Examples:
  # Quick look at today's casts:
  ctdreport draft /data/cnv/ ./draft_out/

  # Keep the intermediate netCDF files for later use:
  ctdreport draft /data/cnv/ ./draft_out/ --keep-nc ./nc_out/

  # Tag the report with a cruise ID:
  ctdreport draft /data/cnv/ --cruise odb2026

  # See what would happen without writing anything:
  ctdreport draft /data/cnv/ --dry-run

  # Process only 1 Hz files (skip 24 Hz or other variants):
  ctdreport draft /data/cnv/ --pattern "msm*1sec.cnv"

  # Exclude pre-soak and anomalous records by salinity bounds:
  ctdreport draft /data/cnv/ --sal 30 36

  # Auto-detect and strip the CTD soak (pump-on window + near-surface dip):
  ctdreport draft /data/cnv/ --trim-soak
"""
    kwargs: dict = {
        "description": (
            "Convert raw CNV files and generate station pages + index + map "
            "(no config file required)."
        ),
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": _epilog,
    }
    if subparsers is not None:
        parser = subparsers.add_parser(
            "draft",
            help="Quick-look: CNV → station pages + index + map (no config needed).",
            **kwargs,
        )
        parser.set_defaults(func=run)
    else:
        parser = argparse.ArgumentParser(prog="ctdreport draft", **kwargs)

    parser.add_argument(
        "cnv_dir",
        type=Path,
        help="Directory of raw SBE CNV files.",
    )
    parser.add_argument(
        "out_dir",
        type=Path,
        nargs="?",
        default=Path("ctd_draft/"),
        help="Output directory (default: ./ctd_draft/).",
    )
    parser.add_argument(
        "--cruise",
        metavar="ID",
        default=None,
        help="Cruise ID shown in the report header (default: read from nc attrs, fallback 'draft').",
    )
    parser.add_argument(
        "--ship",
        metavar="NAME",
        default=None,
        help="Ship name shown in the report header.",
    )
    parser.add_argument(
        "--keep-nc",
        type=Path,
        metavar="DIR",
        default=None,
        help="Save converted netCDF files to DIR instead of discarding after the run.",
    )
    parser.add_argument(
        "--pattern",
        metavar="GLOB",
        default="*.cnv",
        help="Filename glob pattern for CNV files within cnv_dir (default: '*.cnv').",
    )
    parser.add_argument(
        "--sal",
        nargs=2,
        type=float,
        metavar=("MIN", "MAX"),
        default=None,
        help=(
            "Salinity range [MIN MAX] for plot trimming.  Records with salinity_1 "
            "outside this range are excluded from all station page plots "
            "(NC files are not modified).  Example: --sal 30 36"
        ),
    )
    parser.add_argument(
        "--trim-soak",
        action="store_true",
        default=False,
        help=(
            "Auto-detect and strip the pre-soak window from each cast: cuts at least "
            "the first 60 s (pump activation) and any records up to the last time the "
            "CTD was within 2 dbar of the surface after pump-on.  NC files are not "
            "modified; only plots are affected."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Regenerate existing pages regardless of file modification times.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be done without writing any files.",
    )

    return parser


def run(args: argparse.Namespace) -> int:
    """Execute ``ctdreport draft``."""
    import tempfile

    cnv_dir: Path = args.cnv_dir
    out_dir: Path = args.out_dir

    if not cnv_dir.exists():
        print(f"Error: CNV directory not found: {cnv_dir}", file=sys.stderr)
        return 1

    cnv_files = list(cnv_dir.glob(args.pattern))
    if not cnv_files:
        print(
            f"Error: No files matching '{args.pattern}' found in {cnv_dir}",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        nc_dir_display = args.keep_nc if args.keep_nc else Path("<tempdir>")
        print(f"[dry-run] cnv_dir:  {cnv_dir}")
        print(f"[dry-run] pattern:  {args.pattern} ({len(cnv_files)} files matched)")
        print(f"[dry-run] nc_dir:   {nc_dir_display}")
        print(f"[dry-run] out_dir:  {out_dir}")
        print(f"[dry-run] cruise:   {args.cruise or '(from nc attrs)'}")
        print(f"[dry-run] ship:     {args.ship or '(none)'}")
        print(f"[dry-run] force:    {args.force}")
        print(
            "[dry-run] generate: stations=True, index=True, map=True, "
            "sections=False, timeseries=False"
        )
        return 0

    try:
        from ctdreport.converters import get_ctd_backend

        get_ctd_backend("seasenselib")
    except ImportError as exc:
        print(
            f"Error: {exc}\n"
            "Install seasenselib to use ctdreport draft:\n"
            "  pip install seasenselib",
            file=sys.stderr,
        )
        return 1

    cruise_info: dict[str, str] = {}
    if args.cruise:
        cruise_info["cruise_id"] = args.cruise
    if args.ship:
        cruise_info["ship"] = args.ship

    _gen = {
        "stations": True,
        "sections": False,
        "timeseries": False,
        "index": True,
        "map": True,
    }

    sal_range: tuple[float, float] | None = (
        (args.sal[0], args.sal[1]) if args.sal else None
    )
    trim_soak: bool = args.trim_soak

    if args.keep_nc:
        nc_dir: Path = args.keep_nc
        nc_dir.mkdir(parents=True, exist_ok=True)
        return _run_pipeline(
            cnv_dir,
            nc_dir,
            out_dir,
            _gen,
            cruise_info or None,
            args.force,
            args.pattern,
            sal_range,
            trim_soak,
        )

    with tempfile.TemporaryDirectory(prefix="ctdreport_draft_") as _tmp:
        nc_dir = Path(_tmp)
        return _run_pipeline(
            cnv_dir,
            nc_dir,
            out_dir,
            _gen,
            cruise_info or None,
            args.force,
            args.pattern,
            sal_range,
            trim_soak,
        )


def _run_pipeline(
    cnv_dir: Path,
    nc_dir: Path,
    out_dir: Path,
    gen: dict[str, bool],
    cruise_info: dict[str, str] | None,
    force: bool,
    pattern: str = "*.cnv",
    sal_range: tuple[float, float] | None = None,
    trim_soak: bool = False,
) -> int:
    """Convert CNV files then generate HTML; return exit code."""
    from ctdreport.converters import build_profiles, convert_ctd_files
    from ctdreport.index import generate_ctd_report

    n = convert_ctd_files(
        cnv_dir, nc_dir, backend="seasenselib", force=force, pattern=pattern
    )
    if n == 0 and not any(nc_dir.glob("*.nc")):
        print(
            "Warning: no casts converted and nc_dir is empty — nothing to report.",
            file=sys.stderr,
        )
        return 1

    # Build profiles.nc so that the index page shows color section panels.
    _ppath = nc_dir / "profiles.nc"
    profiles_path: Path | None
    try:
        build_profiles(nc_dir, _ppath, force=force)
        profiles_path = _ppath
        print(f"  profiles: {profiles_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"  profiles: skipped ({exc})")
        profiles_path = None

    generate_ctd_report(
        nc_dir,
        out_dir,
        profiles_path=profiles_path,
        generate=gen,
        force=force,
        cruise_info=cruise_info,
        sal_range=sal_range,
        trim_soak=trim_soak,
    )
    print(f"Done. Open {out_dir / 'index.html'}")
    return 0
