"""``ctdreport init`` — write config.yaml and optionally ctd_sections_draft.yaml."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

_CONFIG_TEMPLATE = """\
# ctdreport configuration
# Run 'ctdreport validate config.yaml' to check all paths before the first run.

data:
  # Directory containing per-cast netCDF files (one per cast).
  nc_dir: /path/to/ctd/nc

  # Compiled profiles netCDF on a 1 dbar grid (required for sections and timeseries).
  # Build with: ctdreport convert --build-profiles /path/to/nc/ /path/to/profiles.nc
  profiles_nc: /path/to/profiles.nc

  # Sections/timeseries definition file (ctd_sections.yaml).
  section_yaml: /path/to/ctd_sections.yaml

  # LADCP processed output directory (.mat files named NNN.mat).  Optional.
  # ladcp_dir: /path/to/ladcp

  # Ship track netCDF for the Leaflet map background line.  Optional.
  # ship_track: /path/to/ship_track.nc

  # GEBCO bathymetry netCDF for map background.  Optional.
  # gebco_nc: /path/to/GEBCO_2025.nc

output:
  # Root directory for all generated HTML files.
  dir: outputs/ctd_report

# Which page types to generate on a plain 'ctdreport report' run.
# CLI flags (--stations, --sections, etc.) override these at runtime.
generate:
  stations: true
  sections: true
  timeseries: true
  index: true
  leaflet: true

# Cruise metadata displayed in page headers and station cards.
cruise_info:
  name: ""
  ship: ""
  chief_scientist: ""
  start_date: ""
  end_date: ""
  # Bounding box for the station map axes (degrees).  Optional — auto-fit if omitted.
  # map_lat_min: -30
  # map_lat_max: -10
  # map_lon_min: -30
  # map_lon_max: -10

# Figure appearance overrides.  All are optional.
display:
  # Figure style for section and timeseries plots: "pcolormesh" or "contourf".
  section_style: pcolormesh
  timeseries_style: pcolormesh

  # Profile figure size [width_inches, height_inches].
  # profile_figsize: [7, 10]

  # Overview panel figure size [width_inches, height_inches].
  # overview_figsize: [12, 4]

  # Per-variable colormap overrides (variable names as in the netCDF file).
  # var_cmaps:
  #   temperature_1: RdYlBu_r
  #   salinity_1: viridis

  # Per-variable colormap range overrides.
  # vmin:
  #   CT: 0
  # vmax:
  #   CT: 30
"""

_SECTIONS_TEMPLATE = """\
# ctd_sections.yaml — define transect groups and timeseries.
#
# Each entry under 'sections:' groups casts into a named transect page.
# cast_numbers can be individual integers or [first, last] ranges (inclusive).
#
# Each entry under 'timeseries:' groups casts into a cruise-wide property panel.

sections:
  TransectA:
    description: "Transect A — west to east"
    cast_numbers:
      - [1, 10]
    color: "#2e86ab"

# timeseries:
#   AllCasts:
#     description: "All casts"
#     cast_numbers:
#       - [1, 999]
#     color: "#444444"
"""

# Matplotlib tab10 palette — 10 visually distinct colours.
_TAB10_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the forward bearing in [0, 360) degrees from (lat1, lon1) to (lat2, lon2)."""
    dlon = math.radians(lon2 - lon1)
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    x = math.sin(dlon) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _angle_diff(b1: float, b2: float) -> float:
    """Return the smallest unsigned angular difference between two bearings, in [0, 180]."""
    delta = abs(b2 - b1) % 360.0
    return min(delta, 360.0 - delta)


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdreport init``."""
    _epilog = """
Examples:
  ctdreport init                        write template config.yaml here
  ctdreport init cruise/                write config.yaml inside cruise/
  ctdreport init myconfig.yaml          write to a specific filename
  ctdreport init . --sections           also write template ctd_sections.yaml
  ctdreport init . --force              overwrite existing files
  ctdreport init --interactive          prompt for paths; auto-detect sections
  ctdreport init --interactive \\
    --dx-timeseries 5 --dx-section 50  set detection thresholds explicitly
