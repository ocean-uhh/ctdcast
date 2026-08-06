"""``ctdcast report`` — generate HTML report pages."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdcast report``."""
    _epilog = """
If any page-type flag is given, only those page types are built.
With no flags, all page types are built (respecting config generate.* values).

Examples:
  # Smart update — only rebuild pages whose source is newer than the output:
  ctdcast report config.yaml

  # Force-rebuild everything:
  ctdcast report config.yaml --force

  # Quick check of a single new cast:
  ctdcast report config.yaml --cast 42

  # Rebuild section and time series pages after adding 10 new casts:
  ctdcast report config.yaml --sections --timeseries --force
"""
    kwargs: dict = {
        "description": "Generate HTML report pages from a config file.",
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": _epilog,
    }
    if subparsers is not None:
        parser = subparsers.add_parser(
            "report",
            help="Generate HTML report pages from a config file.",
            **kwargs,
        )
        parser.set_defaults(func=run)
    else:
        parser = argparse.ArgumentParser(prog="ctdcast report", **kwargs)

    parser.add_argument("config", type=Path, help="Path to config YAML file.")

    # Page-type selection
    page = parser.add_argument_group("page selection")
    page.add_argument(
        "--stations",
        action="store_true",
        default=False,
        help="Generate per-cast station pages.",
    )
    page.add_argument(
        "--sections",
        action="store_true",
        default=False,
        help="Generate transect section pages.",
    )
    page.add_argument(
        "--timeseries",
        action="store_true",
        default=False,
        help="Generate cruise-wide time series page.",
    )
    page.add_argument(
        "--index",
        action="store_true",
        default=False,
        help="Generate navigation pages (index.html, station_index.html, sections.html).",
    )
    page.add_argument(
        "--map",
        action="store_true",
        default=False,
        help="Generate interactive Leaflet map page.",
    )

    # Per-cast targeting
    parser.add_argument(
        "--cast",
        type=int,
        nargs="+",
        metavar="N",
        default=None,
        help="Rebuild station pages for one or more cast numbers (implies --stations). "
        "Example: --cast 42  or  --cast 42 43 44",
    )

    parser.add_argument(
        "--sal",
        nargs=2,
        type=float,
        metavar=("MIN", "MAX"),
        default=None,
        help=(
            "Salinity range [MIN MAX] for plot trimming.  Records with salinity_1 "
            "outside this range are excluded from station page plots "
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
        "--dbar-step",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Plot every Nth dbar level from profiles.nc for section and timeseries "
            "figures (default: 1, full 1-dbar resolution).  build_profiles() always "
            "stores 1-dbar data; this controls plot-time resolution only."
        ),
    )

    # Run behaviour
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Regenerate all pages regardless of mtime.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=False,
        help="Skip any page that already exists (old behaviour; ignores mtime).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be generated without writing any files.",
    )

    return parser


