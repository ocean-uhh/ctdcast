"""Contributors and institutions: config → validated records → netCDF attributes.

The conventions store people as **parallel delimited strings aligned by
position** — ``contributor_name``, ``contributor_email``, ``contributor_role``
and ``contributor_id`` are separate attributes whose *n*-th elements describe the
same person.  That representation has two silent failure modes, and this module
exists to make both impossible:

* **A delimiter inside a value.**  OG1 specifies comma-separated,
  OceanSITES semicolon-separated.  Comma is unsafe — ``"A. Sanchez Franks, NOC"``
  is a real string from a CCHDO header, and splitting it yields two people.
  ctdcast writes **semicolon**-separated (per OceanSITES) and refuses any
  person-level value containing ``;`` or ``,``, so the output survives a reader
  that assumes either.

  Institution names are the exception and are checked for ``;`` only: EDMO's
  official names contain commas unavoidably — *"University of Hamburg,
  Institute of Oceanography"* — which is itself the demonstration that comma
  cannot serve as the delimiter for ``contributing_institutions``.
* **Lists of unequal length.**  Four names and three emails parses cleanly and
  attributes the wrong address to the wrong person.  The strings are generated
  from one structured list here, so they cannot drift.

Note the direction of travel.  ``amocatlas.contributors`` *parses* delimited
strings out of other people's files and is deliberately lenient — it splits on
both delimiters and warns heuristically.  ctdcast *writes* its own files and
controls the delimiter, so it can be strict instead, which is the stronger
guarantee.

Roles come from **NERC C89** (BODC data/cruise roles) — the vocabulary that fits a
research-cruise dataset (``Cruise principal scientist``, ``Project principal
investigator``, ``Project collaborator``, …).  It is the only NVS collection
with cruise-scoped terms, and so the only one able to record a chief scientist —
``PS``, whose definition explicitly allows the role to be shared.  A role may be given in config as its full
prefLabel or its short C89 code (``PS``, ``PI``, ``CO``); it is normalised to the
prefLabel on write, and ``contributor_role_vocabulary`` names C89.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

#: Separator written between entries in the parallel attribute strings.
#: OceanSITES mandates ``;``; OG1 says ``,``.  Semicolon is the safe choice
#: because personal names and "Name, Institution" strings contain commas.
SEPARATOR = "; "

#: Characters that may never appear inside a field value, because a reader
#: assuming either convention's delimiter would mis-split the string.
FORBIDDEN_IN_VALUE = (";", ",")

#: The role vocabularies ctdcast can author in, keyed by short name.  Each maps
#: concept id → prefLabel, and each ``uri`` is what goes into
#: ``contributor_role_vocabulary``.
#:
#: These are alternatives to CHOOSE BETWEEN, never things to convert between.
#: A mapping from one to another is necessarily lossy — C89 distinguishes the
#: chief scientist from the funded PI, G04 cannot — and a converted file
#: has no way to record that the detail was dropped.  So ctdcast validates and
#: writes in whichever vocabulary the config declares, and does not translate.
#: A consumer needing a different vocabulary can map it themselves, knowing
#: their own tolerance for the loss; that judgement is not ours to make.
ROLE_VOCABULARIES: dict[str, dict[str, Any]] = {
    # BODC dataset roles.  The default: the only NVS collection with
    # cruise-scoped terms, and the only one able to say "chief scientist".
    "C89": {
        "uri": "https://vocab.nerc.ac.uk/collection/C89/current/",
        "title": "BODC dataset roles",
        "terms": {
            # --- cruise-scoped ---
            "PS": "Cruise principal scientist",  # the chief scientist
            "DI": "Cruise dataset principal investigator",  # owns one data subset
            "MC": "Cruise data manager",
            "TC": "Cruise technical contact",
            "TS": "Cruise technician",
            "CP": "Cruise participant",
            # --- project-scoped ---
            "PI": "Project principal investigator",
            "CI": "Project co-investigator",
            "CO": "Project collaborator",
            "DP": "Project dataset principal investigator",
            "MP": "Project data manager",
            "PM": "Project manager",
            "PA": "Project administrator",
            "PD": "Project research assistant",
            "PG": "Project research student",
            "RA": "Project technician",
            # --- unscoped ---
            "DM": "Data manager",
            "DC": "Dataset supply contact",
        },
    },
    # ISO 19115-1 CI_RoleCode.  What the IOOS Metadata Profile expects, and what
    # SeaDataNet CSR records actually carry.  Choose this when a compliance
    # checker requires it, accepting that a chief scientist can only be called
    # ``principalInvestigator``.
    "G04": {
        "uri": "https://vocab.nerc.ac.uk/collection/G04/current/",
        "title": "ISO 19115 CI_RoleCode",
        "terms": {
            "001": "resourceProvider",
            "002": "custodian",
            "003": "owner",
            "004": "user",
            "005": "distributor",
            "006": "originator",
            "007": "pointOfContact",
            "008": "principalInvestigator",
            "009": "processor",
            "010": "publisher",
            "011": "author",
            "012": "sponsor",
            "013": "coAuthor",
            "014": "collaborator",
            "015": "editor",
            "016": "mediator",
            "017": "rightsHolder",
            "018": "contributor",
            "019": "funder",
            "020": "stakeholder",
        },
    },
}

#: Used when ``cruise_info.role_vocabulary`` is absent.
DEFAULT_ROLE_VOCABULARY = "C89"

#: Roles that denote responsibility for the science or the data, per vocabulary.
#: Only used to decide whether the "nobody is leading this" warning fires.
_LEAD_ROLES: dict[str, frozenset[str]] = {
    "C89": frozenset({"PS", "DI", "PI", "DP"}),
    "G04": frozenset({"008"}),
}

#: Convenience alias for the default vocabulary's terms (code → prefLabel).
C89_ROLES: dict[str, str] = ROLE_VOCABULARIES["C89"]["terms"]


def role_choices(vocabulary: str | None = None) -> list[str]:
    """Return the prefLabels of a role vocabulary, in definition order.

    Intended for interactive prompting, where a numbered list of human-readable
    roles is wanted rather than concept codes.

    Parameters
    ----------
    vocabulary : str, optional
        Short name from :data:`ROLE_VOCABULARIES`; defaults to
        :data:`DEFAULT_ROLE_VOCABULARY`.

    Returns
    -------
    list of str
        prefLabels, ordered as the vocabulary defines them (cruise-scoped terms
        first, for C89).
    """
    name = vocabulary or DEFAULT_ROLE_VOCABULARY
    return list(ROLE_VOCABULARIES[name]["terms"].values())


def role_vocabulary(cruise_info: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return ``(name, spec)`` for the vocabulary this config authors in.

    Parameters
    ----------
    cruise_info : dict
        The ``cruise_info:`` mapping; ``role_vocabulary`` selects the vocabulary
        by short name and defaults to :data:`DEFAULT_ROLE_VOCABULARY`.

    Returns
    -------
    name : str
    spec : dict
        ``uri``, ``title`` and ``terms`` for the selected vocabulary.

    Raises
    ------
    KeyError
        If the named vocabulary is not one of :data:`ROLE_VOCABULARIES`.
    """
    name = str(cruise_info.get("role_vocabulary") or DEFAULT_ROLE_VOCABULARY)
    return name, ROLE_VOCABULARIES[name]


