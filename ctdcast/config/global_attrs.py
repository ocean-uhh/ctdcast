"""Assemble a compiled file's global attributes from config + derived bounds.

Three layers, kept apart on purpose (see the file-level-metadata design note):

* **derived** — ``geospatial_*`` and ``time_coverage_*`` bounds, ``date_created``.
  Computed from the data at write time, **never** authored and **never** copied
  up from a per-cast file.  Copying the first cast's latitude up into the cruise
  file states a bounding box containing one station; the fix is to compute.
* **authored** — ``title``, ``project``, ``acknowledgement``, people, embargo.
  Taken from ``cruise_info:`` in the cruise config, once, at the level it is true.
* **entity** — ``platform_*`` and the ``expocode`` (the latter is emitted by the
  caller as an ``N_PROF`` coordinate, not a global — CCHDO does not assume one
  file is one cruise).

The one rule that decides where a fact goes: **a global attribute must be true of
the entire file.**  Anything that varies within the file (cast lat/lon, station
name, sensor serial) is a variable, not an attribute.

Conformance target is ACDD-1.3 (with CF).  We take OG1's *vocabularies* (C89
roles, EDMO institutions, L06 platform, L08 access policy) without adopting OG1's
glider-mission entity model.
"""

from __future__ import annotations

import datetime as _dt
import warnings
from typing import Any

import numpy as np
from ctdcast._version import __version__ as _CTDCAST_VERSION
from ctdcast.config.parameters import VARIABLES
from ctdcast.config.platforms import (
    PlatformError,
    expocode_from_cruise_info,
    parse_config_date,
    platform_attrs,
)

from ctdcast.config.people import check_contributors, contributor_attrs

#: Canonical coordinate units, taken from the single source of truth in
#: :data:`ctdcast.config.parameters.VARIABLES` so the bound units always match
#: the units written on the ``latitude``/``longitude`` variables themselves.
_LAT_UNITS = VARIABLES["latitude"]["units"]
_LON_UNITS = VARIABLES["longitude"]["units"]

#: CC BY 4.0 canonical URL, named as the licence that applies *on release*.
_CC_BY_4_URL = "https://creativecommons.org/licenses/by/4.0/"

#: Software provenance written into the ``history`` attribute.  URL, not a DOI —
#: ctdcast has no minted DOI yet; swap in the DOI here if/when one exists.
_CTDCAST_URL = "https://github.com/ocean-uhh/ctdcast"

