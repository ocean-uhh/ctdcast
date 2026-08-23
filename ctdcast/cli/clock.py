"""``ctdcast clock`` — diagnose the acquisition-clock error for a cruise and suggest a correction."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdcast clock``."""
    _epilog = """
Reads every stage-1 cast under the config's ctd_root, compares each cast's
System (acquisition) clock against its NMEA (GPS) clock, and classifies the
cruise: a constant offset, a step change (one row per segment), a drift, or
too little to tell.  It moves nothing -- it prints the verdict and a paste-ready
'processing.clock' block for config.yaml; applying it is a stage-2 step.

Examples:
  # Diagnose and print the verdict + suggested config:
  ctdcast clock config.yaml

  # Also write the offset-vs-cast figure to eyeball the segmentation:
  ctdcast clock config.yaml --figure clock_offsets.png
"""
    kwargs: dict = {
        "description": "Diagnose the acquisition-clock error for a cruise.",
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": _epilog,
    }
    if subparsers is not None:
        parser = subparsers.add_parser(
            "clock",
            help="Diagnose the acquisition-clock error for a cruise.",
            **kwargs,
        )
        parser.set_defaults(func=run)
    else:
        parser = argparse.ArgumentParser(prog="ctdcast clock", **kwargs)

    parser.add_argument("config", type=Path, help="Path to config YAML file.")
    parser.add_argument(
        "-f",
        "--figure",
        type=Path,
        metavar="PNG",
        default=None,
        help="Also write the offset-vs-cast figure to this path.",
    )
    return parser


def _print_segments(segments: list) -> None:
    """Print the segment table (one row per level) to stdout."""
    print("\nSegments:")
    print(f"  {'casts':<10} {'first cast (UTC)':<19} {'offset':>8} {'sd':>6} {'n':>5}")
    for seg in segments:
        print(
            f"  {seg.cast_range:<10} {seg.start:%Y-%m-%d %H:%M}   "
            f"{seg.offset_seconds:>+7.2f} {seg.sd_seconds:>6.2f} {seg.n_casts:>5}"
        )


def run(args: argparse.Namespace) -> int:
    """Execute ``ctdcast clock``."""
    import yaml

    from ctdcast.analysis.clock import (
        classify_offsets,
        clock_offsets,
        coordinate_summary,
        correction_status,
        suggested_config_yaml,
    )

    cfg_path: Path = args.config
    if not cfg_path.exists():
        print(f"Config file not found: {cfg_path}", file=sys.stderr)
        return 1
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f) or {}

    data = cfg.get("data") or {}
    root_raw = data.get("ctd_root") or data.get("nc_dir")
    if not root_raw:  # unset root must fail here, not fall through to "no clock pairs"
        print("Config error: data.ctd_root is required.", file=sys.stderr)
        return 1
    root = Path(root_raw)
    if not root.exists():
        print(f"Config error: data.ctd_root does not exist: {root}", file=sys.stderr)
        return 1

    series, scanned, coordinate_counts = clock_offsets(root)
    verdict = classify_offsets(series, n_scanned=scanned)

    print(
        f"Clock diagnostic — {scanned} cast(s) scanned, {len(series)} with a clock pair."
    )
    print(coordinate_summary(coordinate_counts, scanned))
    print(f"Verdict: {verdict.kind}")
    print(f"  {verdict.note}")
    if verdict.resolution_caveat:
        print(f"  Caveat: {verdict.resolution_caveat}")
    if verdict.segments:
        _print_segments(verdict.segments)

    snippet = suggested_config_yaml(verdict)
    status = correction_status(coordinate_counts)
    if snippet is not None and status == "on_gps":
        print(
            "\nNo correction suggested — the coordinate is already on GPS (NMEA); the measured "
            "offset is a comparison artefact and is not applied."
        )
    elif snippet is not None and status == "undetermined":
        print(
            "\nNo correction suggested — the time-coordinate source could not be determined from "
            "the headers (no start_time bracket), so whether a correction applies is unknown."
        )
    elif snippet is not None:  # status == "apply"
        current = (cfg.get("processing") or {}).get("clock")
        current_desc = current if current else "{} (no correction configured)"
        print(f"\nCurrent processing.clock in {cfg_path.name}: {current_desc}")
        print(
            f"\nSuggested — paste into {cfg_path.name}, then re-run "
            f"`ctdcast process {cfg_path.name} --stage 2 --force`:\n"
        )
        print(snippet)

    if args.figure is not None:
        if verdict.segments:
            _write_figure(series, verdict, args.figure)
            print(f"\nWrote figure: {args.figure}")
        else:
            print(
                f"\nNo figure written: {verdict.kind} has nothing to plot.",
                file=sys.stderr,
            )
    return 0


def _write_figure(series: list, verdict: object, path: Path) -> None:
    """Render the offset-vs-cast figure under the report style and save it to *path*."""
    import matplotlib.pyplot as plt

    from ctdcast.config.report_tokens import FIG_DPI, MPLSTYLE_PATH
    from ctdcast.plotters.plots import draw_clock_offset_fig

    with plt.style.context(str(MPLSTYLE_PATH)):
        fig = draw_clock_offset_fig(series, verdict)
        if fig is not None:
            fig.savefig(path, dpi=FIG_DPI, bbox_inches="tight")
            plt.close(fig)
