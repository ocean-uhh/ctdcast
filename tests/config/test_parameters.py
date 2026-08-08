"""Consistency tests for ctdcast.config.parameters.

These tests protect against silent drift between tables that must agree.
100% import-coverage on a data module proves nothing; these tests do.
"""

from __future__ import annotations

from ctdcast.config.parameters import (
    _VAR_CMAPS,
    CCHDO_COMPOSITE,
    CCHDO_QC,
    CCHDO_VARIABLES,
    CNV_ALIASES,
    SECTION_BIOGEO_VARS,
    SECTION_PHYSICS_VARS,
    VAR_COLORS,
    VARIABLES,
)


def test_var_cmaps_derived_from_variables() -> None:
    """_VAR_CMAPS is a subset of VARIABLES with no extra keys."""
    assert set(_VAR_CMAPS) <= set(VARIABLES), (
        f"_VAR_CMAPS has keys not in VARIABLES: {set(_VAR_CMAPS) - set(VARIABLES)}"
    )


def test_var_colors_keys_in_variables() -> None:
    """VAR_COLORS only references variables that VARIABLES knows about."""
    assert set(VAR_COLORS) <= set(VARIABLES), (
        f"VAR_COLORS has keys not in VARIABLES: {set(VAR_COLORS) - set(VARIABLES)}"
    )


def test_cchdo_composite_keys_in_variables() -> None:
    """CCHDO_COMPOSITE only references variables that VARIABLES knows about."""
    assert set(CCHDO_COMPOSITE) <= set(VARIABLES), (
        f"CCHDO_COMPOSITE has keys not in VARIABLES: "
        f"{set(CCHDO_COMPOSITE) - set(VARIABLES)}"
    )


def test_cchdo_variables_keys_in_variables() -> None:
    """CCHDO_VARIABLES only references variables that VARIABLES knows about."""
    # latitude, longitude, btm_depth are output-only coordinates — not in VARIABLES.
    coord_only = {"latitude", "longitude", "btm_depth"}
    extra = set(CCHDO_VARIABLES) - set(VARIABLES) - coord_only
    assert not extra, f"CCHDO_VARIABLES has unexpected keys: {extra}"


def test_cchdo_qc_woce_inversion() -> None:
    """CCHDO_QC maps QARTOD pass (1) to WOCE acceptable (2), not WOCE 1.

    WOCE 1 = not_calibrated (bad).  WOCE 2 = acceptable_measurement (good).
    A naive 1→1 pass-through silently marks every good value as uncalibrated.
    """
    assert CCHDO_QC[1] == 2, "QARTOD pass must map to WOCE 2 (acceptable), not WOCE 1"
    assert CCHDO_QC[2] == 1, "QARTOD not_evaluated must map to WOCE 1 (not_calibrated)"
    assert CCHDO_QC[3] == 3
    assert CCHDO_QC[4] == 4
    assert CCHDO_QC[9] == 9


def test_cnv_aliases_values_in_variables() -> None:
    """Every CNV_ALIASES target variable must have an entry in VARIABLES.

    Exceptions: coordinate names (latitude, longitude) and oxygen_raw_1
    (raw SBE 43 voltage, intentionally excluded from the plotting pipeline).
    Without this check, a new alias can silently fall back to 'viridis'
    if the target name is absent from VARIABLES.
    """
    _coords = {"latitude", "longitude"}
    _pipeline_excluded = {"oxygen_raw_1"}
    targets_as_vars = set(CNV_ALIASES.values()) - _coords - _pipeline_excluded
    missing = targets_as_vars - set(VARIABLES)
    assert not missing, f"CNV_ALIASES targets missing from VARIABLES: {missing}"


def test_section_panel_vars_in_variables() -> None:
    """Every variable in SECTION_PHYSICS_VARS and SECTION_BIOGEO_VARS must be in VARIABLES.

    Ensures the three report modules (section, timeseries, index) cannot silently
    produce blank panels because a variable was renamed in VARIABLES without updating
    the panel lists.
    """
    all_panel_vars = set(SECTION_PHYSICS_VARS) | set(SECTION_BIOGEO_VARS)
    missing = all_panel_vars - set(VARIABLES)
    assert not missing, f"Panel variables missing from VARIABLES: {missing}"


def test_section_panel_vars_have_label_and_label_units() -> None:
    """Every panel variable must have both 'label' and 'label_units' entries in VARIABLES."""
    for var in (*SECTION_PHYSICS_VARS, *SECTION_BIOGEO_VARS):
        entry = VARIABLES[var]
        assert "label" in entry, f"{var!r} is missing 'label' in VARIABLES"
        assert "label_units" in entry, f"{var!r} is missing 'label_units' in VARIABLES"


def test_load_display_config_merges_overrides() -> None:
    """load_display_config applies cruise overrides without mutating VARIABLES."""
    from ctdcast.config.loader import load_display_config

    original_vmin = VARIABLES["ctd_temperature_1"]["vmin"]

    cfg = {"display": {"variables": {"ctd_temperature_1": {"vmin": 4, "vmax": 25}}}}
    merged = load_display_config(cfg)

    assert merged["ctd_temperature_1"]["vmin"] == 4
    assert merged["ctd_temperature_1"]["vmax"] == 25
    # Global VARIABLES must not be mutated.
    assert VARIABLES["ctd_temperature_1"]["vmin"] == original_vmin


def test_load_display_config_empty_cruise_cfg() -> None:
    """load_display_config with no display block returns package defaults."""
    from ctdcast.config.loader import load_display_config

    merged = load_display_config({})
    assert merged["ctd_temperature_1"]["vmin"] == VARIABLES["ctd_temperature_1"]["vmin"]
