"""ctdcast's owned report design: the package accent and the effective colormaps.

This is the single owned file that configures the vendored report layer for
ctdcast — the vendored modules under ``reports/_vendored/`` name no package.  The
package accent is applied to the shared CSS generator here, and the family
per-quantity colormap defaults are overridden with ctdcast's own science choices
and resolved to a concrete colormap name per variable.
"""

from __future__ import annotations

import warnings

from ctdcast.config import global_attrs as _global_attrs
from ctdcast.config.parameters import VARIABLES
from ctdcast.config.unit_tables import UNIT_LABEL_OVERRIDES, unit_label
from ctdcast.reports._vendored.css import _JS_SORT_TABLES, _JS_TOP_LINKS, emit_css
from ctdcast.reports._vendored.design_tokens import CMAPS as _FAMILY_CMAPS
from ctdcast.reports._vendored.design_tokens import (
    QUANTITY_BY_STANDARD_NAME,
    register_cmocean,
)
from ctdcast.reports._vendored.nc_tables import ATTR_GROUPS as _VENDORED_ATTR_GROUPS

#: ctdcast's package accent — chosen here, not in the vendored tokens.  Points at
#: ``--ocean`` so the accent (wordmark, table header, footer rule) is ocean navy;
#: change this one line to rebrand.  Any CSS colour value works.
PACKAGE_ACCENT: str = "var(--ocean)"

#: ctdcast's overrides on the vendored UI-token defaults — recolours a page role (nav pill +
#: masthead together, ``role-<key>``), the ``(_QC)`` marker (``qc-mark``), or ``package-accent``.
#: Empty: ctdcast keeps the family colours.  Each key must be an overridable token (an unknown key
#: raises in ``emit_css``); data palettes (QC flag colours, track colours, colormaps) are not here.
CSS_OVERRIDES: dict[str, str] = {}

#: The generated stylesheet, ready to concatenate into a page ``<style>`` block.
SHARED_CSS: str = emit_css(PACKAGE_ACCENT, overrides=CSS_OVERRIDES)

#: ctdcast turns the per-figure ``source:`` caption ON; the vendored default
#: (``design_tokens.SHOW_FIGURE_SOURCE``) is OFF.  This is the package override —
#: the same pattern as :data:`CMAP_OVERRIDES`: ctdcast's choice lives here, not in
#: the shared table.  The report env reads it as the ``show_source`` template global.
FIGURE_SOURCE: bool = True

#: ctdcast's own global-attribute names, added to the vendored canonical
#: :data:`~ctdcast.reports._vendored.nc_tables.ATTR_GROUPS` for the inventory page's
#: grouped-globals table.  Derived from the on-disk grouping in
#: :data:`ctdcast.config.global_attrs.ATTR_GROUPS` (the single source of truth for
#: ctdcast's own globals and their order) minus every name a named convention already
#: defines in the vendored groups — so the two cannot drift: adding a ctdcast global to
#: ``config.global_attrs`` makes it appear here, under the same group title, with no edit.
_VENDORED_ATTR_NAMES: frozenset[str] = frozenset(
    name for _title, names in _VENDORED_ATTR_GROUPS for name in names
)
ATTR_GROUP_EXTRAS: dict[str, tuple[str, ...]] = {
    title: tuple(n for n in names if n not in _VENDORED_ATTR_NAMES)
    for title, names in _global_attrs.ATTR_GROUPS
}

#: Tolerances for the inventory page's coverage check (file-stated ``geospatial_*`` /
#: ``time_coverage_*`` versus the values recomputed from the data): a |diff| above the
#: axis tolerance is flagged.  Owned here, not vendored — the vertical axis is dbar in
#: ctdcast and metres elsewhere, so the numbers are a per-package judgement.  Degrees for
#: lat/lon, dbar for vertical, seconds for time (second-truncated written stamps versus
#: sub-second data times would otherwise flag every cast).
COVERAGE_TOLERANCE: dict[str, float] = {
    "lat": 1e-3,
    "lon": 1e-3,
    "vertical": 1.0,
    "time": 1.0,
}

#: Per-table-kind column widths for the inventory page (``{"variables": [...], ...}``);
#: empty means the browser lays every table out.  Deferred until a column misbehaves.
TABLE_WIDTHS: dict[str, list[str]] = {}

#: Attribute names, in priority order, that record a variable's source name for the
#: ``original → name`` cell in the inventory tables.  ``original_name`` is the family-shared
#: spelling ctdcast writes now (CTD and LADCP alike); ``cnv_original_name`` (CNV) and
#: ``source_variable`` (LADCP) are the pre-0.4.0 spellings, read for older files.  The first
#: present and non-empty wins.
ORIGINAL_NAME_ATTRS: tuple[str, ...] = (
    "original_name",
    "cnv_original_name",
    "source_variable",
)

# ``unit_label`` and ``UNIT_LABEL_OVERRIDES`` live in :mod:`ctdcast.config.unit_tables` (which
# imports only the vendored units layer, so ``config.parameters.vlabel`` can route display
# units through the same ctdcast ``TABLES`` without the ``config`` ↔ ``reports.design`` import
# cycle).  They are re-exported here so this module's public surface (``design.unit_label`` /
# the inventory tables' display units) is unchanged.