"""
    kwargs: dict = {
        "description": (
            "Write config.yaml and optionally detect sections/timeseries from profiles.nc. "
            "Use --interactive to prompt for real paths."
        ),
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": _epilog,
    }
    if subparsers is not None:
        parser = subparsers.add_parser(
            "init",
            help="Write a commented template config.yaml (--interactive to populate from data).",
            **kwargs,
        )
        parser.set_defaults(func=run)
    else:
        parser = argparse.ArgumentParser(prog="ctdreport init", **kwargs)

    parser.add_argument(
        "dest",
        nargs="?",
        type=Path,
        default=Path("."),
        help=(
            "Destination: a directory (config.yaml written inside) "
            "or an explicit .yaml filename.  Default: current directory."
        ),
    )
    parser.add_argument(
        "--sections",
        action="store_true",
        default=False,
        help="Also write a template ctd_sections.yaml (non-interactive mode only).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing files.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        default=False,
        help=(
            "Prompt for data paths and cruise info.  If profiles.nc is provided, "
            "offers to auto-detect sections and write ctd_sections_draft.yaml."
        ),
    )
    parser.add_argument(
        "--dx-timeseries",
        type=float,
        default=5.0,
        metavar="KM",
        dest="dx_timeseries",
        help=(
            "Maximum straight-line span (km) for a cast group to be classified as "
            "a repeat station (timeseries).  Default: 5 km."
        ),
    )
    parser.add_argument(
        "--dx-section",
        type=float,
        default=50.0,
        metavar="KM",
        dest="dx_section",
        help=(
            "Inter-cast distance (km) that triggers a section break (transit). "
            "Consecutive casts farther apart than this start a new group.  Default: 50 km."
        ),
    )
    parser.add_argument(
        "--max-section-casts",
        type=int,
        default=25,
        metavar="N",
        dest="max_section_casts",
        help=(
            "Maximum number of casts in a single section group.  Stable-heading runs "
            "longer than this are split into consecutive chunks.  Default: 25."
        ),
    )
    parser.add_argument(
        "--max-turn-deg",
        type=float,
        default=45.0,
        metavar="DEG",
        dest="max_turn_deg",
        help=(
            "Maximum heading change (degrees) between consecutive casts within a section. "
            "A larger turn ends the current stable-heading run and starts a new one.  "
            "Default: 45."
        ),
    )
    parser.add_argument(
        "--min-run-casts",
        type=int,
        default=4,
        metavar="N",
        dest="min_run_casts",
        help=(
            "Minimum number of casts for a stable-heading run to be kept as a section or "
            "timeseries group.  Must be >= 3.  Default: 4."
        ),
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """Execute ``ctdreport init``."""
    if hasattr(args, "min_run_casts") and args.min_run_casts < 3:
        print("ERROR: --min-run-casts must be >= 3.", file=sys.stderr)
        return 1
    if args.interactive:
        return _run_interactive(args)

    dest: Path = args.dest
    if dest.suffix in {".yaml", ".yml"}:
        config_path = dest
    else:
        config_path = dest / "config.yaml"

    if config_path.exists() and not args.force:
        print(
            f"ERROR: {config_path} already exists. Use --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    config_path.parent.mkdir(parents=True, exist_ok=True)
    _write_file(config_path, _CONFIG_TEMPLATE)
    print(f"Written: {config_path}")

    if args.sections:
        sections_path = config_path.parent / "ctd_sections.yaml"
        if sections_path.exists() and not args.force:
            print(
                f"ERROR: {sections_path} already exists. Use --force to overwrite.",
                file=sys.stderr,
            )
            return 1
        _write_file(sections_path, _SECTIONS_TEMPLATE)
        print(f"Written: {sections_path}")

    return 0


# --------------------------------------------------------------------------- #
# Interactive mode                                                              #
# --------------------------------------------------------------------------- #


def _prompt(
    label: str, default: str | None = None, required: bool = False
) -> str | None:
    """Print a prompt and return the stripped user input, or *default* on empty.

    Returns ``None`` when the field is optional and the user presses Enter.
    """
    if default is not None:
        suffix = f" [{default}]"
    elif required:
        suffix = " (required)"
    else:
        suffix = " (optional, Enter to skip)"
    try:
        val = input(f"  {label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise
    return val if val else default


def _resolve_output_path(initial: Path, force: bool) -> Path | None:
    """Return a writable output path, prompting to overwrite or rename if it exists.

    Returns ``None`` if the user cancels.  When *force* is ``True`` the existing
    file is accepted immediately without prompting.  In a non-interactive
    environment (stdin is not a tty) a conflict is treated as a cancel.
    """
    path = initial
    while path.exists() and not force:
        if not sys.stdin.isatty():
            print(
                f"  {path} already exists and stdin is not a tty — use --force to overwrite."
            )
            return None
        print(f"\n  {path} already exists.")
        print("  [o] Overwrite   [r] Rename   [c] Cancel")
        try:
            choice = input("  Enter choice (o/r/c): ").lower().strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if choice in {"o", "overwrite"}:
            break
        if choice in {"c", "cancel", ""}:
            return None
        if choice in {"r", "rename"}:
            try:
                new_name = input(f"  New filename [{initial.name}]: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return None
            if not new_name:
                new_name = initial.name
            new = Path(new_name)
            path = new if new.suffix in {".yaml", ".yml"} else new / initial.name
        else:
            print("  Invalid choice — enter o, r, or c.")
    return path


def _run_interactive(args: argparse.Namespace) -> int:
    """Run the interactive init wizard; write ctd_sections_draft.yaml then config.yaml.

    Detection runs before config.yaml is written so the draft path can be
    recorded as ``section_yaml`` in the config automatically.
    """
    dest: Path = args.dest
    initial = dest if dest.suffix in {".yaml", ".yml"} else dest / "config.yaml"

    print("\n=== ctdreport init (interactive) ===\n")

    config_path = _resolve_output_path(initial, args.force)
    if config_path is None:
        return 0

    print("Data paths")
    nc_dir = _prompt("nc_dir — per-cast netCDF directory", required=True)
    if not nc_dir:
        print("ERROR: nc_dir is required.", file=sys.stderr)
        return 1
    cnv_dir = _prompt("cnv_dir — raw CNV files directory (for ctdreport run --ctd)")
    cnv_pattern = _prompt("cnv_pattern — glob to select CNV files", default="*.cnv")
    profiles_nc = _prompt("profiles_nc — compiled profiles.nc")
    ladcp_dir = _prompt("ladcp_dir — LADCP .mat directory")
    gebco_nc = _prompt("gebco_nc — GEBCO bathymetry .nc")
    section_yaml = _prompt(
        "section_yaml — sections definition file (auto-set if detection runs)",
        default="ctd_sections.yaml",
    )

    print("\nOutput")
    output_dir = (
        _prompt("output_dir", default="outputs/ctd_report") or "outputs/ctd_report"
    )

    print("\nCruise info (optional)")
    cruise_name = _prompt("cruise name") or ""
    ship = _prompt("ship") or ""
    chief_scientist = _prompt("chief scientist") or ""
    start_date = _prompt("start date (YYYY-MM-DD)") or ""
    end_date = _prompt("end date (YYYY-MM-DD)") or ""

    # Run detection first so we can wire the draft path into config.yaml.
    draft_path: Path | None = None
    if not profiles_nc:
        print(
            "  (no profiles.nc — skipping detection; "
            "build one with: ctdreport convert --build-profiles)"
        )
    else:
        profiles_path = Path(profiles_nc)
        if not profiles_path.exists():
            print(f"  WARNING: {profiles_path} not found — skipping section detection.")
        else:
            try:
                ans = (
                    input(
                        "\nRun section/timeseries detection from profiles.nc? [Y/n]: "
                    )
                    .strip()
                    .lower()
                )
            except (EOFError, KeyboardInterrupt):
                print()
                ans = "n"
            if ans not in {"n", "no"}:
                dx_ts = args.dx_timeseries
                dx_sec = args.dx_section
                max_turn = args.max_turn_deg
                min_run = args.min_run_casts
                max_sec = args.max_section_casts
                print(
                    f"\nDetection thresholds (--dx-timeseries {dx_ts} km,"
                    f" --dx-section {dx_sec} km, --max-turn-deg {max_turn},"
                    f" --min-run-casts {min_run})"
                )
                try:
                    v = input(f"  Repeat-station radius km [{dx_ts}]: ").strip()
                    if v:
                        dx_ts = float(v)
                    v = input(f"  Section break distance km [{dx_sec}]: ").strip()
                    if v:
                        dx_sec = float(v)
                    v = input(f"  Max heading change within section deg [{max_turn}]: ").strip()
                    if v:
                        max_turn = float(v)
                    v = input(f"  Min casts per section [{min_run}]: ").strip()
                    if v:
                        new_min = int(v)
                        if new_min < 3:
                            print("  WARNING: --min-run-casts must be >= 3; using 3.")
                            new_min = 3
                        min_run = new_min
                except (EOFError, KeyboardInterrupt, ValueError):
                    print()
                print(
                    f"\nDetecting (dx_timeseries={dx_ts} km, dx_section={dx_sec} km,"
                    f" max_turn={max_turn}°, min_run={min_run}, max_section_casts={max_sec})..."
                )
                try:
                    sections, timeseries = _detect_groups(
                        profiles_path, dx_ts, dx_sec, max_sec, max_turn, min_run
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"  ERROR: {exc}", file=sys.stderr)
                    return 1
                _print_detection_summary(sections, timeseries)
                _draft_initial = config_path.parent / "ctd_sections_draft.yaml"
                resolved = _resolve_output_path(_draft_initial, args.force)
                if resolved is not None:
                    yaml_text = _format_sections_yaml(
                        sections, timeseries, dx_ts, dx_sec, max_sec, max_turn, min_run
                    )
                    _write_file(resolved, yaml_text)
                    print(
                        f"Written: {resolved}"
                        "  (draft — rename to ctd_sections.yaml after editing)"
                    )
                    draft_path = resolved

    # Wire the draft path into section_yaml if detection produced one.
    effective_section_yaml = str(draft_path) if draft_path is not None else section_yaml

    config_text = _build_config_text(
        nc_dir=nc_dir,
        cnv_dir=cnv_dir,
        cnv_pattern=cnv_pattern,
        profiles_nc=profiles_nc,
        ladcp_dir=ladcp_dir,
        gebco_nc=gebco_nc,
        section_yaml=effective_section_yaml,
        output_dir=output_dir,
        cruise_name=cruise_name,
        ship=ship,
        chief_scientist=chief_scientist,
        start_date=start_date,
        end_date=end_date,
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _write_file(config_path, config_text)
    print(f"\nWritten: {config_path}")
    return 0


# --------------------------------------------------------------------------- #
# Detection algorithm                                                           #
# --------------------------------------------------------------------------- #


def _detect_groups(
    profiles_path: Path,
    dx_timeseries_km: float,
    dx_section_km: float,
    max_section_casts: int = 25,
    max_turn_deg: float = 45.0,
    min_run_casts: int = 4,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Detect section and timeseries groups from *profiles_path*.

    Reads per-cast positions from the downcast rows of ``profiles.nc``.

    Algorithm (two-level):

    1. **Coarse gap split** — consecutive casts separated by more than
       *dx_section_km* km start a new coarse group (long transits at sea).
    2. **Stable-heading run detection** — within each coarse group, find
       maximal sub-sequences where every consecutive heading change is
       ≤ *max_turn_deg*.  Runs shorter than *min_run_casts* are discarded as
       transit noise.  A backward-extension step checks whether the cast
       immediately before a run approaches from the same bearing as the run
       (handles the common "approach station" case where the ship arrives at
       the first section station from a different direction).
    3. **Safety cap** — runs longer than *max_section_casts* are split into
       consecutive chunks.
    4. **Classification** — span ≤ *dx_timeseries_km* → timeseries (repeat
       station); span > *dx_timeseries_km* → section (transect).

    Parameters
    ----------
    profiles_path:
        Path to a compiled ``profiles.nc`` file.
    dx_timeseries_km:
        Maximum first-to-last span (km) for a group to be a repeat station.
    dx_section_km:
        Inter-cast distance (km) that triggers a coarse section break (transit).
    max_section_casts:
        Safety cap — stable runs longer than this are split into chunks.
        Default: 25.
    max_turn_deg:
        Maximum heading change (degrees) between consecutive casts within a
        stable-heading run.  Default: 45.
    min_run_casts:
        Minimum number of casts for a run to be kept.  Must be >= 3.
        Default: 4.

    Returns
    -------
    tuple[list[dict], list[dict]]
        ``(sections, timeseries)`` — each entry has keys ``name``,
        ``description``, ``cast_numbers``, and ``color``.
    """
    import gsw
    import numpy as np
    import xarray as xr

    if min_run_casts < 3:
        raise ValueError(f"min_run_casts must be >= 3, got {min_run_casts}")

    ds = xr.open_dataset(profiles_path, engine="netcdf4")
    mask = ds["cast_type"].values == "down"
    cast_nums = ds["cast_number"].values[mask].astype(int)
    lats = ds["latitude"].values[mask].astype(float)
    lons = ds["longitude"].values[mask].astype(float)
    ds.close()

    if len(cast_nums) == 0:
        return [], []

    order = np.argsort(cast_nums)
    cast_nums = cast_nums[order]
    lats = lats[order]
    lons = lons[order]
    n = len(cast_nums)

    # inter_km[i] = distance (km) from cast i-1 to cast i; inter_km[0] = 0.
    inter_km = np.zeros(n)
    if n > 1:
        inter_km[1:] = np.asarray(gsw.distance(lons, lats)) / 1000.0

    # Level 1: coarse gap split — large transits between regions.
    gap_groups: list[list[int]] = []
    start = 0
    for i in range(1, n + 1):
        if i == n or inter_km[i] > dx_section_km:
            gap_groups.append(list(range(start, i)))
            start = i

    # Level 2: within each coarse group, find stable-heading runs.
    # local_bearings[i] = bearing FROM g[i-1] TO g[i] (None for i=0).
    # A "turn" at local position p = angle between local_bearings[p] and local_bearings[p+1].
    # We end a run when that turn exceeds max_turn_deg.
    raw_groups: list[list[int]] = []

    for g in gap_groups:
        n_g = len(g)
        if n_g < 2:
            continue

        local_bearings: list[float | None] = [None]
        for i in range(1, n_g):
            local_bearings.append(
                _bearing_deg(float(lats[g[i - 1]]), float(lons[g[i - 1]]),
                             float(lats[g[i]]), float(lons[g[i]]))
            )

        # Find all maximal stable runs (local index lists within g).
        all_local_runs: list[list[int]] = []
        run_start = 0
        for i in range(1, n_g + 1):
            end_run = i == n_g
            if not end_run:
                b_arrive = local_bearings[i - 1]   # how we arrived at g[i-1]
                b_depart = local_bearings[i]        # how we leave g[i-1] toward g[i]
                if b_arrive is not None and b_depart is not None:
                    end_run = _angle_diff(b_arrive, b_depart) > max_turn_deg
            if end_run:
                all_local_runs.append(list(range(run_start, i)))
                run_start = i

        # Keep only runs meeting the minimum-cast threshold.
        kept: list[list[int]] = [r for r in all_local_runs if len(r) >= min_run_casts]

        # Mark which local indices are already claimed by a kept run.
        claimed: set[int] = set()
        for r in kept:
            claimed.update(r)

        # Backward extension: if the cast just before a run approaches from
        # the same bearing as the run, include it (handles "approach station").
        for r_idx, local_run in enumerate(kept):
            prev_local = local_run[0] - 1
            if prev_local < 0 or prev_local in claimed:
                continue
            main_bear = _bearing_deg(
                float(lats[g[local_run[0]]]), float(lons[g[local_run[0]]]),
                float(lats[g[local_run[-1]]]), float(lons[g[local_run[-1]]]),
            )
            approach_bear = _bearing_deg(
                float(lats[g[prev_local]]), float(lons[g[prev_local]]),
                float(lats[g[local_run[0]]]), float(lons[g[local_run[0]]]),
            )
            if _angle_diff(approach_bear, main_bear) <= max_turn_deg:
                kept[r_idx] = [prev_local] + local_run
                claimed.add(prev_local)

        # Convert to global indices, apply max_section_casts safety cap.
        for local_run in kept:
            global_run = [g[li] for li in local_run]
            for chunk_start in range(0, len(global_run), max_section_casts):
                raw_groups.append(global_run[chunk_start : chunk_start + max_section_casts])

    sections: list[dict[str, Any]] = []
    timeseries: list[dict[str, Any]] = []

    for group_idx, g in enumerate(raw_groups):
        g_casts = cast_nums[g]
        g_lats = lats[g]
        g_lons = lons[g]
        n_g = len(g)
        first_cast = int(g_casts[0])
        last_cast = int(g_casts[-1])
        color = _TAB10_COLORS[group_idx % len(_TAB10_COLORS)]

        span_km = (
            float(
                np.asarray(
                    gsw.distance(
                        np.array([g_lons[0], g_lons[-1]]),
                        np.array([g_lats[0], g_lats[-1]]),
                    )
                )[0]
            )
            / 1000.0
        )
        path_km = float(np.sum(inter_km[g[1:]])) if n_g > 1 else 0.0
        cast_numbers = _cast_range(g_casts)

        if span_km <= dx_timeseries_km:
            lat_c = float(np.nanmean(g_lats))
            lon_c = float(np.nanmean(g_lons))
            ns = "N" if lat_c >= 0 else "S"
            ew = "E" if lon_c >= 0 else "W"
            idx = len(timeseries) + 1
            timeseries.append(
                {
                    "name": f"Station_{idx:03d}",
                    "description": (
                        f"Station {idx:03d} — ~{abs(lat_c):.1f}°{ns} {abs(lon_c):.1f}°{ew}"
                        f" ({n_g} cast{'s' if n_g != 1 else ''})"
                    ),
                    "cast_numbers": cast_numbers,
                    "color": color,
                }
            )
        else:
            idx = len(sections) + 1
            sections.append(
                {
                    "name": f"Section_{idx:03d}",
                    "description": (
                        f"Section {idx:03d} — casts {first_cast:03d}–{last_cast:03d}"
                        f" ({n_g} casts, {path_km:.0f} km)"
                    ),
                    "cast_numbers": cast_numbers,
                    "color": color,
                }
            )

    return sections, timeseries


