"""Tests for :mod:`ctdcast.config.people` — contributors and institutions."""

from __future__ import annotations

import pytest

from ctdcast.config.people import (
    SEPARATOR,
    W08_ROLES,
    check_contributors,
    contributor_attrs,
    load_institutions,
)


def _cruise_info(**overrides):
    """A minimal valid cruise_info block, with overrides applied."""
    base = {
        "creator": {
            "name": "Eleanor Frajka-Williams",
            "type": "person",
            "institution": "uhh",
            "orcid": "0000-0001-8773-7838",
        },
        "contributors": [
            {
                "name": "Eleanor Frajka-Williams",
                "role": "PI",
                "institution": "uhh",
                "orcid": "0000-0001-8773-7838",
            },
            {"name": "David Amblas", "role": "PI", "institution": "ub", "orcid": None},
        ],
    }
    base.update(overrides)
    return base


# --- the delimiter trap ----------------------------------------------------


@pytest.mark.parametrize("bad_name", ["Sanchez Franks, NOC", "Amblas; David"])
def test_delimiter_in_a_name_is_an_error(bad_name):
    """A value containing a delimiter would split one person into two.

    "A. Sanchez Franks, NOC" is a real string from a CCHDO header, which is why
    this is checked rather than assumed.
    """
    ci = _cruise_info(
        contributors=[{"name": bad_name, "role": "PI", "institution": "uhh"}]
    )
    errors, _ = check_contributors(ci)
    assert any("contains" in e for e in errors)


def test_delimiter_checked_in_role_and_email_too():
    ci = _cruise_info(
        contributors=[
            {
                "name": "A Person",
                "role": "PI",
                "institution": "uhh",
                "email": "a@b.org, c@d.org",
            }
        ]
    )
    errors, _ = check_contributors(ci)
    assert any(".email contains" in e for e in errors)


# --- roles and institutions ------------------------------------------------


def test_role_must_be_a_w08_term():
    ci = _cruise_info(
        contributors=[
            {"name": "A Person", "role": "Chief Scientist", "institution": "uhh"}
        ]
    )
    errors, _ = check_contributors(ci)
    assert any("W08" in e for e in errors)


def test_every_w08_role_is_accepted():
    for role in W08_ROLES:
        ci = _cruise_info(
            contributors=[{"name": "A Person", "role": role, "institution": "uhh"}]
        )
        errors, _ = check_contributors(ci)
        assert not errors, f"role {role!r} rejected: {errors}"


def test_unknown_institution_slug_is_an_error():
    ci = _cruise_info(
        contributors=[{"name": "A Person", "role": "PI", "institution": "nope"}]
    )
    errors, _ = check_contributors(ci)
    assert any("institutions.yaml" in e for e in errors)


@pytest.mark.parametrize(
    "given",
    [
        "0000-0001-8773-7838",
        "https://orcid.org/0000-0001-8773-7838",
        "http://orcid.org/0000-0001-8773-7838",
        "https://www.orcid.org/0000-0001-8773-7838",
    ],
)
def test_orcid_accepted_bare_or_as_url(given):
    """People paste whichever form their browser shows; both normalise."""
    ci = _cruise_info(
        contributors=[
            {"name": "A Person", "role": "PI", "institution": "uhh", "orcid": given}
        ]
    )
    errors, _ = check_contributors(ci)
    assert not errors
    attrs = contributor_attrs(ci)
    assert attrs["contributor_id"] == "https://orcid.org/0000-0001-8773-7838"


def test_orcid_with_a_checksum_x_is_accepted():
    ci = _cruise_info(
        contributors=[
            {
                "name": "A Person",
                "role": "PI",
                "institution": "uhh",
                "orcid": "0000-0002-1825-009X",
            }
        ]
    )
    errors, _ = check_contributors(ci)
    assert not errors


@pytest.mark.parametrize(
    "bad", ["0000-0001-8773", "not-an-orcid", "0000-0001-8773-78380"]
)
def test_malformed_orcid_is_an_error(bad):
    ci = _cruise_info(
        contributors=[
            {"name": "A Person", "role": "PI", "institution": "uhh", "orcid": bad}
        ]
    )
    errors, _ = check_contributors(ci)
    assert any("orcid" in e for e in errors)


def test_missing_orcid_warns_but_does_not_fail():
    """Absent ORCIDs are legitimate mid-cruise; they must be settled before release."""
    errors, warnings = check_contributors(_cruise_info())
    assert not errors
    assert any("no ORCID" in w for w in warnings)


def test_no_pi_warns():
    ci = _cruise_info(
        contributors=[{"name": "A Person", "role": "Operator", "institution": "uhh"}]
    )
    _, warnings = check_contributors(ci)
    assert any("'PI'" in w for w in warnings)


# --- generated attributes --------------------------------------------------


def test_parallel_strings_have_equal_length():
    """The whole point of generating rather than authoring these strings."""
    attrs = contributor_attrs(_cruise_info())
    lengths = {
        key: len(attrs[key].split(";"))
        for key in ("contributor_name", "contributor_role", "contributor_id")
        if key in attrs
    }
    assert len(set(lengths.values())) == 1, lengths


def test_role_vocabulary_is_a_single_uri_not_a_list():
    attrs = contributor_attrs(_cruise_info())
    assert ";" not in attrs["contributor_role_vocabulary"]


def test_all_empty_optional_field_is_omitted_entirely():
    """An empty delimited string asserts N empty values; absence asserts nothing."""
    ci = _cruise_info(
        contributors=[
            {"name": "A Person", "role": "PI", "institution": "uhh", "orcid": None},
            {"name": "B Person", "role": "PI", "institution": "ub", "orcid": None},
        ]
    )
    attrs = contributor_attrs(ci)
    assert "contributor_id" not in attrs
    assert "contributor_email" not in attrs


def test_institutions_are_deduplicated_and_not_positionally_aligned():
    """Two people at one institution yield one institution entry, not two.

    ``contributing_institutions`` therefore must NOT be zipped with
    ``contributor_name``.
    """
    ci = _cruise_info(
        contributors=[
            {"name": "A Person", "role": "PI", "institution": "ub"},
            {"name": "B Person", "role": "PI", "institution": "ub"},
        ]
    )
    attrs = contributor_attrs(ci)
    assert len(attrs["contributing_institutions"].split(";")) == 1
    assert len(attrs["contributor_name"].split(";")) == 2


def test_institution_names_may_contain_commas_but_never_semicolons():
    """EDMO's official names contain commas — the reason semicolon is the delimiter."""
    for slug, entry in load_institutions().items():
        assert ";" not in entry["name"], slug


def test_separator_is_semicolon():
    assert SEPARATOR.strip() == ";"


def test_creator_is_separate_from_contributors():
    attrs = contributor_attrs(_cruise_info())
    assert attrs["creator_name"] == "Eleanor Frajka-Williams"
    assert ";" not in attrs["creator_name"]


def test_absent_contributors_warns_and_returns_no_attrs():
    errors, warnings = check_contributors({})
    assert not errors
    assert any("contributors is absent" in w for w in warnings)
    assert contributor_attrs({}) == {}
