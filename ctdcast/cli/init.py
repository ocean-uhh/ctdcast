"""``ctdcast init`` — write config.yaml and optionally ctd_sections_draft.yaml."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

_CONFIG_TEMPLATE = """\
# ctdcast configuration
# Run 'ctdcast validate config.yaml' to check all paths before the first run.

data:
  # Directory containing per-cast netCDF files (one per cast).
  nc_dir: /path/to/ctd/nc

  # Compiled profiles netCDF on a 1 dbar grid (required for sections and timeseries).
  # Build with: ctdcast convert --build-profiles /path/to/nc/ /path/to/profiles.nc
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

# Which page types to generate on a plain 'ctdcast report' run.
# CLI flags (--casts, --sections, etc.) override these at runtime.
generate:
  stations: true
  sections: true
  timeseries: true
  index: true
  leaflet: true

# Cruise metadata: shown in page headers and written into the compiled files as
# ACDD/CF global attributes.  All optional — but the more you fill in, the more
# self-describing and citable the output netCDF is.  Run 'ctdcast validate' to
# check it.  Fill the blanks; uncomment and complete the example blocks you need.
cruise_info:
  name: ""
  cruise_id: ""                  # short identifier, e.g. "MSM142" (the file's `cruise`)
  ship: ""                       # display name shown in the report masthead

  # Vessel for the EXPOCODE and platform_* attributes.  Either a platforms.yaml
  # slug (e.g. odb, msm), OR — for a vessel not in the registry — an inline block.
  # platform: odb
  # platform:
  #   name: "RV Example"
  #   ices_code: "XXXX"          # look up your ship at https://ocean.ices.dk/codes/ShipCodes.aspx
  #   platform_vocabulary: "https://vocab.nerc.ac.uk/collection/L06/current/31/"

  project: ""
  start_date: ""                 # DEPARTURE from port, YYYY-MM-DD; feeds the EXPOCODE (not the first cast)
  end_date: ""                   # return to port; drives the default embargo release date

  # Who produced the file (ACDD creator_*).  Singular — not a PI list.
  # creator:
  #   name: ""
  #   type: person               # person | group | institution
  #   orcid: null                # https://orcid.org/0000-0000-0000-000X

  # Everyone with a named role.  Each person once.  Roles are NERC C89 codes:
  #   PS Cruise principal scientist   PI Project principal investigator
  #   DI Cruise dataset PI   MC Cruise data manager   CO Project collaborator  ...
  #   (full list: https://vocab.nerc.ac.uk/collection/C89/current/)
  # A role may apply to every file, or be scoped to one product (ctd / ladcp).
  # contributors:
  #   - name: ""
  #     orcid: null
  #     roles: [PS, PI]          # both compiled files
  #   - name: ""
  #     orcid: null
  #     roles:
  #       ctd: [MC]              # profiles.nc only
  #       ladcp: [DI]           # ladcp_profiles.nc only

  # Contributing institutions.  Either an institutions.yaml slug, or inline for
  # one not in the registry (look up the EDMO code at https://edmo.seadatanet.org/).
  # The CONLEAD entries are what the CF `institution` attribute is derived from,
  # so a list where nothing leads produces no `institution` at all.
  # institutions:
  #   - slug: uhh
  #     role: CONLEAD            # CONLEAD (leads) | CONMEM (takes part) | FUND (funder)
  #   - name: "Example Funder"
  #     id: "https://ror.org/..."   # ROR, or https://edmo.seadatanet.org/report/<code>
  #     role: FUND

  # Access policy.  An embargo is NOT a licence — during it the file carries a
  # self-describing moratorium statement, not CC-BY.
  # embargo:
  #   policy: "SDN:L08::MO"      # NERC L08 moratorium
  #   until: null               # null -> end_date + 2 years; or a fixed YYYY-MM-DD
  #   contact: null             # PI email for access requests
  # license_after_embargo: "CC-BY-4.0"

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
  # dbar_step: 1  # plot every Nth dbar from profiles.nc (1 = full resolution)

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
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(
        lat2r
    ) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _angle_diff(b1: float, b2: float) -> float:
    """Return the smallest unsigned angular difference between two bearings, in [0, 180]."""
    delta = abs(b2 - b1) % 360.0
    return min(delta, 360.0 - delta)


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdcast init``."""
    _epilog = """