#: Canonical grouping + order of the compiled-file global attributes.  Single
#: source of truth for both the on-disk write order (:func:`order_attrs`) and the
#: inventory page's grouped tables (:func:`group_attrs`).  The order within each
#: group is the canonical order; the group titles are the HTML section headings.
ATTR_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Identity & discovery",
        (
            # Order per Eleanor's spec (2026-08-22); platform folded in here.
            "title",
            "cruise",
            "platform",
            "platform_name",
            "platform_ices_code",
            "platform_vocabulary",
            "expocode",
            "id",
            "naming_authority",
            "project",
            "internal_mission_identifier",
            # emitted but unlisted / future-proof — trail the spec'd order:
            "summary",
            "program",
            "references",
        ),
    ),
    (
        "Spatiotemporal coverage",
        (
            "geospatial_lat_min",
            "geospatial_lat_max",
            "geospatial_lat_units",
            "geospatial_lon_min",
            "geospatial_lon_max",
            "geospatial_lon_units",
            "geospatial_vertical_min",
            "geospatial_vertical_max",
            "geospatial_vertical_units",
            "geospatial_vertical_positive",
            "time_coverage_start",
            "time_coverage_end",
            "time_coverage_duration",
            "time_coverage_resolution",
        ),
    ),
    (
        "People & institutions",
        (
            # The cruise contributors (the science) and the contributing
            # institutions.  The file's *creator* (who produced the file) lives in
            # Provenance & processing, not here.
            "contributor_name",
            "contributor_role",
            "contributor_role_vocabulary",
            "contributor_id",
            "contributor_email",
            "contributing_institutions",
            # `_id` (identifiers), NOT OG1's `contributing_institutions_vocabulary`
            # -- see the note at the emit site in people.py.  Naming rule for this
            # whole block: `*_id` identifies the thing the attribute names,
            # `*_vocabulary` is the scheme URI the neighbouring codes come from.
            "contributing_institutions_id",
            "contributing_institutions_role",
            "contributing_institutions_role_vocabulary",
            # CF `institution` is a lossy projection of the three attributes
            # above (their lead-role entries, joined), so it groups with them.
            # It is the ONLY institution attribute in the file: the creator is a
            # person identified by ORCID, with no institution of their own.  See
            # people._cf_institution.
            "institution",
            "publisher_name",
            "publisher_email",
            "publisher_url",
        ),
    ),
    (
        "Rights & access",
        (
            # Order per Eleanor's spec (2026-08-22): acknowledgement first.
            "acknowledgement",
            "license",
            "access_constraint",
            "date_available",
            "license_after_embargo",
            "citation",
            "doi",
        ),
    ),
    (
        "Provenance & processing",
        (
            "date_created",
            "date_modified",
            "history",
            # The file's creator (who produced it) — distinct from the cruise
            # contributors above.  The creator is a person, identified by
            # `creator_id` (ORCID); no institution is attached to them, so that
            # every institution in the file comes from `institutions:` and its
            # CF projection.  `source` sits here as the how of the original
            # measurement, paired with the `institution` that says where.
            "creator_name",
            "creator_type",
            "creator_id",
            "source",
            "processing_level",
            "data_mode",
            "data_mode_meaning",
            "Conventions",
            "featureType",
            "cdm_data_type",
            "pressure_units",
            "pressure_spacing_dbar",
            "pressure_binning",
            "cchdo_software_version",
            "cchdo_parameters_version",
        ),
    ),
)

#: Title for attributes not named in :data:`ATTR_GROUPS` (never dropped).
OTHER_GROUP = "Other"


def canonical_attr_order() -> list[str]:
    """Return the flat canonical order of all named global attributes."""
    return [name for _title, names in ATTR_GROUPS for name in names]


