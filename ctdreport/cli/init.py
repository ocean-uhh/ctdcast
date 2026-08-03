"""``ctdreport init`` — write a commented template config.yaml."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_CONFIG_TEMPLATE = """\
# ctdreport configuration
# Run 'ctdreport validate config.yaml' to check all paths before the first run.

data:
  # Directory containing per-cast netCDF files (one per cast).
  nc_dir: /path/to/ctd/nc

  # Compiled profiles netCDF on a 1 dbar grid (required for sections and timeseries).
  # Built externally by cnv_build_profiles.py.
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


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdreport init``."""
    _epilog = """
Examples:
  ctdreport init                     write config.yaml in the current directory
  ctdreport init cruise/             write config.yaml inside cruise/
  ctdreport init myconfig.yaml       write to a specific filename
  ctdreport init . --sections        also write ctd_sections.yaml
  ctdreport init . --force           overwrite existing files
"""
    kwargs: dict = {
        "description": "Write a commented template config.yaml (and optionally ctd_sections.yaml).",
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": _epilog,
    }
    if subparsers is not None:
        parser = subparsers.add_parser(
            "init",
            help="Write a commented template config.yaml.",
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
            "Destination: a directory (config.yaml is written inside it) "
            "or an explicit .yaml filename.  Default: current directory."
        ),
    )
    parser.add_argument(
        "--sections",
        action="store_true",
        default=False,
        help="Also write a template ctd_sections.yaml.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing files.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """Execute ``ctdreport init``."""
    dest: Path = args.dest

    # Resolve config output path.
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
    _write_ruamel(config_path, _CONFIG_TEMPLATE)
    print(f"Written: {config_path}")

    if args.sections:
        sections_dir = config_path.parent
        sections_path = sections_dir / "ctd_sections.yaml"
        if sections_path.exists() and not args.force:
            print(
                f"ERROR: {sections_path} already exists. Use --force to overwrite.",
                file=sys.stderr,
            )
            return 1
        sections_path.write_text(_SECTIONS_TEMPLATE)
        print(f"Written: {sections_path}")

    return 0


def _write_ruamel(path: Path, text: str) -> None:
    """Write *text* to *path*, preserving comments in the template verbatim."""
    path.write_text(text)
