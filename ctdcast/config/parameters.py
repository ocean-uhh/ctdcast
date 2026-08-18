"""Package-wide constants: plotting parameters, CNV aliases, variable metadata, CCHDO conventions.

Compile-time constants only — the per-run display settings (GEBCO path,
clean_spines, figsizes, map bounds, colormap overrides) live in the frozen
:class:`ctdcast.config.report_config.ReportConfig`, built once and threaded down.

Section headers mark what kind of constant each block holds, because that determines
who may change it and what breaks when they do:

  Contract  — changing it makes output wrong or non-conformant.
              Requires a code review and a version bump.
  Science   — changing it gives a different but equally valid answer.
              Per-cruise overrides go in ``display.variables:`` in the cruise
              ``config.yaml``; use :func:`ctdcast.config.loader.load_display_config`.
  Derived   — computed from another constant; must live here to avoid drift.
  Deferred  — belongs in ``oceanvis`` once that package exists.

"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xarray as xr

# ---------------------------------------------------------------------------
# Sentinel values  [Contract — changing breaks output provenance]
# ---------------------------------------------------------------------------
# Fallback cruise identifier used in report titles and metadata when the netCDF
# attributes contain no ``cruise`` key and no cruise_id is supplied via
# cruise_info.  "UNK" is deliberately conspicuous so mislabelled output is
# obvious rather than plausible.
UNKNOWN_CRUISE_ID: str = "UNKCRUISE"

# Zero-padding width for cast-number tags used in filename filtering.
# Filenames are expected to embed a zero-padded 3-digit cast number (e.g.
# "mixsed2_042.nc").  Adjust only if your naming convention uses a different
# width; keeping it here avoids the constant being hardcoded in 4 different
# places across the processors and CLI.
CAST_TAG_WIDTH: int = 3

# Slot widths, section aspect constants, and other presentation tokens now live
# in the vendored, package-neutral ``config/report_tokens.py`` (spec §11/§14).
# This file holds only scientific/variable metadata.

# ---------------------------------------------------------------------------
# Variable metadata  [Science — vmin/vmax/cmap are per-cruise science choices]
# ---------------------------------------------------------------------------
# Internal variable name → CF metadata and display defaults.
#
# standard_name: CF 1.8 canonical. null when none exists.
# units: CF canonical spelling (degree_Celsius, not degC; S m-1, not S/m).
# reference_scale: only where non-trivial (ITS-90, PSS-78, TEOS-10).
# cmap: matplotlib colormap; null when no standard section/profile orientation.
# vmin/vmax: soft default axis limits — per-cruise science choices, override freely
#   via display.variables: in cruise config.yaml (see load_display_config).
#   null means cast-dependent or sensor-dependent; plotter clips to data range.
#
# To override for a cruise, add to config.yaml:
#   display:
#     variables:
#       ctd_temperature_1:
#         vmin: 4
#         vmax: 25
VARIABLES: dict[str, dict] = {
    "pressure": {
        "label": "Pressure",
        "label_units": "dbar",
        "long_name": "Sea pressure",
        "units": "dbar",
        "standard_name": "sea_water_pressure",
        "cmap": None,
        "vmin": 0,
        "vmax": None,
    },
    "latitude": {
        "label": "Latitude",
        "label_units": "°N",
        "long_name": "Latitude",
        "units": "degrees_north",
        "standard_name": "latitude",
        "cmap": None,
        "vmin": None,
        "vmax": None,
    },
    "longitude": {
        "label": "Longitude",
        "label_units": "°E",
        "long_name": "Longitude",
        "units": "degrees_east",
        "standard_name": "longitude",
        "cmap": None,
        "vmin": None,
        "vmax": None,
    },
    "ctd_temperature_1": {
        "label": "$T_1$",
        "label_units": "°C",
        "long_name": "In-situ temperature (primary)",
        "units": "degree_Celsius",
        "standard_name": "sea_water_temperature",
        "reference_scale": "ITS-90",
        "cmap": "RdYlBu_r",
        "vmin": -2,
        "vmax": 20,
    },
    "ctd_temperature_2": {
        "label": "$T_2$",
        "label_units": "°C",
        "long_name": "In-situ temperature (secondary)",
        "units": "degree_Celsius",
        "standard_name": "sea_water_temperature",
        "reference_scale": "ITS-90",
        "cmap": "RdYlBu_r",
        "vmin": -2,
        "vmax": 20,
    },
    # Best-sensor composite: copy of ctd_temperature_1 or ctd_temperature_2, whichever
    # is set as preferred in config.yaml. Which sensor is in attrs["preferred_sensor"].
    # Created by stage3 when preferred_temperature_sensor is configured; absent otherwise.
    "ctd_temperature": {
        "label": "T",
        "label_units": "°C",
        "long_name": "In-situ temperature (preferred sensor)",
        "units": "degree_Celsius",
        "standard_name": "sea_water_temperature",
        "reference_scale": "ITS-90",
        "cmap": "RdYlBu_r",
        "vmin": -2,
        "vmax": 20,
    },
    "conductivity_1": {
        "label": "$C_1$",
        "label_units": "mS cm⁻¹",
        "long_name": "Conductivity (primary)",
        "units": "mS cm-1",
        "standard_name": "sea_water_electrical_conductivity",
        "cmap": None,
        "vmin": None,
        "vmax": None,
    },
    "conductivity_2": {
        "label": "$C_2$",
        "label_units": "mS cm⁻¹",
        "long_name": "Conductivity (secondary)",
        "units": "mS cm-1",
        "standard_name": "sea_water_electrical_conductivity",
        "cmap": None,
        "vmin": None,
        "vmax": None,
    },
    "ctd_salinity_1": {
        "label": "$S_{P1}$",
        "label_units": "PSU",
        "long_name": "Practical salinity (primary)",
        "units": "1",  # PSS-78 is dimensionless per CF
        "standard_name": "sea_water_practical_salinity",
        "reference_scale": "PSS-78",
        "cmap": "YlGnBu_r",
        "vmin": 34.0,
        "vmax": 35.5,
    },
    "ctd_salinity_2": {
        "label": "$S_{P2}$",
        "label_units": "PSU",
        "long_name": "Practical salinity (secondary)",
        "units": "1",
        "standard_name": "sea_water_practical_salinity",
        "reference_scale": "PSS-78",
        "cmap": "YlGnBu_r",
        "vmin": 34.0,
        "vmax": 35.5,
    },
    # ctd_salinity: preferred sensor composite — see ctd_temperature note above.
    "ctd_salinity": {
        "label": "SP",
        "label_units": "PSU",
        "long_name": "Practical salinity (preferred sensor)",
        "units": "1",
        "standard_name": "sea_water_practical_salinity",
        "reference_scale": "PSS-78",
        "cmap": "YlGnBu_r",
        "vmin": 34.0,
        "vmax": 35.5,
    },
    "ctd_oxygen_1": {
        "label": "$O_2$",
        "label_units": "µmol kg⁻¹",
        "long_name": "Dissolved oxygen (primary)",
        "units": "umol kg-1",
        "standard_name": "moles_of_oxygen_per_unit_mass_in_sea_water",
        "cmap": "RdYlGn",
        "vmin": 0,
        "vmax": 350,
    },
    "ctd_oxygen_2": {
        "label": "$O_2$ (2)",
        "label_units": "µmol kg⁻¹",
        "long_name": "Dissolved oxygen (secondary)",
        "units": "umol kg-1",
        "standard_name": "moles_of_oxygen_per_unit_mass_in_sea_water",
        "cmap": "RdYlGn",
        "vmin": 0,
        "vmax": 350,
    },
    # ctd_oxygen: preferred sensor composite — see ctd_temperature note above.
    "ctd_oxygen": {
        "label": "$O_2$",
        "label_units": "µmol kg⁻¹",
        "long_name": "Dissolved oxygen (preferred sensor)",
        "units": "umol kg-1",
        "standard_name": "moles_of_oxygen_per_unit_mass_in_sea_water",
        "cmap": "RdYlGn",
        "vmin": 0,
        "vmax": 350,
    },
    # oxygen_saturation: derived on demand from ctd_oxygen + T/S/P; not stored.
    # Entry kept for vlabel() and plot metadata; no netCDF write.
    "oxygen_saturation": {
        "label": "$O_2$ sat",
        "label_units": "%",
        "long_name": "Dissolved oxygen saturation",
        "units": "percent",
        "standard_name": None,
        "cmap": "RdYlGn",
        "vmin": 0,
        "vmax": 110,
    },
    "ctd_fluor": {
        "label": "Fluorescence",
        "label_units": "mg m⁻³",
        "long_name": "Chlorophyll fluorescence",
        "units": "mg m-3",
        "standard_name": "mass_concentration_of_chlorophyll_in_sea_water",
        "cmap": "YlGn",
        "vmin": 0,
        "vmax": None,
    },
    "ctd_turbidity": {
        "label": "Turbidity",
        "label_units": "NTU",
        "long_name": "Turbidity",
        "units": "1",  # dimensionless per CF for NTU
        "standard_name": "sea_water_turbidity",
        "cmap": "YlOrBr",
        "vmin": 0,
        "vmax": None,
    },
    "ctd_altimeter": {
        "label": "Altimeter",
        "label_units": "m",
        "long_name": "Altimeter distance to seafloor",
        "units": "m",
        "standard_name": "altitude_of_sea_floor",
        "cmap": None,
        "vmin": 0,
        "vmax": None,
    },
    # TEOS-10 derived — computed on-the-fly by derive_teos10(), not stored in NC
    "conservative_temperature": {
        "label": "CT",
        "label_units": "°C",
        "long_name": "Conservative Temperature",
        "units": "degree_Celsius",
        "standard_name": "sea_water_conservative_temperature",
        "reference_scale": "TEOS-10",
        "cmap": "RdYlBu_r",
        "vmin": -2,
        "vmax": 20,
    },
    "absolute_salinity": {
        "label": "SA",
        "label_units": "g kg⁻¹",
        "long_name": "Absolute Salinity",
        "units": "g kg-1",
        "standard_name": "sea_water_absolute_salinity",
        "reference_scale": "TEOS-10",
        "cmap": "YlGnBu_r",
        "vmin": 34.0,
        "vmax": 35.5,
    },
    "sigma0": {
        "label": "$\\sigma_0$",
        "label_units": "kg m⁻³",
        "long_name": "Potential density anomaly (ref 0 dbar)",
        "units": "kg m-3",
        "standard_name": "sea_water_sigma_theta",
        "cmap": "Purples",
        "vmin": 26.5,
        "vmax": 28.2,
    },
    # Derived diagnostics
    "AOU": {
        "label": "AOU",
        "label_units": "µmol kg⁻¹",
        "long_name": "Apparent Oxygen Utilization",
        "units": "umol kg-1",
        "standard_name": None,
        "cmap": "RdBu_r",  # blue = near saturation, red = depleted
        "vmin": None,
        "vmax": None,
    },
    # LADCP velocity components
    "U": {
        "label": "U",
        "label_units": "m s⁻¹",
        "long_name": "Eastward velocity",
        "units": "m s-1",
        "standard_name": "eastward_sea_water_velocity",
        "cmap": None,
        "vmin": -2.0,
        "vmax": 2.0,
    },
    "V": {
        "label": "V",
        "label_units": "m s⁻¹",
        "long_name": "Northward velocity",
        "units": "m s-1",
        "standard_name": "northward_sea_water_velocity",
        "cmap": None,
        "vmin": -2.0,
        "vmax": 2.0,
    },
    # Stability diagnostics
    "N2": {
        "label": "N²",
        "label_units": "s⁻²",  # rad² is conventional to omit on oceanographic plots
        "long_name": "Squared buoyancy frequency",
        "units": "rad2 s-2",
        "standard_name": "square_of_brunt_vaisala_frequency_in_sea_water",
        "cmap": None,
        "vmin": None,
        "vmax": None,
    },
    "Turner": {
        "label": "Turner angle",
        "label_units": "°",
        "long_name": "Turner angle",
        "units": "degree",
        "standard_name": None,
        "cmap": None,
        "vmin": -90,
        "vmax": 90,
    },
}

# ---------------------------------------------------------------------------
# Colour and colormap tables  [Deferred — will move to oceanvis]
# ---------------------------------------------------------------------------
# Physics (CT/SA/σ₀/U/V/N²/Turner): Okabe-Ito palette — Bang Wong, Nature Methods 8:441 (2011).
# Biogeochemistry (O₂/fluorescence/turbidity): Paul Tol palette.
#
# Keys use the long internal names from VARIABLES (not short aliases like CT/SA).
VAR_COLORS: dict[str, str] = {
    "conservative_temperature": "#56B4E9",  # sky blue     — Okabe-Ito
    "absolute_salinity": "#E69F00",  # orange       — Okabe-Ito
    "sigma0": "#009E73",  # bluish green — Okabe-Ito
    "U": "#D55E00",  # vermillion   — Okabe-Ito
    "V": "#0072B2",  # blue         — Okabe-Ito
    "ctd_oxygen_1": "#332288",  # indigo       — Paul Tol
    "ctd_fluor": "#117733",  # forest green — Paul Tol
    "ctd_turbidity": "#661100",  # dark red     — Paul Tol
    "N2": "#000000",
    "Turner": "#000000",
}

#: Plotter-facing colormap lookup, derived from VARIABLES so the two cannot drift.
_VAR_CMAPS: dict[str, str] = {
    k: v["cmap"] for k, v in VARIABLES.items() if v.get("cmap") is not None
}


#: Physics variables drawn on section, overview, and timeseries pages, in order.
#: Use ``vlabel(var)`` for the axis/panel label and ``VARIABLES[var]["label"]``
#: for the short caption.  Defined here so the three report modules share one
#: source of truth and cannot silently diverge from each other or from VARIABLES.
SECTION_PHYSICS_VARS: tuple[str, ...] = (
    "conservative_temperature",
    "absolute_salinity",
    "sigma0",
)

#: Biogeochemical variables drawn on section, overview, and timeseries pages, in order.
SECTION_BIOGEO_VARS: tuple[str, ...] = (
    "ctd_oxygen_1",
    "ctd_fluor",
    "ctd_turbidity",
)


def vlabel(var: str, prefix: str = "") -> str:
    """Return a matplotlib axis label for *var* using the VARIABLES registry.

    Format is ``"Label (units)"`` when ``label_units`` is non-empty, or just
    ``"Label"`` when there are no units (e.g. dimensionless quantities).
    Units are always in the Unicode display form from ``label_units`` — never
    the ASCII-safe ``units`` string used for netCDF attributes.

    Parameters
    ----------
    var:
        VARIABLES key (e.g. ``"conservative_temperature"``).
    prefix:
        Optional prefix prepended to the label component only, not the units.
        Use ``"Δ"`` to produce difference labels such as ``"ΔCT (°C)"``.

    Returns
    -------
    str
        Ready-to-use axis label string.  Falls back to *var* itself when *var*
        is not in VARIABLES.
    """
    entry = VARIABLES.get(var, {})
    lbl = f"{prefix}{entry.get('label', var)}"
    lu = entry.get("label_units", "")
    return f"{lbl} ({lu})" if lu else lbl


def vunit(var: str) -> str:
    """Return the Unicode display unit for *var*, or ``""`` when dimensionless.

    The unit half of :func:`vlabel`, for field colorbars that place the unit as a
    title on top of the bar rather than a ``"Label (units)"`` side label.  Uses the
    ``label_units`` display form (never the ASCII ``units`` netCDF string).  Works
    for both canonical and single-/dual-sensor-resolved names (both carry the same
    ``label_units`` in :data:`VARIABLES`).
    """
    return VARIABLES.get(var, {}).get("label_units", "")


#: Greek/command replacements for the mathtext→Unicode label converter.
_MATHTEXT_TOKENS: dict[str, str] = {r"\sigma": "σ", r"\log": "log"}
_SUBSCRIPT_MAP = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
_SUPERSCRIPT_MAP = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")


def _mathtext_to_unicode(text: str) -> str:
    """Convert the mathtext spans in *text* to their Unicode equivalents.

    ``VARIABLES`` labels carry subscripts as mathtext (``$\\sigma_0$``) so matplotlib
    renders them reliably; this rewrites those spans to Unicode (``σ₀``) for HTML
    contexts, where mathtext would show as literal ``$…$``.  Handles the ``\\sigma``/
    ``\\log`` tokens our labels use plus ``_`` subscripts and ``^`` superscripts; a
    label using an unmapped TeX command is caught by ``test_vlabel_html_round_trips``
    rather than leaking silently.
    """

    def _convert(match: re.Match[str]) -> str:
        body = match.group(1)
        for tex, char in _MATHTEXT_TOKENS.items():
            body = body.replace(tex, char)
        body = re.sub(
            r"_\{([^}]*)\}", lambda m: m.group(1).translate(_SUBSCRIPT_MAP), body
        )
        body = re.sub(r"_(.)", lambda m: m.group(1).translate(_SUBSCRIPT_MAP), body)
        body = re.sub(
            r"\^\{([^}]*)\}", lambda m: m.group(1).translate(_SUPERSCRIPT_MAP), body
        )
        body = re.sub(r"\^(.)", lambda m: m.group(1).translate(_SUPERSCRIPT_MAP), body)
        return body

    return re.sub(r"\$([^$]*)\$", _convert, text)


def vlabel_html(var: str, prefix: str = "") -> str:
    """Return :func:`vlabel` as HTML-ready text — mathtext subscripts as Unicode.

    Use this wherever a variable label is written into HTML (a figure caption, a
    table cell): matplotlib needs the mathtext form, but HTML must show ``σ₀``, not
    the literal ``$\\sigma_0$``.  One helper so the label-form choice lives in one place.
    """
    return _mathtext_to_unicode(vlabel(var, prefix))


def resolve_sensor_var(ds: xr.Dataset, var: str) -> str:
    """Return the name to use for *var* in *ds*, applying the single/dual-sensor rule.

    A variable may be stored plain (single sensor, e.g. ``ctd_oxygen``) or suffixed
    (dual sensor, e.g. ``ctd_oxygen_1``).  This resolves whichever form *ds* actually
    holds: a suffixed *var* falls back to its plain form, and a plain *var* falls back
    to the ``_1`` form.  Returns *var* unchanged when neither is present, so the
    caller's draw function then returns ``None`` for the missing variable.

    Parameters
    ----------
    ds:
        The dataset whose variables to resolve against.
    var:
        The requested variable name (plain or ``_1``/``_2`` suffixed).

    Returns
    -------
    str
        The name present in *ds*, or *var* unchanged if neither form is found.
    """
    if var in ds:
        return var
    # Suffixed var not found; try the plain (single-sensor) form.
    if var.endswith("_1") and var[:-2] in ds:
        return var[:-2]
    # Plain var not found; try the suffixed form.
    if not var.endswith(("_1", "_2")) and f"{var}_1" in ds:
        return f"{var}_1"
    return var


# ---------------------------------------------------------------------------
# CNV input aliases  [Science — firmware column names, not per-cruise choices]
# ---------------------------------------------------------------------------
# SeaBird/CNV column name (lowercase) → ctdcast internal variable name.
# Used by readers/cnv.py to rename columns on ingest.
# Keys are lowercase; readers must lower-case incoming names before lookup.
#
# Entries confirmed from mixsed2_011.nc CNV header:
#   t090C, c0S/m, t190C, c1S/m, altM, flECO-AFL, turbWETntu0, sbeox0PS, sbox0Mm/Kg, sbeox0V
# Other entries are plausible SeaBird firmware variants, not yet verified.
#
# CCHDO read-direction mappings (CTDTMP → temperature_1) belong in CCHDO_VARIABLES below.
CNV_ALIASES: dict[str, str] = {
    # -------------------------------------------------------------------
    # Raw CNV column names (SBE firmware names, lowercase)
    # Used when a future backend reads CNV directly without pre-sanitization.
    # -------------------------------------------------------------------
    # Temperature — CCHDO nc_var names with _1/_2 suffix for dual sensors
    "t090c": "ctd_temperature_1",  # SBE 9+ primary, ITS-90
    "t190c": "ctd_temperature_2",  # SBE 9+ secondary, ITS-90
    "tv290c": "ctd_temperature_2",  # some SeaBird firmware variants
    # Conductivity — no CCHDO equivalent; keep plain names
    "c0s/m": "conductivity_1",  # SBE 9+ primary, S/m
    "c1s/m": "conductivity_2",  # SBE 9+ secondary, S/m
    # Pressure
    "prsm": "pressure",  # strain-gauge, metres (rare)
    "prdm": "pressure",  # strain-gauge, dbar
    # Salinity (rarely written in CNV; normally derived from C/T/P)
    "sal00": "ctd_salinity_1",
    "sal11": "ctd_salinity_2",
    # Oxygen — µmol/kg only; % saturation is derived on demand, not stored
    "sbox0mm/kg": "ctd_oxygen_1",  # SBE 43, µmol/kg
    "sbeox0v": "oxygen_raw_1",  # SBE 43 raw voltage; not used in normal pipeline
    # Biogeo
    "fleco-afl": "ctd_fluor",  # WET Labs ECO-AFL/FL fluorometer
    "turbwetntu0": "ctd_turbidity",  # WET Labs ECO NTU turbidity sensor
    "obs": "ctd_turbidity",  # OBS turbidity (alternative sensor type)
    # Navigation (sometimes embedded in CNV)
    "latitude": "latitude",
    "longitude": "longitude",
    # Altimeter
    # -------------------------------------------------------------------
    # seasenselib-sanitized names — seasenselib applies its own mapping
    # before returning the Dataset, so _normalise() sees these names, not
    # the raw CNV column names above.  Both sets must be present so that
    # _normalise() is backend-agnostic.
    # -------------------------------------------------------------------
    "temperature_1": "ctd_temperature_1",
    "temperature_2": "ctd_temperature_2",
    "salinity_1": "ctd_salinity_1",
    "salinity_2": "ctd_salinity_2",
    # Note: seasenselib's oxygen_1/oxygen_2 are % saturation (from sbeox0PS),
    # not µmol/kg.  They are dropped in _normalise(); the µmol/kg value comes
    # from sbox0Mm/Kg → ctd_oxygen_1 via the raw CNV alias above.
    "fluorescence": "ctd_fluor",
    "turbidity": "ctd_turbidity",
    "altimeter": "ctd_altimeter",
    # Raw CNV altimeter column name
    "altm": "ctd_altimeter",  # sea-floor distance, metres
}

# ---------------------------------------------------------------------------
# CCHDO output convention  [Contract — wrong WHP name = non-conformant file]
# ---------------------------------------------------------------------------
# Source: 740H20200119_ctd.nc (James Cook JC191, A05 24N Atlantic, 2020-01-19)
#   Conventions: CF-1.8 CCHDO-1.0 / cchdo_parameters_version: params 0.1.21
# WHP parameter reference: https://exchange-format.readthedocs.io/en/latest/parameters.html

# Dimension names and order — mirror CCHDO exactly.
# N_PROF = one element per cast/profile; N_LEVELS = pressure levels per cast.
CCHDO_DIMS: tuple[str, str] = ("N_PROF", "N_LEVELS")

# Best-sensor composite: maps the plain (unsuffixed) ctdcast name to the CCHDO
# nc_var name. The plain name exists only when preferred_sensor is configured in
# config.yaml and stage3 has promoted one of the suffixed channels. If not set,
# the CCHDO writer falls back to the _1 sensor.
# Under the CCHDO naming scheme these are identity mappings — the names already match.
CCHDO_COMPOSITE: dict[str, str] = {
    "ctd_temperature": "ctd_temperature",
    "ctd_salinity": "ctd_salinity",
    "ctd_oxygen": "ctd_oxygen",
}

# Variables NOT written to CCHDO output.
CCHDO_EXCLUDE: frozenset[str] = frozenset(
    {
        "timeJ",  # Julian-day timestamp; CCHDO uses ISO 8601 time coordinate
        "timeS",  # elapsed seconds; not a scientific variable
        "speed_of_sound",  # SeaBird bookkeeping
        "density",  # in-situ density; ctdcast writes sigma0 — no density WHP param
        "flag",  # SeaBird processing flag, not a QC flag
        "oxygen_raw_1",  # raw SBE 43 voltage
        # oxygen_saturation is not stored (derived on demand) — no entry needed here
    }
)

# Station/cast identifiers written as coordinates (not data variables).
CCHDO_IDENTIFIERS: dict[str, str] = {
    "expocode": "EXPOCODE",
    "station": "STNNBR",
    "cast": "CASTNO",
    "sample": "SAMPNO",
}

# QARTOD → WOCE CTD QC flag translation.  [Contract — do not edit without a version bump]
# CRITICAL: WOCE 2 = acceptable (good), WOCE 1 = not_calibrated (NOT good).
# A naive 1→1 pass-through silently labels every good measurement as uncalibrated.
CCHDO_QC: dict[int, int] = {
    1: 2,  # pass          → acceptable_measurement
    2: 1,  # not_evaluated → not_calibrated
    3: 3,  # suspect       → questionable_measurement
    4: 4,  # fail          → bad_measurement
    9: 9,  # missing       → not_sampled
    # WOCE 5 (not_reported), 6 (interpolated), 7 (despiked) have no QARTOD equivalent;
    # derive from processing history at write time.
}

# ctdcast internal name → CCHDO attributes the writer must set on output.
CCHDO_VARIABLES: dict[str, dict] = {
    "pressure": {
        "whp_name": "CTDPRS",
        "whp_unit": "DBAR",
        "units": "dbar",
        "C_format": "%.1f",
    },
    # ctd_temperature: written directly (names already match CCHDO nc_var).
    # Prefer the plain name (preferred sensor); fall back to ctd_temperature_1.
    "ctd_temperature": {
        "whp_name": "CTDTMP",
        "whp_unit": "ITS-90",
        "units": "degC",  # CCHDO uses degC, not degree_Celsius
        "reference_scale": "ITS-90",
        "C_format": "%.4f",
    },
    "ctd_salinity": {
        "whp_name": "CTDSAL",
        "whp_unit": "PSS-78",
        "units": "1",  # PSS-78 is dimensionless per CF
        "C_format": "%.4f",
    },
    "ctd_oxygen": {
        "whp_name": "CTDOXY",
        "whp_unit": "UMOL/KG",
        "units": "umol/kg",  # CCHDO uses umol/kg, not umol kg-1
        "C_format": "%.1f",
    },
    "latitude": {
        "whp_name": "LATITUDE",
        "units": "degree_north",
        "C_format": "%.5f",
    },
    "longitude": {
        "whp_name": "LONGITUDE",
        "units": "degree_east",
        "C_format": "%.5f",
    },
    # btm_depth: not yet stored in ctdcast netCDF — stub for Phase 4.
    "btm_depth": {
        "whp_name": "DEPTH",
        "whp_unit": "METERS",
        "units": "meters",
        "C_format": "%.0f",
    },
    # fluorescence and turbidity: no WHP names confirmed from reference file.
    # Omit from CCHDO output until verified from a biogeo-sensor CCHDO file.
}
