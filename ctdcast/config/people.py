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

Roles come from NERC W08 (SensorML Contact Section Terms), the vocabulary OG1
names in ``contributor_role_vocabulary``.
"""

from __future__ import annotations

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

#: NERC W08 — the vocabulary OG1 names for contributor roles.
ROLE_VOCABULARY = "https://vocab.nerc.ac.uk/collection/W08/current/"

#: W08 prefLabel → concept id.  The complete collection; there is no
#: "data manager" term, ``Data scientist`` (CONT0006) being the nearest.
W08_ROLES: dict[str, str] = {
    "Manufacturer": "CONT0001",
    "Owner": "CONT0002",
    "Operator": "CONT0003",
    "PI": "CONT0004",
    "Technical Coordinator": "CONT0005",
    "Data scientist": "CONT0006",
    "Service Provider": "CONT0007",
}

#: ACDD 1.3 ``creator_type`` values.
CREATOR_TYPES = ("person", "group", "institution", "position")

#: An ORCID, bare or as a resolvable URL.  Both forms are accepted and
#: normalised to the URL on write, since AMOCatlas's registry stores ``id_url``
#: and people paste whichever form their browser shows.
_ORCID_RE = re.compile(
    r"^(?:https?://(?:www\.)?orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_INSTITUTIONS_YAML = Path(__file__).parent / "institutions.yaml"


@dataclass(frozen=True)
class Person:
    """One contributor, as resolved from config."""

    name: str
    role: str
    institution: str | None = None
    email: str | None = None
    orcid: str | None = None


@lru_cache(maxsize=1)
def load_institutions() -> dict[str, dict[str, Any]]:
    """Return the institution registry keyed by slug.

    Returns an empty mapping when the registry file is absent, so a config that
    names no institutions still works.
    """
    if not _INSTITUTIONS_YAML.exists():
        return {}
    with open(_INSTITUTIONS_YAML, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("institutions") or {}


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

    registry = load_institutions()
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

    seen_names: set[str] = set()
    n_pi = 0

    for i, entry in enumerate(contributors, start=1):
        where = f"cruise_info.contributors[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{where} must be a mapping, not {type(entry).__name__}")
            continue

        name = (entry.get("name") or "").strip()
        if not name:
            errors.append(f"{where}: name is required")
        else:
            if name in seen_names:
                warnings.append(f"{where}: duplicate name {name!r}")
            seen_names.add(name)

        # The delimiter check — the whole reason this function exists.
        for key in ("name", "role", "email"):
            value = entry.get(key)
            if isinstance(value, str):
                bad = [c for c in FORBIDDEN_IN_VALUE if c in value]
                if bad:
                    errors.append(
                        f"{where}.{key} contains {bad!r}: {value!r}. Entries are "
                        f"written as delimited strings, so a value containing "
                        f"a delimiter splits into two people."
                    )

        role = entry.get("role")
        if not role:
            errors.append(f"{where}: role is required (one of {sorted(W08_ROLES)})")
        elif role not in W08_ROLES:
            errors.append(
                f"{where}: role {role!r} is not a NERC W08 term. "
                f"Valid: {sorted(W08_ROLES)}"
            )
        elif role == "PI":
            n_pi += 1

        inst = entry.get("institution")
        if inst is None:
            warnings.append(f"{where} ({name}): no institution")
        elif inst not in registry:
            errors.append(
                f"{where}: institution {inst!r} is not in institutions.yaml. "
                f"Known: {sorted(registry)}"
            )
        else:
            # Institution names are checked for ";" only, never ",".  EDMO's
            # official names contain commas by necessity — "University of
            # Hamburg, Institute of Oceanography" — which is itself the proof
            # that comma cannot be the delimiter for this list.
            inst_name = str(registry[inst].get("name") or "")
            if ";" in inst_name:
                errors.append(
                    f"institutions.yaml[{inst}].name contains ';': {inst_name!r}"
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
            "no contributor has role 'PI' — OG1 makes contributor_name/role "
            "mandatory for the PI"
        )

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
        cinst = creator.get("institution")
        if cinst is not None and cinst not in registry:
            errors.append(
                f"cruise_info.creator.institution {cinst!r} is not in institutions.yaml"
            )

    return errors, warnings


def contributor_attrs(cruise_info: dict[str, Any]) -> dict[str, str]:
    """Build the netCDF global attributes describing people and institutions.

    Generates the parallel strings from one structured list, so they cannot fall
    out of alignment.  An attribute whose every entry would be empty is **omitted
    entirely** rather than written as ``"; ; ; "`` — an empty delimited string
    asserts four empty values, whereas an absent attribute asserts nothing was
    recorded.

    ``contributing_institutions`` is deduplicated and therefore does **not**
    align positionally with ``contributor_name``; OG1 treats institutions as
    their own list.

    Parameters
    ----------
    cruise_info : dict
        The ``cruise_info:`` mapping from the cruise config.

    Returns
    -------
    dict of str to str
        Global attributes, ready to merge into the dataset.
    """
    registry = load_institutions()
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
        inst = registry.get(creator.get("institution") or "")
        if inst:
            attrs["creator_institution"] = str(inst["name"])
            attrs["institution"] = str(inst["name"])

    contributors = cruise_info.get("contributors") or []
    if not contributors:
        return attrs

    names, roles, emails, ids = [], [], [], []
    for entry in contributors:
        names.append(str(entry.get("name") or ""))
        roles.append(str(entry.get("role") or ""))
        emails.append(str(entry.get("email") or ""))
        orcid = entry.get("orcid")
        ids.append(orcid_uri(str(orcid)) if orcid else "")

    attrs["contributor_name"] = SEPARATOR.join(names)
    attrs["contributor_role"] = SEPARATOR.join(roles)
    attrs["contributor_role_vocabulary"] = ROLE_VOCABULARY
    if any(emails):
        attrs["contributor_email"] = SEPARATOR.join(emails)
    if any(ids):
        attrs["contributor_id"] = SEPARATOR.join(ids)

    # Institutions: deduplicated, first-seen order, and NOT positionally aligned
    # with the contributor lists.
    slugs: list[str] = []
    for entry in contributors:
        slug = entry.get("institution")
        if slug and slug in registry and slug not in slugs:
            slugs.append(slug)
    if slugs:
        attrs["contributing_institutions"] = SEPARATOR.join(
            str(registry[s]["name"]) for s in slugs
        )
        uris = [str(registry[s].get("edmo_uri") or "") for s in slugs]
        if any(uris):
            attrs["contributing_institutions_vocabulary"] = SEPARATOR.join(uris)
        attrs.setdefault("institution", str(registry[slugs[0]]["name"]))

    return attrs
