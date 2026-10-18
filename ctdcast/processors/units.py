"""Canonicalise variable units at each processing boundary.

The units *knowledge* — which spelling is canonical per quantity, which reader spellings
convert to it and with what factor — is the shared family data in
:mod:`ctdcast.reports._vendored.units_tables`, read through
:func:`ctdcast.reports._vendored.units.resolve_units`; ctdcast's view of it, with its own
additions, is :data:`ctdcast.config.unit_tables.TABLES`.  This module holds only the transform that
applies it, :func:`to_canonical_units` — a loop over ``resolve_units`` run at the netCDF write
boundary (every stage persists through the writer, so each stage's output is canonicalised).
Every written file carries one canonical spelling per quantity, a factor ``≠ 1`` spelling has
its values converted, and an unrecognised spelling stops the run loudly rather than being
silently overwritten.

The display spelling (``mS cm-1`` → ``mS/cm``) is a separate concern, derived from the
canonical string by :func:`ctdcast.config.unit_tables.unit_label`; it is never stored.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import numpy as np

from ctdcast.config import parameters as params
from ctdcast.config.unit_tables import TABLES, registry_standard_names
from ctdcast.reports._vendored.units import UnitsError, resolve_units

if TYPE_CHECKING:
    from collections.abc import Callable

    import xarray as xr

    from ctdcast.reports._vendored.units import Tables

# Re-exported so existing callers keep importing it from the processing layer.
__all__ = ["UnitsError", "to_canonical_units"]


def to_canonical_units(
    ds: xr.Dataset,
    *,
    tables: Tables = TABLES,
    registry: dict[str, str] | None = None,
    log_fn: Callable[[str], None] | None = None,
    stage: int | str | None = None,
) -> xr.Dataset:
    """Rewrite each registered variable's units to its canonical spelling.

    The canonical for a variable is its registry ``units`` when the variable is registered
    (known by name, which works before the writer stamps ``standard_name`` on the dataset),
    else the canonical for its CF ``standard_name``.  The current ``units`` string is resolved
    against that canonical's accepted group (the canonical ``×1`` plus the family aliases plus
    the scoped spellings for the quantity); a factor ``≠ 1`` match multiplies the values and
    drops any stale integer packing, a pure spelling rewrite leaves the values untouched.  The
    conversion is *not* stamped on the variable — a factor ``≠ 1`` is reported through *log_fn*
    at the boundary.  Temperature variables additionally get the CF-1.11
    ``units_metadata = "temperature: on_scale"``.

    A registered variable with *no* units attribute has its canonical filled from the registry
    (ctdcast derives composites and carries channels whose units are supplied at the write
    boundary, not by the reader) — a fill, not a conversion.  The pass is idempotent — a
    variable already carrying its canonical string is left unchanged — so it runs at every
    write without double-converting (stage 2/3 re-read an already-canonical stage-1 file).
    Unregistered engineering variables (no registry entry and no matching ``standard_name``)
    are left untouched.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset to canonicalise in place (also returned).
    tables : Tables, optional
        The units view to resolve against; defaults to :data:`ctdcast.config.unit_tables.TABLES`.
    registry : dict of str to str, optional
        ``{variable name: standard_name}`` map; defaults to
        :func:`ctdcast.config.unit_tables.registry_standard_names`.  Used to find a variable's
        ``standard_name`` (for the scoped spellings) before the writer stamps it on the
        dataset.
    log_fn : callable, optional
        Called with one message per variable whose units string changed.
    stage : int or str, optional
        Processing stage, used only to annotate the log and error messages.

    Returns
    -------
    xarray.Dataset
        The same dataset, with canonical units on every registered variable.

    Raises
    ------
    UnitsError
        If a registered variable carries a units string that is *present* but is not a
        recognised spelling of its canonical.  The pass never guesses or silently passes an
        unknown unit through; a missing units attribute is filled (see above), not raised.
    """
    if registry is None:
        registry = registry_standard_names()
    for var in list(ds.variables):
        canonical = (
            params.VARIABLES[var].get("units") if var in params.VARIABLES else None
        )
        standard_name = ds[var].attrs.get("standard_name") or registry.get(var)
        if canonical is None and standard_name:
            canonical = tables.canonical.get(standard_name)
        if canonical is None:
            continue  # unregistered engineering channel — left untouched
        current = str(ds[var].attrs.get("units", "")).strip()
        where = f" (stage {stage})" if stage is not None else ""
        if not current:
            # Registered variable with no units: fill the canonical from the registry.  ctdcast
            # derives composites and carries channels whose units are supplied at the write
            # boundary, not by the reader, so a missing units attribute is normal here — a
            # fill, not a conversion.  A *present* unrecognised spelling is still refused below.
            ds[var].attrs["units"] = canonical
        elif current != canonical:
            try:
                resolved, factor = resolve_units(
                    current, standard_name, tables=tables, canonical=canonical
                )
            except UnitsError as exc:
                raise UnitsError(f"{var!r}{where}: {exc}") from exc
            if factor != 1.0:
                converted = ds[var].copy(
                    data=np.asarray(ds[var].values, dtype=float) * factor
                )
                # The value scale changed, so any integer packing carried from the reader is no
                # longer valid; drop it and let the writer re-encode.
                for key in ("dtype", "scale_factor", "add_offset"):
                    converted.encoding.pop(key, None)
                ds[var] = converted
                # A factor != 1 scales the values; announce it (never silent — provenance) even
                # when no log_fn is wired, so the one caller that passes none (the writer) still
                # surfaces the conversion.  Not stamped on the variable (branch ruling).
                warnings.warn(
                    f"{var!r}: values scaled x{factor:g} converting units "
                    f"{current!r} -> {resolved!r}{where}.",
                    stacklevel=2,
                )
            attrs = dict(ds[var].attrs)
            attrs["units"] = resolved
            ds[var].attrs = attrs
            if log_fn:
                log_fn(f"  {var}: {current} -> {resolved} (x{factor:g}){where}")
        # CF 1.11: mark the temperature scale so a reader can tell a scale value from a
        # difference.  Applied at every boundary like the units string itself.
        if canonical == "degree_Celsius":
            ds[var].attrs["units_metadata"] = "temperature: on_scale"
    return ds
