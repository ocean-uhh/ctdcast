"""Guard the colormap adoption: resolving through the layers changes no colormap.

The vendored ``design_tokens.CMAPS`` carries the family default per quantity, the
owned ``reports/design.py`` overrides it with ctdcast's current science choices
(seeded so this change is pixel-identical), and ``cmap_for`` resolves each
variable.  These tests pin that every variable that has a colormap today resolves
to exactly the same colormap name, and that nothing resolves to nothing.
"""

from ctdcast.config.parameters import VARIABLES
from ctdcast.reports._vendored.design_tokens import CMAPS as _FAMILY
from ctdcast.reports.design import CMAP_OVERRIDES, VAR_CMAPS, cmap_for

#: The colormap name each variable carried before the quantity indirection — the
#: names that must survive adoption unchanged.
_ORIGINAL = {
    "ctd_temperature_1": "RdYlBu_r",
    "ctd_temperature_2": "RdYlBu_r",
    "ctd_temperature": "RdYlBu_r",
    "ctd_salinity_1": "YlGnBu_r",
    "ctd_salinity_2": "YlGnBu_r",
    "ctd_salinity": "YlGnBu_r",
    "ctd_oxygen_1": "RdYlGn",
    "ctd_oxygen_2": "RdYlGn",
    "ctd_oxygen": "RdYlGn",
    "oxygen_saturation": "RdYlGn",
    "ctd_fluor": "YlGn",
    "ctd_turbidity": "YlOrBr",
    "conservative_temperature": "RdYlBu_r",
    "absolute_salinity": "YlGnBu_r",
    "sigma0": "Purples",
    "AOU": "RdBu_r",
}


def test_resolved_table_matches_the_original_names_exactly():
    """VAR_CMAPS resolves to the same keys and names as before the change."""
    assert VAR_CMAPS == _ORIGINAL


def test_cmap_for_resolves_each_variable_to_its_original_name():
    """Adoption moves no pixel: every variable resolves to today's colormap."""
    for var, expected in _ORIGINAL.items():
        assert cmap_for(var) == expected, f"{var}: {cmap_for(var)!r} != {expected!r}"


def test_no_cmap_variable_resolves_to_nothing():
    """Every registry variable with a colormap resolves — a gap raises, not skips."""
    for var, entry in VARIABLES.items():
        if entry.get("cmap") is not None:
            cmap_for(var)  # raises KeyError (loud) if unresolvable — no viridis default


def test_overrides_are_a_subset_of_the_vendored_quantities():
    """A typo in CMAP_OVERRIDES must not invent a quantity."""
    assert set(CMAP_OVERRIDES) <= set(_FAMILY), (
        f"override keys not in vendored CMAPS: {set(CMAP_OVERRIDES) - set(_FAMILY)}"
    )
