"""On-disk stage layout: per-stage paths and best-available cast-file discovery.

The single source of truth for the stage-file naming, so nothing elsewhere
hard-codes ``_stageN`` or ``stageN/``.  Each processing stage writes its own
per-cast netCDF under a stage subdirectory of one instrument root, with the
stage carried in the filename as well as the path::

    <root>/stage1/<cast_stem>_stage1.nc
    <root>/stage2/<cast_stem>_stage2.nc
    <root>/stage3/<cast_stem>_stage3.nc

The subdirectory bounds each directory's file count by cast count rather than
cast count times stages; the filename suffix means a file copied out of its
directory is still identifiable and still parses.  :func:`parse_stage` reads the
stage off the filename and does not trust the parent directory, so the two can
disagree (the filename wins, with a warning) without losing the file.

The cast stages here mirror the ``"cast"``-scope entries of
:data:`ctdcast.processors.STAGES` (the pipeline registry); the two are tied by a
consistency test rather than derived from each other, because the registry
imports the stage modules that import this one — deriving would be an import
cycle.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable
from pathlib import Path

from ctdcast.identity import cast_id_from_name, format_cast_id

#: Subdirectory under the instrument root that holds each stage's files.  This is
#: the one hand-maintained map; the suffixes and the stage tuple derive from it,
#: so adding a stage (e.g. a future hex→CNV stage 0) is a single line here.
STAGE_DIRS: dict[int, str] = {1: "stage1", 2: "stage2", 3: "stage3"}

#: Filename suffix (before ``.nc``) carried by each stage's per-cast file.  The
#: stage's directory name and filename suffix are the same token by construction,
#: matching the sibling oceanarray package's "stage name doubles as the suffix".
STAGE_SUFFIXES: dict[int, str] = {n: f"_{d}" for n, d in STAGE_DIRS.items()}

#: The per-cast stages that write stage files, in ascending order.
STAGES: tuple[int, ...] = tuple(sorted(STAGE_DIRS))


def _check_stage(stage: int) -> None:
    """Raise :class:`ValueError` if *stage* is not a known per-cast stage."""
    if stage not in STAGE_DIRS:
        raise ValueError(
            f"unknown stage {stage!r}; expected one of {sorted(STAGE_DIRS)}"
        )


def stage_dir(root: Path | str, stage: int, *, create: bool = False) -> Path:
    """Return ``root/stageN``.

    Parameters
    ----------
    root : Path or str
        The instrument stage root (e.g. the CTD or LADCP root).
    stage : int
        The processing stage (1, 2, or 3).
    create : bool, optional
        Create the directory (and parents) when true.

    Returns
    -------
    Path
        The stage subdirectory.
    """
    _check_stage(stage)
    directory = Path(root) / STAGE_DIRS[stage]
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def stage_path(root: Path | str, cast_stem: str, stage: int) -> Path:
    """Return the per-cast output path ``root/stageN/<cast_stem>_stageN.nc``.

    Parameters
    ----------
    root : Path or str
        The instrument stage root.
    cast_stem : str
        The cast's base stem, without any stage suffix (e.g. ``mixsed2_017``).
    stage : int
        The processing stage (1, 2, or 3).

    Returns
    -------
    Path
        The stage-suffixed per-cast netCDF path.
    """
    _check_stage(stage)
    return stage_dir(root, stage) / f"{cast_stem}{STAGE_SUFFIXES[stage]}.nc"


def parse_stage(path: Path | str) -> tuple[str, int] | None:
    """Return ``(base_stem, stage)`` parsed from a filename, or ``None``.

    The stage is read from the filename suffix, not the parent directory, so a
    file copied out of its stage directory still parses.  When the filename
    suffix and the parent directory disagree, the filename wins and a warning is
    emitted rather than the file being misread or dropped.

    Parameters
    ----------
    path : Path or str
        A per-cast netCDF path or name.

    Returns
    -------
    tuple of (str, int) or None
        The base stem (stage suffix stripped) and the stage number, or ``None``
        when the name carries no recognised stage suffix.
    """
    path = Path(path)
    stem = path.stem  # drops the ``.nc`` extension
    for stage, suffix in STAGE_SUFFIXES.items():
        if stem.endswith(suffix):
            base = stem[: -len(suffix)]
            parent = path.parent.name
            if parent in STAGE_DIRS.values() and parent != STAGE_DIRS[stage]:
                warnings.warn(
                    f"{path.name} carries {suffix!r} but sits in {parent!r}; "
                    "trusting the filename",
                    stacklevel=2,
                )
            return base, stage
    return None


def best_available(root: Path | str, cast_stem: str) -> Path | None:
    """Return the highest-stage file present for *cast_stem*, else ``None``.

    Precedence is stage 3, then stage 2, then stage 1 — the one place this rule
    lives.

    Parameters
    ----------
    root : Path or str
        The instrument stage root.
    cast_stem : str
        The cast's base stem, without any stage suffix.

    Returns
    -------
    Path or None
        The best-available per-cast file, or ``None`` when no stage file exists.
    """
    for stage in sorted(STAGES, reverse=True):
        candidate = stage_path(root, cast_stem, stage)
        if candidate.exists():
            return candidate
    # Flat/suffix-less shim: an old ``nc_dir`` holds ``<stem>.nc`` directly under
    # the root, no stage subdirectory and no suffix.  It counts as stage 1, and
    # ranks below any nested stage file (checked above first).
    flat = Path(root) / f"{cast_stem}.nc"
    if flat.exists():
        return flat
    return None


def group_by_cast(root: Path | str) -> dict[tuple[int, str], dict[int, Path]]:
    """Map each cast identity to the stage files present for it.

    Walks ``root/stage*/`` and groups every recognised stage file by its cast
    identity ``(cast_num, cast_suffix)`` — so a plain cast ``NNN`` and its
    lettered sibling ``NNNb`` are distinct keys.  Files whose name carries no
    stage suffix or no cast number are skipped.

    A suffix-less ``*.nc`` directly under the root (the old flat ``nc_dir``
    layout, and the committed test fixtures) is folded in as **stage 1**, unless
    a nested ``stage1/…_stage1.nc`` already exists for that cast — the nested file
    wins.  Compiled products such as ``profiles.nc`` carry no cast number and are
    skipped automatically.

    Parameters
    ----------
    root : Path or str
        The instrument stage root.

    Returns
    -------
    dict
        ``{(cast_num, cast_suffix): {stage: path}}``.
    """
    root = Path(root)
    groups: dict[tuple[int, str], dict[int, Path]] = {}
    for stage in STAGES:
        directory = root / STAGE_DIRS[stage]
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(f"*{STAGE_SUFFIXES[stage]}.nc")):
            parsed = parse_stage(path)
            if parsed is None:  # pragma: no cover - glob guarantees the suffix
                continue
            base, file_stage = parsed
            cast_id = cast_id_from_name(base)
            if cast_id is None:
                continue
            groups.setdefault(cast_id, {})[file_stage] = path
    # Flat/suffix-less shim: top-level suffix-less cast files count as stage 1,
    # ranking below any nested stage-1 file already found (hence ``setdefault``).
    for path in sorted(root.glob("*.nc")):
        if parse_stage(path) is not None:
            continue  # a suffixed file loose at the root — not a flat stage 1
        if is_product_name(path):
            continue  # compiled product (…profiles.nc), even if its name has digits
        cast_id = cast_id_from_name(path.stem)
        if cast_id is None:
            continue  # non-cast file
        groups.setdefault(cast_id, {}).setdefault(1, path)
    return groups


def matches_tags(cast_id: tuple[int, str], tags: set[str]) -> bool:
    """Return whether *cast_id* is selected by any zero-padded cast *tag*.

    Matches on the parsed cast identity, not a filename substring — so a cruise
    or leg number in the stem cannot be mistaken for the cast number (the bug in
    the old ``tag in stem`` rule), and a lettered sibling ``004b`` is selected by
    its own tag (``"004b"``) or by the bare number (``"004"``).

    Parameters
    ----------
    cast_id : tuple of (int, str)
        The ``(cast_num, cast_suffix)`` identity from :func:`group_by_cast`.
    tags : set of str
        Zero-padded cast tags (e.g. ``{"042", "004b"}``), as the CLI produces
        from ``--only``.

    Returns
    -------
    bool
        True if any tag names this cast.
    """
    num, suffix = cast_id
    return format_cast_id(num, suffix) in tags or format_cast_id(num) in tags


#: Filename suffix of the compiled gridded products (``profiles.nc``,
#: ``ladcp_profiles.nc``) that sit at the stage root beside the stage directories.
PRODUCT_SUFFIX = "profiles.nc"


def is_product_name(name: Path | str) -> bool:
    """Return whether *name* is a compiled-product file, not a per-cast file.

    Compiled products (``…profiles.nc``) live at the stage root; they are terminal
    gridded artefacts, not casts, and must never be folded into cast discovery —
    even when the name carries a cruise number (e.g. ``msm_142_profiles.nc``),
    which would otherwise parse as cast 142.
    """
    return Path(name).name.endswith(PRODUCT_SUFFIX)


def select_best_available(
    root: Path | str,
) -> list[tuple[tuple[int, str], Path, int]]:
    """Return ``(cast_id, best_path, source_stage)`` per cast, sorted by identity.

    The one place the best-available precedence lives for every consumer (the
    report, ``build_profiles``, the LADCP compile).  ``best_path`` is the
    highest-stage file present (3 > 2 > 1); ``source_stage`` is that rung, or 0
    when the best file is a flat/suffix-less file that does not state its own
    stage (the compatibility shim only *assumes* stage 1, so 0 = "unknown, guessed
    stage 1" stays distinct from a stated stage 1).

    Parameters
    ----------
    root : Path or str
        The instrument stage root.

    Returns
    -------
    list of (tuple(int, str), Path, int)
        One ``((cast_num, cast_suffix), path, source_stage)`` per cast, sorted by
        cast identity.
    """
    out: list[tuple[tuple[int, str], Path, int]] = []
    for cast_id, stages in group_by_cast(root).items():
        best = max(stages)
        path = stages[best]
        stage = 0 if (best == 1 and parse_stage(path) is None) else best
        out.append((cast_id, path, stage))
    return sorted(out)


def is_up_to_date(target: Path | str, sources: Iterable[Path]) -> bool:
    """Return whether *target* exists and is newer than every source in *sources*.

    The one skip/re-run test for a derived file (a stage output or a compiled
    product): skip only when the output already exists **and** no input has been
    rewritten since (by mtime).  This is what makes a forced re-run of an earlier
    step propagate — ``process --stage 1 --only 42 --force`` followed by a plain
    ``process --stage 2 3 profiles`` regenerates cast 42 downstream instead of
    silently skipping because a stale output happened to exist.  A missing source
    is ignored (it cannot make the target stale).
    """
    target = Path(target)
    if not target.exists():
        return False
    t_mtime = target.stat().st_mtime
    return all(Path(s).stat().st_mtime <= t_mtime for s in sources if Path(s).exists())
