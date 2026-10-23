"""Tests for the vendored units layer and its ctdcast wiring.

The vendored module (:mod:`ctdcast.reports._vendored.units`) is the family source of truth:
``resolve_units`` (reader spelling -> canonical + factor), ``merge_tables`` (a package's view
over the defaults, with the redundant-override warning and the factor-conflict refusal), and
``format_units`` (the display label, resolving first so a foreign file's ``degC`` reads
``°C``).  ctdcast owns these tests because ctdcast ``main`` is the vendoring source.
"""

import ast
import sys
from pathlib import Path

import pytest

from ctdcast.reports import design
from ctdcast.reports._vendored import units as vu
from ctdcast.reports._vendored import units_tables as vt

# --- format_units: display labelling ---------------------------------------------------


def test_specials_are_whole_string_not_substring():
    """The ``degree`` special must not corrupt ``degrees_north`` / ``degree_Celsius``."""
    assert vu.format_units("degree") == "°"
    assert vu.format_units("degrees_north") == "°N"
    assert vu.format_units("degree_Celsius") == "°C"
    assert vu.format_units("percent") == "%"


def test_exponent_rule():
    """The single-denominator UDUNITS forms convert to the slash/superscript form."""
    assert vu.format_units("mS cm-1") == "mS/cm"
    assert vu.format_units("m s-1") == "m/s"
    assert vu.format_units("kg m-3") == "kg/m³"
    assert vu.format_units("umol kg-1") == "µmol/kg"
    assert vu.format_units("s-2") == "s⁻²"
    assert vu.format_units("dbar") == "dbar"
    assert vu.format_units("") == ""


def test_multi_denominator_superscripts_each_term():
    """A unit with two or more denominator terms superscripts in place, not a slash."""
    assert vu.format_units("umol m-2 s-1") == "µmol m⁻² s⁻¹"
    assert vu.format_units("W m-2 s-1") == "W m⁻² s⁻¹"
    assert vu.format_units("days since 1970-01-01") == "days since 1970-01-01"


def test_numerator_power_superscripted():
    """A power concatenated on a letter numerator token is superscripted."""
    assert vu.format_units("rad2 s-2") == "rad²/s²"
    assert vu.format_units("m2 s-1") == "m²/s"
    assert vu.format_units("m s-1") == "m/s"
    assert vu.format_units("mg m-3") == "mg/m³"


def test_standard_name_scale_labels():
    """Turbidity and dimensionless practical salinity key off standard_name."""
    assert vu.format_units("1", "sea_water_turbidity") == "NTU"
    assert vu.format_units("1", "sea_water_practical_salinity") == "PSU"
    assert vu.format_units("1") == "1"


def test_format_units_resolves_a_foreign_spelling_before_labelling():
    """A ``x1`` foreign spelling is labelled by its canonical; a factor != 1 keeps its own.

    ``degC`` on a file ctdcast did not write resolves to ``degree_Celsius`` and reads ``°C``;
    ``S/m`` is a factor != 1 of ``mS cm-1`` and must stay ``S/m`` — the values it labels have
    not been scaled, so relabelling them ``mS/cm`` would misstate the axis.
    """
    assert vu.format_units("degC") == "°C"
    assert vu.format_units("ITS-90, deg C") == "°C"
    assert vu.format_units("S/m", "sea_water_electrical_conductivity") == "S/m"


def test_overrides_win_through_a_merged_label():
    """A package label override reaches ``format_units`` through its ``tables``."""
    tables = vu.merge_tables(vu.DEFAULT_TABLES, labels={"m s-1": "m s⁻¹"})
    assert vu.format_units("m s-1", tables=tables) == "m s⁻¹"
    assert vu.format_units("m s-1") == "m/s"  # the family default is unchanged
    assert design.unit_label("m s-1") == "m/s"  # ctdcast overrides none


# --- resolve_units ---------------------------------------------------------------------


def test_resolve_each_family_alias_to_its_canonical_and_factor():
    """Every spelling in the vendored alias table resolves to its canonical and factor."""
    for canonical, group in vt.ALIASES.items():
        for spelling, factor in group.items():
            got_canonical, got_factor = vu.resolve_units(
                spelling, canonical=canonical, tables=vu.DEFAULT_TABLES
            )
            assert (got_canonical, got_factor) == (canonical, factor), spelling


def test_resolve_scoped_spelling_only_for_its_quantity():
    """PSU resolves on salinity, NTU on turbidity; each refused on the other."""
    assert vu.resolve_units("PSU", "sea_water_practical_salinity", canonical="1") == (
        "1",
        1.0,
    )
    assert vu.resolve_units("NTU", "sea_water_turbidity", canonical="1") == ("1", 1.0)
    with pytest.raises(vu.UnitsError, match="NTU"):
        vu.resolve_units("NTU", "sea_water_practical_salinity", canonical="1")


def test_resolve_plane_angle_degree_but_deg_stays_scoped():
    """degrees/° canonicalise to the plane-angle ``degree``; ``deg`` is lat/lon-only, not global."""
    assert vu.resolve_units("degrees", canonical="degree") == ("degree", 1.0)
    assert vu.resolve_units("°", canonical="degree") == ("degree", 1.0)
    # deg resolves on the lat/lon axes (scoped)...
    assert vu.resolve_units("deg", "latitude") == ("degrees_north", 1.0)
    assert vu.resolve_units("deg", "longitude") == ("degrees_east", 1.0)
    # ...but is refused on a plane-angle channel, where it would be ambiguous.
    with pytest.raises(vu.UnitsError, match="deg"):
        vu.resolve_units("deg", canonical="degree")


