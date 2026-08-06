"""Cast identity: cast-number parsing, expansion, and compact formatting.

Single home for the three cast-identity operations shared across the package:
parse a cast number and letter suffix from a filename (:func:`cast_id_from_name`),
expand a ``cast_numbers`` config spec to a flat, order-preserving list of ints
(:func:`expand_cast_numbers`), and format a list of cast numbers compactly with
collapsed ranges (:func:`compact_cast_list`).
"""

from __future__ import annotations

import re

_CAST_ID_RE = re.compile(r"_(\d{3,})([a-z]*)(?=_|$)")


def _is_plain_int(x: object) -> bool:
    """Return True for a real int, excluding bool (which subclasses int)."""
    return isinstance(x, int) and not isinstance(x, bool)


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


def expand_cast_numbers(cast_numbers: list) -> list[int]:
    """Expand a ``cast_numbers`` spec to a flat list of ints, preserving order.

    Each item is either an int (kept where it sits) or a two-element
    ``[first, last]`` list (expanded inclusively in place).  Input order is
    preserved and duplicates are kept — section ordering relies on the author's
    given order, so sorting and de-duplication are deliberately not applied.

    Raises ``ValueError`` on any item that is neither a plain int nor a
    two-element list of plain ints, so a malformed config fails loudly rather
    than silently dropping or coercing casts.
    """
    result: list[int] = []
    for item in cast_numbers:
        if _is_plain_int(item):
            result.append(item)
        elif (
            isinstance(item, list)
            and len(item) == 2
            and all(_is_plain_int(x) for x in item)
        ):
            result.extend(range(item[0], item[1] + 1))
        else:
            raise ValueError(
                f"Invalid cast_numbers entry {item!r}: expected an int or a "
                "two-element [first, last] list of ints."
            )
    return result


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
