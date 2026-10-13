"""ctdcast's owned report design: the package accent and the effective colormaps.

This is the single owned file that configures the vendored report layer for
ctdcast — the vendored modules under ``reports/_vendored/`` name no package.  The
package accent is applied to the shared CSS generator here, and the family
per-quantity colormap defaults are overridden with ctdcast's own science choices
and resolved to a concrete colormap name per variable.
"""

from __future__ import annotations

import warnings

from ctdcast.config.parameters import VARIABLES
from ctdcast.reports._vendored.css import _JS_TOP_LINKS, emit_css
from ctdcast.reports._vendored.design_tokens import CMAPS as _FAMILY_CMAPS
from ctdcast.reports._vendored.design_tokens import (
    QUANTITY_BY_STANDARD_NAME,
    register_cmocean,
)

#: ctdcast's package accent — chosen here, not in the vendored tokens.  Points at
#: ``--ocean`` so the accent (wordmark, table header, footer rule) is ocean navy;
#: change this one line to rebrand.  Any CSS colour value works.
PACKAGE_ACCENT: str = "var(--ocean)"

#: The generated stylesheet, ready to concatenate into a page ``<style>`` block.
SHARED_CSS: str = emit_css(PACKAGE_ACCENT)

#: ctdcast turns the per-figure ``source:`` caption ON; the vendored default
#: (``design_tokens.SHOW_FIGURE_SOURCE``) is OFF.  This is the package override —
#: the same pattern as :data:`CMAP_OVERRIDES`: ctdcast's choice lives here, not in
#: the shared table.  The report env reads it as the ``show_source`` template global.
FIGURE_SOURCE: bool = True

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
    "CMAPS",
    "CMAP_OVERRIDES",
    "FIGURE_SOURCE",
    "PACKAGE_ACCENT",
    "SHARED_CSS",
    "VAR_CMAPS",
    "_JS_TOP_LINKS",
    "cmap_for",
]
