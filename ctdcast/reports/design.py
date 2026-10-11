"""ctdcast's owned report design: the package accent and the effective colormaps.

This is the single owned file that configures the vendored report layer for
ctdcast — the vendored modules under ``reports/_vendored/`` name no package.  The
package accent is applied to the shared CSS generator here, and the family
per-quantity colormap defaults are overridden with ctdcast's own science choices
and resolved to a concrete colormap name per variable.
"""

from __future__ import annotations

from ctdcast.config.parameters import VARIABLES
from ctdcast.reports._vendored.css import _JS_TOP_LINKS, emit_css
from ctdcast.reports._vendored.design_tokens import CMAPS as _FAMILY_CMAPS
from ctdcast.reports._vendored.design_tokens import QUANTITY_BY_STANDARD_NAME

#: ctdcast's package accent — chosen here, not in the vendored tokens.  Points at
#: ``--ocean`` so the accent (wordmark, table header, footer rule) is ocean navy;
#: change this one line to rebrand.  Any CSS colour value works.
PACKAGE_ACCENT: str = "var(--ocean)"

#: The generated stylesheet, ready to concatenate into a page ``<style>`` block.
SHARED_CSS: str = emit_css(PACKAGE_ACCENT)

#: ctdcast's per-quantity colormap overrides on the vendored family defaults — its
#: current science choices, kept so this change moves no pixel.  Removing an entry
#: lets that quantity fall through to the family default; that visible step is a
#: later commit, not this one.
CMAP_OVERRIDES: dict[str, str] = {
    "temperature": "RdYlBu_r",
    "salinity": "YlGnBu_r",
    "density": "Purples",
    "oxygen": "RdYlGn",
    "oxygen_saturation": "RdYlGn",
    "chlorophyll": "YlGn",
    "turbidity": "YlOrBr",
}

#: Effective per-quantity table: vendored family defaults, then ctdcast's overrides.
CMAPS: dict[str, str] = {**_FAMILY_CMAPS, **CMAP_OVERRIDES}


def cmap_for(var: str) -> str:
    """Return the colormap name for a variable, resolved through the design layers.

    The registry's ``"cmap"`` is used directly when it is a literal colormap and
    resolved through :data:`CMAPS` when it names a quantity — ``CMAPS.get(spec,
    spec)`` does both.  A variable with no explicit ``"cmap"`` is bridged by its CF
    ``standard_name`` through
    :data:`~ctdcast.reports._vendored.design_tokens.QUANTITY_BY_STANDARD_NAME`.

    Parameters
    ----------
    var : str
        A variable name in :data:`~ctdcast.config.parameters.VARIABLES`.

    Returns
    -------
    str
        The resolved colormap name.

    Raises
    ------
    KeyError
        If the variable has neither an explicit colormap nor a standard name that
        maps to a quantity — a science variable with no colormap is a registry
        gap, never a silent default.
    """
    entry = VARIABLES.get(var, {})
    spec = entry.get("cmap")
    if spec is not None:
        return CMAPS.get(spec, spec)
    quantity = QUANTITY_BY_STANDARD_NAME.get(entry.get("standard_name"))
    if quantity is not None:
        return CMAPS[quantity]
    raise KeyError(
        f"no colormap for variable {var!r}: no 'cmap' and no mapped standard_name"
    )


#: Resolved ``variable -> colormap name`` table, the default for
#: :attr:`ctdcast.config.report_config.ReportConfig.var_cmaps`.  Built over the
#: variables that carry a ``"cmap"`` today, so it has the same keys as before this
#: change and — via the seeded overrides — the same values.
VAR_CMAPS: dict[str, str] = {
    var: cmap_for(var) for var, v in VARIABLES.items() if v.get("cmap") is not None
}

__all__ = [
    "CMAPS",
    "CMAP_OVERRIDES",
    "PACKAGE_ACCENT",
    "SHARED_CSS",
    "VAR_CMAPS",
    "_JS_TOP_LINKS",
    "cmap_for",
]
