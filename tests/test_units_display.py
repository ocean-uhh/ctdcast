"""Tests for the vendored units display layer and its ctdcast wiring.

The pin test ties the registry's ``label_units`` column to the derived
:func:`ctdcast.reports.design.unit_label` so the two cannot drift; the
exact-match test guards the whole-string specials; the purity test keeps the
vendored module package-neutral.
"""

import ast
import sys
from pathlib import Path

from ctdcast.config.parameters import VARIABLES
from ctdcast.reports import design
from ctdcast.reports._vendored import units_display as ud


def test_label_units_column_equals_derived_label():
    """Every registry ``label_units`` equals ``unit_label(units, standard_name)``.

    U, V and N2 are label *corrections* on this branch (``m s⁻¹`` → ``m/s`` and
    ``s⁻²`` → ``rad²/s²``), not pins of a prior value; they are included here
    because the corrected column now matches the derived form.
    """
    mismatches = []
    for name, entry in VARIABLES.items():
        label = entry.get("label_units")
        if label is None:
            continue
        derived = design.unit_label(entry.get("units", ""), entry.get("standard_name"))
        if derived != label:
            mismatches.append((name, entry.get("units"), label, derived))
    assert mismatches == [], f"label_units drifted from unit_label: {mismatches}"


def test_specials_are_whole_string_not_substring():
    """The ``degree`` special must not corrupt ``degrees_north`` / ``degree_Celsius``."""
    assert ud.format_units("degree") == "°"
    assert ud.format_units("degrees_north") == "°N"
    assert ud.format_units("degree_Celsius") == "°C"
    assert ud.format_units("percent") == "%"


def test_exponent_rule():
    """The single-denominator UDUNITS forms convert to the slash/superscript form."""
    assert ud.format_units("mS cm-1") == "mS/cm"
    assert ud.format_units("m s-1") == "m/s"
    assert ud.format_units("kg m-3") == "kg/m³"
    assert ud.format_units("umol kg-1") == "µmol/kg"
    assert ud.format_units("s-2") == "s⁻²"
    assert ud.format_units("dbar") == "dbar"
    assert ud.format_units("") == ""


def test_multi_denominator_superscripts_each_term():
    """A unit with two or more denominator terms has no X/Y form — superscript in place.

    ``umol m-2 s-1`` (the PAR/SPAR units) used to half-convert to ``µmol m-2/s``; it must
    now render every term's exponent, and a ``since`` time encoding is left untouched.
    """
    assert ud.format_units("umol m-2 s-1") == "µmol m⁻² s⁻¹"
    assert ud.format_units("W m-2 s-1") == "W m⁻² s⁻¹"
    assert ud.format_units("days since 1970-01-01") == "days since 1970-01-01"


def test_numerator_power_superscripted():
    """A power written concatenated on a letter numerator token is superscripted.

    The same rule applied to numerator and denominator; a bare letter or number is
    untouched so ``m s-1`` stays ``m/s``.
    """
    assert ud.format_units("rad2 s-2") == "rad²/s²"
    assert ud.format_units("m2 s-1") == "m²/s"
    assert ud.format_units("m s-1") == "m/s"
    assert ud.format_units("mg m-3") == "mg/m³"


def test_standard_name_scale_labels():
    """Turbidity and dimensionless practical salinity key off standard_name."""
    assert ud.format_units("1", "sea_water_turbidity") == "NTU"
    assert ud.format_units("1", "sea_water_practical_salinity") == "PSU"
    assert ud.format_units("1") == "1"


def test_overrides_win():
    """A package override for the exact units string is consulted first."""
    assert ud.format_units("m s-1", overrides={"m s-1": "m s⁻¹"}) == "m s⁻¹"
    assert design.unit_label("m s-1") == "m/s"  # ctdcast overrides none


def test_plot_modules_use_no_hardcoded_superscript_minus():
    """No plotting module hard-codes a ``⁻`` unit (e.g. ``m s⁻¹``).

    The LADCP velocity axes had regressed to ``m s⁻¹`` because they were string
    literals that never passed through the registry, so they did not follow the
    ``m/s`` display rule.  Every unit label now comes from ``vlabel``/``vunit``
    (hence ``format_units``); this greps the plotting source so a new literal
    superscript-minus unit is caught before it reaches a figure.
    """
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


def test_import_purity_package_neutral():
    """units_display imports only the standard library (no numpy/xarray needed)."""
    src = Path(ud.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    allowed_top = set(sys.stdlib_module_names) | {"numpy", "xarray"}
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders += [
                a.name for a in node.names if a.name.split(".")[0] not in allowed_top
            ]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            top = (node.module or "").split(".")[0]
            if top not in allowed_top:
                offenders.append(node.module)
    assert offenders == [], f"non-neutral imports: {offenders}"