def test_resolve_unknown_spelling_names_string_and_canonical():
    """An unrecognised spelling raises, naming the string and the canonical."""
    with pytest.raises(vu.UnitsError, match=r"nonsense.*degree_Celsius"):
        vu.resolve_units("nonsense", canonical="degree_Celsius")


def test_resolve_empty_raises():
    """An empty units string cannot be resolved."""
    with pytest.raises(vu.UnitsError):
        vu.resolve_units("", canonical="dbar")


def test_resolve_recovers_canonical_for_display_without_a_hint():
    """With no canonical and no standard_name, a known alias still recovers its canonical."""
    assert vu.resolve_units("degC") == ("degree_Celsius", 1.0)
    assert vu.resolve_units("S/m") == ("mS cm-1", 10.0)
    # an entirely unknown string is its own canonical, factor 1 (a package-decided unit)
    assert vu.resolve_units("widgets") == ("widgets", 1.0)


def test_resolve_then_format_scales_and_labels_together():
    """The consumer composition: resolve gives the factor, format labels the canonical.

    For every factor != 1 alias in the family table, a read-only consumer scales the values by
    the factor and labels the canonical; ``format_units`` of the spelling alone stays
    conservative (labels the spelling, since it cannot scale the data it labels).
    """
    for canonical, group in vt.ALIASES.items():
        for spelling, factor in group.items():
            if factor == 1.0:
                continue
            got_canonical, got_factor = vu.resolve_units(spelling)
            assert (got_canonical, got_factor) == (canonical, factor)
            # label of the canonical is its display form; label of the spelling stays itself
            assert vu.format_units(spelling) == spelling


# --- merge_tables ----------------------------------------------------------------------


def test_merge_adds_a_new_canonical_alias_and_label():
    """A canonical / alias group / label the base lacks is added."""
    tables = vu.merge_tables(
        vu.DEFAULT_TABLES,
        canonical={"sverdrup": "sverdrup"},
        aliases={"V": {"volts": 1.0}},
        labels={"sverdrup": "Sv"},
    )
    assert tables.canonical["sverdrup"] == "sverdrup"
    assert tables.aliases["V"]["volts"] == 1.0
    assert tables.labels["sverdrup"] == "Sv"
    # the base is untouched
    assert "sverdrup" not in vu.DEFAULT_TABLES.canonical


def test_merge_accepts_a_different_canonical_as_a_deliberate_override():
    """A different canonical for a quantity the base has is an accepted override."""
    tables = vu.merge_tables(
        vu.DEFAULT_TABLES, canonical={"sea_water_practical_salinity": "1e-3"}
    )
    assert tables.canonical["sea_water_practical_salinity"] == "1e-3"


def test_merge_warns_on_a_redundant_override():
    """An override identical to the base is a no-op and warns, so it cannot shadow later."""
    with pytest.warns(UserWarning, match="redundant"):
        vu.merge_tables(
            vu.DEFAULT_TABLES, canonical={"sea_water_practical_salinity": "1"}
        )
    with pytest.warns(UserWarning, match="redundant"):
        vu.merge_tables(vu.DEFAULT_TABLES, labels={"percent": "%"})
    with pytest.warns(UserWarning, match="redundant"):
        vu.merge_tables(vu.DEFAULT_TABLES, aliases={"dbar": {"db": 1.0}})


def test_merge_raises_on_a_factor_conflict():
    """An alias factor that disagrees with the base is a bug, not a preference — it raises."""
    with pytest.raises(vu.UnitsError, match="factor conflict"):
        vu.merge_tables(vu.DEFAULT_TABLES, aliases={"mS cm-1": {"S/m": 1.0}})


# --- import purity ---------------------------------------------------------------------


def test_plot_modules_use_no_hardcoded_superscript_minus():
    """No plotting module hard-codes a ``⁻`` unit (e.g. ``m s⁻¹``)."""
    import ctdcast.plotters.plots as plots_mod
    import ctdcast.plotters.primitives as primitives_mod
    import ctdcast.reports._plots as rplots_mod

    offenders = [
        Path(mod.__file__).name
        for mod in (plots_mod, rplots_mod, primitives_mod)
        if "⁻" in Path(mod.__file__).read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"plotting modules hard-code a superscript-minus unit: {offenders}"
    )


@pytest.mark.parametrize("module", [vu, vt])
def test_import_purity_stdlib_only(module):
    """The vendored units modules import only the standard library and each other.

    Nothing here touches a dataset, so no numpy / xarray dependency — a display-only consumer
    (glidertest) carries the module with no third-party cost.  A sibling vendored module is
    reached by a relative import (``from . import ...``), which is package-name-neutral.
    """
    src = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    allowed = set(sys.stdlib_module_names)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders += [
                a.name for a in node.names if a.name.split(".")[0] not in allowed
            ]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            top = (node.module or "").split(".")[0]
            if top not in allowed:
                offenders.append(node.module)
    assert offenders == [], f"non-stdlib imports: {offenders}"