def order_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Return *attrs* in canonical order.

    Named attributes come first in :func:`canonical_attr_order`; any remaining
    ones keep their original relative order and follow (so nothing is dropped and
    an unrecognised attribute stays visible rather than being silently reordered
    away).
    """
    rank = {name: i for i, name in enumerate(canonical_attr_order())}
    known = [k for k in canonical_attr_order() if k in attrs]
    extra = [k for k in attrs if k not in rank]
    return {k: attrs[k] for k in (*known, *extra)}


def group_attrs(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    """Split *attrs* into the canonical groups for display.

    Groups appear in :data:`ATTR_GROUPS` order; within each group the attributes
    keep the order they appear in *attrs* (i.e. the file order), so the rendered
    page can be checked visually against the canonical spec.  Unnamed attributes
    fall into a trailing :data:`OTHER_GROUP`.  Empty groups are omitted.

    Returns
    -------
    list of dict
        ``[{"title": str, "rows": [(key, value), ...]}, ...]``.  The key is
        ``rows`` (not ``items``) so a Jinja template's ``group.rows`` does not
        collide with the dict ``.items()`` method.
    """
    group_of: dict[str, str] = {
        name: title for title, names in ATTR_GROUPS for name in names
    }
    buckets: dict[str, list[tuple[str, Any]]] = {title: [] for title, _ in ATTR_GROUPS}
    buckets[OTHER_GROUP] = []
    for key, value in attrs.items():
        buckets[group_of.get(key, OTHER_GROUP)].append((key, value))
    ordered_titles = [title for title, _ in ATTR_GROUPS] + [OTHER_GROUP]
    return [
        {"title": title, "rows": buckets[title]}
        for title in ordered_titles
        if buckets[title]
    ]


def _finite(values: Any) -> np.ndarray:
    """Return the finite (non-NaN, non-inf) subset of *values* as a 1-D array."""
    arr = np.asarray(values, dtype="float64").ravel()
    return arr[np.isfinite(arr)]


def coverage_attrs(
    *,
    lats: Any,
    lons: Any,
    vertical_min: float | None = None,
    vertical_max: float | None = None,
    vertical_units: str = "dbar",
    times: Any = None,
) -> dict[str, str]:
    """Return the derived ACDD coverage attributes.

    Every value here is computed from the data, so a multi-station file states a
    bounding box that brackets *all* its stations — the property the accompanying
    test asserts.

    Parameters
    ----------
    lats, lons : array-like
        Per-profile latitudes/longitudes (NaNs ignored).
    vertical_min, vertical_max : float, optional
        Shallowest and deepest levels, in *vertical_units*.  Omitted when None.
    vertical_units : str
        Units of the vertical bounds.  ``"dbar"`` for a pressure grid (the honest
        label — the profiles are gridded on pressure, not converted to metres).
    times : array-like of datetime64, optional
        Per-profile times; drives ``time_coverage_start/end/duration``.

    Returns
    -------
    dict of str to str
        ACDD ``geospatial_*`` and ``time_coverage_*`` attributes.
    """
    attrs: dict[str, str] = {}

    flat_lat = _finite(lats)
    flat_lon = _finite(lons)
    if flat_lat.size:
        attrs["geospatial_lat_min"] = float(flat_lat.min())
        attrs["geospatial_lat_max"] = float(flat_lat.max())
        attrs["geospatial_lat_units"] = _LAT_UNITS
    if flat_lon.size:
        attrs["geospatial_lon_min"] = float(flat_lon.min())
        attrs["geospatial_lon_max"] = float(flat_lon.max())
        attrs["geospatial_lon_units"] = _LON_UNITS

    # Guard on finiteness, not just None: an all-NaN pressure column reduces to
    # NaN, and writing geospatial_vertical_max=NaN is a silently invalid bound.
    if (
        vertical_min is not None
        and vertical_max is not None
        and np.isfinite(vertical_min)
        and np.isfinite(vertical_max)
    ):
        attrs["geospatial_vertical_min"] = float(vertical_min)
        attrs["geospatial_vertical_max"] = float(vertical_max)
        attrs["geospatial_vertical_units"] = vertical_units
        # Without this a min of 0 and max of 4000 is ambiguous between depth and
        # height; the profiles increase downward.
        attrs["geospatial_vertical_positive"] = "down"

    if times is not None:
        t = np.asarray(times).ravel()
        # Only a datetime64 array can carry NaT and be turned into a timestamp;
        # anything else (numeric epochs, object dtype) is not a wall-clock time we
        # can label safely, so it is skipped rather than mis-encoded.
        if t.dtype.kind == "M":
            t = t[~np.isnat(t)]
            if t.size:
                t0 = np.datetime64(t.min(), "s")
                t1 = np.datetime64(t.max(), "s")
                attrs["time_coverage_start"] = str(t0) + "Z"
                attrs["time_coverage_end"] = str(t1) + "Z"
                attrs["time_coverage_duration"] = _iso_duration(t1 - t0)

    return attrs


def _iso_duration(delta: np.timedelta64) -> str:
    """Format a timedelta64 as an ISO-8601 duration, never truncating to ``P0D``.

    Whole days become ``P<days>D``; any remainder adds a ``T<h>H<m>M<s>S`` time
    part, down to seconds — so a six-hour survey reads ``PT6H`` and a 45-second
    span reads ``PT45S`` rather than the ``P0D`` that a coarser division would
    emit for a real elapsed time.  Only a genuinely zero-length span is ``P0D``.
    """
    total_seconds = int(delta / np.timedelta64(1, "s"))
    total_seconds = max(total_seconds, 0)
    days, rem = divmod(total_seconds, 86_400)
    hours, rem = divmod(rem, 3_600)
    minutes, seconds = divmod(rem, 60)
    date_part = f"{days}D" if days else ""
    time_bits = (
        (f"{hours}H" if hours else "")
        + (f"{minutes}M" if minutes else "")
        + (f"{seconds}S" if seconds else "")
    )
    time_part = f"T{time_bits}" if time_bits else ""
    if not date_part and not time_part:
        # Genuinely zero-length span.
        return "P0D"
    return "P" + date_part + time_part


def _plus_two_years(date: _dt.date) -> _dt.date:
    """Return *date* two calendar years later, mapping 29 Feb → 28 Feb."""
    try:
        return date.replace(year=date.year + 2)
    except ValueError:  # 29 February in a leap year
        return date.replace(year=date.year + 2, day=28)


def license_attrs(cruise_info: dict[str, Any]) -> dict[str, str]:
    """Return the ``license`` (and embargo companions) for a cruise.

    An embargo is **not** a licence: a CC BY grant is irrevocable and takes effect
    the instant it is written, so an embargoed file must carry a self-describing
    *restriction* statement, not ``CC-BY-4.0``.  This function writes:

    * a **moratorium** free-text ``license`` citing NERC L08 and COAR when
      ``cruise_info.embargo`` is present.  The release date is
      ``embargo.until`` when set, otherwise ``end_date + 2 years``.  Machine
      readers also get ``date_available`` and ``access_constraint``;
    * a bare CC BY statement when ``cruise_info.license`` names it and there is
      no embargo;
    * nothing when neither is configured — an absent ``license`` asserts nothing,
      which is safer mid-cruise than a wrong claim.

    Parameters
    ----------
    cruise_info : dict
        The ``cruise_info:`` mapping.

    Returns
    -------
    dict of str to str
        ``license`` and, under embargo, ``date_available`` / ``access_constraint``.
    """
    embargo = cruise_info.get("embargo")
    if isinstance(embargo, dict):
        until = parse_config_date(embargo.get("until"))
        if until is None:
            end = parse_config_date(cruise_info.get("end_date"))
            until = _plus_two_years(end) if end is not None else None
        until_str = until.isoformat() if until else "a date to be set"

        policy = str(embargo.get("policy") or "SDN:L08::MO")
        policy_uri = str(
            embargo.get("policy_uri")
            or "http://vocab.nerc.ac.uk/collection/L08/current/MO/"
        )
        access_rights = str(
            embargo.get("access_rights") or "http://purl.org/coar/access_right/c_f1cf"
        )
        after = str(cruise_info.get("license_after_embargo") or "CC-BY-4.0")
        contact = embargo.get("contact")
        contact_clause = (
            f" Contact {contact} for access."
            if contact
            else " Contact the PI for access."
        )

        attrs: dict[str, str] = {
            "license": (
                f"Embargoed until {until_str} (moratorium, two years after the end "
                f"of the cruise). Access restriction policy: moratorium ({policy}, "
                f"{policy_uri}). Access rights: embargoed access ({access_rights}). "
                f"Not for redistribution before that date.{contact_clause} "
                f"On release these data will be made available under {after} "
                f"({_CC_BY_4_URL})."
            ),
            "access_constraint": policy,
        }
        if until:
            attrs["date_available"] = until.isoformat()
        return attrs

    lic = cruise_info.get("license")
    if lic:
        return {"license": str(lic)}
    return {}


def provenance_attrs(now: _dt.datetime | None = None) -> dict[str, str]:
    """Return ``date_created`` / ``date_modified``, a software ``history`` line,
    and CF/ACDD conformance tags.

    The ``history`` line records the software provenance — which ctdcast version
    produced the file, and where to find it — so the file is traceable to its
    generator (CF's audit-trail attribute).

    Parameters
    ----------
    now : datetime, optional
        Creation timestamp; defaults to the current UTC time.  Injectable so a
        test can assert an exact value.

    Returns
    -------
    dict of str to str
    """
    stamp = (now or _dt.datetime.now(_dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "date_created": stamp,
        "date_modified": stamp,
        "history": f"{stamp}: created by ctdcast v{_CTDCAST_VERSION} ({_CTDCAST_URL})",
        "Conventions": "CF-1.13, ACDD-1.3",
        "featureType": "profile",
        "cdm_data_type": "Profile",
    }


def cruise_global_attrs(
    cruise_info: dict[str, Any] | None,
    *,
    lats: Any = None,
    lons: Any = None,
    vertical_min: float | None = None,
    vertical_max: float | None = None,
    vertical_units: str = "dbar",
    times: Any = None,
    source: str | None = None,
    config: dict[str, Any] | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, str]:
    """Compose the full global-attribute set for a compiled cruise file.

    Merges, in order: authored discovery fields (``title``/``summary``/``project``/
    ``program``/``cruise_id``/``acknowledgement``), derived coverage bounds,
    provenance/conformance tags, licence/embargo, people (creator + contributors),
    and platform attributes.  The ``expocode`` is **not** here — the caller emits
    it as an ``N_PROF`` coordinate.

    Parameters
    ----------
    cruise_info : dict or None
        The ``cruise_info:`` mapping.  None or empty yields only derived +
        provenance attributes.
    lats, lons, vertical_min, vertical_max, vertical_units, times
        Passed to :func:`coverage_attrs`.
    source : str, optional
        Product key (``"ctd"``, ``"ladcp"``).  Passed to
        :func:`ctdcast.config.people.contributor_attrs`, which writes only the
        roles each contributor scoped to this product (their ``roles: {all, ctd,
        ladcp}`` mapping) plus their unscoped roles — so a product's own
        processing personnel are credited on that file alone.
    config : dict, optional
        The whole cruise config.  Only used to read ``processing.profiles_dbar``
        for the grid token in :func:`dataset_identity`; without it a CTD file is
        identified at the 1 dbar default.
    now : datetime, optional
        Creation timestamp (injectable for tests).

    Returns
    -------
    dict of str to str
        Ready to merge into the dataset's ``attrs``.
    """
    ci = cruise_info or {}
    attrs: dict[str, str] = {}

    # Authored discovery fields, each written only when present.
    for key in ("title", "summary", "project", "program"):
        if ci.get(key):
            attrs[key] = str(ci[key])

    # `cruise` is the attribute; `cruise_id` is only the config KEY that feeds it.
    # It used to sit in the loop above, which writes each key out under its own
    # name -- correct for title/summary/project/program, where key and attribute
    # coincide, and an accident for this one, which emitted a `cruise_id`
    # attribute duplicating `cruise` in every file.  Emitting `cruise` here (not
    # only in the CTD builder) is also what gives the LADCP product a cruise
    # name at all: it merges per-cast attrs with drop_conflicts, and the OdB
    # per-cast files carry no `cruise` attribute to survive that merge.
    if ci.get("cruise_id"):
        attrs["cruise"] = str(ci["cruise_id"])
    if ci.get("acknowledgement"):
        # Collapse the YAML folded-scalar newlines into one line.
        attrs["acknowledgement"] = " ".join(str(ci["acknowledgement"]).split())

    attrs.update(
        coverage_attrs(
            lats=lats,
            lons=lons,
            vertical_min=vertical_min,
            vertical_max=vertical_max,
            vertical_units=vertical_units,
            times=times,
        )
    )
    attrs.update(provenance_attrs(now))
    attrs.update(license_attrs(ci))

    # Validate before writing (``ctdcast validate`` is optional, so this is the
    # last line of defence).  Only a *contributor-level* error — a bad ORCID, a
    # delimiter in a value, an unknown role/scope, or a bad role vocabulary — can
    # corrupt the positional parallel strings, so only those omit the people
    # block.  An institution or creator error does NOT: contributor_attrs skips an
    # unresolved institution and still writes the contributors, so a valid PI list
    # must not be dropped over an institution typo (that was the earlier bug).
    # Any residual raise (e.g. a bad creator ORCID) is caught and omits, not
    # crashes.  Per-product scoping is handled inside contributor_attrs via
    # ``source`` (each person's ``roles: {ctd, ladcp, all}`` mapping).
    people_errors, _ = check_contributors(ci)
    contributor_fatal = [
        e for e in people_errors if "contributors" in e or "role_vocabulary" in e
    ]
    if people_errors:
        warnings.warn(
            "cruise_info metadata has errors: " + "; ".join(people_errors),
            stacklevel=2,
        )
    if not contributor_fatal:
        try:
            attrs.update(contributor_attrs(ci, source=source))
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"omitting people attributes from the compiled file: {exc}",
                stacklevel=2,
            )

    if source:
        attrs.update(dataset_identity(ci, source, config=config))

    # platform may be a slug (str) or an inline dict for a vessel not in the
    # registry; platform_attrs handles both, so don't stringify it.
    platform = ci.get("platform") or ci.get("ship_slug")
    if platform:
        attrs.update(platform_attrs(platform))

    # EXPOCODE is also emitted per-profile as an N_PROF coordinate (the composable,
    # CCHDO-round-trippable form).  It is repeated here as a global for discovery:
    # a ctdcast file is a single cruise, so it is constant, and both come from the
    # one safe resolver below, so they cannot drift.
    expocode = cruise_expocode(ci)
    if expocode:
        attrs["expocode"] = expocode

    return attrs


#: OceanSITES Reference Table 4 data modes.  Single letters rather than OG1's
#: spelled-out forms because OG1's own examples are inconsistent — it shows both
#: ``sea008_..._delayed`` and ``sp032_..._R`` — and oceanarray already uses the
#: OceanSITES letters, so one convention serves both packages.
DATA_MODES: dict[str, str] = {
    "R": "real-time",
    "P": "provisional",
    "D": "delayed-mode",
    "M": "mixed",
}

#: Vertical grid of each compiled product, when it is fixed by the processing
#: rather than chosen per cruise.  LADCP casts arrive on a native 10 m grid; the
#: CTD bin comes from ``processing.profiles_dbar`` and so is looked up per run.
_FIXED_GRID = {"ladcp": "10m"}


def grid_token(product: str, config: dict[str, Any] | None = None) -> str | None:
    """Return the vertical-grid token for a product, e.g. ``"2dbar"`` or ``"10m"``.

    The grid belongs in the identifier because it is part of what the file *is*,
    not a parameter of how it was made: regridding the same casts at 1 dbar and
    at 3 dbar yields two products that a user may legitimately want to keep side
    by side, and nothing else in the name would tell them apart.

    Parameters
    ----------
    product : str
        ``"ctd"`` or ``"ladcp"``.
    config : dict, optional
        The whole cruise config, read for ``processing.profiles_dbar``.

    Returns
    -------
    str or None
        A token safe for an identifier field (no ``_``), or None if unknown.
    """
    if product in _FIXED_GRID:
        return _FIXED_GRID[product]
    if product == "ctd":
        dbar = ((config or {}).get("processing") or {}).get("profiles_dbar", 1)
        try:
            value = float(dbar)
        except (TypeError, ValueError):
            return None
        text = f"{value:g}"
        return f"{text}dbar"
    return None


def dataset_identity(
    cruise_info: dict[str, Any] | None,
    product: str,
    *,
    config: dict[str, Any] | None = None,
    grid: str | None = None,
) -> dict[str, str]:
    """Build the ACDD identity attributes for one compiled product.

    Two identifiers, sharing a tail::

        id                          29OD20260709_R_ctd_2dbar
        internal_mission_identifier mixsed2_20260709_R_ctd_2dbar

    ``id`` follows OG1's ``<platform_serial>_<start_date>_<data_mode>`` shape,
    with the EXPOCODE standing in for platform-plus-date — it already *is* the
    ICES ship code followed by the departure date, so repeating the date would be
    redundant.  ``internal_mission_identifier`` is the institution's own name for
    the cruise and carries the date explicitly, since a project short name like
    ``mixsed2`` has none.  The product and grid then distinguish the files within
    one cruise.

    The leading ``<expocode>_ctd`` is exactly CCHDO's own file name
    (``740H20200119_ctd.nc``), so a ctdcast identifier is a strict extension of
    the convention ctdcast already reads.

    ``_`` separates fields and must not occur inside one — the OceanSITES rule,
    adopted so the identifier can be split back apart.

    Parameters
    ----------
    cruise_info : dict or None
        The ``cruise_info:`` mapping.  Reads ``data_mode``, ``naming_authority``
        and ``internal_id``.
    product : str
        ``"ctd"`` or ``"ladcp"``.
    config : dict, optional
        The whole cruise config, for the grid lookup.
    grid : str, optional
        Overrides the derived grid token.

    Returns
    -------
    dict of str to str
        ``id``, ``naming_authority``, ``internal_mission_identifier``,
        ``data_mode`` and ``data_mode_meaning`` — only those that can be built.
    """
    ci = cruise_info or {}
    attrs: dict[str, str] = {}

    mode = str(ci.get("data_mode") or "D").upper()
    if mode not in DATA_MODES:
        warnings.warn(
            f"cruise_info.data_mode {mode!r} is not an OceanSITES data mode "
            f"({sorted(DATA_MODES)}); using 'D'.",
            stacklevel=2,
        )
        mode = "D"
    attrs["data_mode"] = mode
    attrs["data_mode_meaning"] = DATA_MODES[mode]

    token = grid if grid is not None else grid_token(product, config)
    tail = [mode, product] + ([token] if token else [])

    # A placeholder EXPOCODE is fine as an attribute -- it states what is missing
    # -- but not in `id`, which ACDD ties to the file name: braces are hostile in
    # a shell and an `id` that changes once the date is filled in would break the
    # promise that the identifier and the file on disk do not drift.
    expocode = cruise_expocode(ci)
    if expocode and not is_placeholder_expocode(expocode):
        attrs["id"] = "_".join([expocode, *tail])

    internal = ci.get("internal_id")
    start = ci.get("start_date")
    if internal:
        parts = [str(internal)]
        if start is not None:
            parts.append(_compact_date(start))
        attrs["internal_mission_identifier"] = "_".join([*parts, *tail])

    authority = ci.get("naming_authority")
    if authority:
        attrs["naming_authority"] = str(authority)

    return attrs


def dataset_filename(
    cruise_info: dict[str, Any] | None,
    product: str,
    *,
    config: dict[str, Any] | None = None,
    grid: str | None = None,
) -> str | None:
    """Return ``<id>.nc`` for a compiled product, or None when no ``id`` exists.

    ACDD notes that the ``id`` may be the file name without its suffix, which is
    what this enforces, so the file on disk and the identifier inside it cannot
    drift apart.
    """
    identity = dataset_identity(cruise_info, product, config=config, grid=grid)
    ident = identity.get("id")
    return f"{ident}.nc" if ident else None


def _compact_date(value: Any) -> str:
    """Return ``YYYYMMDD`` for a date, datetime or ISO-ish string."""
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "")[:8]


#: Stand-ins for the two halves of an EXPOCODE when config cannot supply them.
#: Braces are not legal in an EXPOCODE (it is ICES code + ``YYYYMMDD``, both
#: alphanumeric), so a placeholder can never be mistaken for a real code by a
#: reader or a regex — the same reasoning as ``UNKCRUISE`` in
#: :mod:`ctdcast.config.parameters`: conspicuous beats plausible.
#: [Contract — a file carrying one of these is provisional. Do not publish it.]
EXPOCODE_PLACEHOLDER_ICES = "{ICES}"
EXPOCODE_PLACEHOLDER_DATE = "{YYYYMMDD}"


def is_placeholder_expocode(expocode: str | None) -> bool:
    """True when *expocode* carries a placeholder for a missing config value."""
    return bool(expocode) and "{" in str(expocode)


def cruise_expocode(cruise_info: dict[str, Any] | None) -> str | None:
    """Return the cruise EXPOCODE, with placeholders for what config omits.

    A *present* but unusable slug (ambiguous, no ICES code, or a forbidden code)
    is a config error that :func:`ctdcast.config.platforms.derive_expocode` raises
    on — but at build time a wrong EXPOCODE is worse than none and a hard crash
    mid-pipeline is worse still, so here it is downgraded to a loud warning and
    ``None``.  The resolver keeps its strict raising contract for direct callers;
    this is the lenient wrapper the file builders use.

    A *missing* ``platform``/``ship_slug`` or ``start_date`` is different: the
    cruise is mid-processing and has simply not settled that value yet.  Returning
    ``None`` there meant the compiled file carried no cruise identifier at all,
    and — because the departure date appears nowhere else (see the CCHDO
    exemplar, which encodes it only inside the EXPOCODE) — the fact was lost
    rather than merely deferred.  So the shape is kept and the missing half is
    filled with a conspicuous placeholder::

        29OD{YYYYMMDD}      departure date not yet set
        {ICES}20260709      ship not yet resolved to an ICES code

    With *neither* half given there is nothing to defer — no cruise is being
    described — so that returns ``None`` as before rather than a placeholder on
    every profile.

    The file can therefore be generated and read, and states plainly which fact
    is absent.  Callers that must not see a placeholder — the filename builder
    above all — test with :func:`is_placeholder_expocode`.

    Parameters
    ----------
    cruise_info : dict or None
        The ``cruise_info:`` mapping.

    Returns
    -------
    str or None
        The EXPOCODE, possibly containing placeholders; ``None`` only when the
        slug is present but unusable.
    """
    ci = cruise_info or {}
    platform = ci.get("platform") or ci.get("ship_slug")
    start_date = ci.get("start_date")

    if not platform and not start_date:
        # Nothing to defer.  A placeholder marks a value the config has started
        # to specify and not yet settled; with neither half given there is no
        # cruise being described, and `{ICES}{YYYYMMDD}` would be noise on every
        # profile rather than a statement about anything.
        return None

    try:
        if platform and start_date:
            return expocode_from_cruise_info(ci)
        # One half is absent: build the shape by hand rather than asking the
        # resolver, which correctly refuses an incomplete config.
        if platform:
            head = expocode_from_cruise_info({**ci, "start_date": "1900-01-01"})
            head = head[: -len("19000101")]
        else:
            head = EXPOCODE_PLACEHOLDER_ICES
    except PlatformError as exc:
        warnings.warn(
            f"cannot derive EXPOCODE; omitting it from the compiled file: {exc}",
            stacklevel=2,
        )
        return None

    tail = _compact_date(start_date) if start_date else EXPOCODE_PLACEHOLDER_DATE
    missing = [
        n
        for n, v in (("platform", platform), ("start_date", start_date))
        if not v
    ]
    placeholder = f"{head}{tail}"
    warnings.warn(
        f"cruise_info.{' and '.join(missing)} not set; writing the placeholder "
        f"EXPOCODE {placeholder!r} so the file can still be built. It is not a "
        f"valid EXPOCODE — do not publish this file, and the compiled product "
        f"keeps its fallback name rather than being named after it.",
        stacklevel=2,
    )
    return placeholder


def expocode_coordinate(
    cruise_info: dict[str, Any] | None, n_profiles: int
) -> tuple[list[str], np.ndarray, dict[str, str]] | None:
    """Return the ``(dims, data, attrs)`` triple for the ``expocode`` coordinate.

    CCHDO stores the EXPOCODE per profile (a file may hold more than one cruise),
    so both compiled builders emit it as an ``N_PROF`` variable.  This is the one
    place that builds it, so the CTD and LADCP files describe it identically.
    Returns ``None`` when no EXPOCODE can be derived.

    Parameters
    ----------
    cruise_info : dict or None
        The ``cruise_info:`` mapping.
    n_profiles : int
        Length of the ``N_PROF`` dimension to broadcast the constant value over.

    Returns
    -------
    tuple or None
        ``(["N_PROF"], data, attrs)`` ready to assign to a variable, or ``None``.
    """
    expocode = cruise_expocode(cruise_info)
    if not expocode:
        return None
    return (
        ["N_PROF"],
        np.array([expocode] * n_profiles),
        {
            "long_name": "Expedition code (ICES ship code + departure date)",
            "comment": (
                "Derived as <ICES platform code><YYYYMMDD departure>; "
                "CCHDO/GO-SHIP EXPOCODE convention."
            ),
        },
    )
