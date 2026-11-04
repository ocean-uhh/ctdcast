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

import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import xarray as xr

from ctdcast.identity import expand_cast_numbers
from ctdcast.processors import corrections as C
from ctdcast.processors.editing import (
    apply_loop_edit,
    apply_wild_edit,
    resolve_loop_edit,
    resolve_wild_edit,
)
from ctdcast.processors.filtering import (
    apply_filter,
    apply_window_filter,
    check_filter,
    check_window_filter,
)
from ctdcast.processors.history import append_history
from ctdcast.processors.products import check_binavg, check_products, check_split


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
        Scans an earlier Loop Edit marked, for a later Wild Edit's or Window Filter's
        ``exclude_flagged``.
    marked : dict
        ``{variable: mask}`` of values an earlier Wild Edit marked, which later filters leave out.
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
    marked: dict[str, np.ndarray] = field(default_factory=dict)
    changed: set[str] = field(default_factory=set)
    edge_masks: dict[str, np.ndarray] = field(default_factory=dict)
    applied: list[str] = field(default_factory=list)


def _apply_wildedit(ds: xr.Dataset, params: dict, ctx: StepContext) -> xr.Dataset:
    ds, marks = apply_wild_edit(
        ds, {"wildedit": params}, excluded=ctx.excluded, cast_label=ctx.cast_label
    )
    for var, mask in marks.items():
        ctx.marked[var] = ctx.marked.get(var, np.zeros(mask.size, dtype=bool)) | mask
    return ds


def _skip_reason(ds: xr.Dataset, module: str) -> str | None:
    """Why a scan-by-scan step cannot run on this cast, or None when it can."""
    interval, reason = C.native_interval(ds)
    if reason is not None or interval is None:
        return reason or "not at the native scan rate"
    header = C.header_from_raw_metadata(ds.attrs.get("raw_metadata")) or ""
    if module in C.applied_sbe_corrections(header)["modules"]:
        return f"Sea-Bird {module} already ran"
    return None


def _apply_filtering(
    name: str, module: str
) -> Callable[[xr.Dataset, dict, StepContext], xr.Dataset]:
    def run(ds: xr.Dataset, params: dict, ctx: StepContext) -> xr.Dataset:
        reason = _skip_reason(ds, module)
        if reason is not None:
            message = f"{name} skipped: {reason}"
            warnings.warn(f"cast {ctx.cast_label}: {message}", stacklevel=3)
            append_history(ds.attrs, message, stage="stage3")
            return ds
        if name == "filter":
            ds, done = apply_filter(ds, params, marked=ctx.marked)
        else:
            ds, done = apply_window_filter(
                ds, params, marked=ctx.marked, excluded=ctx.excluded
            )
        ctx.changed.update(done)
        return ds

    return run


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


def _apply_loopedit(ds: xr.Dataset, params: dict, ctx: StepContext) -> xr.Dataset:
    reason = _skip_reason(ds, "loopedit")
    if reason is not None:
        message = f"loopedit skipped: {reason}"
        warnings.warn(f"cast {ctx.cast_label}: {message}", stacklevel=3)
        append_history(ds.attrs, message, stage="stage3")
        return ds
    interval, _ = C.native_interval(ds)
    ds, mask = apply_loop_edit(
        ds, params, interval, excluded=ctx.excluded, cast_label=ctx.cast_label
    )
    ctx.excluded = mask if ctx.excluded is None else (ctx.excluded | mask)
    return ds


def _check_loopedit(params: Any, cast: int | None) -> None:  # noqa: ANN401, ARG001  # one signature for every check
    resolve_loop_edit(params)


def _check_filter(params: Any, cast: int | None) -> None:  # noqa: ANN401, ARG001  # one signature for every check
    check_filter(params)


def _check_window_filter(params: Any, cast: int | None) -> None:  # noqa: ANN401, ARG001  # one signature for every check
    check_window_filter(params)


def _check_split(params: Any, cast: int | None) -> None:  # noqa: ANN401, ARG001  # one signature for every check
    check_split(params)


def _check_binavg(params: Any, cast: int | None) -> None:  # noqa: ANN401, ARG001  # one signature for every check
    check_binavg(params)


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


#: Steps that change which scans there are: allowed only in ``data_processing.products``.
PRODUCT_ONLY = ("split", "binavg")

#: Every step ``data_processing.steps`` may list, in no particular order.
STEPS: dict[str, Step] = {
    s.name: s
    for s in (
        Step("wildedit", _apply_wildedit, _check_wildedit),
        Step("alignctd", _apply_correction("alignctd"), _check_alignctd),
        Step("celltm", _apply_correction("celltm"), _check_celltm),
        Step(
            "window_filter",
            _apply_filtering("window_filter", "wfilter"),
            _check_window_filter,
        ),
        Step("filter", _apply_filtering("filter", "filter"), _check_filter),
        Step("loopedit", _apply_loopedit, _check_loopedit),
        Step("split", None, _check_split),
        Step("binavg", None, _check_binavg),
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
    names = [
        n
        for n, _ in iter_steps(data_processing)
        if STEPS[n].apply is None and n not in PRODUCT_ONLY
    ]
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
    unknown = set(dp) - {
        "steps",
        "products",
        "slope_offset",
        "oxygen",
        "allow_unapplied",
    }
    if unknown:
        raise ValueError(f"data_processing: unknown key(s) {sorted(unknown)}")
    steps = iter_steps(dp)
    for i, (name, _params) in enumerate(steps):
        if name in PRODUCT_ONLY:
            raise ValueError(
                f"data_processing.steps[{i}]: {name} changes which scans there are; the "
                "stage-3 file keeps every scan, so put it in a product "
                "(data_processing.products)"
            )
    check_products(dp.get("products"))
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
