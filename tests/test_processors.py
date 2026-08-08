"""Tests for ctdcast.processors registry (STAGES, resolve_stage, process API)."""

from __future__ import annotations

import pytest

from ctdcast.processors import STAGES, Stage, resolve_stage


def test_stages_is_nonempty_tuple_of_stage() -> None:
    """STAGES is a non-empty tuple of Stage dataclasses."""
    assert isinstance(STAGES, tuple)
    assert len(STAGES) > 0
    for s in STAGES:
        assert isinstance(s, Stage)


def test_stages_numbered_stages_have_unique_numbers() -> None:
    """Numbered stages each have a distinct positive integer."""
    numbers = [s.number for s in STAGES if s.number is not None]
    assert len(numbers) == len(set(numbers)), "Duplicate stage numbers in STAGES"
    assert all(n > 0 for n in numbers)


def test_resolve_stage_by_number() -> None:
    """resolve_stage(1) returns the stage with number 1."""
    s = resolve_stage(1)
    assert s.number == 1
    assert s.name == "stage1"


def test_resolve_stage_by_name() -> None:
    """resolve_stage('profiles') returns the profiles stage."""
    s = resolve_stage("profiles")
    assert s.name == "profiles"
    assert s.number is None


def test_resolve_stage_name_case_insensitive() -> None:
    """Stage names are matched case-insensitively."""
    assert resolve_stage("STAGE1") == resolve_stage("stage1")


def test_resolve_stage_none_raises() -> None:
    """resolve_stage(None) must raise ValueError, not silently match 'profiles'.

    Stage('profiles', None, ...) has number=None, so without an explicit guard
    None==None would match it via the number comparison.
    """
    with pytest.raises(ValueError, match="None"):
        resolve_stage(None)  # type: ignore[arg-type]


def test_resolve_stage_unknown_raises() -> None:
    """resolve_stage with an unknown value raises ValueError listing valid choices."""
    with pytest.raises(ValueError, match="unknown stage"):
        resolve_stage(99)


def test_resolve_stage_invalid_name_raises() -> None:
    """resolve_stage with an unrecognised name raises ValueError."""
    with pytest.raises(ValueError, match="unknown stage"):
        resolve_stage("bogus")


def test_profiles_stage_has_no_number() -> None:
    """The profiles stage is named-only (number=None) — stage=4 must not match it."""
    profiles = resolve_stage("profiles")
    assert profiles.number is None
    with pytest.raises(ValueError):
        resolve_stage(4)


def test_resolve_stage_bool_raises() -> None:
    """True == 1 in Python, so resolve_stage(True/False) must raise, not match stage1.

    Without the isinstance(stage, bool) guard, resolve_stage(True) silently returned
    the stage-1 Stage object because True == 1.
    """
    with pytest.raises(ValueError):
        resolve_stage(True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        resolve_stage(False)  # type: ignore[arg-type]


def test_resolve_stage_float_resolves() -> None:
    """1.0 == 1 in Python; resolve_stage(1.0) resolves to stage1 (not a defect)."""
    s = resolve_stage(1.0)  # type: ignore[arg-type]
    assert s.number == 1
