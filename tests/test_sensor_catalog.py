"""Tests for ``processors/sensor_catalog.py`` — the catalog reader and per-number collapse."""

from __future__ import annotations

from ctdcast.processors.sensor_catalog import catalog_by_cast_number


def _rec(role: str, name: str) -> dict:
    return {"role": role, "name": name, "channel": 0, "attrs": {}}


def _pair(t1: str, c1: str) -> list[dict]:
    return [_rec("temperature_1", t1), _rec("conductivity_1", c1)]


def test_collapse_keeps_one_catalog_per_number() -> None:
    per_identity = [((10, ""), _pair("T_A", "C_A")), ((11, ""), _pair("T_B", "C_B"))]
    by_number, warnings = catalog_by_cast_number(per_identity)
    assert set(by_number) == {10, 11}
    assert warnings == []


def test_siblings_with_same_serials_do_not_warn() -> None:
    # 010 and 010b, identical hardware -> the per-number declaration fits both, no warning.
    per_identity = [((10, ""), _pair("T_A", "C_A")), ((10, "b"), _pair("T_A", "C_A"))]
    by_number, warnings = catalog_by_cast_number(per_identity)
    assert set(by_number) == {10}
    assert warnings == []


def test_catalog_less_sibling_does_not_warn() -> None:
    # A catalog-less cast (empty records) sharing a number with a catalogued sibling must
    # NOT raise a spurious "different serials" warning — an empty signature isn't a mismatch.
    per_identity = [((10, ""), _pair("T_A", "C_A")), ((10, "b"), [])]
    by_number, warnings = catalog_by_cast_number(per_identity)
    assert set(by_number) == {10}
    assert warnings == []
    # the catalogued sibling's records are kept, not clobbered by the empty one
    assert by_number[10] == _pair("T_A", "C_A")


def test_siblings_with_different_serials_warn() -> None:
    # 010 and 010b swapped the temperature sensor -> the per-number declaration cannot
    # distinguish them, so the collapse flags it explicitly (decision J caveat).
    per_identity = [((10, ""), _pair("T_A", "C_A")), ((10, "b"), _pair("T_A2", "C_A"))]
    by_number, warnings = catalog_by_cast_number(per_identity)
    assert set(by_number) == {10}
    assert any("different sensor serials" in w for w in warnings)
    assert any("010" in w and "010b" in w for w in warnings)
