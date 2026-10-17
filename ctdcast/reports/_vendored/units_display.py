"""Shared units display layer — the CF/UDUNITS ``units`` string to a plot label.

This module is written to be **vendored** across the packages that share the
report design system.  It is package-neutral — it names no package and holds only
data plus one pure transform — so the copies can be frozen and checked against
``MANIFEST.txt``.  Its data lives here as Python (not a ``.yaml`` file) so the
module stays importable with no third-party dependency, the same choice as
:mod:`design_tokens`; the import-purity test guards it.

One function, :func:`format_units`, turns the stored ``units`` string (and the
optional CF ``standard_name``) into the display form used on plot axes and in the
report tables: the UDUNITS exponent spelling ``X Y-n`` becomes the slash form
``X/Yⁿ``, a handful of whole-string specials map to their symbol, and two
dimensionless scales key off ``standard_name``.  A package layers its own label
choices on top through the ``overrides`` argument; the package never edits this
file.
"""

from __future__ import annotations

import re

#: Digits 0-9 mapped to their Unicode superscripts, for the exponent rule.
_SUPERSCRIPT_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")

#: Whole-string unit spellings that map to a fixed display symbol.  Matched
#: exactly (not as a substring) so ``degree`` cannot corrupt ``degrees_north`` or
#: ``degree_Celsius`` — those have their own entries and are matched first.
SPECIALS: dict[str, str] = {
    "degree_Celsius": "°C",  # origin: oceanarray format_units _DISPLAY_SPECIALS
    "degrees_north": "°N",  # origin: oceanarray format_units _DISPLAY_SPECIALS
    "degrees_east": "°E",  # origin: oceanarray format_units _DISPLAY_SPECIALS
    "percent": "%",  # origin: ctdcast registry label_units (oxygen_saturation)
    "degree": "°",  # origin: ctdcast registry label_units (Turner)
}

#: CF ``standard_name`` → fixed scale label, consulted before the units string.
#: Turbidity is a scale label on any units; practical salinity labels a
#: dimensionless (``"1"``) quantity.
BY_STANDARD_NAME: dict[str, str] = {
    "sea_water_turbidity": "NTU",  # origin: oceanarray format_units
    "sea_water_practical_salinity": "PSU",  # origin: oceanarray format_units (units == "1")
}

#: Substring token substitutions applied before the exponent rule.
TOKENS: dict[str, str] = {
    "umol": "µmol",  # origin: oceanarray format_units
}


def format_units(
    units: str, standard_name: str | None = None, *, overrides: dict[str, str] | None = None
) -> str:
    """Return the display label for a CF/UDUNITS ``units`` string.

    Resolution order: a package *override* for the exact units string, then the
    ``standard_name`` scale labels, then the whole-string :data:`SPECIALS`, then
    the token substitutions and the exponent rule.  The exponent rule converts a
    single-denominator UDUNITS term — ``X Y-1`` → ``X/Y``, ``X Y-n`` → ``X/Yⁿ``,
    a bare ``Y-n`` → ``Y⁻ⁿ`` — and superscripts a trailing power written
    concatenated on a letter numerator token (``rad2 s-2`` → ``rad²/s²``); this
    covers every unit the family writes, and a string the rule does not match is
    returned unchanged.

    Parameters
    ----------
    units : str
        CF/UDUNITS units string (e.g. ``"mS cm-1"``).  An empty string returns
        ``""``.
    standard_name : str or None, optional
        CF standard name, used for the dimensionless turbidity / practical
        salinity labels.
    overrides : dict of str to str, optional
        A package's exact-units-string → label map, checked first; the one place
        a package pins a label that differs from the family default.

    Returns
    -------
    str
        The display units string; ``""`` when *units* is empty.
    """
    if not units:
        return ""
    if overrides and units in overrides:
        return overrides[units]
    if standard_name == "sea_water_turbidity":
        return BY_STANDARD_NAME[standard_name]
    if units == "1":
        return BY_STANDARD_NAME.get(standard_name or "", "1")
    if units in SPECIALS:
        return SPECIALS[units]
    s = units
    for token, display in TOKENS.items():
        s = s.replace(token, display)
    m = re.match(r"^(?:(.+?)\s+)?(\S+?)-(\d+)$", s)
    if not m:
        return s
    num, den, exp = m.group(1), m.group(2), m.group(3)
    # A positive power is written concatenated in UDUNITS (`rad2` = rad²), so superscript a
    # trailing single digit on a letter-only numerator token — the same rule the denominator
    # exponent gets.  Restricted to `[A-Za-z]+[2-9]` so a bare number or `m` is untouched.
    if num and re.fullmatch(r"[A-Za-z]+[2-9]", num):
        num = num[:-1] + num[-1].translate(_SUPERSCRIPT_DIGITS)
    if num:
        return (
            f"{num}/{den}"
            if exp == "1"
            else f"{num}/{den}{exp.translate(_SUPERSCRIPT_DIGITS)}"
        )
    return f"{den}⁻{exp.translate(_SUPERSCRIPT_DIGITS)}"
