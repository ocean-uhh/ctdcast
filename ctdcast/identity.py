"""Cast identity: cast-number parsing, expansion, and compact formatting.

PR 1a seeds this module with ``compact_cast_list`` (moved out of the old
``analysis.py`` so ``analysis`` could become a package).  PR 1c consolidates the
triplicated filename regex and ``expand_cast_numbers`` here as well.
"""

from __future__ import annotations


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
