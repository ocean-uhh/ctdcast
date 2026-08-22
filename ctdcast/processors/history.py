"""Stamped ``history`` notes for the processing ladder.

Every stage records what it did — and the parameters it used — as a line in the
CF ``history`` global attribute, so the treatment is reconstructable from the
output file alone.  Because each stage reads its predecessor and copies its
attributes, ``history`` accumulates: stage 3 inherits the stage 1 and stage 2
lines and appends its own.

The one format, shared by every call site, is::

    <ISO-8601 UTC> ctdcast <version> <stage>: <note>

joined with newlines.  Keeping it in one helper means the format cannot drift
between stages and the package version is recorded on every line.
"""

from __future__ import annotations

import datetime
from typing import MutableMapping

from ctdcast._version import __version__


def append_history(
    attrs: MutableMapping[str, object],
    note: str,
    *,
    stage: str,
    version: str = __version__,
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
        The stage token that did the work (``"stage1"``, ``"stage2"``,
        ``"stage3"``, ``"profiles"``, ``"ladcp_profiles"``).
    version:
        The ctdcast version to stamp; defaults to the installed package version.

    """
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"{stamp} ctdcast {version} {stage}: {note}"
    prev = str(attrs.get("history", ""))
    attrs["history"] = f"{prev}\n{entry}".lstrip("\n")
