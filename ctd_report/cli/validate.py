"""``oceancast validate`` — check config and data paths without writing anything."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``oceancast validate``."""
    _epilog = """
Checks performed:
  - config YAML is readable and has required keys
  - data.nc_dir exists and contains at least one .nc file
  - first cast netCDF opens without error
  - profiles_nc exists (if sections or timeseries are enabled)
  - section_yaml exists and is valid YAML (if sections are enabled)
  - output directory is writable (or can be created)

With --strict:
  - every cast number in section_yaml exists in nc_dir

Examples:
  oceancast validate config.yaml
  oceancast validate config.yaml --strict
"""
    kwargs: dict = {
        "description": "Validate config file and data paths without writing any output.",
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": _epilog,
    }
    if subparsers is not None:
        parser = subparsers.add_parser(
            "validate",
            help="Validate config and data paths without writing anything.",
            **kwargs,
        )
        parser.set_defaults(func=run)
    else:
        parser = argparse.ArgumentParser(prog="oceancast validate", **kwargs)

    parser.add_argument("config", type=Path, help="Path to config YAML file.")
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Also verify every cast number in section_yaml exists in nc_dir.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """Execute ``oceancast validate``."""
    errors: list[str] = []
    warnings: list[str] = []

    cfg_path: Path = args.config
    if not cfg_path.exists():
        print(f"ERROR: config file not found: {cfg_path}", file=sys.stderr)
        return 1

    try:
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        print(f"ERROR: config YAML parse error: {exc}", file=sys.stderr)
        return 1

    if not isinstance(cfg, dict):
        print("ERROR: config file is empty or not a YAML mapping.", file=sys.stderr)
        return 1

    data = cfg.get("data") or {}
    output = cfg.get("output") or {}
    gen_cfg = cfg.get("generate", {})

    # Required keys
    if not data.get("nc_dir"):
        errors.append("data.nc_dir is missing or blank")
    if not output.get("dir"):
        errors.append("output.dir is missing or blank")

    nc_dir: Path | None = Path(data["nc_dir"]) if data.get("nc_dir") else None
    out_dir: Path | None = Path(output["dir"]) if output.get("dir") else None

    # nc_dir
    if nc_dir is not None:
        if not nc_dir.exists():
            errors.append(f"data.nc_dir does not exist: {nc_dir}")
        else:
            nc_files = sorted(nc_dir.glob("*.nc"))
            if not nc_files:
                errors.append(f"data.nc_dir contains no .nc files: {nc_dir}")
            else:
                print(f"  nc_dir: {len(nc_files)} cast files found")
                # Try opening the first cast
                try:
                    import xarray as xr

                    with xr.open_dataset(nc_files[0], engine="netcdf4"):
                        pass
                    print(f"  first cast opens ok: {nc_files[0].name}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"first cast netCDF unreadable: {nc_files[0].name}: {exc}")

    # profiles_nc
    need_profiles = gen_cfg.get("sections", True) or gen_cfg.get("timeseries", True)
    profiles_raw = data.get("profiles_nc")
    if need_profiles and not profiles_raw:
        warnings.append("data.profiles_nc not set; sections and timeseries pages will be skipped")
    elif profiles_raw:
        profiles_path = Path(profiles_raw)
        if not profiles_path.exists():
            errors.append(f"data.profiles_nc not found: {profiles_path}")
        else:
            print(f"  profiles_nc: ok ({profiles_path})")

    # section_yaml
    need_sections = gen_cfg.get("sections", True)
    section_yaml_raw = data.get("section_yaml")
    sections_cfg: dict = {}
    if need_sections and not section_yaml_raw:
        warnings.append("data.section_yaml not set; section pages will be skipped")
    elif section_yaml_raw:
        section_yaml = Path(section_yaml_raw)
        if not section_yaml.exists():
            errors.append(f"data.section_yaml not found: {section_yaml}")
        else:
            try:
                with open(section_yaml) as f:
                    yaml_data = yaml.safe_load(f) or {}
                sections_cfg = yaml_data.get("sections", {})
                print(f"  section_yaml: {len(sections_cfg)} section(s) defined")
            except yaml.YAMLError as exc:
                errors.append(f"section_yaml parse error: {exc}")

    # gebco_nc (optional, just warn if set but missing)
    gebco_raw = data.get("gebco_nc")
    if gebco_raw:
        gebco_path = Path(gebco_raw)
        if not gebco_path.exists():
            warnings.append(f"data.gebco_nc not found (maps will render without bathymetry): {gebco_path}")
        else:
            print(f"  gebco_nc: ok ({gebco_path})")

    # output dir
    if out_dir is not None:
        if out_dir.exists() and not out_dir.is_dir():
            errors.append(f"output.dir exists but is not a directory: {out_dir}")
        else:
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                print(f"  output.dir: ok ({out_dir})")
            except OSError as exc:
                errors.append(f"output.dir not writable: {exc}")

    # Strict: verify cast numbers in section_yaml exist in nc_dir
    if args.strict and nc_dir and nc_dir.exists() and sections_cfg:
        nc_cast_nums = _parse_cast_nums_from_dir(nc_dir)
        for sec_name, sec_cfg in sections_cfg.items():
            for cast_num in _expand_cast_numbers(sec_cfg.get("cast_numbers", [])):
                if cast_num not in nc_cast_nums:
                    errors.append(
                        f"section '{sec_name}': cast {cast_num} not found in {nc_dir}"
                    )

    # Report
    for w in warnings:
        print(f"  WARNING: {w}")
    for e in errors:
        print(f"  ERROR: {e}", file=sys.stderr)

    if errors:
        print(f"\nValidation failed: {len(errors)} error(s).", file=sys.stderr)
        return 1

    print("\nValidation passed.")
    return 0


def _parse_cast_nums_from_dir(nc_dir: Path) -> set[int]:
    """Return the set of integer cast numbers present in nc_dir."""
    nums: set[int] = set()
    for p in nc_dir.glob("*.nc"):
        stem = p.stem  # e.g. "cast_042"
        parts = stem.split("_")
        if parts:
            try:
                nums.add(int(parts[-1]))
            except ValueError:
                pass
    return nums


def _expand_cast_numbers(cast_numbers: list) -> list[int]:
    """Expand cast_numbers spec (list of ints and [start, end] ranges) to a flat list."""
    result: list[int] = []
    for item in cast_numbers:
        if isinstance(item, int):
            result.append(item)
        elif isinstance(item, list) and len(item) == 2:
            result.extend(range(item[0], item[1] + 1))
    return result
