"""Tests for :mod:`ctdcast.config.global_attrs` — derived + authored file globals.

The load-bearing test is :func:`test_bounds_bracket_every_station`: it catches the
copy-from-first-cast bug (a cruise file whose bounding box contains one station),
which the file-level-metadata design note names as the most likely way this goes
wrong.
"""

from __future__ import annotations

import datetime

import numpy as np

from ctdcast.config.global_attrs import (
    coverage_attrs,
    cruise_expocode,
    cruise_global_attrs,
    license_attrs,
    provenance_attrs,
)


# --- derived coverage ------------------------------------------------------


def test_bounds_bracket_every_station():
    """geospatial_lat/lon min<max and bracket all stations; NaNs ignored."""
    lats = [65.1, 65.9, np.nan, 65.5]
    lons = [-30.2, np.nan, -29.4, -29.8]
    a = coverage_attrs(lats=lats, lons=lons)
    assert a["geospatial_lat_min"] < a["geospatial_lat_max"]
    for v in (65.1, 65.9, 65.5):
        assert a["geospatial_lat_min"] <= v <= a["geospatial_lat_max"]
    for v in (-30.2, -29.4, -29.8):
        assert a["geospatial_lon_min"] <= v <= a["geospatial_lon_max"]


def test_coverage_units_come_from_parameters():
    """Bound units match the canonical VARIABLES units, not a local literal."""
    from ctdcast.config.parameters import VARIABLES

    a = coverage_attrs(lats=[1.0, 2.0], lons=[3.0, 4.0])
    assert a["geospatial_lat_units"] == VARIABLES["latitude"]["units"]
    assert a["geospatial_lon_units"] == VARIABLES["longitude"]["units"]


def test_vertical_bounds_carry_positive_down():
    a = coverage_attrs(lats=[1.0], lons=[2.0], vertical_min=1.0, vertical_max=3800.0)
    assert a["geospatial_vertical_min"] == 1.0
    assert a["geospatial_vertical_max"] == 3800.0
    assert a["geospatial_vertical_positive"] == "down"
    assert a["geospatial_vertical_units"] == "dbar"


def test_time_coverage_and_iso_duration():
    times = np.array(["2026-07-09T10:00", "2026-07-31T18:00"], dtype="datetime64[ns]")
    a = coverage_attrs(lats=[1.0], lons=[2.0], times=times)
    assert a["time_coverage_start"].endswith("Z")
    assert a["time_coverage_duration"] == "P22D"


def test_all_nan_positions_yield_no_geospatial():
    a = coverage_attrs(lats=[np.nan, np.nan], lons=[np.nan])
    assert "geospatial_lat_min" not in a
    assert "geospatial_lon_min" not in a


# --- embargo / licence -----------------------------------------------------


def test_moratorium_until_derives_end_plus_two_years():
    ci = {"end_date": "2026-07-31", "embargo": {"policy": "SDN:L08::MO"}}
    a = license_attrs(ci)
    assert a["date_available"] == "2028-07-31"
    assert a["access_constraint"] == "SDN:L08::MO"
    assert "Embargoed until 2028-07-31" in a["license"]
    assert "CC-BY-4.0" in a["license"] or "CC BY" in a["license"]


def test_explicit_until_overrides_the_derived_date():
    ci = {"end_date": "2026-07-31", "embargo": {"until": "2027-01-01"}}
    a = license_attrs(ci)
    assert a["date_available"] == "2027-01-01"


def test_no_embargo_but_plain_license_is_written():
    a = license_attrs({"license": "CC-BY-4.0"})
    assert a["license"] == "CC-BY-4.0"


def test_embargoed_file_never_writes_bare_cc_by_as_license():
    """A CC BY grant is irrevocable — an embargoed file must not carry it as-is."""
    ci = {"end_date": "2026-07-31", "embargo": {"policy": "SDN:L08::MO"}}
    a = license_attrs(ci)
    assert a["license"] != "CC-BY-4.0"
    assert "Embargoed" in a["license"]


