"""Cast identity: cast-number parsing, expansion, and compact formatting.

Single home for the cast-identity operations shared across the package:
parse a cast number and letter suffix from a filename (:func:`cast_id_from_name`),
expand a ``cast_numbers`` config spec to order-preserving pairs or ints
(:func:`expand_cast_ids` / :func:`expand_cast_numbers`), format a single cast id as
a zero-padded string (:func:`format_cast_id`), and format a list of cast numbers
compactly with collapsed ranges (:func:`compact_cast_list`).
"""

from __future__ import annotations

import re

from ctdcast.config.parameters import CAST_TAG_WIDTH

_CAST_ID_RE = re.compile(r"_(\d{3,})([a-z]*)(?=_|$)")


def _is_plain_int(x: object) -> bool:
    """Return True for a real int, excluding bool (which subclasses int)."""
    return isinstance(x, int) and not isinstance(x, bool)


def format_cast_id(cast_num: int, cast_suffix: str = "") -> str:
    """Format a cast identity as a zero-padded id string, e.g. ``(10, "b") -> "010b"``.

    The single formatter for the ``NNN``/``NNNb`` convention used in output
    filenames (``cast_010b.html``), page labels, and cast pills.  Changing the
    pad width or suffix rule here changes it everywhere.
    """
    return f"{cast_num:0{CAST_TAG_WIDTH}d}{cast_suffix}"


def cast_id_from_name(name: str) -> tuple[int, str] | None:
    """Extract ``(cast_num, cast_suffix)`` from a cast filename stem.

    Uses the last 3+-digit group in the stem as the cast number, so cruise or
    leg numbers earlier in the name (e.g. the ``142`` in
    ``msm_142_1_001_1sec``) are not mistaken for the cast number.  Letter
    suffixes are recognised whether directly appended (``mixsed2_004b``) or
    underscore-separated (``mixsed2_004_b``).  Returns ``None`` when no 3+-digit
    group is present.
    """
    matches = _CAST_ID_RE.findall(name)
    if not matches:
        return None
    cast_num_str, cast_suffix = matches[-1]
    if not cast_suffix:
        m = re.search(rf"_{re.escape(cast_num_str)}_([a-z]+)$", name)
        if m:
            cast_suffix = m.group(1)
    return int(cast_num_str), cast_suffix


_CAST_TOKEN_RE = re.compile(r"(\d+)([a-z]*)")


def _parse_cast_token(item: object) -> list[tuple[int, str]]:
    """Parse one ``cast_numbers`` entry to a list of ``(number, suffix)`` pairs.

    An int or a ``"NNN"`` string is a plain cast (empty suffix); a ``"NNNb"``
    string names a lettered sibling event; a two-element ``[first, last]`` list
    expands to plain casts only.  Raises ``ValueError`` on anything else.
    """
    if _is_plain_int(item):
        return [(item, "")]
    if isinstance(item, str):
        m = _CAST_TOKEN_RE.fullmatch(item.strip())
        if m is None:
            raise ValueError(
                f"Invalid cast_numbers entry {item!r}: expected e.g. '10' or '10b'."
            )
        return [(int(m.group(1)), m.group(2))]
    if (
        isinstance(item, list)
        and len(item) == 2
        and all(_is_plain_int(x) for x in item)
    ):
        return [(n, "") for n in range(item[0], item[1] + 1)]
    raise ValueError(
        f"Invalid cast_numbers entry {item!r}: expected an int, a 'NNN'/'NNNb' "
        "string, or a two-element [first, last] list of ints."
    )


def expand_cast_ids(cast_numbers: list) -> list[tuple[int, str]]:
    """Expand a ``cast_numbers`` spec to ``(number, suffix)`` pairs, preserving order.

    A plain cast `NNN` and its lettered sibling `NNNb` are distinct events, so
    identity is the pair, not the bare number.  A bare int or range names plain
    events only (suffix ``""``); a `"NNNb"` string names the lettered event.
    Input order is preserved and duplicates are kept — section ordering relies on
    the author's given order, so sorting and de-duplication are not applied.

    Raises ``ValueError`` on a malformed entry, so a bad config fails loudly
    rather than silently dropping or coercing casts.
    """
    result: list[tuple[int, str]] = []
    for item in cast_numbers:
        result.extend(_parse_cast_token(item))
    return result


def expand_cast_numbers(cast_numbers: list) -> list[int]:
    """Expand a ``cast_numbers`` spec to a flat list of station numbers, in order.

    The integer view of :func:`expand_cast_ids` — the letter suffix is dropped,
    so a `"10b"` entry contributes station ``10``.  Use this where callers key on
    the integer station (LADCP files, map positions, membership); use
    :func:`expand_cast_ids` where a plain cast must be distinguished from its
    lettered sibling (section and timeseries profile selection).
    """
    return [num for num, _suffix in expand_cast_ids(cast_numbers)]


def compact_cast_list(nums: list[int]) -> str:
    """Format a cast number list compactly, collapsing consecutive runs into ranges.

    Example: [131, 133, 134, 136, 163] → "131, 133–134, 136, 163".
    """
    if not nums:
        return "—"
    nums = sorted(set(nums))
    parts: list[str] = []
    start = end = nums[0]
    for n in nums[1:]:
        if n == end + 1:
            end = n
        else:
            parts.append(str(start) if start == end else f"{start}–{end}")
            start = end = n
    parts.append(str(start) if start == end else f"{start}–{end}")
    return ", ".join(parts)
