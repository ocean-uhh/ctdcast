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

from ctdcast.processors import ladcp as _ladcp
from ctdcast.processors import profiles as _profiles
from ctdcast.processors import stage1 as _stage1
from ctdcast.processors import stage2 as _stage2
from ctdcast.processors import stage3 as _stage3

Scope = Literal["cast", "cruise"]


@dataclass(frozen=True)
class StagePaths:
    """The full set of pipeline input/output paths, as resolved from config.

    A single value threaded to every stage's normalised ``run`` so each stage
    can pick the paths for whichever sources are configured (CTD, LADCP, …) and
    ignore the rest.  Sources are inferred from which paths are present: a
    ``None`` path means that source is not configured and its half of a stage is
    silently skipped.
    """

    cnv_dir: Path | None = None
    ctd_root: Path | None = None
    ladcp_dir: Path | None = None
    ladcp_root: Path | None = None
    #: Set only when the config names a compiled product explicitly; ``None``
    #: means "derive it from the root", which is the normal case.
    profiles_override: Path | None = None
    ladcp_profiles_override: Path | None = None

    @property
    def profiles_path(self) -> Path | None:
        """Compiled CTD product: the explicit override, else ``<ctd_root>/profiles.nc``."""
        if self.profiles_override is not None:
            return self.profiles_override
        return self.ctd_root / "profiles.nc" if self.ctd_root else None

    @property
    def ladcp_profiles_path(self) -> Path | None:
        """Compiled LADCP product: override, else ``<ladcp_root>/ladcp_profiles.nc``."""
        if self.ladcp_profiles_override is not None:
            return self.ladcp_profiles_override
        return self.ladcp_root / "ladcp_profiles.nc" if self.ladcp_root else None

    @classmethod
    def from_config(cls, data: dict) -> "StagePaths":
        """Resolve a config ``data:`` block, applying the flat-layout shim.

        The one place the ``nc_dir`` → ``ctd_root`` compatibility rule lives, so
        no caller decides it twice.  A config predating the stage layout names
        ``nc_dir``/``ladcp_nc``; those become the roots directly, and
        :mod:`ctdcast.processors.stage_paths` recognises the unsuffixed files
        under them as stage 1 — flatness is a *naming* variant, so it is detected
        where naming lives rather than carried as a flag.

        Parameters
        ----------
        data : dict
            The config's ``data:`` mapping.

        Returns
        -------
        StagePaths
            Paths for whichever sources are configured; ``None`` for the rest.
        """

        def _p(*keys: str) -> Path | None:
            for k in keys:
                if data.get(k):
                    return Path(str(data[k]))
            return None

        return cls(
            cnv_dir=_p("cnv_dir"),
            ctd_root=_p("ctd_root", "nc_dir"),
            ladcp_dir=_p("ladcp_dir"),
            ladcp_root=_p("ladcp_root", "ladcp_nc"),
            profiles_override=_p("profiles_nc"),
            ladcp_profiles_override=_p("ladcp_profiles_nc"),
        )


@dataclass(frozen=True)
class Stage:
    """One pipeline stage — a row in the :data:`STAGES` single source of truth.

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
        Normalised entry point with the uniform signature
        ``run(paths: StagePaths, *, force, dry_run, cast_tags, **kw) -> object``.
        The wrapper fans out over every configured source for that stage and
        names only the tuning kwargs it uses (swallowing the rest via ``**_kw``),
        so :func:`process` and the CLI dispatch identically for every stage.
    """

    name: str
    number: int | None
    scope: Scope
    run: Callable


# ---------------------------------------------------------------------------
# Normalised stage wrappers — one per stage token.  Each takes the uniform
# ``(paths, *, force, dry_run, cast_tags, **kw)`` signature, fans out over the
# sources configured in *paths*, and names only the tuning kwargs it needs.
# This is what lets the registry store a single callable per stage and dispatch
# without any per-stage branching (mirrors oceanarray's normalised wrappers).
# ---------------------------------------------------------------------------


def _run_stage1(
    paths: StagePaths,
    *,
    force: bool = False,
    dry_run: bool = False,
    cast_tags: set[str] | None = None,
    backend: str = "seasenselib",
    pattern: str = "*.cnv",
    ladcp_pattern: str | None = None,
    **_kw: object,
) -> int:
    """Ingest raw files → per-cast netCDF for every configured source (CTD + LADCP)."""
    total = 0
    if paths.cnv_dir is not None and paths.ctd_root is not None:
        total += (
            _stage1.run(
                paths.cnv_dir,
                paths.ctd_root,
                force=force,
                dry_run=dry_run,
                cast_tags=cast_tags,
                backend=backend,
                pattern=pattern,
            )
            or 0
        )
    if paths.ladcp_dir is not None and paths.ladcp_root is not None:
        total += (
            _ladcp.run_convert(
                paths.ladcp_dir,
                paths.ladcp_root,
                force=force,
                dry_run=dry_run,
                cast_tags=cast_tags,
                ladcp_pattern=ladcp_pattern,
            )
            or 0
        )
    return total