def _cast_range(cast_nums: Any) -> list[int | list[int]]:
    """Return compact cast_numbers list: single ``[first, last]`` range if fully consecutive, else individual ints."""
    nums = sorted(int(c) for c in cast_nums)
    if not nums:
        return []
    if nums == list(range(nums[0], nums[-1] + 1)):
        return [[nums[0], nums[-1]]]
    return nums


def _print_detection_summary(
    sections: list[dict[str, Any]],
    timeseries: list[dict[str, Any]],
) -> None:
    """Print a human-readable table of detected groups."""
    total = len(sections) + len(timeseries)
    print(
        f"  Found {total} group(s): {len(sections)} section(s), {len(timeseries)} timeseries station(s)\n"
    )
    if sections:
        print("  Sections:")
        for s in sections:
            print(f"    {s['name']:16s}  {s['description']}")
    if timeseries:
        print("\n  Timeseries:")
        for t in timeseries:
            print(f"    {t['name']:16s}  {t['description']}")
    print()


# --------------------------------------------------------------------------- #
# YAML and config formatters                                                    #
# --------------------------------------------------------------------------- #


def _format_sections_yaml(
    sections: list[dict[str, Any]],
    timeseries: list[dict[str, Any]],
    dx_timeseries_km: float,
    dx_section_km: float,
    max_section_casts: int = 25,
    max_turn_deg: float = 45.0,
    min_run_casts: int = 4,
) -> str:
    """Return a YAML string for ``ctd_sections_draft.yaml``."""
    lines: list[str] = [
        "# ctd_sections_draft.yaml — auto-generated by ctdreport init --interactive",
        (
            f"# Detection thresholds: dx_timeseries={dx_timeseries_km} km,"
            f" dx_section={dx_section_km} km, max_turn={max_turn_deg}°,"
            f" min_run={min_run_casts}, max_section_casts={max_section_casts}"
        ),
        "# Review carefully: rename groups, adjust cast ranges, move entries between",
        "# sections/timeseries as appropriate.  Rename to ctd_sections.yaml when done.",
        "",
    ]

    def _append_group(entries: list[dict[str, Any]]) -> None:
        for entry in entries:
            lines.append(f"  {entry['name']}:")
            lines.append(f'    description: "{entry["description"]}"')
            lines.append("    cast_numbers:")
            for item in entry["cast_numbers"]:
                if isinstance(item, list):
                    lines.append(f"      - [{item[0]}, {item[1]}]")
                else:
                    lines.append(f"      - {item}")
            lines.append(f'    color: "{entry["color"]}"')
            lines.append("")

    if sections:
        lines.append("sections:")
        _append_group(sections)
    else:
        lines += ["sections: {}", ""]

    if timeseries:
        lines.append("timeseries:")
        _append_group(timeseries)
    else:
        lines += ["# timeseries: {}", ""]

    return "\n".join(lines)


