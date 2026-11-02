"""The processing steps ``data_processing.steps`` may list: one table, used by stage 3 and the checks.

Each :class:`Step` names a Sea-Bird module, says whether stage 3 applies it yet, how it is
applied, and how its parameters are checked before any cast is processed.  :data:`STEPS` is the
single list: adding a step is one row here; stage 3, :func:`iter_steps` and
:func:`validate_data_processing` all read it.

A step listed in the config but not yet applied is refused unless the config says
``allow_unapplied: true`` beside ``steps``: the steps after it would otherwise run on data the
config meant to be changed first, and the stage-3 file would look complete.  With the switch, the
step is skipped, named in a warning, in ``history`` and in the file's ``data_processing_steps``
attribute.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import xarray as xr

from ctdcast.identity import expand_cast_numbers
from ctdcast.processors import corrections as C
from ctdcast.processors.editing import apply_wild_edit, resolve_wild_edit


@dataclass
class StepContext:
    """What one cast's steps share as they run, in order.

    Attributes
    ----------
    cast_number : int or None
        The cast's number, for per-cast-range values.
    cast_label : str
        How the cast is named in warnings.
    excluded : numpy.ndarray or None
        Scans an earlier Loop Edit marked, for a later Wild Edit's ``exclude_flagged``.
    changed : set of str
        Variables whose values a step changed.
    edge_masks : dict
        ``{variable: mask}`` of scans an alignment set NaN.
    applied : list of str
        What ran, in order, one entry per step (``"filter (not applied)"`` for one skipped).
    """

    cast_number: int | None = None
    cast_label: str = "?"
    excluded: np.ndarray | None = None
    changed: set[str] = field(default_factory=set)
    edge_masks: dict[str, np.ndarray] = field(default_factory=dict)
    applied: list[str] = field(default_factory=list)


def _apply_wildedit(ds: xr.Dataset, params: dict, ctx: StepContext) -> xr.Dataset:
    ds, _marks = apply_wild_edit(
        ds, {"wildedit": params}, excluded=ctx.excluded, cast_label=ctx.cast_label
    )
    return ds


def _apply_correction(
    name: str,
) -> Callable[[xr.Dataset, dict, StepContext], xr.Dataset]:
    def run(ds: xr.Dataset, params: dict, ctx: StepContext) -> xr.Dataset:
        ds, record = C.apply_corrections(
            ds, {name: params}, ctx.cast_number, cast_label=ctx.cast_label
        )
        ctx.changed.update(record.changed)
        ctx.edge_masks.update(record.edge_masks)
        return ds

    return run


def _ranges_casts(params: Any) -> set[int]:  # noqa: ANN401  # a config value of any shape
    """Every cast number named in a ``ranges:`` anywhere in a step's parameters."""
    found: set[int] = set()
    if isinstance(params, dict):
        for rng in params.get("ranges") or []:
            if isinstance(rng, dict) and "casts" in rng:
                found.update(expand_cast_numbers(rng["casts"]))
        for value in params.values():
            found |= _ranges_casts(value)
    return found


def _check_alignctd(params: dict, cast: int | None) -> None:
    for var in C._ALIGN_TARGETS:
        C.resolve_alignment({"alignctd": params}, var, cast)


def _check_celltm(params: dict, cast: int | None) -> None:
    for var in ("conductivity_1", "conductivity_2"):
        C.resolve_cell_thermal_mass({"celltm": params}, var, cast)


def _check_wildedit(params: dict, cast: int | None) -> None:  # noqa: ARG001  # one signature for every check
    resolve_wild_edit({"wildedit": params})


def _check_mapping(params: Any, cast: int | None) -> None:  # noqa: ANN401, ARG001  # not applied yet: shape only
    if not isinstance(params, dict):
        raise ValueError(f"expected a mapping of parameters, got {params!r}")


@dataclass(frozen=True)
class Step:
    """One processing step stage 3 knows.

    Attributes
    ----------
    name : str
        The step's name in ``data_processing.steps``, as Sea-Bird names the module.
    apply : callable or None
        ``apply(ds, params, ctx) -> ds``; None while stage 3 does not apply it yet.
    check : callable
        ``check(params, cast)``: raises ValueError on a malformed entry for that cast.
    """

    name: str
    apply: Callable[[xr.Dataset, dict, StepContext], xr.Dataset] | None
    check: Callable[[Any, int | None], None]