Examples:
  ctdcast init                        write template config.yaml here
  ctdcast init cruise/                write config.yaml inside cruise/
  ctdcast init myconfig.yaml          write to a specific filename
  ctdcast init . --sections           also write template ctd_sections.yaml
  ctdcast init . --force              overwrite existing files
  ctdcast init --interactive          prompt for paths; auto-detect sections
  ctdcast init --interactive \\
    --dx-section 20 --max-turn-deg 45  set detection thresholds explicitly
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
        parser = argparse.ArgumentParser(prog="ctdcast init", **kwargs)

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
        "--auto-section",
        action="store_true",
        default=False,
        dest="auto_section",
        help=(
            "Read profiles_nc from an existing config file and rewrite "
            "ctd_sections_draft.yaml using the current detection parameters.  "
            "Does not touch config.yaml.  Requires dest to be an existing config file."
        ),
    )
    parser.add_argument(
        "--dx-diameter",
        type=float,
        default=1.0,
        metavar="KM",
        dest="dx_diameter",
        help=(
            "Maximum inter-cast distance (km) within a repeat-station cluster. "
            "Unclaimed casts (not in any directional run) that are consecutively "
            "within this distance of each other are grouped as a repeat station. "
            "Default: 1 km."
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
    """Execute ``ctdcast init``."""
    if hasattr(args, "min_run_casts") and args.min_run_casts < 3:
        print("ERROR: --min-run-casts must be >= 3.", file=sys.stderr)
        return 1
    if args.auto_section:
        return _run_auto_section(args)
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
# Detect-only mode                                                              #
# --------------------------------------------------------------------------- #


def _run_auto_section(args: argparse.Namespace) -> int:
    """Re-run section/timeseries detection and rewrite ctd_sections_draft.yaml.

    Reads ``profiles_nc`` from the config file passed as *dest*.  Does not
    modify the config file.  All detection parameters come from CLI flags.
    """
    import yaml

    config_path = Path(args.dest)
    if config_path.suffix not in {".yaml", ".yml"}:
        config_path = config_path / "config.yaml"
    if not config_path.exists():
        print(f"ERROR: config file not found: {config_path}", file=sys.stderr)
        return 1

    with config_path.open() as fh:
        cfg = yaml.safe_load(fh) or {}

    data_cfg: dict = cfg.get("data") or {}
    profiles_nc_raw: str | None = data_cfg.get("profiles_nc")
    if not profiles_nc_raw:
        print("ERROR: profiles_nc not set in config.", file=sys.stderr)
        return 1

    profiles_path = Path(profiles_nc_raw)
    if not profiles_path.exists():
        print(f"ERROR: profiles_nc not found: {profiles_path}", file=sys.stderr)
        return 1

    # Derive draft output path: if section_yaml is set, write the draft alongside it
    # (resolving relative to the config file's directory).
    section_yaml_raw: str | None = data_cfg.get("section_yaml")
    if section_yaml_raw:
        section_yaml_path = (config_path.parent / section_yaml_raw).resolve()
        draft_path = section_yaml_path.parent / "ctd_sections_draft.yaml"
    else:
        draft_path = config_path.parent / "ctd_sections_draft.yaml"

    dx_sec = args.dx_section
    dx_diam = args.dx_diameter
    max_turn = args.max_turn_deg
    min_run = args.min_run_casts
    max_sec = args.max_section_casts

    print(
        f"Detecting from {profiles_path}\n"
        f"  dx_section={dx_sec} km  dx_diameter={dx_diam} km"
        f"  max_turn={max_turn}°  min_run={min_run}  max_section_casts={max_sec}"
    )
    try:
        sections, timeseries = _detect_groups(
            profiles_path, dx_sec, max_sec, max_turn, min_run, dx_diam
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    _print_detection_summary(sections, timeseries)

    resolved = _resolve_output_path(draft_path, args.force)
    if resolved is None:
        return 0
    yaml_text = _format_sections_yaml(
        sections, timeseries, dx_sec, max_sec, max_turn, min_run, dx_diam
    )
    _write_file(resolved, yaml_text)
    print(f"Written: {resolved}")
    return 0


# --------------------------------------------------------------------------- #
# Interactive mode                                                              #
# --------------------------------------------------------------------------- #


def _parse_date(raw: str) -> str:
    """Normalise a date string to YYYY-MM-DD, accepting several common formats.

    Accepted: YYYY-MM-DD, YYYYMMDD, DD.MM.YYYY, DD/MM/YYYY, MM/DD/YYYY.
    Returns the original string unchanged if it cannot be parsed.
    """
    import re

    raw = raw.strip()
    # Already correct.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    # YYYYMMDD
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # DD.MM.YYYY or DD/MM/YYYY  (day first — European)
    m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", raw)
    if m:
        d, mo, y = m.group(1), m.group(2), m.group(3)
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
    return raw


def _trunc_default(value: str, max_len: int = 55) -> str:
    """Return *value* truncated to *max_len* chars, prefixed with '…' if shortened."""
    if len(value) <= max_len:
        return value
    return "…" + value[-(max_len - 1) :]


def _section_header(title: str, width: int = 62) -> None:
    """Print a visual section separator."""
    bar = "─" * max(0, width - len(title) - 4)
    print(f"\n── {title} {bar}" if bar else f"\n── {title}")


def _prompt(
    label: str, default: str | None = None, required: bool = False
) -> str | None:
    """Print a prompt and return the stripped user input, or *default* on empty.

    Returns ``None`` when the field is optional and the user presses Enter.
    """
    if default is not None:
        disp = _trunc_default(default)
        suffix = f" [{disp}]"
    elif required:
        suffix = " (required)"
    else:
        suffix = ""
    # Bold the key name (part before ' — ') when running interactively.
    if sys.stdout.isatty() and " — " in label:
        key, rest = label.split(" — ", 1)
        display = f"\033[1m{key}\033[0m — {rest}"
    else:
        display = label
    try:
        val = input(f"  {display}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise
    return val if val else default


#: A short hint for the commented template: the cruise-scoped C89 codes, which
#: are the ones most cruise configs need.  The full list is served by the
#: interactive prompt via :func:`ctdcast.config.people.role_choices`.
_ROLE_HINT = (
    "PS Cruise principal scientist, DI Cruise dataset principal investigator, "
    "MC Cruise data manager, TC Cruise technical contact, TS Cruise technician, "
    "CP Cruise participant, PI Project principal investigator"
)


def _prompt_platform() -> str:
    """Prompt for a ``platforms.yaml`` vessel slug, listing the known slugs.

    The slug (not the free-text ship name) is what resolves the ICES code used to
    derive the EXPOCODE.  Returns an empty string when the user skips it.
    """
    from ctdcast.config.platforms import load_platforms

    slugs = sorted(load_platforms())
    if slugs:
        print(f"  known vessel slugs: {', '.join(slugs)}")
    return (
        _prompt("platform slug (platforms.yaml key; feeds the EXPOCODE)", default="")
        or ""
    )


def _resolve_role(choice: str, roles: list[str]) -> str:
    """Map a menu number or a typed role name to a valid role.

    Accepts the concept code (``PS``) as well as the prefLabel, since both are
    valid in config.  Falls back to ``PI`` (with a note) for an unrecognised
    entry; ``ctdcast validate`` still catches a genuinely wrong role before any
    file is written.
    """
    choice = (choice or "").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(roles):
        return roles[int(choice) - 1]
    for role in roles:
        if choice.lower() == role.lower():
            return role
    # A concept code (PS, DI, CP...) is equally valid in config, so accept it.
    from ctdcast.config.people import DEFAULT_ROLE_VOCABULARY, ROLE_VOCABULARIES

    terms = ROLE_VOCABULARIES[DEFAULT_ROLE_VOCABULARY]["terms"]
    for code, label in terms.items():
        if choice.upper() == code.upper():
            return label
    print("    unrecognised role — defaulting to PI (edit later if wrong).")
    return "PI"


#: Product scopes for a contributor, mapped from a one-letter answer.
_SCOPE_CHOICE = {
    "a": "all",
    "all": "all",
    "c": "ctd",
    "ctd": "ctd",
    "l": "ladcp",
    "ladcp": "ladcp",
}


def _prompt_contributors() -> list[dict[str, object]]:
    """Collect contributors interactively, one entry per PERSON.

    A person is entered once, with their name and ORCID, and may then hold
    several roles, each optionally scoped to one product.  That mirrors the
    config model: repeating a person to give them a second role is what the
    writer does on output, not what the author does in config.

    Returns
    -------
    list of dict
        ``[{"name": str, "orcid": str, "roles": {scope: [role, ...]}}]``, in the
        order entered.
    """
    from ctdcast.config.people import role_choices

    people: list[dict[str, object]] = []
    ans = (_prompt("add contributors now? (y/N)", default="n") or "n").lower()
    if ans not in {"y", "yes"}:
        return people

    roles = role_choices()
    print("    roles:")
    for i, r in enumerate(roles, start=1):
        print(f"      {i:>2}={r}")

    while True:
        name = (_prompt("    name (blank to finish)", default="") or "").strip()
        if not name:
            break
        if ";" in name or "," in name:
            print("    name may not contain ';' or ',' — skipped.")
            continue

        orcid = (_prompt("    ORCID (optional)", default="") or "").strip()
        scoped_roles: dict[str, list[str]] = {}
        while True:
            role = _resolve_role(
                _prompt("      role (number, code or name)", default="1") or "1", roles
            )
            scope_in = (
                _prompt(
                    "      applies to: [a]ll files / [c]td only / [l]adcp only",
                    default="a",
                )
                or "a"
            ).lower()
            scope = _SCOPE_CHOICE.get(scope_in, "all")
            scoped_roles.setdefault(scope, [])
            if role not in scoped_roles[scope]:
                scoped_roles[scope].append(role)
            print(f"      + {role} ({scope})")
            more = (
                _prompt("      another role for this person? (y/N)", default="n") or "n"
            ).lower()
            if more not in {"y", "yes"}:
                break

        entry: dict[str, object] = {"name": name, "roles": scoped_roles}
        if orcid:
            entry["orcid"] = orcid
        people.append(entry)
        flat = ", ".join(f"{r} ({s})" for s, rs in scoped_roles.items() for r in rs)
        print(f"    added: {name} — {flat}")
    return people


def _prompt_institutions() -> list[dict[str, str]]:
    """Collect institution slugs interactively, listing the known ones.

    Institutions are a list of their own, deliberately not attached to people:
    one person may sit at several institutions and one institution may send
    several people, so the two lists are not positionally aligned.

    Each entry also takes a role, because the role is load-bearing rather than
    decorative: the lead entries are what the CF ``institution`` attribute is
    derived from, so a list where nothing leads produces no ``institution`` at
    all.  Asking here is cheaper than the user discovering the omission later.

    Returns
    -------
    list of dict
        ``{"slug": str, "role": str}`` in the order entered; empty when skipped.
    """
    from ctdcast.config.people import (
        DEFAULT_INSTITUTION_ROLE,
        INSTITUTION_ROLE_VOCABULARIES,
        load_institutions,
    )

    roles = INSTITUTION_ROLE_VOCABULARIES["C59"]["terms"]
    known = sorted(load_institutions())
    chosen: list[dict[str, str]] = []
    ans = (_prompt("add institutions now? (y/N)", default="n") or "n").lower()
    if ans not in {"y", "yes"}:
        return chosen
    if known:
        print(f"    known slugs: {', '.join(known)}")
    print(
        "    (one that is not listed can be written inline in the config, or added"
        " to ~/.config/ctdcast/institutions.yaml)"
    )
    print(f"    roles: {', '.join(f'{c} ({label})' for c, label in roles.items())}")
    seen: set[str] = set()
    while True:
        slug = (_prompt("    slug (blank to finish)", default="") or "").strip()
        if not slug:
            break
        if known and slug not in known:
            print(f"    {slug!r} is in no registry — write it inline instead.")
            continue
        if slug in seen:
            continue
        role = (
            _prompt(f"    role for {slug}", default=DEFAULT_INSTITUTION_ROLE) or ""
        ).strip() or DEFAULT_INSTITUTION_ROLE
        if role not in roles:
            print(f"    {role!r} is not a C59 code — using {DEFAULT_INSTITUTION_ROLE}.")
            role = DEFAULT_INSTITUTION_ROLE
        seen.add(slug)
        chosen.append({"slug": slug, "role": role})
    if chosen and not any(c["role"] == "CONLEAD" for c in chosen):
        print(
            "    note: nothing holds CONLEAD, so the CF `institution` attribute "
            "will be omitted."
        )
    return chosen


def _person_lines(person: dict[str, object], item_indent: str) -> list[str]:
    """Render one contributor as YAML list-item lines at *item_indent*.

    Uses the compact ``roles: [...]`` form when every role applies to every
    compiled file, and the scoped mapping form otherwise.
    """
    field = item_indent + "  "
    lines = [f'{item_indent}- name: "{person["name"]}"']
    lines.append(f"{field}orcid: {person.get('orcid') or 'null'}")

    roles = person.get("roles")
    if isinstance(roles, dict):
        scopes = {s: rs for s, rs in roles.items() if rs}
        if set(scopes) == {"all"}:
            joined = ", ".join(f'"{r}"' for r in scopes["all"])
            lines.append(f"{field}roles: [{joined}]")
        else:
            lines.append(f"{field}roles:")
            for scope in ("all", "ctd", "ladcp"):
                if scopes.get(scope):
                    joined = ", ".join(f'"{r}"' for r in scopes[scope])
                    lines.append(f"{field}  {scope}: [{joined}]")
    elif isinstance(roles, list):
        joined = ", ".join(f'"{r}"' for r in roles)
        lines.append(f"{field}roles: [{joined}]")
    else:
        lines.append(f"{field}role: {person.get('role', 'PI')}")
    return lines


def _format_contributors_yaml(
    contributors: list[dict[str, object]] | dict[str, list[dict[str, str]]] | None,
    institutions: list[dict[str, str]] | None = None,
) -> str:
    """Render the ``contributors:`` and ``institutions:`` blocks for the config.

    Emits a commented template when nothing was entered, so the generated file
    still shows the shape.  Accepts the list from :func:`_prompt_contributors`,
    and — for back-compat — the older ``{"all": [...], "ctd": [...]}`` scoped
    dict, which is folded into per-person scoped roles.

    Institution entries are ``{"slug": ..., "role": ...}``; a bare string is
    still accepted and takes the registry's default role.
    """
    people: list[dict[str, object]] = []
    if isinstance(contributors, dict):
        merged: dict[str, dict[str, object]] = {}
        for scope, entries in contributors.items():
            for c in entries or []:
                who = merged.setdefault(
                    str(c["name"]),
                    {"name": c["name"], "orcid": c.get("orcid"), "roles": {}},
                )
                bucket = who["roles"]
                assert isinstance(bucket, dict)
                bucket.setdefault(scope, []).append(c.get("role", "PI"))
        people = list(merged.values())
    elif contributors:
        people = list(contributors)

    institutions = institutions or []

    if not people and not institutions:
        return (
            "  # Each person appears ONCE and may hold several roles; a role can be"
            " scoped\n"
            "  # to one product (`all`, `ctd`, `ladcp`).\n"
            f"  #   # roles (NERC C89): {_ROLE_HINT}\n"
            "  # contributors:\n"
            '  #   - name: "Jane Doe"\n'
            "  #     orcid: null\n"
            "  #     roles: [PS, PI]          # both roles, on every compiled file\n"
            '  #   - name: "Sam Rivera"\n'
            "  #     orcid: null\n"
            "  #     roles:\n"
            "  #       all: [PI]              # every compiled file\n"
            "  #       ctd: [MC]              # profiles.nc only\n"
            "  #       ladcp: [DI]            # ladcp_profiles.nc only\n"
            "  # institutions:                # NOT aligned with the people list\n"
            "  #   - uhh                      # a registry slug\n"
            '  #   - name: "Some Institute"   # or inline, needing no registry\n'
            '  #     id: "https://ror.org/…"\n'
            "  #     role: FUND\n"
        )

    lines: list[str] = []
    if people:
        lines.append("  contributors:")
        for person in people:
            lines.extend(_person_lines(person, "    "))
    if institutions:
        lines.append("  institutions:              # not aligned with the people list")
        for item in institutions:
            if isinstance(item, dict):
                lines.append(f"    - slug: {item['slug']}")
                lines.append(f"      role: {item['role']}")
            else:
                lines.append(f"    - {item}")
    return "\n".join(lines) + "\n"


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
    """Run the interactive init wizard; write config.yaml and optionally ctd_sections_draft.yaml.

    The config always records the user's intended production ``section_yaml`` path.
    When detection runs, the draft is written alongside that path for review.
    """
    dest: Path = args.dest
    initial = dest if dest.suffix in {".yaml", ".yml"} else dest / "config.yaml"

    print("\n=== ctdcast init (interactive) ===\n")

    # Pre-populate prompts from an existing config file so the user can press
    # Enter to keep each current value rather than re-entering everything.
    _ex: dict[str, str] = {}
    if initial.exists():
        try:
            import yaml as _yaml

            _cfg = _yaml.safe_load(initial.read_text()) or {}
            _d = _cfg.get("data", {}) or {}
            _o = _cfg.get("output", {}) or {}
            _ci = _cfg.get("cruise_info", {}) or {}
            _ex = {
                "nc_dir": str(_d.get("nc_dir", "") or ""),
                "cnv_dir": str(_d.get("cnv_dir", "") or ""),
                "cnv_pattern": str(_d.get("cnv_pattern", "") or ""),
                "profiles_nc": str(_d.get("profiles_nc", "") or ""),
                "ladcp_dir": str(_d.get("ladcp_dir", "") or ""),
                "ladcp_pattern": str(_d.get("ladcp_pattern", "") or ""),
                "gebco_nc": str(_d.get("gebco_nc", "") or ""),
                "section_yaml": str(_d.get("section_yaml", "") or ""),
                "output_dir": str(_o.get("dir", "") or ""),
                # `cruise_id` first: that is what the wizard now writes, so
                # re-running against a config it generated must pre-fill from it.
                # `name` is the pre-2026-08-21 spelling, kept so an old config
                # still pre-fills rather than silently blanking.
                "cruise_name": str(
                    _ci.get("cruise")
                    or _ci.get("cruise_id")
                    or _ci.get("name", "")
                    or ""
                ),
                "ship": str(_ci.get("ship", "") or ""),
                "start_date": str(_ci.get("start_date", "") or ""),
                "end_date": str(_ci.get("end_date", "") or ""),
            }
            print(f"(Pre-filling from existing {initial.name})\n")
        except Exception:  # noqa: BLE001
            pass

    config_path = _resolve_output_path(initial, args.force)
    if config_path is None:
        return 0

    _section_header("Data paths")
    nc_dir = _prompt(
        "nc_dir — per-cast netCDF directory"
        " (one .nc per cast, converted from CNV, 1 dbar, both downcast and upcast)",
        default=_ex.get("nc_dir", ""),
        required=True,
    )
    if not nc_dir:
        print("ERROR: nc_dir is required.", file=sys.stderr)
        return 1
    cnv_dir = _prompt(
        "cnv_dir — raw CNV files directory (for ctdcast run --ctd)",
        default=_ex.get("cnv_dir", ""),
    )
    cnv_pattern = _prompt(
        "cnv_pattern — glob to select CNV files",
        default=_ex.get("cnv_pattern", "") or "*.cnv",
    )
    profiles_nc = _prompt(
        "profiles_nc — compiled profiles.nc"
        " (required for section/timeseries auto-detection; optional otherwise)",
        default=_ex.get("profiles_nc", ""),
    )
    ladcp_dir = _prompt(
        "ladcp_dir — LADCP .mat directory",
        default=_ex.get("ladcp_dir", ""),
    )
    ladcp_pattern = None
    if ladcp_dir:
        ladcp_pattern = _prompt(
            "ladcp_pattern — filename pattern (* = zero-padded cast number)",
            default=_ex.get("ladcp_pattern", "") or "*.mat",
        )
    gebco_nc = _prompt(
        "gebco_nc — GEBCO bathymetry .nc",
        default=_ex.get("gebco_nc", ""),
    )
    print(
        "  ↳ ctdcast reads this YAML when generating reports."
        " If detection runs, a draft (ctd_sections_draft.yaml)"
        " is written in the same directory for review."
    )
    section_yaml = _prompt(
        "section_yaml — production YAML path",
        default=_ex.get("section_yaml", "") or "ctd_sections.yaml",
    )

    _section_header("Report")
    output_dir = (
        _prompt("report dir", default=_ex.get("output_dir", "") or "outputs/ctd_report")
        or "outputs/ctd_report"
    )

    _section_header("Cruise info (optional)")
    # The cruise identifier — written to `cruise_id`, which is what the compiled
    # files and report headers read; a value like "MSM142".  (Was previously
    # written to `name`, which nothing reads — the cause of cruise=UNK.)
    cruise_name = (
        _prompt("cruise id (e.g. MSM142)", default=_ex.get("cruise_name", "")) or ""
    )
    # Ask the vessel slug first, then default the free-text ship (masthead) name
    # to that vessel's registry name — deriving the name from the ICES code
    # (unambiguous) rather than validating a typed name into a code (ambiguous).
    from ctdcast.config.platforms import platform_display_name

    platform = _prompt_platform()
    _ship_default = platform_display_name(platform) or _ex.get("ship", "")
    ship = _prompt("ship", default=_ship_default) or ""
    # The chief scientist is captured in the contributor step (role PS, Cruise
    # principal scientist) rather than a separate free-text field.
    start_date = _parse_date(
        _prompt("start date (YYYY-MM-DD)", default=_ex.get("start_date", "")) or ""
    )
    end_date = _parse_date(
        _prompt("end date (YYYY-MM-DD)", default=_ex.get("end_date", "")) or ""
    )
    contributors = _prompt_contributors()
    institutions = _prompt_institutions()

    # Run detection if profiles.nc is available.
    _draft_msg: str = ""
    if not profiles_nc:
        print(
            "  (no profiles.nc — skipping detection; "
            "build one with: ctdcast convert --build-profiles)"
        )
    else:
        profiles_path = Path(profiles_nc)
        if not profiles_path.exists():
            print(f"  WARNING: {profiles_path} not found — skipping section detection.")
        else:
            _section_header("Section / timeseries detection")
            try:
                ans = input("  Run detection from profiles.nc? [Y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                ans = "n"
            if ans not in {"n", "no"}:
                dx_sec = args.dx_section
                dx_diam = args.dx_diameter
                max_turn = args.max_turn_deg
                min_run = args.min_run_casts
                max_sec = args.max_section_casts
                print(
                    f"\n  Thresholds — section break: {dx_sec} km,"
                    f" repeat-station diameter: {dx_diam} km,"
                    f" max heading change: {max_turn}°, min casts/section: {min_run}"
                    f"\n  (Press Enter to accept each default)"
                )
                try:
                    v = input(
                        f"  Repeat-station cluster diameter km [{dx_diam}]: "
                    ).strip()
                    if v:
                        dx_diam = float(v)
                    v = input(f"  Section break distance km [{dx_sec}]: ").strip()
                    if v:
                        dx_sec = float(v)
                    v = input(
                        f"  Max heading change within section deg [{max_turn}]: "
                    ).strip()
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
                    f"\nDetecting (dx_section={dx_sec} km, dx_diameter={dx_diam} km,"
                    f" max_turn={max_turn}°, min_run={min_run}, max_section_casts={max_sec})..."
                )
                try:
                    sections, timeseries = _detect_groups(
                        profiles_path,
                        dx_sec,
                        max_sec,
                        max_turn,
                        min_run,
                        dx_diam,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"  ERROR: {exc}", file=sys.stderr)
                    return 1
                _print_detection_summary(sections, timeseries)
                _draft_dir = (
                    Path(section_yaml).parent if section_yaml else config_path.parent
                )
                _draft_initial = _draft_dir / "ctd_sections_draft.yaml"
                resolved = _resolve_output_path(_draft_initial, args.force)
                if resolved is not None:
                    yaml_text = _format_sections_yaml(
                        sections,
                        timeseries,
                        dx_sec,
                        max_sec,
                        max_turn,
                        min_run,
                        dx_diam,
                    )
                    _write_file(resolved, yaml_text)
                    _target = section_yaml or "ctd_sections.yaml"
                    _same = Path(_target).resolve() == resolved.resolve()
                    if _same:
                        _draft_msg = (
                            f"  Draft written  : {resolved}"
                            f"\n  section_yaml   : {_target}"
                            f"\n  ↳ Draft is already at the production path — no rename needed."
                        )
                    else:
                        _draft_msg = (
                            f"  Draft written  : {resolved}"
                            f"\n  section_yaml   : {_target}"
                            f"\n  ↳ Review the draft, then rename to activate:"
                            f"\n      mv {resolved} {_target}"
                        )
    # Config always points to the user's intended production path; the draft
    # is a temporary review copy that the user renames to activate.
    effective_section_yaml = section_yaml

    config_text = _build_config_text(
        nc_dir=nc_dir,
        cnv_dir=cnv_dir,
        cnv_pattern=cnv_pattern,
        profiles_nc=profiles_nc,
        ladcp_dir=ladcp_dir,
        ladcp_pattern=ladcp_pattern,
        gebco_nc=gebco_nc,
        section_yaml=effective_section_yaml,
        output_dir=output_dir,
        cruise_name=cruise_name,
        ship=ship,
        start_date=start_date,
        end_date=end_date,
        platform=platform,
        contributors=contributors,
        institutions=institutions,
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _write_file(config_path, config_text)
    _section_header("Done")
    print(f"  Config written : {config_path}")
    if _draft_msg:
        print(_draft_msg)
    return 0


# --------------------------------------------------------------------------- #
# Detection algorithm                                                           #
# --------------------------------------------------------------------------- #


def _detect_groups(
    profiles_path: Path,
    dx_section_km: float,
    max_section_casts: int = 25,
    max_turn_deg: float = 45.0,
    min_run_casts: int = 4,
    dx_diameter_km: float = 1.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Detect section and timeseries groups from *profiles_path*.

    Reads per-cast positions from the downcast rows of ``profiles.nc``.

    Algorithm:

    1. **Coarse gap split** — consecutive casts separated by more than
       *dx_section_km* km start a new coarse group (long transits at sea).
    2. **Heading-based section detection** — within each coarse group, find
       maximal sub-sequences where every consecutive heading change is
       ≤ *max_turn_deg*.  Runs shorter than *min_run_casts* are discarded as
       transit noise.  A backward-extension step checks whether the cast
       immediately before a run approaches from the same bearing as the run
       (handles the common "approach station" case where the ship arrives at
       the first section station from a different direction).  Groups detected
       this way are classified as **sections**.
    2b. **Repeat-station cluster detection** — unclaimed casts (not in any
        heading run) are grouped into tight clusters: consecutive unclaimed
        casts with no claimed casts between them and inter-cast distance
        ≤ *dx_diameter_km*.  Clusters of ≥ 2 casts are classified as
        **timeseries** (repeat stations / yoyos).
    3. **Safety cap** — heading runs longer than *max_section_casts* are
       split into consecutive chunks.

    The detection method determines the type: heading runs → section,
    diameter clusters → timeseries.  There is no span-based reclassification.

    Parameters
    ----------
    profiles_path:
        Path to a compiled ``profiles.nc`` file.
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
    dx_diameter_km:
        Maximum inter-cast distance (km) within a repeat-station cluster.
        Unclaimed casts closer than this are grouped as a repeat station.
        Default: 1.0.

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

    # Level 2: within each coarse group, find heading-consistent runs (sections)
    # and tight repeat-station clusters (timeseries).
    # local_bearings[i] = bearing FROM g[i-1] TO g[i] (None for i=0).
    section_groups: list[list[int]] = []
    timeseries_groups: list[list[int]] = []

    for g in gap_groups:
        n_g = len(g)
        if n_g < 2:
            continue

        local_bearings: list[float | None] = [None]
        for i in range(1, n_g):
            local_bearings.append(
                _bearing_deg(
                    float(lats[g[i - 1]]),
                    float(lons[g[i - 1]]),
                    float(lats[g[i]]),
                    float(lons[g[i]]),
                )
            )

        # Find all maximal stable runs (local index lists within g).
        all_local_runs: list[list[int]] = []
        run_start = 0
        for i in range(1, n_g + 1):
            end_run = i == n_g
            if not end_run:
                b_arrive = local_bearings[i - 1]  # how we arrived at g[i-1]
                b_depart = local_bearings[i]  # how we leave g[i-1] toward g[i]
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
                float(lats[g[local_run[0]]]),
                float(lons[g[local_run[0]]]),
                float(lats[g[local_run[-1]]]),
                float(lons[g[local_run[-1]]]),
            )
            approach_bear = _bearing_deg(
                float(lats[g[prev_local]]),
                float(lons[g[prev_local]]),
                float(lats[g[local_run[0]]]),
                float(lons[g[local_run[0]]]),
            )
            if _angle_diff(approach_bear, main_bear) <= max_turn_deg:
                kept[r_idx] = [prev_local] + local_run
                claimed.add(prev_local)

        # Convert to global indices, apply max_section_casts safety cap.
        # Heading-detected runs are sections.
        for local_run in kept:
            global_run = [g[li] for li in local_run]
            for chunk_start in range(0, len(global_run), max_section_casts):
                section_groups.append(
                    global_run[chunk_start : chunk_start + max_section_casts]
                )

        # Step 2b: collect unclaimed casts; split into tight repeat-station clusters.
        # Consecutive unclaimed local indices with no claimed casts between them
        # AND inter-cast distance ≤ dx_diameter_km form one cluster.
        unclaimed = [li for li in range(n_g) if li not in claimed]
        if len(unclaimed) >= 2:
            sub_start = 0
            for si in range(1, len(unclaimed) + 1):
                end_sub = si == len(unclaimed)
                if not end_sub:
                    a_li, b_li = unclaimed[si - 1], unclaimed[si]
                    if b_li - a_li > 1:
                        end_sub = True  # claimed casts between these two
                    else:
                        d = (
                            float(
                                np.asarray(
                                    gsw.distance(
                                        [lons[g[a_li]], lons[g[b_li]]],
                                        [lats[g[a_li]], lats[g[b_li]]],
                                    )
                                )[0]
                            )
                            / 1000.0
                        )
                        end_sub = d > dx_diameter_km
                if end_sub:
                    sub = unclaimed[sub_start:si]
                    if len(sub) >= 2:
                        # Diameter-clustered groups are timeseries.
                        timeseries_groups.append([g[li] for li in sub])
                    sub_start = si

    sections: list[dict[str, Any]] = []
    timeseries: list[dict[str, Any]] = []
    color_idx = 0

    for g in section_groups:
        g_casts = cast_nums[g]
        g_lats = lats[g]
        g_lons = lons[g]
        n_g = len(g)
        first_cast = int(g_casts[0])
        last_cast = int(g_casts[-1])
        color = _TAB10_COLORS[color_idx % len(_TAB10_COLORS)]
        color_idx += 1
        path_km = float(np.sum(inter_km[g[1:]])) if n_g > 1 else 0.0
        cast_numbers = _cast_range(g_casts)
        idx = len(sections) + 1
        sections.append(
            {
                "name": f"Section_{idx:03d}",
                "description": (
                    f"Section {idx:03d} — casts {first_cast:03d}–{last_cast:03d}"
                    f" ({n_g} casts, {path_km:.0f} km)"
                ),
                "cast_numbers": cast_numbers,
                # Draft x-axis origin: the lowest cast number in the group. A true
                # geographic endpoint only if the section was occupied end-to-end;
                # the author should repoint it to an actual end if not.
                "key_cast": int(min(g_casts)),
                "color": color,
            }
        )

    for g in timeseries_groups:
        g_casts = cast_nums[g]
        g_lats = lats[g]
        g_lons = lons[g]
        n_g = len(g)
        color = _TAB10_COLORS[color_idx % len(_TAB10_COLORS)]
        color_idx += 1
        cast_numbers = _cast_range(g_casts)
        lat_c = float(np.nanmean(g_lats))
        lon_c = float(np.nanmean(g_lons))
        ns = "N" if lat_c >= 0 else "S"
        ew = "E" if lon_c >= 0 else "W"
        first_cast_ts = int(g_casts[0])
        last_cast_ts = int(g_casts[-1])
        cast_range_str = (
            f"{first_cast_ts:03d}–{last_cast_ts:03d}"
            if last_cast_ts != first_cast_ts
            else f"{first_cast_ts:03d}"
        )
        idx = len(timeseries) + 1
        timeseries.append(
            {
                "name": f"Station_{idx:03d}",
                "description": (
                    f"Station {idx:03d} — ~{abs(lat_c):.1f}°{ns} {abs(lon_c):.1f}°{ew}"
                    f" ({n_g} cast{'s' if n_g != 1 else ''}: {cast_range_str})"
                ),
                "cast_numbers": cast_numbers,
                "color": color,
                "_lat": lat_c,
                "_lon": lon_c,
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
        f"\n  Detected {total} groups: "
        f"{len(sections)} section(s), {len(timeseries)} repeat station(s)"
    )
    if sections:
        print("\n  Sections")
        print("  " + "─" * 58)
        for s in sections:
            print(f"  {s['description']}")
    if timeseries:
        print("\n  Repeat stations")
        print("  " + "─" * 58)
        for t in timeseries:
            print(f"  {t['description']}")
        # Warn about stations that appear to be at the same location.
        _warned: set[tuple[int, int]] = set()
        for i, a in enumerate(timeseries):
            for j, b in enumerate(timeseries):
                if j <= i:
                    continue
                pair = (i, j)
                if pair in _warned:
                    continue
                a_lat = a.get("_lat")
                b_lat = b.get("_lat")
                a_lon = a.get("_lon")
                b_lon = b.get("_lon")
                if (
                    a_lat is not None
                    and b_lat is not None
                    and abs(a_lat - b_lat) < 0.1
                    and abs(a_lon - b_lon) < 0.1  # type: ignore[operator]
                ):
                    print(
                        f"\n  ⚠  {a['name']} and {b['name']} are at the same location"
                        " — consider merging in the draft YAML."
                    )
                    _warned.add(pair)
    print()


# --------------------------------------------------------------------------- #
# YAML and config formatters                                                    #
# --------------------------------------------------------------------------- #


def _format_sections_yaml(
    sections: list[dict[str, Any]],
    timeseries: list[dict[str, Any]],
    dx_section_km: float,
    max_section_casts: int = 25,
    max_turn_deg: float = 45.0,
    min_run_casts: int = 4,
    dx_diameter_km: float = 1.0,
) -> str:
    """Return a YAML string for ``ctd_sections_draft.yaml``."""
    lines: list[str] = [
        "# ctd_sections_draft.yaml — auto-generated by ctdcast init --interactive",
        (
            f"# Detection thresholds: dx_section={dx_section_km} km,"
            f" dx_diameter={dx_diameter_km} km, max_turn={max_turn_deg}°,"
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
            if "key_cast" in entry:
                lines.append(
                    f"    key_cast: {entry['key_cast']}"
                    "   # x-axis origin; repoint to a section endpoint if needed"
                )
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
    ladcp_pattern: str | None,
    gebco_nc: str | None,
    section_yaml: str | None,
    output_dir: str,
    cruise_name: str,
    ship: str,
    start_date: str,
    end_date: str,
    platform: str = "",
    contributors: list[dict[str, object]]
    | dict[str, list[dict[str, str]]]
    | None = None,
    institutions: list[dict[str, str]] | None = None,
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
    ladcp_pattern_default = "*.mat"
    ladcp_pattern_line = (
        f"  ladcp_pattern: {ladcp_pattern}"
        if ladcp_pattern and ladcp_pattern != ladcp_pattern_default
        else f"  # ladcp_pattern: {ladcp_pattern_default}  # * = zero-padded cast number"
    )
    gebco_line = (
        f"  gebco_nc: {gebco_nc}"
        if gebco_nc
        else "  # gebco_nc: /path/to/GEBCO_2025.nc"
    )
    platform_line = (
        f"  platform: {platform}"
        if platform
        else "  # platform: odb   # platforms.yaml slug -> ICES code for the EXPOCODE"
    )
    contributors_block = _format_contributors_yaml(
        contributors or [], institutions or []
    )
    return (
        "# ctdcast configuration — generated by ctdcast init --interactive\n"
        "# Run 'ctdcast validate config.yaml' to check all paths before the first run.\n"
        "\n"
        "data:\n"
        f"  nc_dir: {nc_dir}\n"
        f"{cnv_line}\n"
        f"{cnv_pattern_line}\n"
        f"{profiles_line}\n"
        f"{sections_line}\n"
        f"{ladcp_line}\n"
        f"{ladcp_pattern_line}\n"
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
        f'  cruise_id: "{cruise_name}"\n'
        f'  ship: "{ship}"\n'
        f"{platform_line}\n"
        f'  start_date: "{start_date}"\n'
        f'  end_date: "{end_date}"\n'
        f"{contributors_block}"
        "  # embargo:                   # moratorium -> a self-describing license\n"
        '  #   policy: "SDN:L08::MO"\n'
        "  #   until: null              # null -> end_date + 2 years\n"
        "\n"
        "display:\n"
        "  section_style: pcolormesh\n"
        "  timeseries_style: pcolormesh\n"
        "  # dbar_step: 1  # plot every Nth dbar from profiles.nc (1 = full resolution)\n"
    )


def _write_file(path: Path, text: str) -> None:
    """Write *text* to *path*."""
    path.write_text(text)


# Keep old name as alias so existing callers are not broken.
_write_ruamel = _write_file