def _build_config_text(
    nc_dir: str,
    cnv_dir: str | None,
    cnv_pattern: str | None,
    profiles_nc: str | None,
    ladcp_dir: str | None,
    gebco_nc: str | None,
    section_yaml: str | None,
    output_dir: str,
    cruise_name: str,
    ship: str,
    chief_scientist: str,
    start_date: str,
    end_date: str,
) -> str:
    """Build a config.yaml string with user-supplied paths and cruise metadata."""
    cnv_line = f"  cnv_dir: {cnv_dir}" if cnv_dir else "  # cnv_dir: /path/to/cnv"
    pattern_default = "*.cnv"
    cnv_pattern_line = (
        f"  cnv_pattern: {cnv_pattern}"
        if cnv_pattern and cnv_pattern != pattern_default
        else f"  # cnv_pattern: {pattern_default}  # glob to select CNV files"
    )
    profiles_line = (
        f"  profiles_nc: {profiles_nc}"
        if profiles_nc
        else "  # profiles_nc: /path/to/profiles.nc"
    )
    sections_line = (
        f"  section_yaml: {section_yaml}"
        if section_yaml
        else "  # section_yaml: /path/to/ctd_sections.yaml"
    )
    ladcp_line = (
        f"  ladcp_dir: {ladcp_dir}" if ladcp_dir else "  # ladcp_dir: /path/to/ladcp"
    )
    gebco_line = (
        f"  gebco_nc: {gebco_nc}"
        if gebco_nc
        else "  # gebco_nc: /path/to/GEBCO_2025.nc"
    )
    return (
        "# ctdreport configuration — generated by ctdreport init --interactive\n"
        "# Run 'ctdreport validate config.yaml' to check all paths before the first run.\n"
        "\n"
        "data:\n"
        f"  nc_dir: {nc_dir}\n"
        f"{cnv_line}\n"
        f"{cnv_pattern_line}\n"
        f"{profiles_line}\n"
        f"{sections_line}\n"
        f"{ladcp_line}\n"
        "  # ship_track: /path/to/ship_track.nc\n"
        f"{gebco_line}\n"
        "\n"
        "output:\n"
        f"  dir: {output_dir}\n"
        "\n"
        "generate:\n"
        "  stations: true\n"
        "  sections: true\n"
        "  timeseries: true\n"
        "  index: true\n"
        "  leaflet: true\n"
        "\n"
        "cruise_info:\n"
        f'  name: "{cruise_name}"\n'
        f'  ship: "{ship}"\n'
        f'  chief_scientist: "{chief_scientist}"\n'
        f'  start_date: "{start_date}"\n'
        f'  end_date: "{end_date}"\n'
        "\n"
        "display:\n"
        "  section_style: pcolormesh\n"
        "  timeseries_style: pcolormesh\n"
    )


def _write_file(path: Path, text: str) -> None:
    """Write *text* to *path*."""
    path.write_text(text)


# Keep old name as alias so existing callers are not broken.
_write_ruamel = _write_file
