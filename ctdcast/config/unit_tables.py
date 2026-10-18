"""ctdcast's view of the family units tables.

The one place ctdcast speaks about units.  Three override dicts are folded over the vendored
family defaults (:data:`ctdcast.reports._vendored.units.DEFAULT_TABLES`) into :data:`TABLES`,
which every call site takes; :func:`unit_label` is the display entry point and
:func:`registry_standard_names` the ``{variable name: standard_name}`` map the storage pass
needs before CF attributes are stamped.

An override entry identical to the family default is a no-op and ``merge_tables`` warns about
it, so a restatement cannot silently shadow a later change to the base — hence the two
override dicts here are empty with a commented example showing the shape, and only the real
additions (ctdcast's ``volts``/``seconds`` engineering spellings) are live.

Module-level imports here are the vendored layer only; ``parameters`` is imported inside
:func:`registry_standard_names` (it does not exist yet while it is importing this module), so
this module is the leaf that lets ``parameters`` import :func:`unit_label` without a cycle.
"""

from __future__ import annotations

import functools
import os

from ctdcast.reports._vendored.units import (
    DEFAULT_TABLES,
    Tables,
    format_units,
    merge_tables,
)

#: Debug aid for a visual regen check: when the environment variable
#: ``CTDCAST_UNIT_LABEL_DEBUG`` is set, :func:`unit_label` appends a ``*`` to every non-empty
#: display label, so a report regenerated with it set shows at a glance which plot axes,
#: colorbar titles and captions route through the units layer (all of them should).  Off by
#: default, so normal builds and the test suite are unaffected.
_DEBUG_STAR = bool(os.environ.get("CTDCAST_UNIT_LABEL_DEBUG"))

#: Stored-spelling overrides, keyed by CF ``standard_name``.  Empty: ctdcast writes CF/CCHDO
#: spellings, which are the family defaults.  A package that writes a different convention
#: overrides here — e.g. a seaglider/OG1 package storing practical salinity as ``1e-3``:
#:
#:     CANONICAL_UNIT_OVERRIDES = {"sea_water_practical_salinity": "1e-3"}
#:
#: A live entry that restates the family default is a no-op and warns, so leave it empty.
CANONICAL_UNIT_OVERRIDES: dict[str, str] = {}

#: Extra reader spellings the family table lacks, keyed by canonical spelling, each evidenced.
#: These are ctdcast's engineering-channel spellings (not in the family baseline because they
#: are specific to the SBE channels ctdcast keeps); a spelling with a factor other than ``1``
#: would be a conversion and belongs in the vendored table after review, never here.
UNIT_ALIAS_EXTRAS: dict[str, dict[str, float]] = {
    # ctdcast cnv/mixsed2_004.cnv:44 sbeox0V: Oxygen raw [V] — seasenselib emits "volts"
    "V": {"volts": 1.0},
    # ctdcast cnv/mixsed2_004.cnv timeS: elapsed time — seasenselib emits "seconds"
    "s": {"seconds": 1.0},
}

#: Display-label overrides, keyed by units string.  Empty: ctdcast takes the family label for
#: every unit.  Add an entry to pin a ctdcast-specific label the family rule does not produce:
#:
#:     UNIT_LABEL_OVERRIDES = {"percent": "%sat"}
#:
#: A live entry that restates the family label is a no-op and warns, so leave it empty.
UNIT_LABEL_OVERRIDES: dict[str, str] = {}

#: ctdcast's resolved view: the family defaults with the overrides above folded in.  Every
#: call site (``unit_label``, the storage pass, ``vlabel``/``vunit``) takes this.
TABLES: Tables = merge_tables(
    DEFAULT_TABLES,
    canonical=CANONICAL_UNIT_OVERRIDES,
    aliases=UNIT_ALIAS_EXTRAS,
    labels=UNIT_LABEL_OVERRIDES,
)


@functools.cache
def registry_standard_names() -> dict[str, str]:
    """Return the ``{variable name: standard_name}`` map from the variable registry.

    The storage pass needs each variable's CF ``standard_name`` to resolve a scoped spelling
    (``PSU`` is salinity-only) and to canonicalise before the writer stamps ``standard_name``
    on the dataset.  Cached after the first call — ``VARIABLES`` is a module-level literal that
    is never mutated at runtime (``load_display_config`` returns a merged copy), and
    :func:`to_canonical_units` calls this once per write.  :mod:`ctdcast.config.parameters` is
    imported inside the function, not at module level, because ``parameters`` imports
    :func:`unit_label` from this module and its ``VARIABLES`` does not exist yet while this
    module is loading.

    Returns
    -------
    dict of str to str
        Variable name mapped to its CF ``standard_name``, for every registry entry that
        declares one.
    """
    from ctdcast.config import parameters as params

    return {
        name: entry["standard_name"]
        for name, entry in params.VARIABLES.items()
        if entry.get("standard_name")
    }


def unit_label(units: str, standard_name: str | None = None) -> str:
    """Return the display label for a units string, with ctdcast's overrides applied.

    The single display-unit entry point: :func:`ctdcast.reports._vendored.units.format_units`
    against ctdcast's :data:`TABLES`, so an override in this module reaches both the plot axes
    (via :func:`ctdcast.config.parameters.vlabel` / :func:`~ctdcast.config.parameters.vunit`)
    and the owned report-design layer that re-exports this.

    Parameters
    ----------
    units : str
        CF/UDUNITS units string (e.g. ``"mS cm-1"``).
    standard_name : str or None, optional
        CF standard name, for the dimensionless turbidity / salinity labels.

    Returns
    -------
    str
        The display units string; ``""`` when *units* is empty.
    """
    label = format_units(units, standard_name, tables=TABLES)
    if label and _DEBUG_STAR:
        return f"{label}*"
    return label
