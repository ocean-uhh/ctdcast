"""CTD processing pipeline — all stages in execution order.

``STAGES`` is the single source of truth for :func:`process`, the CLI, and
the re-run rule.  Each :class:`Stage` carries the stage name, an optional
position number (for the numbered stages), the scope (per-cast or
per-cruise), and a ``run`` callable.  Each stage's ``run`` signature
takes explicit path arguments rather than a base directory.

Usage::

    import ctdcast
    ctdcast.process(stage=1, cnv_dir="/data/cnv", nc_dir="/data/nc")
    ctdcast.process(stage="profiles", nc_dir="/data/nc", profiles_path="/data/profiles.nc")
    ctdcast.process(cnv_dir="/data/cnv", nc_dir="/data/nc", profiles_path="/data/profiles.nc")
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ctdcast.processors import profiles as _profiles
from ctdcast.processors import stage1 as _stage1
from ctdcast.processors import stage2 as _stage2
from ctdcast.processors import stage3 as _stage3

Scope = Literal["cast", "cruise"]


@dataclass(frozen=True)
class Stage:
    """One pipeline stage.

    Attributes
    ----------
    name:
        Canonical stage name as used on the CLI and in log messages.
    number:
        Position for the numbered stages; ``None`` for named-only stages
        (e.g. ``"profiles"``). This is what makes ``stage=1`` resolvable
        and ``stage=4`` an error.
    scope:
        Whether the stage operates per-cast or per-cruise.
    run:
        Entry point.  Signature varies by stage — each stage's ``run()``
        takes explicit path arguments (e.g. ``cnv_dir`` + ``nc_dir`` for
        stage1; ``nc_dir`` alone for stage2/stage3; ``nc_dir`` +
        ``profiles_path`` for profiles), plus ``force``, ``dry_run``,
        ``cast_tags``, and stage-specific keyword arguments.
    """

    name: str
    number: int | None
    scope: Scope
    run: Callable


#: Pipeline stages in execution order.  Single source of truth for
#: :func:`process`, the CLI, and the re-run rule.
STAGES: tuple[Stage, ...] = (
    Stage("stage1", 1, "cast", _stage1.run),
    Stage("stage2", 2, "cast", _stage2.run),
    Stage("stage3", 3, "cast", _stage3.run),
    Stage("profiles", None, "cruise", _profiles.run),
)


def resolve_stage(stage: int | str) -> Stage:
    """Return the :class:`Stage` named or numbered by *stage*.

    Parameters
    ----------
    stage:
        ``1``, ``2``, ``3``; or a name — ``"stage1"``, ``"stage2"``,
        ``"stage3"``, ``"profiles"``.  Names are matched
        case-insensitively. Integers resolve only to numbered stages:
        ``"profiles"`` has no number, so ``4`` would be an error rather
        than a guess.

    Raises
    ------
    ValueError
        If *stage* matches no entry in :data:`STAGES`.  The message lists
        every valid value.
    """
    if stage is None:
        raise ValueError("stage must be a number or name, not None")
    for s in STAGES:
        if not isinstance(stage, bool) and (
            stage == s.number or (isinstance(stage, str) and stage.lower() == s.name)
        ):
            return s
    valid = ", ".join(
        [str(s.number) for s in STAGES if s.number is not None]
        + [repr(s.name) for s in STAGES]
    )
    raise ValueError(f"unknown stage {stage!r}; expected one of: {valid}")


def process(
    stage: int | str | None = None,
    *,
    cnv_dir: Path | str | None = None,
    nc_dir: Path | str | None = None,
    profiles_path: Path | str | None = None,
    force: bool = False,
    dry_run: bool = False,
    cast_tags: set[str] | None = None,
    **kw: object,
) -> object:
    """Run one pipeline stage, or every stage in order.

    Parameters
    ----------
    stage:
        Which stage to run — ``1``, ``2``, ``3``, or a name such as
        ``"stage1"`` or ``"profiles"``.  ``None`` (the default) runs all
        stages in :data:`STAGES` order.
    cnv_dir:
        Directory of raw SBE CNV files (required for stage 1).
    nc_dir:
        Directory of per-cast netCDF files (required for stages 1–3 and profiles).
    profiles_path:
        Output path for the compiled profiles netCDF (required for profiles stage).
    force:
        Re-run even when outputs already exist.
    dry_run:
        Print what would run without writing any files.
    cast_tags:
        If given, process only files whose stem contains one of the zero-padded
        3-digit cast numbers (e.g. ``{"042", "043"}``).  Ignored by the profiles stage.
    **kw:
        Forwarded to the chosen stage's ``run()`` function (e.g. ``backend``,
        ``near_surface_dbar``, ``cruise_cfg``, ``gebco_path``).

    Returns
    -------
    object
        The return value of the stage's ``run()`` for a single-stage call;
        a list of per-stage return values when *stage* is ``None``.
    """
    _cnv_dir = Path(cnv_dir) if cnv_dir is not None else None
    _nc_dir = Path(nc_dir) if nc_dir is not None else None
    _profiles_path = Path(profiles_path) if profiles_path is not None else None

    common = {"force": force, "dry_run": dry_run}

    def _run_stage(s: Stage) -> object:
        if s.name == "stage1":
            if _cnv_dir is None or _nc_dir is None:
                raise ValueError("stage1 requires cnv_dir and nc_dir.")
            return s.run(_cnv_dir, _nc_dir, cast_tags=cast_tags, **common, **kw)
        if s.name in ("stage2", "stage3"):
            if _nc_dir is None:
                raise ValueError(f"{s.name} requires nc_dir.")
            return s.run(_nc_dir, cast_tags=cast_tags, **common, **kw)
        if s.name == "profiles":
            if _nc_dir is None or _profiles_path is None:
                raise ValueError("profiles stage requires nc_dir and profiles_path.")
            return s.run(_nc_dir, _profiles_path, **common, **kw)
        raise ValueError(f"Unhandled stage: {s.name!r}")  # pragma: no cover

    if stage is None:
        return [_run_stage(s) for s in STAGES]
    return _run_stage(resolve_stage(stage))
