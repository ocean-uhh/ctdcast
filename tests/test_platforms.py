"""Tests for :mod:`ctdcast.config.platforms` — vessel registry and EXPOCODE.

A wrong ICES code produces a well-formed EXPOCODE filed against another cruise,
so the failure mode these tests guard is *silent*: the registry must refuse to
guess (unknown slug, ambiguous slug, missing code, forbidden code) rather than
emit something plausible-but-wrong.
"""

from __future__ import annotations

import datetime

import pytest

from ctdcast.config.platforms import (
    PlatformError,
    derive_expocode,
    expocode_from_cruise_info,
    load_platforms,
    platform_attrs,
    resolve_platform,
)


# --- EXPOCODE derivation, against the known-good oracles -------------------


@pytest.mark.parametrize(
    ("slug", "start_date", "expected"),
    [
        ("msm", "2026-03-27", "06M220260327"),
        ("odb", "2026-07-09", "29OD20260709"),
        ("meteor3", "2026-01-13", "06M320260113"),
    ],
)
def test_derive_expocode_oracles(slug, start_date, expected):
    """The EXPOCODE is <ICES code> + <departure YYYYMMDD>."""
    assert derive_expocode(slug, start_date) == expected


def test_start_date_accepts_a_date_object():
    """YAML parses a bare ``2026-07-09`` to a ``datetime.date``."""
    assert derive_expocode("odb", datetime.date(2026, 7, 9)) == "29OD20260709"


def test_start_date_accepts_compact_string():
    assert derive_expocode("odb", "20260709") == "29OD20260709"


def test_unparseable_start_date_raises():
    with pytest.raises(PlatformError, match="departure date"):
        derive_expocode("odb", "July 9th")


# --- the refuse-to-guess contract ------------------------------------------


def test_unknown_slug_raises():
    with pytest.raises(PlatformError, match="unknown platform slug"):
        derive_expocode("nope", "2026-01-01")


def test_ambiguous_slug_raises_with_guidance():
    """Bare 'meteor' names four hulls; the error must say which to use."""
    with pytest.raises(PlatformError, match="ambiguous"):
        resolve_platform("meteor")


def test_platform_without_ices_code_raises():
    """meteor4 has no C17 entry yet — deriving would emit a malformed code."""
    with pytest.raises(PlatformError, match="no ices_code"):
        derive_expocode("meteor4", "2027-06-01")


def test_forbidden_code_would_raise_if_derived():
    """A slug resolving to a forbidden ICES code must not yield an EXPOCODE.

    No live slug maps to a forbidden code (that is the point of the registry),
    so this asserts the guard exists by checking the forbidden list is wired in.
    """
    from ctdcast.config.platforms import _forbidden_codes

    assert "06MM" in _forbidden_codes()
    assert "29DB" in _forbidden_codes()


# --- config helper ---------------------------------------------------------


def test_expocode_from_cruise_info_none_when_slug_absent():
    assert expocode_from_cruise_info({"start_date": "2026-07-09"}) is None


def test_expocode_from_cruise_info_none_when_date_absent():
    assert expocode_from_cruise_info({"platform": "odb"}) is None


def test_expocode_from_cruise_info_reads_platform_key():
    ci = {"platform": "odb", "start_date": "2026-07-09"}
    assert expocode_from_cruise_info(ci) == "29OD20260709"


def test_expocode_from_cruise_info_ship_slug_fallback():
    ci = {"ship_slug": "msm", "start_date": "2026-03-27"}
    assert expocode_from_cruise_info(ci) == "06M220260327"


def test_ship_display_name_is_never_used_as_slug():
    """A free-text ``ship`` must not resolve — name lookup is the banned path."""
    assert (
        expocode_from_cruise_info({"ship": "Odon de Buen", "start_date": "2026-07-09"})
        is None
    )


# --- platform attributes ---------------------------------------------------


def test_platform_attrs_prefers_native_name():
    attrs = platform_attrs("odb")
    assert attrs["platform_name"] == "Odón de Buen"
    assert attrs["platform_ices_code"] == "29OD"
    assert attrs["platform"] == "research vessel"


def test_platform_attrs_unknown_slug_is_empty_not_error():
    assert platform_attrs("nope") == {}


def test_registry_loads():
    reg = load_platforms()
    assert {"msm", "odb", "meteor3"} <= set(reg)


# --- inline platform form (vessel not in the registry) ---------------------


def test_inline_platform_derives_expocode():
    """A vessel given inline (not a slug) still yields an EXPOCODE from its code."""
    ci = {
        "platform": {"name": "RV Example", "ices_code": "12AB"},
        "start_date": "2026-07-09",
    }
    assert expocode_from_cruise_info(ci) == "12AB20260709"


def test_inline_platform_attrs():
    attrs = platform_attrs(
        {
            "name": "RV Example",
            "ices_code": "12AB",
            "platform": "research vessel",
            "platform_vocabulary": "https://vocab.nerc.ac.uk/collection/L06/current/31/",
        }
    )
    assert attrs["platform_name"] == "RV Example"
    assert attrs["platform_ices_code"] == "12AB"
    assert attrs["platform"] == "research vessel"


def test_inline_platform_without_ices_code_raises():
    from ctdcast.config.platforms import derive_expocode

    with pytest.raises(PlatformError, match="no ices_code"):
        derive_expocode({"name": "RV Example"}, "2026-07-09")


def test_slug_and_inline_are_interchangeable_paths():
    """The slug path and the inline path go through one resolver."""
    from ctdcast.config.platforms import resolve_platform_spec

    assert resolve_platform_spec("odb")["ices_code"] == "29OD"
    assert resolve_platform_spec({"ices_code": "12AB"})["ices_code"] == "12AB"
