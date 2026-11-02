"""``ctdcast fit`` — fit alignment and cell thermal mass over a cruise and suggest the config."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdcast fit``."""
    _epilog = """
Reads every stage-2 cast at its native scan rate under the config's ctd_root,
fits the conductivity alignment (salinity spikes in the thermocline, down and
up) and then the cell thermal mass (down/up salinity below processing.fit.ctm_pmin,
default 200 dbar), and writes the cost surfaces to <ctd_root>/fits.nc.  It
changes no stage file: it prints a paste-ready 'processing:' block, and
'ctdcast report' draws corrections_ts.html from fits.nc.

Examples:
  ctdcast fit config.yaml
  ctdcast fit config.yaml --only 11 12 13
"""
    kwargs: dict = {
        "description": "Fit conductivity alignment and cell thermal mass over a cruise.",
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": _epilog,
    }
    if subparsers is not None:
        parser = subparsers.add_parser(
            "fit",
            help="Fit conductivity alignment and cell thermal mass over a cruise.",
            **kwargs,
        )
        parser.set_defaults(func=run)
    else:
        parser = argparse.ArgumentParser(prog="ctdcast fit", **kwargs)
    parser.add_argument("config", type=Path, help="Path to config YAML file.")
    parser.add_argument(
        "--only",
        type=int,
        nargs="+",
        metavar="N",
        default=None,
        help="Fit only these cast number(s). Example: --only 42 43 44",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="List the casts that would be fitted and write nothing.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """Execute ``ctdcast fit``."""
    import yaml

    from ctdcast.config.parameters import CAST_TAG_WIDTH
    from ctdcast.processors.fit import (
        FITS_FILENAME,
        FitSettings,
        fit_cruise,
        suggested_yaml,
        summarise,
    )
    from ctdcast.processors.stage_layout import group_by_cast, matches_tags
    from ctdcast.writers.netcdf import write

    cfg_path: Path = args.config
    if not cfg_path.exists():
        print(f"Config file not found: {cfg_path}", file=sys.stderr)
        return 1
    with cfg_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    data = cfg.get("data") or {}
    root_raw = data.get("ctd_root") or data.get("nc_dir")
    if not root_raw or not Path(root_raw).is_dir():
        print(
            f"Config error: data.ctd_root (or data.nc_dir) is missing or not a directory: {root_raw}",
            file=sys.stderr,
        )
        return 1
    root = Path(root_raw)
    try:
        settings = FitSettings.from_config(cfg.get("processing"))
    except ValueError as exc:
        print(f"Config error: processing.{exc}", file=sys.stderr)
        return 1
    tags = {f"{c:0{CAST_TAG_WIDTH}d}" for c in args.only} if args.only else None
    if args.dry_run:
        ids = [
            c
            for c, files in sorted(group_by_cast(root).items())
            if 2 in files and (tags is None or matches_tags(c, tags))
        ]
        print(
            f"[dry-run] would fit {len(ids)} stage-2 cast(s) and write {root / FITS_FILENAME}"
        )
        return 0
    try:
        fits = fit_cruise(root, settings, cast_tags=tags)
    except FileNotFoundError as exc:
        print(
            f"{exc}; run 'ctdcast process {cfg_path.name} --stage 1 2' first.",
            file=sys.stderr,
        )
        return 1
    out = root / FITS_FILENAME
    write(fits, out)
    skipped = [
        f"{c} ({r})"
        for c, r in zip(fits["cast_id"].values, fits["skipped"].values, strict=True)
        if r
    ]
    print(f"\nWrote {out}: {fits.sizes['cast']} cast(s), {len(skipped)} skipped.")
    for s in skipped[:10]:
        print(f"  skipped {s}")
    summaries = summarise(fits)
    if not summaries:
        print("No cast could be fitted.", file=sys.stderr)
        return 1
    print(
        f"\nSuggested — paste into {cfg_path.name}, then re-run `ctdcast process {cfg_path.name} --stage 3 --force`:\n"
    )
    print(suggested_yaml(summaries))
    return 0
