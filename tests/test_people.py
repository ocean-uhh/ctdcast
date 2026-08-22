"""Tests for :mod:`ctdcast.config.people` — contributors and institutions."""

from __future__ import annotations

import pytest

from ctdcast.config.people import (
    C89_ROLES,
    SEPARATOR,
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
            "orcid": "0000-0001-8773-7838",
        },
        "institutions": ["uhh", "ub"],
        "contributors": [
            {
                "name": "Eleanor Frajka-Williams",
                "role": "PS",
                "orcid": "0000-0001-8773-7838",
            },
            {"name": "David Amblas", "role": "PI", "orcid": None},
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
    ci = _cruise_info(contributors=[{"name": bad_name, "role": "PI"}])
    errors, _ = check_contributors(ci)
    assert any("contains" in e for e in errors)


def test_delimiter_checked_in_email_too():
    ci = _cruise_info(
        contributors=[{"name": "A Person", "role": "PI", "email": "a@b.org, c@d.org"}]
    )
    errors, _ = check_contributors(ci)
    assert any(".email contains" in e for e in errors)


# --- roles ------------------------------------------------------------------


def test_role_must_be_a_c89_term():
    """ "Chief Scientist" is the everyday phrase; C89 spells it differently."""
    ci = _cruise_info(contributors=[{"name": "A Person", "role": "Chief Scientist"}])
    errors, _ = check_contributors(ci)
    assert any("C89" in e for e in errors)


def test_every_c89_code_and_label_is_accepted():
    for code, label in C89_ROLES.items():
        for given in (code, label):
            ci = _cruise_info(contributors=[{"name": "A Person", "role": given}])
            errors, _ = check_contributors(ci)
            assert not errors, f"role {given!r} rejected: {errors}"


def test_chief_scientist_has_a_real_controlled_term():
    """C89 PS is the chief scientist -- a genuine match, not an approximation.

    Its definition: "The senior manager of the scientific party on a research
    cruise, which may include management responsibility for scientific
    instrumentation technicians."
    """
    assert C89_ROLES["PS"] == "Cruise principal scientist"
    ci = _cruise_info(contributors=[{"name": "A Person", "role": "PS"}])
    errors, _ = check_contributors(ci)
    assert not errors
    attrs = contributor_attrs(ci)
    assert attrs["contributor_role"] == "Cruise principal scientist"
    assert attrs["contributor_role_vocabulary"].endswith("C89/current/")


def test_role_code_and_label_produce_identical_output():
    by_code = contributor_attrs(
        _cruise_info(contributors=[{"name": "X", "role": "PS"}])
    )
    by_label = contributor_attrs(
        _cruise_info(contributors=[{"name": "X", "role": "Cruise principal scientist"}])
    )
    assert by_code == by_label


def test_c89_separates_the_three_investigator_senses():
    """The distinction G04 cannot express: all three flatten to one term."""
    assert C89_ROLES["PI"] == "Project principal investigator"
    assert C89_ROLES["DI"] == "Cruise dataset principal investigator"
    assert C89_ROLES["PS"] == "Cruise principal scientist"


def test_no_lead_role_warns():
    """A cruise of participants and technicians with nobody leading it."""
    ci = _cruise_info(
        contributors=[
            {"name": "A Person", "role": "CP"},
            {"name": "B Person", "role": "TS"},
        ]
    )
    errors, warnings = check_contributors(ci)
    assert not errors
    assert any("lead role" in w for w in warnings)


# --- one person, several roles ---------------------------------------------


def test_roles_list_gives_one_slot_per_role():
    """`roles: [PS, PI]` — one entry in config, two positions in the file."""
    ci = _cruise_info(
        contributors=[
            {"name": "A Person", "orcid": "0000-0001-8773-7838", "roles": ["PS", "PI"]}
        ]
    )
    errors, _ = check_contributors(ci)
    assert not errors
    attrs = contributor_attrs(ci)
    assert attrs["contributor_name"].split("; ") == ["A Person", "A Person"]
    assert attrs["contributor_role"].split("; ") == [
        "Cruise principal scientist",
        "Project principal investigator",
    ]
    # Stated once in config, so the repeated identifiers cannot disagree.
    ids = attrs["contributor_id"].split("; ")
    assert ids[0] == ids[1]


def test_scoped_roles_select_per_product():
    """`roles: {all: [...], ctd: [...]}` — a role that applies to one file only."""
    ci = _cruise_info(
        contributors=[
            {"name": "A Person", "roles": {"all": ["PI"], "ctd": ["DC"]}},
            {"name": "B Person", "roles": {"ladcp": ["DI"]}},
        ]
    )
    errors, _ = check_contributors(ci)
    assert not errors

    ctd = contributor_attrs(ci, source="ctd")
    assert ctd["contributor_name"].split("; ") == ["A Person", "A Person"]
    assert "B Person" not in ctd["contributor_name"]

    ladcp = contributor_attrs(ci, source="ladcp")
    assert ladcp["contributor_name"].split("; ") == ["A Person", "B Person"]
    assert ladcp["contributor_role"].split("; ") == [
        "Project principal investigator",
        "Cruise dataset principal investigator",
    ]


def test_unknown_scope_is_an_error():
    """A typo'd scope would silently drop a person from every file."""
    ci = _cruise_info(
        contributors=[{"name": "A Person", "roles": {"all": ["PI"], "ctdd": ["DC"]}}]
    )
    errors, _ = check_contributors(ci)
    assert any("unknown scope" in e for e in errors)


def test_a_person_with_no_role_in_scope_is_omitted_entirely():
    ci = _cruise_info(contributors=[{"name": "Only LADCP", "roles": {"ladcp": ["DI"]}}])
    assert contributor_attrs(ci, source="ctd").get("contributor_name") is None


def test_a_person_may_hold_several_roles_by_repeating_the_entry():
    """The parallel strings are positional, so one slot cannot carry two roles.

    Repeating the person once per role is the representation, and must not be
    flagged as a duplicate.
    """
    ci = _cruise_info(
        contributors=[
            {
                "name": "Eleanor Frajka-Williams",
                "role": "PS",
                "orcid": "0000-0001-8773-7838",
            },
            {
                "name": "Eleanor Frajka-Williams",
                "role": "MC",
                "orcid": "0000-0001-8773-7838",
            },
        ]
    )
    errors, warnings = check_contributors(ci)
    assert not errors
    assert not any("duplicate" in w.lower() for w in warnings)

    attrs = contributor_attrs(ci)
    assert attrs["contributor_name"].count("Eleanor Frajka-Williams") == 2
    assert (
        attrs["contributor_role"] == "Cruise principal scientist; Cruise data manager"
    )
    assert len(attrs["contributor_id"].split(";")) == 2


def test_repeating_a_person_with_a_different_orcid_is_an_error():
    """Two ORCIDs for one name would be a false claim about a real person."""
    ci = _cruise_info(
        contributors=[
            {"name": "A Person", "role": "PS", "orcid": "0000-0001-8773-7838"},
            {"name": "A Person", "role": "MC", "orcid": "0000-0002-1825-009X"},
        ]
    )
    errors, _ = check_contributors(ci)
    assert any("different" in e and "ORCID" in e for e in errors)


# --- institutions -----------------------------------------------------------


def test_institution_on_a_person_is_rejected():
    """Institutions are a separate list; they do not belong on a contributor."""
    ci = _cruise_info(
        contributors=[{"name": "A Person", "role": "PI", "institution": "uhh"}]
    )
    errors, _ = check_contributors(ci)
    assert any("does not belong on a person" in e for e in errors)


def test_unknown_institution_slug_is_an_error():
    ci = _cruise_info(institutions=["uhh", "nope"])
    errors, _ = check_contributors(ci)
    assert any("institutions.yaml" in e for e in errors)


def test_institutions_are_independent_of_the_people_list():
    """Two institutions, three people, no correspondence between them."""
    ci = _cruise_info(
        institutions=["uhh", "ub"],
        contributors=[
            {"name": "A Person", "role": "PS"},
            {"name": "B Person", "role": "PI"},
            {"name": "C Person", "role": "CP"},
        ],
    )
    attrs = contributor_attrs(ci)
    assert len(attrs["contributing_institutions"].split(";")) == 2
    assert len(attrs["contributor_name"].split(";")) == 3


def test_institution_order_is_preserved_not_sorted():
    a = contributor_attrs(_cruise_info(institutions=["ub", "uhh"]))
    b = contributor_attrs(_cruise_info(institutions=["uhh", "ub"]))
    assert a["contributing_institutions"] != b["contributing_institutions"]


def test_institution_names_may_contain_commas_but_never_semicolons():
    """EDMO's official names contain commas — the reason semicolon is the delimiter."""
    for slug, entry in load_institutions().items():
        assert ";" not in entry["name"], slug


def test_absent_institutions_warns():
    ci = _cruise_info()
    del ci["institutions"]
    errors, warnings = check_contributors(ci)
    assert not errors
    assert any("institutions is absent" in w for w in warnings)


# --- ORCIDs -----------------------------------------------------------------


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
    ci = _cruise_info(contributors=[{"name": "A Person", "role": "PI", "orcid": given}])
    errors, _ = check_contributors(ci)
    assert not errors
    attrs = contributor_attrs(ci)
    assert attrs["contributor_id"] == "https://orcid.org/0000-0001-8773-7838"


def test_orcid_with_a_checksum_x_is_accepted():
    ci = _cruise_info(
        contributors=[
            {"name": "A Person", "role": "PI", "orcid": "0000-0002-1825-009X"}
        ]
    )
    errors, _ = check_contributors(ci)
    assert not errors


@pytest.mark.parametrize(
    "bad", ["0000-0001-8773", "not-an-orcid", "0000-0001-8773-78380"]
)
def test_malformed_orcid_is_an_error(bad):
    ci = _cruise_info(contributors=[{"name": "A Person", "role": "PI", "orcid": bad}])
    errors, _ = check_contributors(ci)
    assert any("orcid" in e for e in errors)


def test_missing_orcid_warns_but_does_not_fail():
    """Absent ORCIDs are legitimate mid-cruise; they must be settled before release."""
    errors, warnings = check_contributors(_cruise_info())
    assert not errors
    assert any("no ORCID" in w for w in warnings)


# --- generated attributes ---------------------------------------------------


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
            {"name": "A Person", "role": "PI", "orcid": None},
            {"name": "B Person", "role": "PI", "orcid": None},
        ]
    )
    attrs = contributor_attrs(ci)
    assert "contributor_id" not in attrs
    assert "contributor_email" not in attrs


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


