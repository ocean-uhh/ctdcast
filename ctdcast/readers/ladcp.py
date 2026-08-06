"""Reader for LDEO IXv14 LADCP ``.mat`` files.

Locates the ``.mat`` file for a cast (:func:`find_ladcp_file`) and loads it with a
single set of ``scipy.io.loadmat`` options (:func:`read_ladcp`), so the loader
options live in one place instead of being repeated in every plot function.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def read_ladcp(path: Path | str) -> dict[str, Any]:
    """Load an LDEO IXv14 LADCP ``.mat`` file.

    Uses ``squeeze_me=True`` and ``struct_as_record=False`` so the LADCP result
    struct is reachable as ``read_ladcp(path)["dr"]`` with attribute access.
    """
    import scipy.io

    return scipy.io.loadmat(str(path), squeeze_me=True, struct_as_record=False)


def find_ladcp_file(
    ladcp_dir: Path,
    cast_num: int,
    cast_suffix: str = "",
    ladcp_pattern: str | None = None,
) -> Path | None:
    """Return the .mat file for *cast_num* in *ladcp_dir*, or ``None`` if absent.

    If *ladcp_pattern* is given (e.g. ``"msm_142_1_*.mat"``), the ``*``
    wildcard is replaced with the zero-padded cast number (and optional suffix)
    and that name is tried first.  Falls back to standard names (``NNN.mat``,
    ``NNNb.mat``) then a ``*_NNN.mat`` glob for cruise-prefixed filenames.
    The first glob match (lexicographic) is returned when multiple files match.
    """
    if ladcp_pattern:
        for cast_str in (f"{cast_num:03d}{cast_suffix}", f"{cast_num:03d}"):
            p = ladcp_dir / ladcp_pattern.replace("*", cast_str)
            if p.exists():
                return p
    for name in (f"{cast_num:03d}{cast_suffix}.mat", f"{cast_num:03d}.mat"):
        p = ladcp_dir / name
        if p.exists():
            return p
    for glob_pat in (
        f"*_{cast_num:03d}{cast_suffix}.mat",
        f"*_{cast_num:03d}.mat",
    ):
        found = sorted(ladcp_dir.glob(glob_pat))
        if found:
            return found[0]
    return None
