"""Tests for the LADCP reader/processor provenance behaviour."""

import warnings

import pytest
from conftest import FIXTURES_LADCP

from ctdcast.readers.ladcp import _SOURCE_MAP, read_ladcp_cast

MAT_011 = FIXTURES_LADCP / "011.mat"


@pytest.fixture
def cast_011():
    """Single-cast LADCP Dataset from the 011 fixture (serial is blank in the .mat)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return read_ladcp_cast(MAT_011, cast_num=11)


def test_blank_serial_flagged_as_unk(cast_011):
    """A blank (nan) hardware serial is recorded as 'UNK', not a silent nan."""
    # The 011 fixture has LADCP_dn_hard_SN = nan.
    assert cast_011.attrs.get("ladcp_downlooker_serial") == "UNK"


def test_blank_serial_emits_warning():
    """Reading a cast with a blank serial warns rather than failing silently."""
    with pytest.warns(UserWarning, match="serial number is blank"):
        read_ladcp_cast(MAT_011, cast_num=11)


def test_source_variable_recorded(cast_011):
    """Each mapped variable carries its .mat source field as source_variable."""
    assert cast_011["u"].attrs.get("source_variable") == "dr.u"
    assert cast_011["u_shear"].attrs.get("source_variable") == "dr.u_shear_method"
    assert cast_011["depth"].attrs.get("source_variable") == "dr.z"


def test_source_map_covers_present_variables(cast_011):
    """Every _SOURCE_MAP key that exists in the dataset is a real variable."""
    present = [k for k in _SOURCE_MAP if k in cast_011.variables]
    assert "u" in present and "v" in present
    for name in present:
        assert cast_011[name].attrs.get("source_variable") == _SOURCE_MAP[name]


def test_inventory_renaming_table_from_source_variable(tmp_path):
    """The netCDF-inventory renaming table is built from source_variable."""
    from ctdcast.processors.ladcp import convert_ladcp_cast
    from ctdcast.reports._dataset import read_dataset_meta

    out = tmp_path / "ladcp_011.nc"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        convert_ladcp_cast(MAT_011, out, cast_num=11, force=True)
    rename_map = read_dataset_meta(out)["rename_map"]
    assert rename_map.get("dr.u") == "u"
    assert rename_map.get("dr.lat") == "latitude"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