# --- CF `institution` is a derived view, not a claim -------------------------


def test_institution_is_the_joined_lead_entries():
    """CF `institution` projects the lead entries of contributing_institutions.

    Not one of them: several institutions really were aboard and contributing,
    so naming one would be false where naming all the leads is merely coarse.
    """
    attrs = contributor_attrs(
        _cruise_info(
            institutions=[
                {"slug": "uhh", "role": "CONLEAD"},
                {"slug": "ulpgc", "role": "CONLEAD"},
                {"slug": "ub", "role": "CONMEM"},
            ]
        )
    )
    names = attrs["institution"].split(SEPARATOR)
    assert len(names) == 2
    assert all(n in attrs["contributing_institutions"] for n in names)
    assert "Barcelona" not in attrs["institution"]  # CONMEM is not a lead


def test_institution_never_disagrees_with_contributing_institutions():
    """It is a projection, so every name in it must appear in the source list."""
    attrs = contributor_attrs(
        _cruise_info(institutions=[{"slug": "uhh", "role": "CONLEAD"}, "ub"])
    )
    for name in attrs["institution"].split(SEPARATOR):
        assert name in attrs["contributing_institutions"].split(SEPARATOR)


def test_institution_is_omitted_when_nothing_leads():
    """An absent attribute asserts nothing; a guessed one misattributes the work."""
    ci = _cruise_info(institutions=["uhh", "ub"])  # both default to CONMEM
    attrs = contributor_attrs(ci)
    assert "institution" not in attrs
    _, warnings = check_contributors(ci)
    assert any("lead role" in w for w in warnings)


