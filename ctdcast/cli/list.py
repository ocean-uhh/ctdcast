"""``ctdcast list`` — show the registry slugs a cruise config names (institutions, platforms, roles)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_CHOICES = ("institutions", "platforms", "roles")


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,  # type: ignore[type-arg]
) -> argparse.ArgumentParser:
    """Build the argument parser for ``ctdcast list``."""
    _epilog = """
A cruise config names institutions, a platform, and roles by slug/code; this lists
what each registry holds so you do not have to open a file in site-packages.

Give a CONFIG to also see what *your* config adds (a cruise institutions_file, and
inline institution/platform entries); without one you see only what ships with ctdcast.

Examples:
  ctdcast list                              # the three registries
  ctdcast list institutions                 # what ships + your user directory
  ctdcast list institutions config.yaml     # ... plus this config's entries
  ctdcast list platforms --search meteor    # filter by slug or name
  ctdcast list roles --vocabulary W08       # one role vocabulary
"""
    kwargs: dict = {
        "description": "List the institution, platform and role registries.",
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": _epilog,
    }
    if subparsers is not None:
        parser = subparsers.add_parser(
            "list", help="List the institution, platform and role registries.", **kwargs
        )
        parser.set_defaults(func=run)
    else:
        parser = argparse.ArgumentParser(prog="ctdcast list", **kwargs)

    parser.add_argument(
        "registry",
        nargs="?",
        choices=_CHOICES,
        default=None,
        help="Which registry to list; omit to see the three registry names.",
    )
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=None,
        help="Optional config.yaml — also shows what this cruise's config adds.",
    )
    parser.add_argument(
        "--search",
        metavar="TEXT",
        default=None,
        help="Case-insensitive filter across slug and name.",
    )
    parser.add_argument(
        "--vocabulary",
        metavar="NAME",
        default=None,
        help="For `roles`: show one vocabulary only (C89, G04, C59, W08).",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """Execute ``ctdcast list``."""
    if args.registry is None:
        print("ctdcast registries (use `ctdcast list <name>`):")
        print(
            "  institutions   research organisations, by slug — cruise_info.institutions"
        )
        print("  platforms      vessels, by slug — cruise_info.platform / ship_slug")
        print("  roles          contributor role codes — cruise_info.*role_vocabulary")
        return 0

    cruise_info = _load_cruise_info(args.config)
    if cruise_info is None:  # a named config that could not be read
        return 1

    if args.registry == "institutions":
        _list_institutions(cruise_info, args.config, args.search)
    elif args.registry == "platforms":
        _list_platforms(cruise_info, args.config, args.search)
    else:  # roles
        return _list_roles(args.vocabulary, args.search)
    return 0


def _load_cruise_info(config: Path | None) -> dict[str, Any] | None:
    """Return the ``cruise_info`` mapping from *config*, ``{}`` when no config, or None on error."""
    if config is None:
        return {}
    if not config.exists():
        print(f"Config file not found: {config}", file=sys.stderr)
        return None
    import yaml

    with open(config) as fh:
        cfg = yaml.safe_load(fh) or {}
    return cfg.get("cruise_info") or {}


def _matches(search: str | None, *fields: str) -> bool:
    """True when *search* is absent, or a case-insensitive substring of any field."""
    return search is None or any(search.lower() in f.lower() for f in fields)


def _print_table(rows: list[dict[str, str]], columns: list[tuple[str, str]]) -> None:
    """Print *rows* as plain aligned columns; *columns* is a list of (key, header)."""
    if not rows:
        print("  (none)")
        return
    widths = {
        key: max(len(header), *(len(str(r.get(key, ""))) for r in rows))
        for key, header in columns
    }
    header = "  ".join(h.ljust(widths[k]) for k, h in columns)
    print(header)
    print("  ".join("-" * widths[k] for k, _ in columns))
    for r in rows:
        print("  ".join(str(r.get(k, "")).ljust(widths[k]) for k, _ in columns))


def _list_institutions(
    cruise_info: dict[str, Any], config: Path | None, search: str | None
) -> None:
    """List institutions with their source (packaged/user/config file/inline)."""
    from ctdcast.config.people import institutions_with_source

    extra = cruise_info.get("institutions_file")
    inline = cruise_info.get("institutions")
    rows = [
        r
        for r in institutions_with_source(extra=extra, inline=inline)
        if _matches(search, r["slug"], r["name"])
    ]
    _print_table(rows, [("slug", "Slug"), ("name", "Name"), ("source", "Source")])

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["source"]] = counts.get(r["source"], 0) + 1
    print(f"\nSources: {', '.join(f'{s} ({n})' for s, n in counts.items()) or 'none'}.")
    if config is None:
        print(
            "No config given — cruise_info.institutions_file and inline entries not shown."
        )


def _list_platforms(
    cruise_info: dict[str, Any], config: Path | None, search: str | None
) -> None:
    """List platforms (packaged + any inline config entry), then the ambiguous/forbidden traps."""
    from ctdcast.config.platforms import (
        ambiguous_slugs,
        forbidden_codes,
        load_platforms,
    )

    rows = [
        {
            "slug": slug,
            "name": str(entry.get("name") or ""),
            "ices": str(entry.get("ices_code") or ""),
            "source": "packaged",
        }
        for slug, entry in load_platforms().items()
    ]
    inline = cruise_info.get("platform")
    if isinstance(inline, dict) and inline.get(
        "name"
    ):  # an inline vessel from this config
        rows.append(
            {
                "slug": "",
                "name": str(inline["name"]),
                "ices": str(inline.get("ices_code") or ""),
                "source": "inline",
            }
        )
    rows = [r for r in rows if _matches(search, r["slug"], r["name"])]
    _print_table(
        rows,
        [("slug", "Slug"), ("name", "Name"), ("ices", "ICES"), ("source", "Source")],
    )

    ambiguous = ambiguous_slugs()
    if ambiguous:
        print("\nAmbiguous slugs (refused — name the specific vessel):")
        for slug, why in ambiguous.items():
            print(f"  {slug}: {why}")
    forbidden = forbidden_codes()
    if forbidden:
        print("\nForbidden ICES codes (refused):")
        for code, why in forbidden.items():
            print(f"  {code}: {why}")

    print(
        "\nPlatforms ship in ctdcast/config/platforms.yaml. Add a vessel not listed with an "
        "inline cruise_info.platform mapping (name + ices_code)."
    )
    if config is None:
        print("No config given — an inline cruise_info.platform would not be shown.")


def _list_roles(vocabulary: str | None, search: str | None) -> int:
    """List contributor role codes, grouped by axis (person / institution), defaults marked.

    Returns 1 when *vocabulary* names no known vocabulary, else 0.
    """
    from ctdcast.config.people import (
        DEFAULT_INSTITUTION_ROLE_VOCABULARY,
        DEFAULT_ROLE_VOCABULARY,
        INSTITUTION_ROLE_VOCABULARIES,
        ROLE_VOCABULARIES,
    )

    axes = [
        ("Person roles", ROLE_VOCABULARIES, DEFAULT_ROLE_VOCABULARY),
        (
            "Institution roles",
            INSTITUTION_ROLE_VOCABULARIES,
            DEFAULT_INSTITUTION_ROLE_VOCABULARY,
        ),
    ]
    if vocabulary is not None:
        known = {**ROLE_VOCABULARIES, **INSTITUTION_ROLE_VOCABULARIES}
        if vocabulary not in known:
            print(
                f"Unknown vocabulary {vocabulary!r}; choose one of {sorted(known)}.",
                file=sys.stderr,
            )
            return 1

    for axis_name, vocabs, default in axes:
        printed_axis = False
        for name, spec in vocabs.items():
            if vocabulary is not None and name != vocabulary:
                continue
            if not printed_axis:
                print(f"\n{axis_name}:")
                printed_axis = True
            marker = "  (default)" if name == default else ""
            print(f"\n  {name} — {spec.get('title', '')}{marker}")
            rows = [
                {"code": code, "label": label}
                for code, label in spec["terms"].items()
                if _matches(search, code, label)
            ]
            for r in rows:
                print(f"    {r['code']:<4} {r['label']}")
    return 0
