"""Package-wide constants: plotting parameters, CNV aliases, variable metadata, CCHDO conventions.

Compile-time constants only — the runtime-mutable display globals (GEBCO_PATH,
CLEAN_SPINES, figsizes, map bounds) stay in :mod:`ctdcast.plotters.plots`.

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

# ---------------------------------------------------------------------------
# Slot widths  [Derived — from dpi and browser scaling maths]
# ---------------------------------------------------------------------------
# Slot widths in inches at savefig.dpi=150 (body usable width = 1086px).
# PNGs are intentionally wider than the slot (1350px vs 1086px at full width) so that
# at 10pt labels, displayed font size (~17px) matches the pre-refactor appearance.
# The browser downscales by ~0.80, giving crisp subpixel rendering.
_W_FULL: float = 9.0  # 1350px PNG → 1086px display
_W_TWOTHIRDS: float = 6.0  # 900px PNG  → 719px display
_W_THREE_FIFTHS: float = 5.4  # 810px PNG  → 652px display (60% slot)
_W_HALF: float = 4.5  # 675px PNG  → 543px display
_W_TWO_FIFTHS: float = 3.6  # 540px PNG  → 434px display (40% slot)
_W_THIRD: float = 3.0  # 450px PNG  → 361px display
# Section aspect-ratio scaling.
# Calibrated so KTout (416 dbar, 94 km) renders at 2.5 in tall at _W_FULL = 9.0 in.
_SECTION_STRETCH: float = 16.0
_MAX_SECTION_H: float = 5.2  # height cap; tall/narrow sections get narrower fig_w

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
#       temperature_1:
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
    "temperature_1": {
        "label": "T₁",
        "label_units": "°C",
        "long_name": "In-situ temperature (primary)",
        "units": "degree_Celsius",
        "standard_name": "sea_water_temperature",
        "reference_scale": "ITS-90",
        "cmap": "RdYlBu_r",
        "vmin": -2,
        "vmax": 20,
    },
    "temperature_2": {
        "label": "T₂",
        "label_units": "°C",
        "long_name": "In-situ temperature (secondary)",
        "units": "degree_Celsius",
        "standard_name": "sea_water_temperature",
        "reference_scale": "ITS-90",
        "cmap": "RdYlBu_r",
        "vmin": -2,
        "vmax": 20,
    },
    # Best-sensor composite: copy of temperature_1 or temperature_2, whichever was
    # judged best for this cruise. Which sensor is in temperature.attrs["preferred_sensor"].
    # CCHDO writer maps this to ctd_temperature (see CCHDO_COMPOSITE).
    "temperature": {
        "label": "T",
        "label_units": "°C",
        "long_name": "In-situ temperature (best sensor)",
        "units": "degree_Celsius",
        "standard_name": "sea_water_temperature",
        "reference_scale": "ITS-90",
        "cmap": "RdYlBu_r",
        "vmin": -2,
        "vmax": 20,
    },
    "conductivity_1": {
        "label": "C₁",
        "label_units": "S m⁻¹",
        "long_name": "Conductivity (primary)",
        "units": "S m-1",
        "standard_name": "sea_water_electrical_conductivity",
        "cmap": None,
        "vmin": None,
        "vmax": None,
    },
    "conductivity_2": {
        "label": "C₂",
        "label_units": "S m⁻¹",
        "long_name": "Conductivity (secondary)",
        "units": "S m-1",
        "standard_name": "sea_water_electrical_conductivity",
        "cmap": None,
        "vmin": None,
        "vmax": None,
    },
    "salinity_1": {
        "label": "SP₁",
        "label_units": "PSU",
        "long_name": "Practical salinity (primary)",
        "units": "1",  # PSS-78 is dimensionless per CF
        "standard_name": "sea_water_practical_salinity",
        "reference_scale": "PSS-78",
        "cmap": "YlGnBu_r",
        "vmin": 34.0,
        "vmax": 35.5,
    },
    "salinity_2": {
        "label": "SP₂",
        "label_units": "PSU",
        "long_name": "Practical salinity (secondary)",
        "units": "1",
        "standard_name": "sea_water_practical_salinity",
        "reference_scale": "PSS-78",
        "cmap": "YlGnBu_r",
        "vmin": 34.0,
        "vmax": 35.5,
    },
    # oxygen_1 = µmol/kg — target name (Phase 3 rename from sbox0Mm_Kg in fixture NC)
    "oxygen_1": {
        "label": "O₂",
        "label_units": "µmol kg⁻¹",
        "long_name": "Dissolved oxygen (primary)",
        "units": "umol kg-1",
        "standard_name": "moles_of_oxygen_per_unit_mass_in_sea_water",
        "cmap": "RdYlGn",
        "vmin": 0,
        "vmax": 350,
    },
    # oxsat_1 = % saturation — target name (Phase 3 rename from oxygen_1 in fixture NC)
    # No CF standard_name and no CCHDO WHP equivalent — excluded from CCHDO output.
    "oxsat_1": {
        "label": "O₂ sat",
        "label_units": "%",
        "long_name": "Dissolved oxygen saturation (primary)",
        "units": "percent",
        "standard_name": None,
        "cmap": "RdYlGn",
        "vmin": 0,
        "vmax": 110,
    },
    "fluorescence": {
        "label": "Fluorescence",
        "label_units": "mg m⁻³",
        "long_name": "Chlorophyll fluorescence",
        "units": "mg m-3",  # uncalibrated; label may vary by cruise
        "standard_name": None,
        "cmap": "YlGn",
        "vmin": 0,
        "vmax": None,
    },
    "turbidity": {
        "label": "Turbidity",
        "label_units": "NTU",
        "long_name": "Turbidity",
        "units": "NTU",  # uncalibrated; NTU not guaranteed for all sensors
        "standard_name": None,
        "cmap": "YlOrBr",
        "vmin": 0,
        "vmax": None,
    },
    "altimeter": {
        "label": "Altimeter",
        "label_units": "m",
        "long_name": "Altimeter distance to bottom",
        "units": "m",
        "standard_name": None,
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
        "label": "σ₀",
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
        "vmin": None,
        "vmax": None,
    },
    "V": {
        "label": "V",
        "label_units": "m s⁻¹",
        "long_name": "Northward velocity",
        "units": "m s-1",
        "standard_name": "northward_sea_water_velocity",
        "cmap": None,
        "vmin": None,
        "vmax": None,
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
    "oxsat_1": "#332288",  # indigo       — Paul Tol
    "fluorescence": "#117733",  # forest green — Paul Tol
    "turbidity": "#661100",  # dark red     — Paul Tol
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
    "oxsat_1",
    "fluorescence",
    "turbidity",
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
    # Temperature
    "t090c": "temperature_1",  # SBE 9+ primary, ITS-90
    "t190c": "temperature_2",  # SBE 9+ secondary, ITS-90
    "tv290c": "temperature_2",  # some SeaBird firmware variants
    # Conductivity
    "c0s/m": "conductivity_1",  # SBE 9+ primary, S/m
    "c1s/m": "conductivity_2",  # SBE 9+ secondary, S/m
    # Pressure
    "prsm": "pressure",  # strain-gauge, metres (rare)
    "prdm": "pressure",  # strain-gauge, dbar
    # Salinity (rarely written in CNV; normally derived from C/T/P)
    "sal00": "salinity_1",
    "sal11": "salinity_2",
    # Oxygen — target names (see CCHDO_COMPOSITE for output mapping)
    "sbeox0ps": "oxsat_1",  # SBE 43, % saturation
    "sbox0mm/kg": "oxygen_1",  # SBE 43, µmol/kg (CCHDO-aligned target name)
    "sbeox0v": "oxygen_raw_1",  # SBE 43 raw voltage; not used in normal pipeline
    # Biogeo
    "fleco-afl": "fluorescence",  # WET Labs ECO-AFL/FL fluorometer
    "turbwetntu0": "turbidity",  # WET Labs ECO NTU turbidity sensor
    "obs": "turbidity",  # OBS turbidity (alternative sensor type)
    # Navigation (sometimes embedded in CNV)
    "latitude": "latitude",
    "longitude": "longitude",
    # Altimeter
    "altm": "altimeter",  # sea-floor distance, metres
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

# Best-sensor composite: CCHDO has one temperature variable (no suffix).
# Key = ctdcast internal name, value = CCHDO output variable name.
CCHDO_COMPOSITE: dict[str, str] = {
    "temperature": "ctd_temperature",
    "salinity_1": "ctd_salinity",
    "oxygen_1": "ctd_oxygen",
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
        "oxsat_1",  # % saturation diagnostic; no CCHDO WHP equivalent
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
    # Written as ctd_temperature per CCHDO_COMPOSITE.
    "temperature": {
        "whp_name": "CTDTMP",
        "whp_unit": "ITS-90",
        "units": "degC",  # CCHDO uses degC, not degree_Celsius
        "reference_scale": "ITS-90",
        "C_format": "%.4f",
    },
    # Written as ctd_salinity per CCHDO_COMPOSITE.
    "salinity_1": {
        "whp_name": "CTDSAL",
        "whp_unit": "PSS-78",
        "units": "1",  # PSS-78 is dimensionless per CF
        "C_format": "%.4f",
    },
    # Written as ctd_oxygen per CCHDO_COMPOSITE.
    # oxygen_1 = µmol/kg after Phase 3 rename — direct passthrough.
    "oxygen_1": {
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