def test_the_creator_carries_no_institution():
    """The creator is a person identified by ORCID; institutions come only from
    `institutions:`, so nothing about them can drift from that one list."""
    ci = _cruise_info(
        institutions=[{"slug": "ulpgc", "role": "CONLEAD"}],
        creator={
            "name": "Someone",
            "type": "person",
            "orcid": "0000-0001-8773-7838",
        },
    )
    attrs = contributor_attrs(ci)
    assert "creator_institution" not in attrs
    assert "creator_institution_id" not in attrs
    assert attrs["creator_id"].startswith("https://orcid.org/")
    assert "Las Palmas" in attrs["institution"]


def test_creator_institution_key_warns_rather_than_silently_doing_nothing():
    """A key that stopped being emitted must say so, not vanish quietly."""
    ci = _cruise_info()
    ci["creator"] = {**ci["creator"], "institution": "uhh"}
    errors, warnings = check_contributors(ci)
    assert not errors
    assert any("creator.institution" in w for w in warnings)


def test_no_institution_id_is_emitted():
    """Identifiers belong to contributing_institutions_id, beside their roles."""
    attrs = contributor_attrs(
        _cruise_info(institutions=[{"slug": "uhh", "role": "CONLEAD"}])
    )
    assert "institution_id" not in attrs
    assert attrs["contributing_institutions_id"].startswith("https://")


