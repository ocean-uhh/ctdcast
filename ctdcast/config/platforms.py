"""Research-vessel registry: config slug → identity, ICES code, and EXPOCODE.

A cruise's EXPOCODE is derived, not allocated::

    EXPOCODE = <4-character ICES ship code> + <departure date YYYYMMDD>

where the departure date is the day the ship left port (``cruise_info.start_date``),
which is **not** necessarily the first cast.  The only piece that must be looked up
is the ICES ship code, and looking it up by vessel *name* is unsafe: names carry
accents, punctuation, and generational ambiguity (four hulls have been called
*Meteor*; two live C17 entries are called *Odon de Buen*).  A wrong code yields a
well-formed EXPOCODE filed against somebody else's cruise — a silent, permanent
error.

So the registry is keyed on a short ASCII **slug** (``odb``, ``msm``, ``meteor3``),
and this module refuses to guess:

* an unknown slug raises;
* a slug listed in ``ambiguous_slugs`` (e.g. bare ``meteor``) raises with the
  message naming the alternatives;
* a slug whose ``ices_code`` is ``null`` (a vessel with no code yet) raises rather
  than emitting a malformed EXPOCODE;
* a derived code appearing in ``forbidden_codes`` raises — each is a real trap
  (deprecated codes, same-name different-ship) that a name lookup would fall into.

Source registry: :data:`ctdcast.config.platforms` ``platforms.yaml``.
"""

from __future__ import annotations

import datetime as _dt
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_PLATFORMS_YAML = Path(__file__).parent / "platforms.yaml"


class PlatformError(ValueError):
    """A platform slug could not be resolved, or its ICES code is unusable.

    Raised rather than returning a sentinel because every caller of this module
    is about to write an EXPOCODE into a file, and a wrong or missing code there
    is worse than a hard failure at build time.
    """