def _run_stage2(
    paths: StagePaths,
    *,
    force: bool = False,
    dry_run: bool = False,
    cast_tags: set[str] | None = None,
    **kw: object,
) -> int:
    """Apply soak/deck flagging to per-cast CTD netCDF (LADCP has no stage 2)."""
    if paths.ctd_root is None:
        return 0
    # stage2.run filters kw to its own accepted keys, so forwarding the full
    # tuning bag is safe here.
    return (
        _stage2.run(
            paths.ctd_root,
            force=force,
            dry_run=dry_run,
            cast_tags=cast_tags,
            **kw,
        )
        or 0
    )


def _run_stage3(
    paths: StagePaths,
    *,
    force: bool = False,
    dry_run: bool = False,
    cast_tags: set[str] | None = None,
    cruise_cfg: dict | None = None,
    **_kw: object,
) -> int:
    """Apply QC + calibration to per-cast CTD netCDF (LADCP has no stage 3)."""
    if paths.ctd_root is None:
        return 0
    return (
        _stage3.run(
            paths.ctd_root,
            force=force,
            dry_run=dry_run,
            cast_tags=cast_tags,
            cruise_cfg=cruise_cfg,
        )
        or 0
    )


def _run_profiles(
    paths: StagePaths,
    *,
    force: bool = False,
    dry_run: bool = False,
    gebco_path: Path | None = None,
    profiles_dbar: int = 1,
    sensor_overrides: object = None,
    cruise_info: dict | None = None,
    **_kw: object,
) -> bool:
    """Compile per-cast netCDF → gridded products for every configured source.

    Builds ``profiles.nc`` (CTD) and/or ``ladcp_profiles.nc`` (LADCP), returning
    True if any product was written.  ``cruise_info`` (the config ``cruise_info:``
    block) supplies the cruise id, discovery metadata, people, embargo, and the
    ship/date from which the EXPOCODE is derived; it is threaded to both builders.
    """
    wrote = False
    if paths.ctd_root is not None and paths.profiles_path is not None:
        wrote = (
            bool(
                _profiles.run(
                    paths.ctd_root,
                    paths.profiles_path,
                    force=force,
                    dry_run=dry_run,
                    gebco_path=gebco_path,
                    dbar=profiles_dbar,
                    sensor_overrides=sensor_overrides,
                    cruise_info=cruise_info,
                )
            )
            or wrote
        )
    if paths.ladcp_root is not None and paths.ladcp_profiles_path is not None:
        wrote = (
            bool(
                _ladcp.run_compile(
                    paths.ladcp_root,
                    paths.ladcp_profiles_path,
                    force=force,
                    dry_run=dry_run,
                    cruise_info=cruise_info,
                )
            )
            or wrote
        )
    return wrote


#: Pipeline stages in execution order.  **Single source of truth** for
#: :func:`process`, the CLI (``--stage`` choices, help, dispatch), and the
#: re-run rule.  Adding a stage — a new CTD step, a cruise-level export, another
#: source — is one row here; everything user-facing derives from this tuple.
#: Each stage fans out over all configured sources inside its ``run`` wrapper,
#: so there is no per-source token: ``--stage 1`` ingests CTD *and* LADCP,
#: ``--stage profiles`` compiles both.
STAGES: tuple[Stage, ...] = (
    Stage("stage1", 1, "cast", _run_stage1),
    Stage("stage2", 2, "cast", _run_stage2),
    Stage("stage3", 3, "cast", _run_stage3),
    Stage("profiles", None, "cruise", _run_profiles),
)


def resolve_stage(stage: int | str) -> Stage:
    """Return the :class:`Stage` named or numbered by *stage*.

    Parameters
    ----------
    stage:
        ``1``, ``2``, ``3``; or a name — ``"stage1"``, ``"stage2"``,
        ``"stage3"``, ``"profiles"``.  Names are matched case-insensitively.
        Numeric strings (``"1"``) resolve as the number.  Integers resolve only
        to numbered stages: ``"profiles"`` has no number, so ``4`` is an error
        rather than a guess.

    Raises
    ------
    ValueError
        If *stage* matches no entry in :data:`STAGES`.  The message lists
        every valid value.
    """
    if stage is None:
        raise ValueError("stage must be a number or name, not None")
    # The CLI passes stage numbers as strings ("1"); accept those as the number.
    key: int | str = int(stage) if isinstance(stage, str) and stage.isdigit() else stage
    for s in STAGES:
        # Guard bool before int: True == 1, so without this resolve_stage(True)
        # would silently return stage1.
        if not isinstance(key, bool) and (
            key == s.number or (isinstance(key, str) and key.lower() == s.name)
        ):
            return s
    valid = ", ".join(
        [str(s.number) for s in STAGES if s.number is not None]
        + [repr(s.name) for s in STAGES]
    )
    raise ValueError(f"unknown stage {stage!r}; expected one of: {valid}")


