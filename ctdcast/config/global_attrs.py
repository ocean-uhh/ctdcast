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

Conformance target is ACDD-1.3 (with CF).  We take OG1's *vocabularies* (W08
roles, EDMO institutions, L06 platform, L08 access policy) without adopting OG1's
glider-mission entity model.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

import numpy as np

from ctdcast.config.parameters import VARIABLES
from ctdcast.config.people import contributor_attrs
from ctdcast.config.platforms import expocode_from_cruise_info, platform_attrs

#: Canonical coordinate units, taken from the single source of truth in
#: :data:`ctdcast.config.parameters.VARIABLES` so the bound units always match
#: the units written on the ``latitude``/``longitude`` variables themselves.
_LAT_UNITS = VARIABLES["latitude"]["units"]
_LON_UNITS = VARIABLES["longitude"]["units"]

#: CC BY 4.0 canonical URL, named as the licence that applies *on release*.
_CC_BY_4_URL = "https://creativecommons.org/licenses/by/4.0/"


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

    if vertical_min is not None and vertical_max is not None:
        attrs["geospatial_vertical_min"] = float(vertical_min)
        attrs["geospatial_vertical_max"] = float(vertical_max)
        attrs["geospatial_vertical_units"] = vertical_units
        # Without this a min of 0 and max of 4000 is ambiguous between depth and
        # height; the profiles increase downward.
        attrs["geospatial_vertical_positive"] = "down"

    if times is not None:
        t = np.asarray(times).ravel()
        t = t[~np.isnat(t)] if t.dtype.kind == "M" else t
        if t.size:
            t0 = np.datetime64(t.min(), "s")
            t1 = np.datetime64(t.max(), "s")
            attrs["time_coverage_start"] = str(t0) + "Z"
            attrs["time_coverage_end"] = str(t1) + "Z"
            days = int((t1 - t0) / np.timedelta64(1, "D"))
            attrs["time_coverage_duration"] = f"P{days}D"

    return attrs


def _with_source_contributors(
    cruise_info: dict[str, Any], source: str | None
) -> dict[str, Any]:
    """Return *cruise_info* with a source's own contributors appended.

    A per-source block — e.g. ``cruise_info["ladcp"]["contributors"]`` — credits
    people who worked on *that product only*.  The LADCP processing personnel
    (``GEN_Processing_personnel`` in the ``.mat``) belong on ``ladcp_profiles.nc``
    but **not** on the CTD file, so they are appended to the cruise-level
    contributors when the LADCP file is written and omitted otherwise.

    Parameters
    ----------
    cruise_info : dict
        The ``cruise_info:`` mapping.
    source : str or None
        The product key (``"ctd"``, ``"ladcp"``).  None or a source with no
        sub-block returns *cruise_info* unchanged.

    Returns
    -------
    dict
        A shallow copy with the merged contributor list, or the original when
        there is nothing to merge.
    """
    if not source:
        return cruise_info
    block = cruise_info.get(source)
    extra = block.get("contributors") if isinstance(block, dict) else None
    if not extra:
        return cruise_info
    merged = dict(cruise_info)
    merged["contributors"] = list(cruise_info.get("contributors") or []) + list(extra)
    return merged


def _plus_two_years(date: _dt.date) -> _dt.date:
    """Return *date* two calendar years later, mapping 29 Feb → 28 Feb."""
    try:
        return date.replace(year=date.year + 2)
    except ValueError:  # 29 February in a leap year
        return date.replace(year=date.year + 2, day=28)


def _as_date(value: Any) -> _dt.date | None:
    """Coerce a config date value (date, ISO string) to a ``date``, or None."""
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
        until = _as_date(embargo.get("until"))
        if until is None:
            end = _as_date(cruise_info.get("end_date"))
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
    """Return ``date_created`` / ``date_modified`` and CF/ACDD conformance tags.

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
        Product key (``"ctd"``, ``"ladcp"``).  When given, contributors from
        ``cruise_info[source]["contributors"]`` are appended to the cruise-level
        list, so a product's own processing personnel are credited on that file
        alone (see :func:`_with_source_contributors`).
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
    for key in ("title", "summary", "project", "program", "cruise_id"):
        if ci.get(key):
            attrs[key] = str(ci[key])
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
    attrs.update(contributor_attrs(_with_source_contributors(ci, source)))

    slug = ci.get("platform") or ci.get("ship_slug")
    if slug:
        attrs.update(platform_attrs(str(slug)))

    # EXPOCODE is also emitted per-profile as an N_PROF coordinate (the composable,
    # CCHDO-round-trippable form).  It is repeated here as a global for discovery:
    # a ctdcast file is a single cruise, so it is constant, and both come from the
    # one source below, so they cannot drift.
    expocode = expocode_from_cruise_info(ci)
    if expocode:
        attrs["expocode"] = expocode

    return attrs


def cruise_expocode(cruise_info: dict[str, Any] | None) -> str | None:
    """Return the cruise EXPOCODE, or None when it cannot be derived.

    Thin pass-through to :func:`ctdcast.config.platforms.expocode_from_cruise_info`
    so callers building the ``expocode`` ``N_PROF`` coordinate have one import.
    """
    return expocode_from_cruise_info(cruise_info or {})