def is_qc(name: str, _ds: object = None) -> bool:
    """Return whether *name* is a QC-companion variable (ctdcast's ``_qc`` suffix).

    The signature takes an optional dataset to match the vendored
    ``is_qc(name, ds)`` callable contract (some conventions need the dataset to
    decide); ctdcast's rule is purely the name suffix, so the dataset is unused.

    Parameters
    ----------
    name : str
        The variable name.
    _ds : object, optional
        The dataset, accepted for signature compatibility and unused.

    Returns
    -------
    bool
        ``True`` when *name* ends with ``_qc``.
    """
    return str(name).endswith("_qc")


def is_sensor(name: str) -> bool:
    """Return whether *name* is a sensor-catalog variable (``SENSOR_*``).

    The narrow catalog predicate: the uppercase ``SENSOR_*`` variables that carry a
    physical sensor's provenance.  The lowercase ``sensor_*`` linkage and channel
    variables are *not* catalog entries and are excluded from the science-variable
    table by a broader rule in :mod:`ctdcast.reports.dataset`.

    Parameters
    ----------
    name : str
        The variable name.

    Returns
    -------
    bool
        ``True`` when *name* starts with ``SENSOR_``.
    """
    return str(name).startswith("SENSOR_")


#: ctdcast's per-quantity colormap overrides on the vendored family defaults — its
#: current science choices.  Empty: ctdcast takes the vendored family defaults for
#: every quantity.  Add a ``quantity -> colormap`` entry here to override one for
#: ctdcast's science (e.g. a different density map for casts) without touching the
#: shared table; the key must be a quantity in the vendored CMAPS.
CMAP_OVERRIDES: dict[str, str] = {}

#: Effective per-quantity table: vendored family defaults, then ctdcast's overrides.
CMAPS: dict[str, str] = {**_FAMILY_CMAPS, **CMAP_OVERRIDES}


def cmap_for(var: str, default: str | None = None) -> str:
    """Return the colormap name for a variable, resolved through the design layers.

    The registry's ``"cmap"`` is used directly when it is a literal colormap and
    resolved through :data:`CMAPS` when it names a quantity — ``CMAPS.get(spec,
    spec)`` does both.  A variable with no explicit ``"cmap"`` is bridged by its CF
    ``standard_name`` through
    :data:`~ctdcast.reports._vendored.design_tokens.QUANTITY_BY_STANDARD_NAME`.  A
    ``cmo.*`` result triggers :func:`~ctdcast.reports._vendored.design_tokens.register_cmocean`
    so the name resolves in matplotlib.

    Parameters
    ----------
    var : str
        A variable name in :data:`~ctdcast.config.parameters.VARIABLES`.
    default : str or None, optional
        Colormap to fall back to when *var* resolves to no colormap.  When given
        (the report path, e.g. ``"viridis"``), the fallback is returned with a
        warning naming the variable — a registry gap should not stop a report.
        When ``None`` (the default), an unresolvable variable raises instead —
        the strict path a config-file validator uses to reject a bad name at load.

    Returns
    -------
    str
        The resolved colormap name, or *default* for an unresolvable variable.

    Raises
    ------
    KeyError
        If *var* resolves to no colormap and *default* is ``None``.
    """
    entry = VARIABLES.get(var, {})
    spec = entry.get("cmap")
    if spec is not None:
        name = CMAPS.get(spec, spec)
    else:
        quantity = QUANTITY_BY_STANDARD_NAME.get(entry.get("standard_name"))
        if quantity is not None:
            name = CMAPS[quantity]
        elif default is not None:
            warnings.warn(
                f"no colormap for variable {var!r}; using {default!r}",
                stacklevel=2,
            )
            return default
        else:
            raise KeyError(
                f"no colormap for variable {var!r}: no 'cmap' and no mapped standard_name"
            )
    if name.startswith("cmo."):
        register_cmocean()
    return name


#: Resolved ``variable -> colormap name`` table, the default for
#: :attr:`ctdcast.config.report_config.ReportConfig.var_cmaps`.  Built over the
#: variables that carry a ``"cmap"`` today, so it has the same keys as before this
#: change; its values are the vendored family defaults (ctdcast overrides none).
VAR_CMAPS: dict[str, str] = {
    var: cmap_for(var) for var, v in VARIABLES.items() if v.get("cmap") is not None
}

__all__ = [
    "ATTR_GROUP_EXTRAS",
    "CMAPS",
    "CMAP_OVERRIDES",
    "COVERAGE_TOLERANCE",
    "FIGURE_SOURCE",
    "PACKAGE_ACCENT",
    "SHARED_CSS",
    "CSS_OVERRIDES",
    "ORIGINAL_NAME_ATTRS",
    "TABLE_WIDTHS",
    "UNIT_LABEL_OVERRIDES",
    "VAR_CMAPS",
    "_JS_SORT_TABLES",
    "_JS_TOP_LINKS",
    "cmap_for",
    "is_qc",
    "is_sensor",
    "unit_label",
]
