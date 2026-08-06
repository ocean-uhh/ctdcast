"""Tests for ctdcast.identity: cast_id_from_name, expand_cast_numbers, compact_cast_list."""

import pytest

from ctdcast.identity import (
    cast_id_from_name,
    compact_cast_list,
    expand_cast_numbers,
)


def test_expand_preserves_order_no_sort():
    # Ranges expand in place; individuals stay where written; no reordering.
    assert expand_cast_numbers([[3, 5], 1, [8, 9]]) == [3, 4, 5, 1, 8, 9]
    assert expand_cast_numbers([12, 11, 10]) == [12, 11, 10]


def test_expand_keeps_duplicates():
    # A cast listed twice stays twice (may double-plot); no dedup.
    assert expand_cast_numbers([1, 1, [2, 3], 2]) == [1, 1, 2, 3, 2]


def test_expand_single_range():
    assert expand_cast_numbers([[11, 14]]) == [11, 12, 13, 14]


def test_expand_descending_range_is_empty():
    # range(5, 3+1) is empty — an inverted range yields nothing, not a raise.
    assert expand_cast_numbers([[5, 3]]) == []


def test_expand_empty():
    assert expand_cast_numbers([]) == []


def test_expand_raises_on_string():
    with pytest.raises(ValueError):
        expand_cast_numbers(["42"])


def test_expand_raises_on_wrong_length_list():
    with pytest.raises(ValueError):
        expand_cast_numbers([[1, 2, 3]])


def test_expand_raises_on_bool():
    # bool subclasses int but is not a valid cast number.
    with pytest.raises(ValueError):
        expand_cast_numbers([True])


def test_expand_raises_on_non_int_range_endpoint():
    with pytest.raises(ValueError):
        expand_cast_numbers([[1, "5"]])


def test_cast_id_directly_appended_suffix():
    assert cast_id_from_name("mixsed2_004b") == (4, "b")


def test_cast_id_underscore_separated_suffix():
    assert cast_id_from_name("mixsed2_004_b") == (4, "b")


def test_cast_id_plain():
    assert cast_id_from_name("mixsed2_011") == (11, "")


def test_cast_id_ignores_leading_leg_number():
    # The last 3+-digit group is the cast (001), not the leg number (142).
    assert cast_id_from_name("msm_142_1_001_1sec") == (1, "")


def test_cast_id_none_when_no_digits():
    assert cast_id_from_name("nodigits") is None


def test_compact_cast_list_collapses_runs():
    assert compact_cast_list([131, 133, 134, 136, 163]) == "131, 133–134, 136, 163"


def test_compact_cast_list_empty():
    assert compact_cast_list([]) == "—"