def test_no_license_config_writes_nothing():
    assert license_attrs({}) == {}


def test_leap_day_end_date_maps_to_feb_28():
    ci = {"end_date": "2024-02-29", "embargo": {}}
    a = license_attrs(ci)
    assert a["date_available"] == "2026-02-28"


# --- provenance ------------------------------------------------------------


def test_provenance_is_injectable_and_acdd():
    now = datetime.datetime(2026, 8, 21, 12, 0, 0, tzinfo=datetime.timezone.utc)
    a = provenance_attrs(now)
    assert a["date_created"] == "2026-08-21T12:00:00Z"
    assert a["date_modified"] == a["date_created"]
    assert "ACDD-1.3" in a["Conventions"]
    assert a["featureType"] == "profile"
    assert a["cdm_data_type"] == "Profile"


# --- composition -----------------------------------------------------------


def test_cruise_global_attrs_composes_all_layers():
    ci = {
        "cruise_id": "odb2026",
        "project": "AEI-DFG DS-MIXSED",
        "platform": "odb",
        "start_date": "2026-07-09",
        "end_date": "2026-07-31",
        "embargo": {"policy": "SDN:L08::MO"},
        "creator": {"name": "E F-W", "type": "person"},
        "contributors": [{"name": "E F-W", "role": "PI"}],
        "acknowledgement": "line one\n line two",
    }
    a = cruise_global_attrs(
        ci, lats=[65.1, 65.9], lons=[-30.0, -29.5], vertical_min=1.0, vertical_max=100.0
    )
    assert a["cruise_id"] == "odb2026"
    assert a["project"] == "AEI-DFG DS-MIXSED"
    assert a["platform_name"] == "Odón de Buen"
    assert a["contributor_name"] == "E F-W"
    assert "Embargoed" in a["license"]
    assert a["geospatial_lat_min"] == 65.1
    # folded acknowledgement collapses to one line
    assert "\n" not in a["acknowledgement"]
    # expocode surfaced as a global too (single cruise)
    assert a["expocode"] == "29OD20260709"


def test_cruise_expocode_matches_platform_derivation():
    ci = {"platform": "odb", "start_date": "2026-07-09"}
    assert cruise_expocode(ci) == "29OD20260709"


def test_empty_cruise_info_still_gives_derived_and_provenance():
    a = cruise_global_attrs({}, lats=[1.0, 2.0], lons=[3.0, 4.0])
    assert "geospatial_lat_min" in a
    assert "date_created" in a
    assert "expocode" not in a


# --- per-source (LADCP-only) contributors ----------------------------------


def _ci_with_ladcp_processors():
    return {
        "contributors": [{"name": "A PI", "role": "PI"}],
        "ladcp": {
            "contributors": [
                {"name": "Angel Ruiz-Angulo", "role": "Data scientist"},
                {"name": "Mara Navarro Buigues", "role": "Data scientist"},
            ]
        },
    }


def test_ladcp_source_appends_its_own_contributors():
    """LADCP processors are credited on the LADCP file, after the cruise PIs."""
    a = cruise_global_attrs(_ci_with_ladcp_processors(), source="ladcp")
    names = a["contributor_name"].split("; ")
    assert names == ["A PI", "Angel Ruiz-Angulo", "Mara Navarro Buigues"]
    assert a["contributor_role"].split("; ") == ["PI", "Data scientist", "Data scientist"]


def test_ctd_source_excludes_ladcp_contributors():
    """The same config yields only the cruise PIs on the CTD file."""
    a = cruise_global_attrs(_ci_with_ladcp_processors(), source="ctd")
    assert a["contributor_name"] == "A PI"


def test_no_source_leaves_contributors_untouched():
    a = cruise_global_attrs(_ci_with_ladcp_processors())
    assert a["contributor_name"] == "A PI"
