"""Stamped ``history`` notes for the processing stages.

Every stage records what it did — and the parameters it used — as a line in the
CF ``history`` global attribute, so the treatment is reconstructable from the
output file alone.  Because each stage reads its predecessor and copies its
attributes, ``history`` accumulates: stage 3 inherits the stage 1 and stage 2
lines and appends its own.

The format, from one helper so it stays consistent, is::

    <timestamp> <producer> <version> <stage>: <note>

joined with newlines.  ctdcast's own stages use the defaults — an ISO-8601 UTC
timestamp, producer ``ctdcast`` — giving ``<ISO-8601 UTC> ctdcast <version> <stage>``.
An upstream Sea-Bird step overrides *producer* (``"SBE Data Processing"``), *timestamp*
(the tool's own verbatim stamp, no ``Z``) and the *stage* field (the module name, e.g.
``celltm``), so a stage-1 file's history shows Sea-Bird's own lines alongside ctdcast's.
"""

from __future__ import annotations

import datetime
from typing import MutableMapping

from ctdcast._version import __version__


def _iso_now() -> str:
    """Return the current UTC time as an ISO-8601 ``…Z`` stamp."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_history(
    attrs: MutableMapping[str, object],
    note: str,
    *,
    stage: str,
    version: str = __version__,
    producer: str = "ctdcast",
    timestamp: str | None = None,
    prepend: bool = False,
) -> None:
    """Append a stamped ``history`` line to *attrs* in place.

    Parameters
    ----------
    attrs:
        The attribute mapping to extend — an ``xarray`` ``ds.attrs`` or the plain
        ``dict`` a builder assembles before constructing its Dataset.  Mutated in
        place: the existing ``history`` (if any) is preserved and the new line is
        appended after a newline.
    note:
        The human-readable record of the operation, including the parameters it
        used (e.g. ``"gross_range: ctd_salinity_1:[2.0,42.0]"``).
    stage:
        The stage token that did the work — ``"stage1"``, ``"stage2"``, ``"stage3"``,
        ``"profiles"``, ``"ladcp_profiles"`` for ctdcast's own stages, or a Sea-Bird
        module name (``"celltm"``, ``"binavg"``, …) for an upstream step.
    version:
        The version to stamp; defaults to the installed ctdcast package version.
    producer:
        Who did the work — ``"ctdcast"`` by default.  An upstream Sea-Bird step
        passes ``"SBE Data Processing"`` so the line reads as Sea-Bird's, not
        ctdcast's.
    timestamp:
        The stamp to use.  ``None`` (the default) uses the current ISO-8601 UTC
        time.  A Sea-Bird step passes its own verbatim timestamp, kept as-is — no
        ``Z`` is appended, because it comes from a processing workstation whose
        offset is unknown and a different clock again from the deck unit.
    prepend:
        Insert the line at the **front** of ``history`` instead of the end.  Used for
        an upstream step (a Sea-Bird module) that predates the reader's own line, so the
        record stays oldest-first; the default appends.

    """
    stamp = timestamp if timestamp is not None else _iso_now()
    # Join the prefix fields skipping any empty one (a Sea-Bird module may have a timestamp
    # but no version), so no double space appears; rstrip drops the trailing space when a
    # module has no salient parameters (an empty note).  ctdcast's own notes are never empty.
    prefix = " ".join(field for field in (stamp, producer, version, stage) if field)
    entry = f"{prefix}: {note}".rstrip()
    prev = str(attrs.get("history", ""))
    if prepend:
        attrs["history"] = f"{entry}\n{prev}".rstrip("\n")
    else:
        attrs["history"] = f"{prev}\n{entry}".lstrip("\n")
