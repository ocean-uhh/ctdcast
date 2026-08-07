"""CTD processing pipeline — all stages in execution order.

``STAGES`` is the single source of truth for :func:`process`, the CLI, and
the re-run rule.  Each :class:`Stage` carries the stage name, an optional
position number (for the numbered stages), the scope (per-cast or
per-cruise), and a ``run`` callable that accepts
``(proc_dir, *, force=False, **kw)``.

Usage::

    import ctdcast
    ctdcast.process(stage=1, proc_dir="/data/cruise/")
    ctdcast.process(stage="profiles", proc_dir="/data/cruise/")
    ctdcast.process(proc_dir="/data/cruise/")    # run all stages in order
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
        Entry point: ``run(proc_dir, *, force=False, **kw)``.
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
    proc_dir: Path | str,
    force: bool = False,
    **kw: object,
) -> object:
    """Run one pipeline stage, or every stage in order.

    Parameters
    ----------
    stage:
        Which stage to run — ``1``, ``2``, ``3``, or a name such as
        ``"stage1"`` or ``"profiles"``. ``None`` (the default) runs all
        stages in :data:`STAGES` order.
    proc_dir:
        Base processing directory.  Each stage reads from and writes to
        conventional sub-paths under this directory (e.g. ``nc/``,
        ``profiles.nc``).
    force:
        Re-run even when outputs already exist.
    **kw:
        Forwarded to the chosen stage's ``run()`` function.

    Returns
    -------
    object
        The return value of the stage's ``run()`` for a single-stage call;
        a list of per-stage return values when *stage* is ``None``.
    """
    proc_dir = Path(proc_dir)
    if stage is None:
        return [s.run(proc_dir, force=force, **kw) for s in STAGES]
    return resolve_stage(stage).run(proc_dir, force=force, **kw)
