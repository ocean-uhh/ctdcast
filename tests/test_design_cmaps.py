"""Pin the per-variable colormap resolution through the design layers.

The vendored ``design_tokens.CMAPS`` carries the family default per quantity, the
owned ``reports/design.py`` may override it (``CMAP_OVERRIDES`` — empty for
ctdcast, which takes the family defaults), and ``cmap_for`` resolves each
variable.  These tests pin the resolved colormap name per variable and that
nothing resolves to nothing.
"""

from ctdcast.config.parameters import VARIABLES
from ctdcast.reports._vendored.design_tokens import CMAPS as _FAMILY
from ctdcast.reports.design import CMAP_OVERRIDES, VAR_CMAPS, cmap_for

#: The colormap each variable resolves to.  ctdcast overrides nothing, so these
#: are the vendored family defaults (temperature ``RdYlBu_r``, salinity
#: ``YlGnBu_r``, density ``BuPu``, oxygen ``cmo.oxy``, oxygen saturation ``BrBG``,
#: chlorophyll ``YlGn``, turbidity ``YlOrBr``); ``AOU`` keeps its literal
#: ``RdBu_r`` (no family quantity).
_EXPECTED = {
    "ctd_temperature_1": "RdYlBu_r",
    "ctd_temperature_2": "RdYlBu_r",
    "ctd_temperature": "RdYlBu_r",
    "ctd_salinity_1": "YlGnBu_r",
    "ctd_salinity_2": "YlGnBu_r",
    "ctd_salinity": "YlGnBu_r",
    "ctd_oxygen_1": "cmo.oxy",
    "ctd_oxygen_2": "cmo.oxy",
    "ctd_oxygen": "cmo.oxy",
    "oxygen_saturation": "BrBG",
    "ctd_fluor": "YlGn",
    "ctd_turbidity": "YlOrBr",
    "conservative_temperature": "RdYlBu_r",
    "absolute_salinity": "YlGnBu_r",
    "sigma0": "BuPu",
    "AOU": "RdBu_r",
}


def test_resolved_table_matches_expected_names_exactly():
    """VAR_CMAPS resolves each variable to the expected (family-default) colormap."""
    assert VAR_CMAPS == _EXPECTED


def test_cmap_for_resolves_each_variable_to_its_expected_name():
    """Every variable resolves through the layers to the expected colormap name."""
    for var, expected in _EXPECTED.items():
        assert cmap_for(var) == expected, f"{var}: {cmap_for(var)!r} != {expected!r}"


def test_no_cmap_variable_resolves_to_nothing():
    """Every registry variable with a colormap resolves — a gap raises, not skips."""
    for var, entry in VARIABLES.items():
        if entry.get("cmap") is not None:
            cmap_for(var)  # raises KeyError (loud) if unresolvable — no viridis default


def test_overrides_are_a_subset_of_the_vendored_quantities():
    """Any CMAP_OVERRIDES key must be a vendored quantity (a typo cannot invent one)."""
    assert set(CMAP_OVERRIDES) <= set(_FAMILY), (
        f"override keys not in vendored CMAPS: {set(CMAP_OVERRIDES) - set(_FAMILY)}"
    )
