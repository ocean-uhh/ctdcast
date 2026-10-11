"""Read the ``SENSOR_*`` catalog stage 1 built, from any per-cast stage file.

Stage 1 writes a dimensionless ``SENSOR_<TYPE>_<SERIAL>`` variable per physical sensor,
carrying its ``sensor_role`` and ``sensor_channel``.  This module reads that catalog back —
the inverse of the stage-1 builder — so every later step (the stage-3 preferred-sensor
stamp, the ``profiles.nc`` compile, and ``ctdcast validate``) shares one reader and no stage
imports a later stage.
"""

from __future__ import annotations

from collections.abc import Iterable

import xarray as xr

from ctdcast.identity import format_cast_id


def read_cast_sensor_catalog(ds: xr.Dataset) -> list[dict]:
    """Return one record per ``SENSOR_*`` catalog entry in a per-cast dataset.

    Reads the catalog stage 1 built: each dimensionless ``SENSOR_<TYPE>_<SERIAL>``
    variable, taking its ``sensor_role`` and ``sensor_channel`` off the entry itself
    (not off the data variables). A sensor with no stored variable — pH, a
    transmissometer — is therefore read exactly like one that has a variable, which
    is what lets the compile aggregate without re-parsing the CNV header.

    Parameters
    ----------
    ds : xarray.Dataset
        A per-cast dataset carrying the stage-1 ``SENSOR_*`` catalog variables.

    Returns
    -------
    list of dict
        One record per catalog entry, each with ``name`` (the catalog variable name,
        already resolved at stage 1), ``role``, ``channel`` (int, or ``-1`` if unstated)
        and ``attrs`` (the full entry attributes, verbatim). ``[]`` when the cast carries
        no catalog.
    """
    records: list[dict] = []
    for name in ds.variables:
        if not str(name).startswith("SENSOR_"):
            continue
        attrs = dict(ds[name].attrs)
        records.append(
            {
                "name": str(name),
                "role": attrs.get("sensor_role", ""),
                "channel": (
                    int(attrs["sensor_channel"]) if "sensor_channel" in attrs else -1
                ),
                "attrs": attrs,
            }
        )
    return records


def _role_signature(records: list[dict]) -> dict[str, str]:
    """Return ``{role: catalog variable name}`` — a cast's sensor configuration fingerprint."""
    return {rec["role"]: rec["name"] for rec in records if rec.get("role")}


def catalog_by_cast_number(
    per_identity: Iterable[tuple[tuple[int, str], list[dict]]],
) -> tuple[dict[int, list[dict]], list[str]]:
    """Collapse per-identity catalogs to one per cast number, flagging sibling mismatches.

    The preferred-sensor declaration is per cast *number*, so a plain cast and its lettered
    sibling (``010`` / ``010b``) share one declaration and collapse to one entry here.  When
    two siblings sharing a number carry **different** sensor serials, the per-number
    declaration cannot distinguish them — a warning naming both casts is returned so the
    operator knows the reconciliation treats them as one.

    Parameters
    ----------
    per_identity : iterable of ((int, str), list of dict)
        ``((cast_number, cast_suffix), records)`` pairs — one per cast identity, records as
        returned by :func:`read_cast_sensor_catalog`.

    Returns
    -------
    tuple of (dict of {int: list of dict}, list of str)
        The catalog keyed by cast number (a later sibling overwrites an earlier one), and the
        sibling-mismatch warning strings (empty when no number has differing siblings).
    """
    by_number: dict[int, list[dict]] = {}
    first_seen: dict[int, tuple[str, dict[str, str]]] = {}
    warnings: list[str] = []
    for (num, suffix), records in per_identity:
        # Keep a catalogued sibling over a catalog-less one for the same number (a
        # catalog-less sibling must not clobber real records).
        if records or num not in by_number:
            by_number[num] = records
        signature = _role_signature(records)
        # A catalog-less cast (no SENSOR_* records) has an empty signature; comparing it
        # against a sibling's would raise a spurious "different serials" warning. Only
        # catalogued casts carry a sibling signature to compare.
        if not signature:
            continue
        if num in first_seen:
            prev_suffix, prev_signature = first_seen[num]
            if signature != prev_signature:
                warnings.append(
                    f"casts {format_cast_id(num, prev_suffix)} and "
                    f"{format_cast_id(num, suffix)} have different sensor serials; the "
                    f"preferred-sensor declaration is per cast number and cannot distinguish "
                    f"them"
                )
        else:
            first_seen[num] = (suffix, signature)
    return by_number, warnings
