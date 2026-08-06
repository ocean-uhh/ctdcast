"""Tests for ctdcast.identity: cast_id_from_name, expand_cast_ids/numbers, compact_cast_list."""

import pytest

from ctdcast.identity import (
    cast_id_from_name,
    compact_cast_list,
    expand_cast_ids,
    expand_cast_numbers,
)


def test_expand_ids_plain_int_and_range():
    # Bare ints and ranges are plain events (empty suffix).
    assert expand_cast_ids([10]) == [(10, "")]
    assert expand_cast_ids([[9, 11]]) == [(9, ""), (10, ""), (11, "")]


def test_expand_ids_suffix_string():
    # A "NNNb" string names the lettered sibling event.
    assert expand_cast_ids(["10b"]) == [(10, "b")]
    assert expand_cast_ids(["010b"]) == [(10, "b")]
    assert expand_cast_ids(["10"]) == [(10, "")]


def test_expand_ids_plain_and_sibling_are_distinct():
    # 10 and 10b are separate events, kept as separate pairs (no false dedup).
    assert expand_cast_ids([10, "10b"]) == [(10, ""), (10, "b")]


def test_expand_ids_preserves_order_no_sort():
    assert expand_cast_ids([[3, 5], 1, "8b"]) == [
        (3, ""),
        (4, ""),
        (5, ""),
        (1, ""),
        (8, "b"),
    ]


def test_expand_numbers_is_integer_view():
    # expand_cast_numbers drops the suffix; "10b" contributes station 10.
    assert expand_cast_numbers([[9, 11], "10b", 12]) == [9, 10, 11, 10, 12]


def test_expand_keeps_duplicates():
    assert expand_cast_numbers([1, 1, [2, 3], 2]) == [1, 1, 2, 3, 2]


def test_expand_descending_range_is_empty():
    assert expand_cast_ids([[5, 3]]) == []


def test_expand_empty():
    assert expand_cast_ids([]) == []
    assert expand_cast_numbers([]) == []


def test_expand_raises_on_malformed_string():
    for bad in ["x", "1-2", ""]:
        with pytest.raises(ValueError):
            expand_cast_ids([bad])


def test_expand_raises_on_wrong_length_list():
    with pytest.raises(ValueError):
        expand_cast_ids([[1, 2, 3]])


def test_expand_raises_on_bool():
    # bool subclasses int but is not a valid cast number.
    with pytest.raises(ValueError):
        expand_cast_ids([True])


def test_expand_raises_on_non_int_range_endpoint():
    with pytest.raises(ValueError):
        expand_cast_ids([[1, "5"]])


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