def _role_lookup(spec: dict[str, Any]) -> dict[str, str]:
    """Map both concept ids and prefLabels of *spec* to the canonical prefLabel."""
    terms: dict[str, str] = spec["terms"]
    return {**dict(terms), **{label: label for label in terms.values()}}


#: Vocabularies for INSTITUTION roles — a different question from a person's
#: role, and a different list.  OG1 names W08 for this
#: (``contributing_institutions_role_vocabulary``), and W08's organisational
#: terms (Operator, Owner, Manufacturer, Service Provider) genuinely are
#: organisation roles, which is why W08 belongs here even though it was the
#: wrong list for people.  C59 is the default because it is project-shaped —
#: lead, member, data management, funding body — which is what an institution
#: is to a funded cruise, and because it can name a funder, which W08 cannot.
INSTITUTION_ROLE_VOCABULARIES: dict[str, dict[str, Any]] = {
    "C59": {
        "uri": "https://vocab.nerc.ac.uk/collection/C59/current/",
        "title": "BODC organisation roles within activities and projects",
        "terms": {
            "CONLEAD": "Project Lead",
            "CONMEM": "Project Member",
            "DATM": "Project Data Management",
            "FUND": "Project Funding body",
        },
    },
    "W08": {
        "uri": "https://vocab.nerc.ac.uk/collection/W08/current/",
        "title": "SensorML Contact Section Terms",
        "terms": {
            "CONT0001": "Manufacturer",
            "CONT0002": "Owner",
            "CONT0003": "Operator",
            "CONT0004": "PI",
            "CONT0005": "Technical Coordinator",
            "CONT0006": "Data scientist",
            "CONT0007": "Service Provider",
        },
    },
}

#: Used when ``cruise_info.institution_role_vocabulary`` is absent.
DEFAULT_INSTITUTION_ROLE_VOCABULARY = "C59"

#: Applied to an institution entry that names no role.
DEFAULT_INSTITUTION_ROLE = "CONMEM"

#: The term meaning "this organisation led the work", per vocabulary URI.  Used
#: only to derive the CF ``institution`` attribute when exactly one institution
#: holds it; W08 has no project-lead term (its roles are instrument-shaped), so
#: it is absent here rather than mapped to a near-miss like Operator.
_INSTITUTION_LEAD_ROLES: dict[str, str] = {
    INSTITUTION_ROLE_VOCABULARIES["C59"]["uri"]: "CONLEAD",
}