def test_setting_institution_in_config_is_an_error():
    """One source of truth: the roles say who led, not a second free-text key."""
    errors, _ = check_contributors(_cruise_info(institution="uhh"))
    assert any("not a config key" in e for e in errors)


def test_institution_ids_go_to_the_id_attribute_not_vocabulary():
    """OG1 calls this `_vocabulary`; the content is identifiers, so we do not."""
    attrs = contributor_attrs(_cruise_info(institutions=["uhh", "ub"]))
    assert "contributing_institutions_vocabulary" not in attrs
    assert attrs["contributing_institutions_id"].count(SEPARATOR) == 1


def test_only_one_family_of_institution_attributes_is_written():
    """`institution` + `contributing_institutions*`, and nothing else."""
    attrs = contributor_attrs(
        _cruise_info(institutions=[{"slug": "uhh", "role": "CONLEAD"}])
    )
    written = {k for k in attrs if "institution" in k}
    assert written == {
        "institution",
        "contributing_institutions",
        "contributing_institutions_id",
        "contributing_institutions_role",
        "contributing_institutions_role_vocabulary",
    }


# --- code-review findings, 2026-08-22 ---------------------------------------


def test_same_orcid_in_both_accepted_forms_is_not_a_conflict():
    """`orcid_uri` promises both forms are accepted, so comparing raw strings
    would reject a config that merely typed one entry each way."""
    errors, _ = check_contributors(
        _cruise_info(
            contributors=[
                {"name": "A Person", "role": "PS", "orcid": "0000-0001-8773-7838"},
                {
                    "name": "A Person",
                    "role": "PI",
                    "orcid": "https://orcid.org/0000-0001-8773-7838",
                },
            ]
        )
    )
    assert not errors


def test_genuinely_different_orcids_for_one_name_still_error():
    errors, _ = check_contributors(
        _cruise_info(
            contributors=[
                {"name": "A Person", "role": "PS", "orcid": "0000-0001-8773-7838"},
                {"name": "A Person", "role": "PI", "orcid": "0000-0002-1825-0097"},
            ]
        )
    )
    assert any("different" in e for e in errors)


def test_orcid_on_only_some_entries_for_one_person_errors():
    """The emitted contributor_id would carry a filled slot and a blank one for
    the same person, which reads as two people."""
    errors, _ = check_contributors(
        _cruise_info(
            contributors=[
                {"name": "A Person", "role": "PS", "orcid": "0000-0001-8773-7838"},
                {"name": "A Person", "role": "PI"},
            ]
        )
    )
    assert any("only some" in e for e in errors)


def test_unquoted_numeric_role_says_so_rather_than_unknown_term():
    """YAML turns `role: 8` into an int; G04 codes are zero-padded strings."""
    errors, _ = check_contributors(
        _cruise_info(
            role_vocabulary="G04",
            contributors=[{"name": "X", "role": 8, "orcid": None}],
        )
    )
    assert any("parsed as int" in e for e in errors)


def test_lead_scoped_to_one_product_does_not_vouch_for_the_other():
    """Counting leads over the scope union hid a CTD file with no lead at all."""
    _, warnings = check_contributors(
        _cruise_info(
            contributors=[
                {"name": "X", "roles": {"ladcp": ["PS"], "ctd": ["CO"]}, "orcid": None}
            ]
        )
    )
    assert any("lead role in the ctd" in w for w in warnings)


def test_unknown_role_raises_rather_than_writing_a_blank_slot():
    """The parallel strings are positional: a "" role would line up with every
    other slot and read as a deliberate attribution of nothing."""
    with pytest.raises(ValueError, match="not a term"):
        contributor_attrs(
            _cruise_info(contributors=[{"name": "X", "role": "NOPE", "orcid": None}])
        )