def stages_for(stage: int | str | list[int | str] | None) -> tuple[Stage, ...]:
    """Resolve *stage* into the stages to run, always in :data:`STAGES` order.

    ``None`` → every stage.  A list/tuple → that subset (deduplicated, canonical
    order regardless of the order requested).  A scalar → that one stage.
    """
    if stage is None:
        return STAGES
    if isinstance(stage, (list, tuple)):
        requested = {resolve_stage(s) for s in stage}
        return tuple(s for s in STAGES if s in requested)
    return (resolve_stage(stage),)


def process(
    stage: int | str | list[int | str] | None = None,
    *,
    cnv_dir: Path | str | None = None,
    ctd_root: Path | str | None = None,
    ladcp_dir: Path | str | None = None,
    ladcp_root: Path | str | None = None,
    # Superseded by the roots above; still accepted so an existing caller keeps
    # working until it migrates (see .claude/stage-files-plan.md §12).
    nc_dir: Path | str | None = None,
    profiles_path: Path | str | None = None,
    ladcp_nc_dir: Path | str | None = None,
    ladcp_profiles_path: Path | str | None = None,
    force: bool = False,
    dry_run: bool = False,
    cast_tags: set[str] | None = None,
    **kw: object,
) -> object:
    """Run one or more pipeline stages across every configured source.

    A stage runs for whichever sources are configured: with both CTD and LADCP
    paths supplied, ``stage="stage1"`` ingests both, and ``stage="profiles"``
    compiles both.  A source whose paths are absent is silently skipped, so a
    cruise without LADCP is not an error.

    Parameters
    ----------
    stage:
        Which stage(s) to run — ``1``, ``2``, ``3``, a name such as ``"stage1"``
        or ``"profiles"``, or a list of these.  A list runs its subset in
        :data:`STAGES` order regardless of the order requested.  ``None`` (the
        default) runs every stage in order.
    cnv_dir, ctd_root:
        CTD pipeline paths.  ``cnv_dir`` is the external CNV input; ``ctd_root``
        is the directory ctdcast owns, holding ``stage1/`` … ``stage3/`` and the
        compiled product.  Present → CTD participates in the relevant stages.
    ladcp_dir, ladcp_root:
        LADCP equivalents.  Present → LADCP participates in stage 1 (convert)
        and ``profiles`` (compile).
    nc_dir, profiles_path, ladcp_nc_dir, ladcp_profiles_path:
        Superseded.  ``nc_dir``/``ladcp_nc_dir`` are read as the roots when the
        root arguments are absent, and the two product paths as explicit
        overrides of the derived ones.  Accepted so an existing caller keeps
        working; prefer the roots.
    force:
        Re-run even when outputs already exist.
    dry_run:
        Print what would run without writing any files.
    cast_tags:
        If given, process only files whose stem contains one of the zero-padded
        cast numbers (e.g. ``{"042", "043"}``).  Cruise-scope stages ignore it.
    **kw:
        Tuning forwarded to the stage wrappers (e.g. ``backend``, ``pattern``,
        ``near_surface_dbar``, ``cruise_cfg``, ``gebco_path``, ``ladcp_pattern``).
        Each wrapper names the kwargs it uses and ignores the rest.

    Returns
    -------
    object
        A list of per-stage return values when *stage* is ``None`` or a list;
        the single stage's return value for a scalar *stage*.
    """
    # Routed through `from_config` so the root-vs-legacy precedence is decided in
    # exactly one place, whether the caller is the CLI reading YAML or Python
    # passing kwargs.
    paths = StagePaths.from_config(
        {
            "cnv_dir": cnv_dir,
            "ctd_root": ctd_root,
            "nc_dir": nc_dir,
            "ladcp_dir": ladcp_dir,
            "ladcp_root": ladcp_root,
            "ladcp_nc": ladcp_nc_dir,
            "profiles_nc": profiles_path,
            "ladcp_profiles_nc": ladcp_profiles_path,
        }
    )

    results = [
        s.run(paths, force=force, dry_run=dry_run, cast_tags=cast_tags, **kw)
        for s in stages_for(stage)
    ]
    if stage is None or isinstance(stage, (list, tuple)):
        return results
    return results[0]