@lru_cache(maxsize=1)
def _load_raw() -> dict[str, Any]:
    """Return the parsed ``platforms.yaml`` (empty mapping when absent)."""
    if not _PLATFORMS_YAML.exists():
        return {}
    with open(_PLATFORMS_YAML, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_platforms() -> dict[str, dict[str, Any]]:
    """Return the platform registry keyed by slug.

    Returns an empty mapping when the registry file is absent, so a config that
    supplies no ``ship_slug`` still works (EXPOCODE is simply not derived).
    """
    return _load_raw().get("platforms") or {}


def _ambiguous_slugs() -> dict[str, str]:
    """Return the ``ambiguous_slugs`` mapping (slug → explanatory message)."""
    return _load_raw().get("ambiguous_slugs") or {}


def _forbidden_codes() -> dict[str, str]:
    """Return the ``forbidden_codes`` mapping (ICES code → reason)."""
    return _load_raw().get("forbidden_codes") or {}


def resolve_platform(slug: str) -> dict[str, Any]:
    """Return the registry record for *slug*.

    Parameters
    ----------
    slug : str
        The ``cruise_info.ship_slug`` value — a key in ``platforms.yaml``.

    Returns
    -------
    dict
        The platform's fields (``name``, ``ices_code``, ``platform``, …).

    Raises
    ------
    PlatformError
        If *slug* is listed in ``ambiguous_slugs`` (quoting its message) or is
        not a key in the registry.
    """
    key = str(slug).strip()
    ambiguous = _ambiguous_slugs()
    if key in ambiguous:
        raise PlatformError(str(ambiguous[key]).strip())
    registry = load_platforms()
    if key not in registry:
        raise PlatformError(
            f"unknown platform slug {key!r}; known slugs: {sorted(registry)}"
        )
    return registry[key]


def parse_config_date(value: Any) -> _dt.date | None:
    """Coerce a config date value to a :class:`datetime.date`, or ``None``.

    Accepts a ``date``/``datetime`` (YAML parses a bare ``2026-03-27`` as a
    ``date``), an ISO ``"YYYY-MM-DD"`` string, or a compact ``"YYYYMMDD"`` string.
    Returns ``None`` for ``None`` or any value it cannot parse, leaving the
    caller to decide whether that is an error.  Shared by the EXPOCODE derivation
    and the embargo-date logic so both accept exactly the same date forms.
    """
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return _dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _departure_yyyymmdd(start_date: str | _dt.date) -> str:
    """Normalise a departure date to a ``YYYYMMDD`` string.

    Raises
    ------
    PlatformError
        If the value cannot be parsed as a calendar date.
    """
    parsed = parse_config_date(start_date)
    if parsed is None:
        raise PlatformError(
            f"cannot parse departure date {start_date!r}; expected YYYY-MM-DD"
        )
    return parsed.strftime("%Y%m%d")


def resolve_platform_spec(platform: str | dict[str, Any]) -> dict[str, Any]:
    """Resolve a config platform value (a registry slug **or** an inline dict).

    A **string** is a slug looked up in ``platforms.yaml``.  A **mapping** is used
    inline — for a vessel not (yet) in the shared registry — and should carry at
    least ``ices_code`` (for the EXPOCODE) and ``name``, plus optional ``platform``
    (L06 category) and ``platform_vocabulary``.  This mirrors the inline
    institution form, so a user can name a new vessel in their own config without
    first editing ``platforms.yaml``.

    Parameters
    ----------
    platform : str or dict
        A ``platforms.yaml`` slug, or an inline platform record.

    Returns
    -------
    dict
        The platform record (registry entry, or the inline mapping as given).
    """
    if isinstance(platform, dict):
        return dict(platform)
    return resolve_platform(str(platform))


def derive_expocode(platform: str | dict[str, Any], start_date: str | _dt.date) -> str:
    """Derive the CCHDO/GO-SHIP EXPOCODE for a cruise.

    ``EXPOCODE = <ICES ship code> + <departure date YYYYMMDD>``.

    Parameters
    ----------
    platform : str or dict
        A ``platforms.yaml`` slug, or an inline platform record carrying at least
        ``ices_code`` (see :func:`resolve_platform_spec`).
    start_date : str or datetime.date
        The departure date from port (``cruise_info.start_date``).  **Not** the
        first cast; the two can differ (MSM142 departs 2026-03-27, first cast
        2026-03-29).

    Returns
    -------
    str
        e.g. ``"29OD20260709"`` for ``odb`` departing 2026-07-09.

    Raises
    ------
    PlatformError
        If a slug is unknown/ambiguous, the platform has no ICES code, the
        derived code is in ``forbidden_codes``, or *start_date* is unparseable.
    """
    record = resolve_platform_spec(platform)
    label = (
        platform if isinstance(platform, str) else (record.get("name") or "<inline>")
    )
    ices_code = record.get("ices_code")
    if not ices_code:
        raise PlatformError(
            f"platform {label!r} has no ices_code, so no EXPOCODE can be derived; "
            f"look up the ICES ship code at https://ocean.ices.dk/codes/ShipCodes.aspx "
            f"(or the NVS mirror https://vocab.nerc.ac.uk/collection/C17/current/), "
            f"or request a new one from ICES before publishing"
        )
    ices_code = str(ices_code).strip()

    forbidden = _forbidden_codes()
    if ices_code in forbidden:
        raise PlatformError(
            f"ICES code {ices_code!r} (from platform {label!r}) is in "
            f"forbidden_codes: {str(forbidden[ices_code]).strip()}"
        )

    return f"{ices_code}{_departure_yyyymmdd(start_date)}"


def expocode_from_cruise_info(cruise_info: dict[str, Any]) -> str | None:
    """Derive the EXPOCODE from a cruise config, or ``None`` when not derivable.

    Returns ``None`` (rather than raising) when the config supplies no
    ``ship_slug`` or no ``start_date`` — a cruise mid-processing may not have
    settled its departure date, and that is not an error.  A *present* slug that
    is ambiguous, unknown, or lacks an ICES code still raises via
    :func:`derive_expocode`, because those are authoring mistakes.

    Parameters
    ----------
    cruise_info : dict
        The ``cruise_info:`` mapping from the cruise config.

    Returns
    -------
    str or None
        The EXPOCODE, or ``None`` when the slug/``start_date`` is absent.

    Notes
    -----
    The slug is read from ``cruise_info["platform"]``, falling back to
    ``cruise_info["ship_slug"]``.  ``ship`` (the free-text display name) is never
    used as a slug — name lookup is exactly the ambiguity this registry avoids.
    """
    platform = cruise_info.get("platform") or cruise_info.get("ship_slug")
    start_date = cruise_info.get("start_date")
    if not platform or not start_date:
        return None
    return derive_expocode(platform, start_date)


def platform_attrs(platform: str | dict[str, Any]) -> dict[str, str]:
    """Return ACDD platform global attributes for a slug or inline platform.

    Emits ``platform``, ``platform_vocabulary``, ``platform_name`` and
    ``platform_ices_code`` from the resolved record, skipping any it omits.
    Returns an empty mapping when a slug does not resolve to a usable record
    (the caller decides whether that is fatal).

    Parameters
    ----------
    platform : str or dict
        A ``platforms.yaml`` slug, or an inline platform record
        (see :func:`resolve_platform_spec`).

    Returns
    -------
    dict of str to str
        Platform attributes ready to merge into a dataset.
    """
    try:
        record = resolve_platform_spec(platform)
    except PlatformError:
        return {}
    attrs: dict[str, str] = {}
    if record.get("platform"):
        attrs["platform"] = str(record["platform"])
    if record.get("platform_vocabulary"):
        attrs["platform_vocabulary"] = str(record["platform_vocabulary"])
    if record.get("name"):
        attrs["platform_name"] = str(record.get("native_name") or record["name"])
    if record.get("ices_code"):
        attrs["platform_ices_code"] = str(record["ices_code"])
    return attrs


def platform_display_name(platform: str | dict[str, Any]) -> str | None:
    """Return the registry display name for a slug or inline platform, or ``None``.

    Uses the plain ``name`` (not ``native_name``), for the report masthead and for
    defaulting the free-text ``ship`` in ``ctdcast init`` from the chosen slug —
    deriving the name from the ICES code (unambiguous) rather than resolving a
    typed name into a code (ambiguous).  Returns ``None`` when a slug does not
    resolve.
    """
    try:
        record = resolve_platform_spec(platform)
    except PlatformError:
        return None
    name = record.get("name")
    return str(name) if name else None
