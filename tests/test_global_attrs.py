"""Tests for :mod:`ctdcast.config.global_attrs` — derived + authored file globals.

The load-bearing test is :func:`test_bounds_bracket_every_station`: it catches the
copy-from-first-cast bug (a cruise file whose bounding box contains one station),
which the file-level-metadata design note names as the most likely way this goes
wrong.
"""

from __future__ import annotations

import datetime

import numpy as np
import pytest

from ctdcast.config.global_attrs import (
    ATTR_GROUPS,
    OTHER_GROUP,
    canonical_attr_order,
    coverage_attrs,
    cruise_expocode,
    cruise_global_attrs,
    expocode_coordinate,
    group_attrs,
    license_attrs,
    order_attrs,
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
    # 22 days 8 hours — the partial day is kept, not truncated to P22D.
    assert a["time_coverage_duration"] == "P22DT8H"


def test_sub_day_span_is_not_p0d():
    """A six-hour survey must not report a zero-length ISO duration."""
    times = np.array(["2026-07-09T10:00", "2026-07-09T16:00"], dtype="datetime64[ns]")
    a = coverage_attrs(lats=[1.0], lons=[2.0], times=times)
    assert a["time_coverage_duration"] == "PT6H"


def test_whole_day_span_has_no_time_part():
    times = np.array(["2026-07-09T00:00", "2026-07-12T00:00"], dtype="datetime64[ns]")
    a = coverage_attrs(lats=[1.0], lons=[2.0], times=times)
    assert a["time_coverage_duration"] == "P3D"


def test_all_nan_vertical_bounds_are_omitted():
    """An all-NaN pressure column must not write a NaN geospatial bound."""
    a = coverage_attrs(
        lats=[1.0], lons=[2.0], vertical_min=float("nan"), vertical_max=float("nan")
    )
    assert "geospatial_vertical_min" not in a
    assert "geospatial_vertical_max" not in a


def test_non_datetime_times_are_skipped_not_misencoded():
    """A numeric epoch array is not a wall-clock time; skip rather than mislabel."""
    a = coverage_attrs(lats=[1.0], lons=[2.0], times=np.array([1_000_000, 2_000_000]))
    assert "time_coverage_start" not in a


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
    assert a["cruise"] == "odb2026"
    assert "cruise_id" not in a  # the config key's name, never an attribute
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


# --- role-scoped contributors (per compiled product) -----------------------


def _ci_scoped():
    """One contributors list; roles scoped per product (the C89 roles model).

    A role under ``all`` (or a bare ``roles: [...]``) lands on every file; a role
    under ``ctd``/``ladcp`` lands only on that product's compiled file.
    """
    return {
        "contributors": [
            {"name": "A PI", "roles": ["PI"]},  # both files
            {"name": "LADCP Person", "roles": {"ladcp": ["DI"]}},  # ladcp only
            {"name": "CTD Person", "roles": {"ctd": ["MC"]}},  # ctd only
        ]
    }


def test_ladcp_source_includes_only_its_scoped_contributors():
    a = cruise_global_attrs(_ci_scoped(), source="ladcp")
    assert a["contributor_name"].split("; ") == ["A PI", "LADCP Person"]
    # roles are written as the C89 prefLabels, not the config codes
    assert a["contributor_role"].split("; ") == [
        "Project principal investigator",
        "Cruise dataset principal investigator",
    ]


def test_ctd_source_includes_only_its_scoped_contributors():
    a = cruise_global_attrs(_ci_scoped(), source="ctd")
    assert a["contributor_name"].split("; ") == ["A PI", "CTD Person"]


def test_no_source_is_the_union_of_scopes():
    a = cruise_global_attrs(_ci_scoped())
    assert a["contributor_name"].split("; ") == ["A PI", "LADCP Person", "CTD Person"]


# --- build-time robustness: warn and omit rather than crash -----------------


def test_malformed_orcid_warns_and_omits_people_not_crash():
    """A typo'd ORCID must not abort the whole compile (was an uncaught ValueError)."""
    ci = {"contributors": [{"name": "X", "role": "PI", "orcid": "not-an-orcid"}]}
    with pytest.warns(UserWarning, match="has errors"):
        a = cruise_global_attrs(ci, lats=[1.0], lons=[2.0])
    assert "contributor_name" not in a
    # the rest of the file's metadata is still produced
    assert "date_created" in a


def test_unknown_role_warns_and_omits_people_not_crash():
    """A role outside the chosen vocabulary omits the people with a warning."""
    ci = {"contributors": [{"name": "X", "roles": ["NotARole"]}]}
    with pytest.warns(UserWarning, match="has errors"):
        a = cruise_global_attrs(ci, source="ladcp")
    assert "contributor_name" not in a


def test_delimiter_in_name_warns_and_omits_people():
    """A comma in a name would split one person into two — caught, people omitted."""
    ci = {"contributors": [{"name": "Bad, Name", "roles": ["PI"]}]}
    with pytest.warns(UserWarning, match="has errors"):
        a = cruise_global_attrs(ci, source="ctd")
    assert "contributor_name" not in a


def test_ambiguous_platform_warns_and_omits_expocode_not_crash():
    """A registered-but-unusable slug must not abort the build."""
    ci = {"platform": "meteor", "start_date": "2026-01-13"}  # ambiguous slug
    with pytest.warns(UserWarning, match="EXPOCODE"):
        a = cruise_global_attrs(ci, lats=[1.0], lons=[2.0])
    assert "expocode" not in a
    assert "date_created" in a


def test_expocode_coordinate_shape_and_none():
    ci = {"platform": "odb", "start_date": "2026-07-09"}
    dims, data, meta = expocode_coordinate(ci, 4)
    assert dims == ["N_PROF"]
    assert list(data) == ["29OD20260709"] * 4
    assert "long_name" in meta
    assert expocode_coordinate({}, 4) is None


# --- canonical order + grouping --------------------------------------------


def test_canonical_order_has_no_duplicate_attrs():
    """No attribute may appear in two groups, or write order is ambiguous."""
    order = canonical_attr_order()
    assert len(order) == len(set(order)), "duplicate attr name in ATTR_GROUPS"


def test_order_attrs_puts_known_first_in_canonical_order():
    # deliberately scrambled input
    attrs = {
        "Conventions": "CF-1.13, ACDD-1.3",
        "geospatial_lat_min": 1.0,
        "title": "T",
        "platform": "research vessel",
    }
    ordered = list(order_attrs(attrs))
    # title (Identity) < platform (Platform) < geospatial (Coverage) < Conventions (Provenance)
    assert ordered == ["title", "platform", "geospatial_lat_min", "Conventions"]


def test_order_attrs_keeps_unknowns_at_end_in_original_order():
    attrs = {"zzz_custom": 1, "title": "T", "aaa_custom": 2}
    ordered = list(order_attrs(attrs))
    assert ordered[0] == "title"
    assert ordered[1:] == ["zzz_custom", "aaa_custom"]  # unknowns keep input order


def test_group_attrs_orders_groups_and_omits_empty():
    attrs = {"title": "T", "license": "x", "Conventions": "CF"}
    groups = group_attrs(attrs)
    titles = [g["title"] for g in groups]
    assert titles == [
        "Identity & discovery",
        "Rights & access",
        "Provenance & processing",
    ]
    # Platform / Coverage / People groups are absent (empty)
    assert "Platform" not in titles


def test_group_attrs_preserves_file_order_within_a_group():
    # two Identity attrs given in reverse-of-canonical order stay in file order
    attrs = {"project": "P", "title": "T"}
    (identity,) = group_attrs(attrs)
    assert [k for k, _ in identity["rows"]] == ["project", "title"]


def test_group_attrs_leftovers_go_to_other_group_last():
    attrs = {"title": "T", "some_future_attr": "x"}
    groups = group_attrs(attrs)
    assert groups[-1]["title"] == OTHER_GROUP
    assert [k for k, _ in groups[-1]["rows"]] == ["some_future_attr"]


def test_group_titles_match_attr_groups_spec():
    spec_titles = [t for t, _ in ATTR_GROUPS]
    assert spec_titles[0] == "Identity & discovery"
    assert "People & institutions" in spec_titles


def test_institution_groups_with_the_institutions_not_the_creator():
    """`institution` describes the data's origin, so it belongs beside the list
    it projects — and it is the only institution attribute left."""
    order = [a for _, attrs in ATTR_GROUPS for a in attrs]
    i = order.index("institution")
    assert order.index("contributing_institutions") < i
    assert i < order.index("creator_name")
    for retired in (
        "institution_id",
        "creator_institution",
        "creator_institution_id",
        "contributing_institutions_vocabulary",
    ):
        assert retired not in order


def test_cruise_id_config_key_becomes_the_cruise_attribute():
    """The LADCP builder sets no `cruise` of its own and merges per-cast attrs
    with drop_conflicts, so this is the only thing naming the cruise in
    ladcp_profiles.nc when the per-cast files carry no `cruise` attribute."""
    a = cruise_global_attrs({"cruise_id": "odb2026"}, source="ladcp")
    assert a["cruise"] == "odb2026"
    assert "cruise_id" not in a
    order = [x for _, attrs in ATTR_GROUPS for x in attrs]
    assert "cruise" in order and "cruise_id" not in order


def test_no_cruise_id_leaves_the_file_attribute_to_win():
    """Absent from config, nothing is written, so the per-cast file's own
    `cruise` attribute survives instead of being overwritten with a blank."""
    assert "cruise" not in cruise_global_attrs({})