#: Every step ``data_processing.steps`` may list, in no particular order.
STEPS: dict[str, Step] = {
    s.name: s
    for s in (
        Step("wildedit", _apply_wildedit, _check_wildedit),
        Step("alignctd", _apply_correction("alignctd"), _check_alignctd),
        Step("celltm", _apply_correction("celltm"), _check_celltm),
        Step("window_filter", None, _check_mapping),
        Step("filter", None, _check_mapping),
        Step("loopedit", None, _check_mapping),
        Step("split", None, _check_mapping),
        Step("binavg", None, _check_mapping),
    )
}


def iter_steps(data_processing: dict | None) -> list[tuple[str, dict]]:
    """Return ``data_processing.steps`` as ``(name, parameters)`` pairs, in order.

    Parameters
    ----------
    data_processing : dict or None
        The ``data_processing:`` config block.

    Returns
    -------
    list of (str, dict)
        One pair per entry; a step may appear more than once.

    Raises
    ------
    ValueError
        When an entry is not a one-key mapping or names an unknown step.
    """
    steps = (data_processing or {}).get("steps") or []
    if not isinstance(steps, list):
        raise ValueError(f"data_processing.steps: expected a list, got {steps!r}")
    out = []
    for i, entry in enumerate(steps):
        if not isinstance(entry, dict) or len(entry) != 1:
            raise ValueError(
                f"data_processing.steps[{i}]: expected one step name with its parameters, "
                f"got {entry!r}"
            )
        ((name, params),) = entry.items()
        if name not in STEPS:
            raise ValueError(
                f"data_processing.steps[{i}]: unknown step {name!r}; use one of {sorted(STEPS)}"
            )
        out.append((name, params if params is not None else {}))
    return out


def unapplied(data_processing: dict | None) -> list[str]:
    """Return the listed steps stage 3 does not apply yet, in order, each once.

    Parameters
    ----------
    data_processing : dict or None
        The ``data_processing:`` config block.

    Returns
    -------
    list of str
        Step names.
    """
    names = [n for n, _ in iter_steps(data_processing) if STEPS[n].apply is None]
    return list(dict.fromkeys(names))


def validate_data_processing(data_processing: dict | None) -> None:
    """Check the ``data_processing:`` block before any cast is processed.

    Every step's values are resolved for the default and for every cast named in a range, so a
    typo or a non-numeric value fails once, up front.  A listed step stage 3 does not apply yet
    is refused unless ``allow_unapplied: true``.

    Parameters
    ----------
    data_processing : dict or None
        The ``data_processing:`` config block.

    Raises
    ------
    ValueError
        On the first malformed entry, naming it; or on a step not yet applied, without
        ``allow_unapplied``.
    """
    dp = data_processing or {}
    unknown = set(dp) - {"steps", "slope_offset", "oxygen", "allow_unapplied"}
    if unknown:
        raise ValueError(f"data_processing: unknown key(s) {sorted(unknown)}")
    steps = iter_steps(dp)
    casts: set[int | None] = {None} | _ranges_casts(dp.get("slope_offset"))
    for _name, params in steps:
        casts |= _ranges_casts(params)
    for i, (name, params) in enumerate(steps):
        for cast in sorted(casts, key=lambda c: -1 if c is None else c):
            try:
                STEPS[name].check(params, cast)
            except ValueError as exc:
                raise ValueError(f"data_processing.steps[{i}] {name}: {exc}") from exc
    for cast in casts:
        for var in ("conductivity_1", "conductivity_2"):
            C.resolve_slope_offset(dp.get("slope_offset"), var, cast)
    C.resolve_oxygen_window(dp)
    pending = unapplied(dp)
    if pending and dp.get("allow_unapplied") is not True:
        raise ValueError(
            f"data_processing.steps lists {', '.join(pending)}, which stage 3 does not apply "
            "yet; the steps after it would run on data it was meant to change first. Remove it, "
            "or set data_processing.allow_unapplied: true to run without it."
        )
