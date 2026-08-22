"""``ctdcast validate`` — check config and data paths without writing anything."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from ctdcast.identity import cast_id_from_name, expand_cast_ids, format_cast_id

from ctdcast.config.loader import SectionsConfig
from ctdcast.config.people import check_contributors, contributor_attrs
from ctdcast.processors import StagePaths


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdcast validate``."""
    _epilog = """
Checks performed:
  - config YAML is readable and has required keys
  - data.ctd_root exists and some stageN/ under it holds at least one .nc file
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
  - every cast number in section_yaml exists under data.ctd_root

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
        help="Also verify every cast number in section_yaml exists under ctd_root.",
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
    if not (data.get("ctd_root") or data.get("nc_dir")):
        errors.append("data.ctd_root is missing or blank")
    if not output.get("dir"):
        errors.append("output.dir is missing or blank")

    # Resolved by the same function the processors use, so validate cannot
    # green-light a config that `process` would read differently.
    _paths = StagePaths.from_config(data)
    nc_dir: Path | None = _paths.ctd_root
    out_dir: Path | None = Path(output["dir"]) if output.get("dir") else None

    # ctd_root: per-cast files live under stageN/, with the flat layout still
    # accepted for a directory written before the stage layout.
    # Same distinction vsclaude drew for the derived profiles.nc, applied one
    # block earlier: `ctd_root` is a directory ctdcast WRITES INTO -- stage1/ and
    # its contents are outputs of `process --stage 1` -- so a fresh, valid config
    # legitimately points at a root that does not exist yet.  Erroring there
    # breaks the same contract.  `output.dir` already sets the precedent: validate
    # creates it rather than failing.
    #
    # A missing root is still ambiguous between "not built yet" and a typo, so use
    # evidence instead of a coin flip: if the PARENT is missing too, the path is
    # wrong or the volume is not mounted -- that is an error, and a loud one,
    # because the alternative is stage 1 writing 200 files somewhere unintended.
    if nc_dir is not None:
        if not nc_dir.exists():
            if nc_dir.parent.exists():
                warnings.append(
                    f"data.ctd_root does not exist yet: {nc_dir} — "
                    f"`ctdcast process --stage 1` will create it."
                )
            else:
                errors.append(
                    f"data.ctd_root does not exist, and neither does its parent "
                    f"{nc_dir.parent}: {nc_dir}. Check the path, and whether the "
                    f"drive is mounted."
                )
        else:
            nc_files = sorted(nc_dir.glob("stage*/*.nc")) or sorted(nc_dir.glob("*.nc"))
            if not nc_files:
                warnings.append(
                    f"data.ctd_root holds no per-cast .nc files, in stage1/…stage3/ "
                    f"or directly: {nc_dir}. Run `ctdcast process --stage 1` first."
                )
            else:
                print(f"  ctd_root: {len(nc_files)} cast file(s) found")
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
    # Derived from the root unless a config names it explicitly.  The distinction
    # matters for a *missing* file: profiles.nc is an OUTPUT of ``process --stage
    # profiles``, so a fresh, valid config that has not been processed yet has no
    # profiles.nc.  A file the config names explicitly but that is absent is an
    # error (a wrong path); a derived path that is simply not built yet is a
    # warning (run the profiles stage before reporting).
    profiles_explicit = data.get("profiles_nc")
    profiles_raw = str(_paths.profiles_path) if _paths.profiles_path else None
    if need_profiles and not profiles_raw:
        warnings.append(
            "data.profiles_nc not set; sections and timeseries pages will be skipped"
        )
    elif profiles_raw:
        profiles_path = Path(profiles_raw)
        if profiles_path.exists():
            print(f"  profiles_nc: ok ({profiles_path})")
        elif profiles_explicit:
            errors.append(f"data.profiles_nc not found: {profiles_path}")
        else:
            warnings.append(
                f"profiles.nc not built yet at {profiles_path}; run "
                "'process --stage profiles' before generating a report"
            )

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
    """Return the cast numbers present under a stage root.

    Walks ``stageN/`` as well as the root itself and defers to
    :func:`ctdcast.identity.cast_id_from_name`, which already knows that the cast
    number is the *last* 3+-digit group — so a cruise or leg number earlier in the
    stem is not mistaken for it — and that a letter suffix may be appended or
    underscore-separated.

    A local re-implementation drifted from that: taking the digits of the final
    underscore-separated field read ``msm_142_1_029_1sec_stage1`` as cast 1 and
    dropped ``mixsed2_030_b_stage1`` entirely, so ``--strict`` could pass on the
    wrong casts or report present casts as missing.

    Parameters
    ----------
    nc_dir : Path
        The instrument stage root.

    Returns
    -------
    set of int
        Cast numbers found; a lettered cast contributes its number.
    """
    nums: set[int] = set()
    for path in [*nc_dir.glob("stage*/*.nc"), *nc_dir.glob("*.nc")]:
        # A compiled product sits at the root beside the stage directories, and a
        # non-default name containing digits parses as a cast: `msm_142_profiles`
        # reads as cast 142. No per-cast file ends in `profiles`, so that is the
        # discriminator.
        if path.stem.endswith("profiles"):
            continue
        parsed = cast_id_from_name(path.stem)
        if parsed is not None:
            nums.add(parsed[0])
    return nums