def run(args: argparse.Namespace) -> int:
    """Execute ``ctdcast report``."""
    cfg_path: Path = args.config
    if not cfg_path.exists():
        print(f"Config file not found: {cfg_path}", file=sys.stderr)
        return 1

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    data = cfg.get("data") or {}
    output = cfg.get("output") or {}
    display = cfg.get("display") or {}
    # _cruise_info_cfg: local dict for map-bounds lookup (always a dict).
    # cruise_info: passed to report() — None tells report() to use YAML block.
    _cruise_info_cfg: dict = cfg.get("cruise_info") or {}
    cruise_info: dict | None = cfg.get("cruise_info") or None

    nc_dir_raw = data.get("nc_dir")
    out_dir_raw = output.get("dir")
    if not nc_dir_raw:
        print("Config error: data.nc_dir is required.", file=sys.stderr)
        return 1
    if not out_dir_raw:
        print("Config error: output.dir is required.", file=sys.stderr)
        return 1

    nc_dir = Path(nc_dir_raw)
    out_dir = Path(out_dir_raw)

    profiles_path: Path | None = (
        Path(data["profiles_nc"]) if data.get("profiles_nc") else None
    )
    section_yaml: Path | None = (
        Path(data["section_yaml"]) if data.get("section_yaml") else None
    )
    ladcp_dir: Path | None = Path(data["ladcp_dir"]) if data.get("ladcp_dir") else None
    ladcp_pattern: str | None = data.get("ladcp_pattern") or None
    ship_track_nc: Path | None = (
        Path(data["ship_track"]) if data.get("ship_track") else None
    )
    gebco_path: Path | None = Path(data["gebco_nc"]) if data.get("gebco_nc") else None

    # Resolve which page types to generate.
    # CLI flags override config; --cast implies stations-only.
    cli_page_flags = {
        "stations": args.stations,
        "sections": args.sections,
        "timeseries": args.timeseries,
        "index": args.index,
        "map": args.map,
    }
    any_cli_flag = any(cli_page_flags.values())
    gen_cfg = cfg.get("generate", {})

    if args.cast is not None:
        gen: dict[str, bool] = {
            "stations": True,
            "sections": False,
            "timeseries": False,
            "index": False,
            "map": False,
        }
    elif any_cli_flag:
        gen = cli_page_flags
    else:
        gen = {
            "stations": gen_cfg.get("stations", True),
            "sections": gen_cfg.get("sections", True),
            "timeseries": gen_cfg.get("timeseries", True),
            "index": gen_cfg.get("index", True),
            "map": gen_cfg.get("leaflet", True),
        }

    force: bool = args.force or bool(cfg.get("force", False))
    skip_existing: bool = args.skip_existing
    dry_run: bool = args.dry_run

    if dry_run:
        print(f"[dry-run] config: {cfg_path}")
        print(f"[dry-run] nc_dir: {nc_dir}")
        print(f"[dry-run] out_dir: {out_dir}")
        print(f"[dry-run] pages: {[k for k, v in gen.items() if v]}")
        print(f"[dry-run] force={force} skip_existing={skip_existing}")
        if args.cast is not None:
            print(f"[dry-run] --cast {args.cast}: rebuild station page only")
        return 0

    # Set module-level plot options before any figure code is imported.
    from ctdcast.plotters import plots

    if gebco_path:
        plots.GEBCO_PATH = gebco_path
    plots.CLEAN_SPINES = bool(display.get("clean_spines", True))
    pf = display.get("profile_figsize", [7, 10])
    plots.PROFILE_FIGSIZE = (float(pf[0]), float(pf[1]))
    ov = display.get("overview_figsize", [12, 4])
    plots.OVERVIEW_FIGSIZE = (float(ov[0]), float(ov[1]))
    plots._VAR_CMAPS.update(display.get("var_cmaps") or {})
    for attr, key in [
        ("MAP_LAT_MIN", "map_lat_min"),
        ("MAP_LAT_MAX", "map_lat_max"),
        ("MAP_LON_MIN", "map_lon_min"),
        ("MAP_LON_MAX", "map_lon_max"),
    ]:
        val = _cruise_info_cfg.get(key)
        if val is not None:
            setattr(plots, attr, float(val))

    vmin_override: dict = {
        k: v for k, v in (display.get("vmin") or {}).items() if v is not None
    }
    vmax_override: dict = {
        k: v for k, v in (display.get("vmax") or {}).items() if v is not None
    }

    from ctdcast.reports._index import report

    report(
        nc_dir,
        out_dir,
        profiles_path=profiles_path,
        section_yaml=section_yaml,
        ladcp_dir=ladcp_dir,
        ladcp_pattern=ladcp_pattern,
        ship_track_nc=ship_track_nc,
        generate=gen,
        force=force,
        skip_existing=skip_existing,
        section_style=display.get("section_style", "pcolormesh"),
        timeseries_style=display.get("timeseries_style", "pcolormesh"),
        vmin_override=vmin_override,
        vmax_override=vmax_override,
        cruise_info=cruise_info,
        cast_filter=args.cast,
        sal_range=(args.sal[0], args.sal[1]) if args.sal else None,
        trim_soak=args.trim_soak,
        dbar_step=args.dbar_step,
    )
    return 0
