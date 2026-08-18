"""Batch warning summarisation for the processing stages.

A whole-cruise stage converts hundreds of casts, and a per-cast library warning
(a blank instrument serial, a ``db`` vs ``dbar`` unit label) would otherwise print
once per cast.  :func:`summarise_warnings` collapses captured warnings into one
counted line per unique message so the console stays readable without hiding the
underlying notice.
"""

from __future__ import annotations

import warnings


def summarise_warnings(caught: list[warnings.WarningMessage]) -> None:
    """Print one counted line per unique captured warning message."""
    counts: dict[str, int] = {}
    for w in caught:
        counts[str(w.message)] = counts.get(str(w.message), 0) + 1
    for msg, count in sorted(counts.items()):
        print(f"  note ({count} cast(s)): {msg}")