def institution_role_vocabulary(
    cruise_info: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Return ``(name, spec)`` for the institution-role vocabulary in use.

    Parameters
    ----------
    cruise_info : dict
        The ``cruise_info:`` mapping; ``institution_role_vocabulary`` selects by
        short name and defaults to
        :data:`DEFAULT_INSTITUTION_ROLE_VOCABULARY`.

    Returns
    -------
    name : str
    spec : dict

    Raises
    ------
    KeyError
        If the named vocabulary is unknown.
    """
    name = str(
        cruise_info.get("institution_role_vocabulary")
        or DEFAULT_INSTITUTION_ROLE_VOCABULARY
    )
    return name, INSTITUTION_ROLE_VOCABULARIES[name]


def resolve_institution(
    item: Any, registry: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """Resolve one ``institutions:`` entry to ``{name, id, role}``.

    An entry may be written three ways, so that a user who installed ctdcast
    from PyPI — and therefore cannot edit the packaged registry — can still name
    an institution the registry does not know::

        institutions:
          - uhh                                   # a registry slug
          - slug: ulpgc                           # a slug, with a role
            role: CONLEAD
          - name: "Agencia Estatal de Investigación"   # inline, no registry
            id: "https://ror.org/003x0zc53"
            role: FUND

    Parameters
    ----------
    item : str or dict
        One entry from ``cruise_info.institutions``.
    registry : dict
        The loaded institution registry, keyed by slug.

    Returns
    -------
    dict or None
        ``{"name": str, "id": str, "role": str}``, or ``None`` when a slug does
        not resolve.
    """
    if isinstance(item, str):
        entry = registry.get(item)
        if entry is None:
            return None
        return {
            "name": str(entry.get("name") or ""),
            "id": str(entry.get("edmo_uri") or ""),
            "role": str(entry.get("role") or DEFAULT_INSTITUTION_ROLE),
        }

    if not isinstance(item, dict):
        return None

    slug = item.get("slug")
    base: dict[str, Any] = {}
    if slug:
        entry = registry.get(str(slug))
        if entry is None:
            return None
        base = {
            "name": str(entry.get("name") or ""),
            "id": str(entry.get("edmo_uri") or ""),
        }
    return {
        "name": str(item.get("name") or base.get("name") or ""),
        "id": str(item.get("id") or base.get("id") or ""),
        "role": str(item.get("role") or DEFAULT_INSTITUTION_ROLE),
    }


#: Scope keys accepted inside a contributor's ``roles:`` mapping.  ``all`` means
#: every compiled file; the others name one product, so a role listed there is
#: written only when that file is built.
ALL_SCOPE = "all"
PRODUCT_SCOPES = ("ctd", "ladcp")
KNOWN_SCOPES = (ALL_SCOPE, *PRODUCT_SCOPES)


def entry_roles(entry: dict[str, Any], source: str | None = None) -> list[str]:
    """Return the roles a contributor holds on one product file, in order.

    A contributor states their roles once, in any of three forms::

        role: PI                      # one role, every file
        roles: [PS, PI]               # several roles, every file
        roles:                        # scoped: some roles only on one product
          all: [PI]
          ctd: [DC]
          ladcp: [DI]

    The scoped form is what lets one person be a project PI everywhere but the
    supply contact for the CTD file only, without repeating their name and ORCID
    and without a second contributor list.

    Parameters
    ----------
    entry : dict
        One contributor mapping.
    source : str or None
        Product key being written (``"ctd"``, ``"ladcp"``).  ``None`` returns
        the union across every scope, which is what validation wants.

    Returns
    -------
    list of str
        Role tokens as written in config (codes or prefLabels), ``all`` first
        then the product's own, with duplicates removed and order preserved.
    """
    roles = entry.get("roles")
    if roles is None:
        single = entry.get("role")
        return [single] if single else []

    if isinstance(roles, (str, int)):
        return [roles]
    if isinstance(roles, list):
        return list(roles)
    if not isinstance(roles, dict):
        return []

    if source is None:
        wanted = [ALL_SCOPE, *[s for s in roles if s != ALL_SCOPE]]
    else:
        wanted = [ALL_SCOPE, source]

    out: list[str] = []
    for scope in wanted:
        for role in roles.get(scope) or []:
            if role not in out:
                out.append(role)
    return out


#: ACDD 1.3 ``creator_type`` values.
CREATOR_TYPES = ("person", "group", "institution", "position")

#: An ORCID, bare or as a resolvable URL.  Both forms are accepted and
#: normalised to the URL on write, since AMOCatlas's registry stores ``id_url``
#: and people paste whichever form their browser shows.
_ORCID_RE = re.compile(
    r"^(?:https?://(?:www\.)?orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$",
    re.IGNORECASE,
)
#: Email pattern taken from ``amocatlas.contributors.is_valid_email`` rather
#: than reinvented: it requires a TLD of at least two letters, so ``user@domain``
#: is correctly rejected where a looser ``.+@.+\..+`` would accept it.
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

_INSTITUTIONS_YAML = Path(__file__).parent / "institutions.yaml"


@dataclass(frozen=True)
class Person:
    """One contributor, as resolved from config."""

    name: str
    role: str
    institution: str | None = None
    email: str | None = None
    orcid: str | None = None


def _user_registry_dir() -> Path:
    """Return the per-user config directory ctdcast reads registries from.

    ``$CTDCAST_CONFIG_DIR`` if set, else ``$XDG_CONFIG_HOME/ctdcast``, else
    ``~/.config/ctdcast``.  Nothing is created; a missing directory simply means
    no user registry.
    """
    env = os.environ.get("CTDCAST_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "ctdcast"


def institution_registry_paths(extra: Path | str | None = None) -> list[Path]:
    """Return the registry files to merge, lowest precedence first.

    Institutions are looked up in three places so that **a user who installed
    ctdcast from PyPI never has to edit package data** — which lives in
    site-packages and is overwritten on upgrade:

    1. the packaged ``ctdcast/config/institutions.yaml`` (the shipped defaults);
    2. ``~/.config/ctdcast/institutions.yaml`` (or ``$CTDCAST_CONFIG_DIR``), for
       institutions an individual or lab uses across cruises;
    3. a path given by ``cruise_info.institutions_file``, for a registry kept
       beside the cruise config and version-controlled with it.

    Later files win key-by-key.  A fourth route needs no registry at all: an
    entry in ``cruise_info.institutions`` may be written inline with its own
    ``name`` and ``id`` — see :func:`resolve_institution`.  Inline is the most
    reproducible option, since the config then carries everything the file
    asserts.

    Parameters
    ----------
    extra : Path or str, optional
        The ``institutions_file`` from the cruise config.

    Returns
    -------
    list of Path
        Existing files only, in merge order.
    """
    candidates = [
        _INSTITUTIONS_YAML,
        _user_registry_dir() / "institutions.yaml",
    ]
    if extra:
        candidates.append(Path(extra).expanduser())
    return [p for p in candidates if p.exists()]


@lru_cache(maxsize=8)
def _load_registry_file(path: Path) -> dict[str, dict[str, Any]]:
    """Load one institution registry file, keyed by slug."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("institutions") or {}


def load_institutions(extra: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """Return the merged institution registry, keyed by slug.

    Merges every file from :func:`institution_registry_paths`, later files
    overriding earlier ones slug by slug.  Returns an empty mapping when no
    registry exists, so a config that defines its institutions inline still
    works.

    Parameters
    ----------
    extra : Path or str, optional
        The ``institutions_file`` from the cruise config.

    Returns
    -------
    dict
        Slug → institution entry.
    """
    merged: dict[str, dict[str, Any]] = {}
    for path in institution_registry_paths(extra):
        merged.update(_load_registry_file(path))
    return merged


def orcid_uri(orcid: str) -> str:
    """Return the resolvable URI for an ORCID given in either accepted form.

    Accepts a bare identifier (``0000-0001-8773-7838``) or a URL
    (``https://orcid.org/0000-0001-8773-7838``) and always returns the URL, so
    the value written to ``contributor_id`` is canonical regardless of how it
    was typed.

    Parameters
    ----------
    orcid : str
        Bare identifier or orcid.org URL.

    Returns
    -------
    str
        ``https://orcid.org/<identifier>``.

    Raises
    ------
    ValueError
        If *orcid* matches neither form.
    """
    match = _ORCID_RE.match(str(orcid).strip())
    if match is None:
        raise ValueError(f"not an ORCID: {orcid!r}")
    return f"https://orcid.org/{match.group(1).upper()}"


def _canonical_orcid(orcid: Any) -> str | None:
    """Return the canonical ORCID URL, or ``None`` when absent or malformed.

    Comparison helper only: a malformed ORCID is reported separately by
    :func:`check_contributors`, so this must not raise on one.

    Parameters
    ----------
    orcid : any
        Bare identifier, orcid.org URL, ``None``, or anything else.

    Returns
    -------
    str or None
        ``https://orcid.org/<identifier>``, or ``None``.
    """
    if orcid is None:
        return None
    try:
        return orcid_uri(str(orcid))
    except ValueError:
        return None


def check_contributors(cruise_info: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Validate the ``contributors``/``creator`` block of a cruise config.

    Returns ``(errors, warnings)``.  Errors are conditions that would produce a
    misleading file — a value containing a delimiter, an unknown role, an
    unresolvable institution.  Warnings are omissions that are legitimate while
    a cruise is in progress but should be settled before publication.

    Parameters
    ----------
    cruise_info : dict
        The ``cruise_info:`` mapping from the cruise config.

    Returns
    -------
    errors : list of str
    warnings : list of str
    """
    errors: list[str] = []
    warnings: list[str] = []

    registry = load_institutions(cruise_info.get("institutions_file"))

    try:
        vocab_name, vocab = role_vocabulary(cruise_info)
    except KeyError:
        errors.append(
            f"cruise_info.role_vocabulary "
            f"{cruise_info.get('role_vocabulary')!r} is unknown. "
            f"Choose one of {sorted(ROLE_VOCABULARIES)}."
        )
        return errors, warnings
    lookup = _role_lookup(vocab)
    lead = {vocab["terms"][c] for c in _LEAD_ROLES.get(vocab_name, frozenset())}

    contributors = cruise_info.get("contributors")

    if contributors is None:
        warnings.append(
            "cruise_info.contributors is absent — no PI will be recorded in the "
            "output files"
        )
        return errors, warnings

    if not isinstance(contributors, list):
        errors.append("cruise_info.contributors must be a list of mappings")
        return errors, warnings

    seen_names: dict[str, Any] = {}
    n_pi = 0
    leads_by_scope: dict[str, int] = dict.fromkeys(PRODUCT_SCOPES, 0)

    for i, entry in enumerate(contributors, start=1):
        where = f"cruise_info.contributors[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{where} must be a mapping, not {type(entry).__name__}")
            continue

        name = (entry.get("name") or "").strip()
        if not name:
            errors.append(f"{where}: name is required")
        else:
            # A repeated name is how one person holds several roles: the entry
            # is duplicated, once per role, because the parallel strings are
            # positional and a single slot cannot carry two roles.  So this is
            # not a duplicate -- but the identifiers must agree, or the file
            # would assert two different ORCIDs for one name.
            # Compare the CANONICAL form: the bare id and the orcid.org URL are
            # the same identifier, and the docstring of `orcid_uri` promises both
            # are accepted, so comparing raw strings would reject a config that
            # merely typed one entry each way.
            orcid_here = entry.get("orcid")
            canon_here = _canonical_orcid(orcid_here)
            if name in seen_names:
                canon_seen = _canonical_orcid(seen_names[name])
                if canon_here is not None and canon_seen is not None:
                    if canon_here != canon_seen:
                        errors.append(
                            f"{where}: {name!r} appears more than once with "
                            f"different ORCIDs ({seen_names[name]!r} and "
                            f"{orcid_here!r}). Repeating a person for a second "
                            f"role must repeat their identifiers unchanged."
                        )
                elif canon_here != canon_seen:
                    # One of the two carries no ORCID: the emitted
                    # `contributor_id` would have a filled slot and a blank one
                    # for the same person, which reads as two people.
                    errors.append(
                        f"{where}: {name!r} appears more than once but only some "
                        f"entries carry an ORCID. Repeat the identifier on every "
                        f"entry for that person, or omit it from all of them."
                    )
            if canon_here is not None or name not in seen_names:
                seen_names[name] = orcid_here

        # The delimiter check — the whole reason this function exists.
        for key in ("name", "email"):
            value = entry.get(key)
            if isinstance(value, str):
                bad = [c for c in FORBIDDEN_IN_VALUE if c in value]
                if bad:
                    errors.append(
                        f"{where}.{key} contains {bad!r}: {value!r}. Entries are "
                        f"written as delimited strings, so a value containing "
                        f"a delimiter splits into two people."
                    )

        raw_roles = entry.get("roles")
        if isinstance(raw_roles, dict):
            unknown = [s for s in raw_roles if s not in KNOWN_SCOPES]
            if unknown:
                errors.append(
                    f"{where}.roles: unknown scope(s) {unknown}. "
                    f"Use {list(KNOWN_SCOPES)} — 'all' for every compiled file, "
                    f"a product key for that file only."
                )

        roles_here = entry_roles(entry)
        if not roles_here:
            errors.append(
                f"{where}: at least one role is required (a {vocab_name} code or "
                f"prefLabel), as `role:`, `roles: [...]` or `roles: {{all: [...]}}`"
            )
        for role in roles_here:
            if not isinstance(role, str):
                # YAML turns an unquoted `role: 8` into an int, and a G04 code is
                # "008" -- zero-padded, so it can never match after str().  Say
                # that, instead of reporting `8` as an unknown term.
                errors.append(
                    f"{where}: role {role!r} parsed as {type(role).__name__}, "
                    f'not text. Quote it (role: "{role}") — {vocab_name} codes '
                    f"are strings and may carry leading zeros."
                )
                continue
            if role not in lookup:
                errors.append(
                    f"{where}: role {role!r} is not a {vocab_name} "
                    f"({vocab['title']}) term. Codes: {sorted(vocab['terms'])}"
                )
            elif lookup[role] in lead:
                n_pi += 1
        # Per-product too: `entry_roles(entry)` unions every scope, so a lead
        # scoped to one product would otherwise vouch for the other product's
        # file, which records no lead at all.
        for scope in PRODUCT_SCOPES:
            for role in entry_roles(entry, scope):
                if isinstance(role, str) and lookup.get(role) in lead:
                    leads_by_scope[scope] += 1

        if "institution" in entry:
            errors.append(
                f"{where}: institution does not belong on a person. The two "
                f"lists are independent -- one person may sit at several "
                f"institutions and one institution sends several people -- so "
                f"list them under cruise_info.institutions instead."
            )

        email = entry.get("email")
        if email and not _EMAIL_RE.match(str(email)):
            errors.append(f"{where}: email {email!r} is not a valid address")

        orcid = entry.get("orcid")
        if orcid is None:
            warnings.append(
                f"{where} ({name}): no ORCID — confirm with the person before publishing"
            )
        elif not _ORCID_RE.match(str(orcid).strip()):
            errors.append(
                f"{where}: orcid {orcid!r} is not of the form "
                "0000-0000-0000-000X or https://orcid.org/0000-0000-0000-000X"
            )

    if contributors and n_pi == 0:
        warnings.append(
            "no contributor holds a lead role (C89 PS / DI / PI / DP) — nobody "
            "is recorded as responsible for the science or the data"
        )
    elif contributors:
        bare = sorted(s for s, n in leads_by_scope.items() if n == 0)
        if bare:
            warnings.append(
                f"no contributor holds a lead role in the {', '.join(bare)} "
                f"file(s): a lead scoped to one product does not vouch for the "
                f"other. Add a lead role under roles: {{all: [...]}} or under "
                f"each product that needs one."
            )

    try:
        inst_vocab_name, inst_vocab = institution_role_vocabulary(cruise_info)
    except KeyError:
        errors.append(
            f"cruise_info.institution_role_vocabulary "
            f"{cruise_info.get('institution_role_vocabulary')!r} is unknown. "
            f"Choose one of {sorted(INSTITUTION_ROLE_VOCABULARIES)}."
        )
        inst_vocab_name, inst_vocab = (
            DEFAULT_INSTITUTION_ROLE_VOCABULARY,
            (INSTITUTION_ROLE_VOCABULARIES[DEFAULT_INSTITUTION_ROLE_VOCABULARY]),
        )
    inst_lookup = _role_lookup(inst_vocab)

    institutions = cruise_info.get("institutions")
    if institutions is None:
        warnings.append(
            "cruise_info.institutions is absent — no contributing institutions "
            "will be recorded"
        )
    elif not isinstance(institutions, list):
        errors.append("cruise_info.institutions must be a list")
    else:
        for i, item in enumerate(institutions, start=1):
            resolved = resolve_institution(item, registry)
            if resolved is None:
                slug = item if isinstance(item, str) else item.get("slug")
                errors.append(
                    f"cruise_info.institutions[{i}]: {slug!r} is not in any "
                    f"institution registry. Known: {sorted(registry)}. Define it "
                    f"inline with `name:` and `id:`, add it to "
                    f"~/.config/ctdcast/institutions.yaml, or point "
                    f"`institutions_file:` at your own registry."
                )
                continue
            if not resolved["name"]:
                errors.append(f"cruise_info.institutions[{i}]: name is required")
            if resolved["role"] not in inst_lookup:
                errors.append(
                    f"cruise_info.institutions[{i}]: role {resolved['role']!r} is "
                    f"not a {inst_vocab_name} ({inst_vocab['title']}) term. "
                    f"Codes: {sorted(inst_vocab['terms'])}"
                )
            for field in ("name", "id", "role"):
                if any(c in resolved[field] for c in FORBIDDEN_IN_VALUE if c == ";"):
                    errors.append(
                        f"cruise_info.institutions[{i}].{field} contains ';': "
                        f"{resolved[field]!r}"
                    )
            continue
        slugs_only = [x for x in institutions if isinstance(x, str)]
        if len(set(slugs_only)) != len(slugs_only):
            warnings.append("cruise_info.institutions contains repeated slugs")

    creator = cruise_info.get("creator")
    if creator is None:
        warnings.append(
            "cruise_info.creator is absent — ACDD creator_* describes whoever "
            "produced the file, which is a different role from PI"
        )
    elif not isinstance(creator, dict):
        errors.append("cruise_info.creator must be a mapping")
    else:
        if not (creator.get("name") or "").strip():
            errors.append("cruise_info.creator.name is required when creator is given")
        ctype = creator.get("type")
        if ctype is not None and ctype not in CREATOR_TYPES:
            errors.append(
                f"cruise_info.creator.type {ctype!r} is not an ACDD creator_type. "
                f"Valid: {list(CREATOR_TYPES)}"
            )
        if creator.get("institution") is not None:
            warnings.append(
                "cruise_info.creator.institution is no longer written to the "
                "file: institutions come from cruise_info.institutions (with "
                "roles) so there is one structured source, and the creator is "
                "identified by their ORCID. Remove the key, and list the "
                "institution under institutions: if it is not there already."
            )

    # CF `institution` is derived from the lead entries of `institutions:`, so
    # there is nothing to validate but that something carries the lead role.
    if cruise_info.get("institution") is not None:
        errors.append(
            "cruise_info.institution is not a config key: the CF `institution` "
            "attribute is derived from the lead entries of "
            "cruise_info.institutions. Give the responsible organisation(s) the "
            "lead role there instead."
        )
    elif (
        cruise_info.get("institutions")
        and _cf_institution(cruise_info, registry) is None
    ):
        warnings.append(
            "no institution holds the lead role, so the CF `institution` "
            "attribute (where the original data was produced) will be omitted."
        )

    return errors, warnings


def _cf_institution(
    cruise_info: dict[str, Any], registry: dict[str, dict[str, Any]]
) -> str | None:
    """Render the CF ``institution`` attribute from ``contributing_institutions``.

    ``institution`` is a **CF** attribute -- "Specifies where the original data
    was produced", paired with ``source`` ("the method of production of the
    original data").  Both describe the *measurement*, so it belongs with the
    origination of the data, not with ``creator_*`` (who produced this file).

    Two things follow, and they are why this is derived rather than configured.

    First, CF presumes the data has *one* producing institution.  For a research
    cruise that presumption is simply false: several institutions are aboard and
    contributing, and only the authorship of one particular *file* resolves to a
    single organisation -- and that organisation is not recorded as an attribute
    at all, because the creator's ORCID (``creator_id``) already resolves to it.
    So this never reduces to one name.

    Second, ``institutions:`` with per-entry roles is this package's structured
    answer to "which organisations, doing what".  A second free-text attribute
    asserting the same fact independently could drift from it, and a reader would
    have no way to know which to believe.  This is therefore a lossy *projection*
    of that list, kept for CF-only consumers (ERDDAP, THREDDS catalogues, NCEI
    harvesters) that will never read ``contributing_institutions``.  The list
    remains the single source of truth; if the two ever disagree, that is a bug
    here, not a decision recorded in config.

    The projection is the lead-role entries, joined -- leads because ACDD glosses
    the same field as "principally responsible", joined because naming one of
    three co-leads would be false where naming three is merely coarse.  CF gives
    the field no syntax, so the join is cosmetic; nothing parses it.

    Parameters
    ----------
    cruise_info : dict
        The ``cruise_info:`` mapping from the cruise config.
    registry : dict
        The loaded institution registry, keyed by slug.

    Returns
    -------
    str or None
        The joined institution name(s), or ``None`` when no entry holds the lead
        role -- in which case the attribute is omitted rather than guessed.
    """
    _, inst_vocab = institution_role_vocabulary(cruise_info)
    lead_code = _INSTITUTION_LEAD_ROLES.get(str(inst_vocab["uri"]))
    if lead_code is None:
        return None
    lead_label = inst_vocab["terms"].get(lead_code)
    leads = [
        r["name"]
        for r in (
            resolve_institution(item, registry)
            for item in (cruise_info.get("institutions") or [])
        )
        if r and r["name"] and r["role"] in (lead_code, lead_label)
    ]
    return SEPARATOR.join(leads) if leads else None


def contributor_attrs(
    cruise_info: dict[str, Any], source: str | None = None
) -> dict[str, str]:
    """Build the netCDF global attributes describing people and institutions.

    Generates the parallel strings from one structured list, so they cannot fall
    out of alignment.  An attribute whose every entry would be empty is **omitted
    entirely** rather than written as ``"; ; ; "`` — an empty delimited string
    asserts four empty values, whereas an absent attribute asserts nothing was
    recorded.

    ``contributing_institutions`` comes from ``cruise_info.institutions``, a
    list independent of the people: one person may sit at several institutions
    and one institution may send several people, so the two must never be
    zipped together.

    Parameters
    ----------
    cruise_info : dict
        The ``cruise_info:`` mapping from the cruise config.

    Returns
    -------
    dict of str to str
        Global attributes, ready to merge into the dataset.
    """
    registry = load_institutions(cruise_info.get("institutions_file"))
    _, vocab = role_vocabulary(cruise_info)
    _, inst_vocab = institution_role_vocabulary(cruise_info)
    lookup = _role_lookup(vocab)
    attrs: dict[str, str] = {}

    creator = cruise_info.get("creator") or {}
    if creator.get("name"):
        attrs["creator_name"] = str(creator["name"])
        if creator.get("type"):
            attrs["creator_type"] = str(creator["type"])
        if creator.get("email"):
            attrs["creator_email"] = str(creator["email"])
        if creator.get("orcid"):
            attrs["creator_id"] = orcid_uri(str(creator["orcid"]))
        # No `creator_institution` / `creator_institution_id`.  Every institution
        # in the file now comes from one structured place -- `institutions:` with
        # roles, projected to CF `institution` -- and a third, unstructured claim
        # attached to a person could only drift from it.  The creator is already
        # identified by `creator_id` (their ORCID), which resolves to a current
        # affiliation maintained by them, whereas a name frozen into the file at
        # write time goes stale and is never corrected.  ACDD marks
        # `creator_institution` Suggested, the weakest tier it has.

    # A view of `contributing_institutions`, never an independent claim -- hence
    # no `institution_id`: the identifiers live in `contributing_institutions_id`,
    # aligned with the roles that justify them.
    cf_institution = _cf_institution(cruise_info, registry)
    if cf_institution:
        attrs["institution"] = cf_institution

    contributors = cruise_info.get("contributors") or []
    if not contributors:
        return attrs

    # One slot per (person, role): the parallel strings are positional, so a
    # person holding two roles occupies two slots with their name and identifiers
    # repeated.  Stating them once in config and expanding here means the repeats
    # cannot disagree.  A person with no role in this scope is omitted from this
    # file entirely.
    names, roles, emails, ids = [], [], [], []
    for entry in contributors:
        for role in entry_roles(entry, source):
            label = lookup.get(str(role))
            if label is None:
                # Never emit a blank role slot: the strings are positional, so a
                # "" would attribute the person a role of nothing while every
                # other slot lines up, which reads as deliberate.  Raising is
                # what `orcid_uri` already does for a malformed identifier, and
                # `cruise_global_attrs` catches both, warns, and omits the people
                # rather than writing a half-true attribution.
                raise ValueError(
                    f"contributor {entry.get('name')!r}: role {role!r} is not a "
                    f"term of the declared vocabulary; run `ctdcast validate` "
                    f"for the accepted codes."
                )
            names.append(str(entry.get("name") or ""))
            roles.append(label)
            emails.append(str(entry.get("email") or ""))
            orcid = entry.get("orcid")
            ids.append(orcid_uri(str(orcid)) if orcid else "")

    if not names:
        return attrs

    attrs["contributor_name"] = SEPARATOR.join(names)
    attrs["contributor_role"] = SEPARATOR.join(roles)
    attrs["contributor_role_vocabulary"] = str(vocab["uri"])
    if any(emails):
        attrs["contributor_email"] = SEPARATOR.join(emails)
    if any(ids):
        attrs["contributor_id"] = SEPARATOR.join(ids)

    # Institutions are their own list, in their own order, with no positional
    # relationship to the contributors: one person may belong to several
    # institutions and one institution may send several people, so zipping the
    # two would assert a correspondence that does not exist.  The two
    # ``contributing_institutions*`` attributes are aligned with each other and
    # with nothing else.
    resolved = [
        r
        for r in (
            resolve_institution(item, registry)
            for item in (cruise_info.get("institutions") or [])
        )
        if r and r["name"]
    ]
    if resolved:
        inst_lookup = _role_lookup(inst_vocab)
        attrs["contributing_institutions"] = SEPARATOR.join(r["name"] for r in resolved)
        attrs["contributing_institutions_role"] = SEPARATOR.join(
            inst_lookup.get(r["role"], "") for r in resolved
        )
        attrs["contributing_institutions_role_vocabulary"] = str(inst_vocab["uri"])
        # `_id`, not OG1's `contributing_institutions_vocabulary`.  The content is
        # per-institution EDMO/ROR *record* URIs -- identifiers -- and OG1 itself
        # documents the field that way ("url to the repository of the id").  Its
        # name is a misnomer we are not obliged to inherit: ctdcast declares
        # CF + ACDD, not OG1, and ACDD defines no institution-id attribute at all,
        # so the name is ours to choose.  Choosing `_id` makes one rule hold
        # across every attribute here: `*_id` is an identifier for the thing named
        # by the attribute it suffixes (creator_id, contributor_id,
        # contributing_institutions_id), and `*_vocabulary` is the scheme URI the
        # neighbouring codes are drawn from (contributor_role_vocabulary,
        # contributing_institutions_role_vocabulary).
        ids = [r["id"] for r in resolved]
        if any(ids):
            attrs["contributing_institutions_id"] = SEPARATOR.join(ids)

    return attrs
