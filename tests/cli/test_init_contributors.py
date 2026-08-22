"""Tests for the interactive contributor/platform prompting in ``ctdcast init``."""

from __future__ import annotations

import yaml

from ctdcast.cli.init import (
    _build_config_text,
    _format_contributors_yaml,
    _resolve_role,
)
from ctdcast.config.people import check_contributors, role_choices

_ROLES = role_choices()


def test_resolve_role_by_number():
    assert _resolve_role("1", _ROLES) == _ROLES[0]
    assert _resolve_role(str(len(_ROLES)), _ROLES) == _ROLES[-1]


def test_resolve_role_by_name_case_insensitive():
    assert _resolve_role("cruise principal scientist", _ROLES) == (
        "Cruise principal scientist"
    )
    # A concept code is equally valid in config, so the prompt accepts it too.
    assert _resolve_role("PS", _ROLES) == "Cruise principal scientist"


def test_resolve_role_unknown_defaults_to_pi():
    assert _resolve_role("chief scientist", _ROLES) == "PI"
    assert _resolve_role("99", _ROLES) == "PI"


def test_empty_contributors_block_is_commented_and_parses():
    block = _format_contributors_yaml([])
    assert block.lstrip().startswith("#")
    # embedded under cruise_info, it must not break YAML parsing
    doc = yaml.safe_load("cruise_info:\n  ship: X\n" + block)
    assert "contributors" not in doc["cruise_info"]


def test_generated_config_with_contributors_parses_and_validates():
    txt = _build_config_text(
        nc_dir="/d/nc",
        cnv_dir=None,
        cnv_pattern=None,
        profiles_nc="/d/p.nc",
        ladcp_dir=None,
        ladcp_pattern=None,
        gebco_nc=None,
        section_yaml=None,
        output_dir="out",
        cruise_name="odb2026",
        ship="Odon de Buen",
        start_date="2026-07-09",
        end_date="2026-07-31",
        platform="odb",
        contributors=[
            {"name": "E F-W", "role": "PI", "orcid": "0000-0001-8773-7838"},
            {"name": "Angel Ruiz-Angulo", "role": "MC"},
        ],
    )
    doc = yaml.safe_load(txt)
    ci = doc["cruise_info"]
    assert ci["cruise_id"] == "odb2026"  # written under cruise_id, not name
    assert ci["platform"] == "odb"
    assert [c["name"] for c in ci["contributors"]] == ["E F-W", "Angel Ruiz-Angulo"]
    errors, _ = check_contributors(ci)
    assert errors == []
