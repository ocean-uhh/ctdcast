"""``ctdcast validate`` — check config and data paths without writing anything."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from ctdcast.identity import expand_cast_ids, format_cast_id

from ctdcast.config.loader import SectionsConfig
from ctdcast.config.people import check_contributors, contributor_attrs


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdcast validate``."""
    _epilog = """
Checks performed:
  - config YAML is readable and has required keys
  - data.nc_dir exists and contains at least one .nc file
  - first cast netCDF opens without error
  - profiles_nc exists (if sections or timeseries are enabled)
  - section_yaml exists and is valid YAML (if sections are enabled)
  - output directory is writable (or can be created)
  - cruise_info platform/start_date are set (else the EXPOCODE is a placeholder)
  - cruise_info contributors: no ";" or "," inside any value (they would split
    one person into two), every role is a term of the declared vocabulary
    (NERC C89 by default), every institution
    resolves in config/institutions.yaml, emails and ORCIDs are well formed

With --strict:
  - every cast number in section_yaml exists in nc_dir

Examples:
  ctdcast validate config.yaml
  ctdcast validate config.yaml --strict
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
        parser = argparse.ArgumentParser(prog="ctdcast validate", **kwargs)

    parser.add_argument("config", type=Path, help="Path to config YAML file.")
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Also verify every cast number in section_yaml exists in nc_dir.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """Execute ``ctdcast validate``."""
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

    # PyYAML resolves a repeated mapping key to the LAST occurrence and says
    # nothing, so a second `cruise_info:` block silently discards the first --
    # ship, cruise_id and project vanish from a file that still parses.  Cheap
    # to detect, and invisible without the check.
    for key, count in _duplicate_top_level_keys(cfg_path).items():
        errors.append(
            f"config defines top-level key '{key}' {count} times; YAML keeps "
            f"only the last, silently discarding the earlier block(s). Merge them."
        )

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
                    errors.append(
                        f"first cast netCDF unreadable: {nc_files[0].name}: {exc}"
                    )

    # profiles_nc
    need_profiles = gen_cfg.get("sections", True) or gen_cfg.get("timeseries", True)
    profiles_raw = data.get("profiles_nc")
    if need_profiles and not profiles_raw:
        warnings.append(
            "data.profiles_nc not set; sections and timeseries pages will be skipped"
        )
    elif profiles_raw:
        profiles_path = Path(profiles_raw)
        if not profiles_path.exists():
            errors.append(f"data.profiles_nc not found: {profiles_path}")
        else:
            print(f"  profiles_nc: ok ({profiles_path})")

    # cruise_info: contributors, creator, institutions
    cruise_info = cfg.get("cruise_info") or {}

    # EXPOCODE: a missing half is not an error (the cruise may not have settled
    # its departure date) but it does mean the compiled file carries a
    # placeholder and keeps a fallback name, so say so here rather than letting
    # it surface as a warning at the end of a long build.
    _missing_expo = [
        k
        for k in ("platform", "start_date")
        if not (
            cruise_info.get(k) or (k == "platform" and cruise_info.get("ship_slug"))
        )
    ]
    if _missing_expo:
        warnings.append(
            f"cruise_info.{' and '.join(_missing_expo)} not set: the compiled "
            f"file will carry a placeholder EXPOCODE and keep its fallback "
            f"name. Fine mid-cruise; not publishable."
        )
    people_errors, people_warnings = check_contributors(cruise_info)
    errors.extend(people_errors)
    warnings.extend(people_warnings)
    if not people_errors:
        n_contrib = len(cruise_info.get("contributors") or [])
        if n_contrib:
            attrs = contributor_attrs(cruise_info)
            n_inst = (
                len((attrs.get("contributing_institutions") or "").split(";"))
                if attrs.get("contributing_institutions")
                else 0
            )
            print(
                f"  contributors: {n_contrib} person(s), "
                f"{n_inst} institution(s) resolved"
            )

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
                _sec_cfg = SectionsConfig.from_yaml(section_yaml)
                sections_cfg = _sec_cfg.sections
                print(f"  section_yaml: {len(sections_cfg)} section(s) defined")
            except yaml.YAMLError as exc:
                errors.append(f"section_yaml parse error: {exc}")

    # gebco_nc (optional, just warn if set but missing)
    gebco_raw = data.get("gebco_nc")
    if gebco_raw:
        gebco_path = Path(gebco_raw)
        if not gebco_path.exists():
            warnings.append(
                f"data.gebco_nc not found (maps will render without bathymetry): {gebco_path}"
            )
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

    # Validate each section's cast_numbers: expand once, reporting a malformed
    # spec as an error and duplicated casts as a warning (duplicates are allowed
    # but will double-plot).
    expanded_sections: dict[str, list[tuple[int, str]]] = {}
    for sec_name, sec_cfg in sections_cfg.items():
        try:
            expanded = expand_cast_ids(sec_cfg.get("cast_numbers", []))
        except ValueError as exc:
            errors.append(f"section '{sec_name}': invalid cast_numbers: {exc}")
            continue
        expanded_sections[sec_name] = expanded
        # A plain cast and its lettered sibling are distinct, so dedupe on the
        # (number, suffix) pair.
        dupes = sorted(
            {format_cast_id(n, s) for (n, s) in expanded if expanded.count((n, s)) > 1}
        )
        if dupes:
            warnings.append(
                f"section '{sec_name}': duplicate cast(s) {dupes} listed more "
                "than once (will be plotted more than once)"
            )
        # key_cast, if set, must be a SINGLE cast that is one of the section's casts.
        key_cfg = sec_cfg.get("key_cast")
        if key_cfg is not None:
            try:
                key_ids = expand_cast_ids([key_cfg])
            except ValueError:
                key_ids = []
            if len(key_ids) != 1:
                errors.append(
                    f"section '{sec_name}': key_cast {key_cfg!r} must be a single "
                    "cast (an int or a 'NNNb' string), not a range or list."
                )
            elif key_ids[0] not in expanded:
                errors.append(
                    f"section '{sec_name}': key_cast {key_cfg!r} is not one of "
                    "the section's cast_numbers."
                )

    # Strict: verify the station numbers in section_yaml exist in nc_dir
    if args.strict and nc_dir and nc_dir.exists() and expanded_sections:
        nc_cast_nums = _parse_cast_nums_from_dir(nc_dir)
        for sec_name, cast_list in expanded_sections.items():
            for cast_num, _suffix in cast_list:
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


def _duplicate_top_level_keys(path: Path) -> dict[str, int]:
    """Return ``{key: count}`` for any top-level YAML key appearing more than once.

    Scans the raw text rather than the parsed object, because parsing is exactly
    what destroys the evidence: ``yaml.safe_load`` keeps the last occurrence of a
    repeated key and reports nothing.

    Parameters
    ----------
    path : Path
        Config file to scan.

    Returns
    -------
    dict of str to int
        Keys seen more than once, with their occurrence counts. Empty when the
        file is well formed or unreadable.
    """
    counts: dict[str, int] = {}
    try:
        text = path.read_text()
    except OSError:
        return {}
    for line in text.splitlines():
        # A top-level key starts in column 0 and is not a comment or list item.
        if not line or line[0] in " \t#-":
            continue
        key, sep, _ = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return {k: n for k, n in counts.items() if n > 1}


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
