"""Shared paths and fixtures for the ctdreport test suite."""

from pathlib import Path

import pytest
import xarray as xr

import ctdreport.plots as _plots

# Surface plotting failures as test errors rather than silently returning None.
_plots.RAISE_ON_PLOT_ERROR = True

_HERE = Path(__file__).parent
FIXTURES_NC = _HERE / "fixtures" / "nc"
FIXTURES_LADCP = _HERE / "fixtures" / "ladcp"

CAST_011 = FIXTURES_NC / "mixsed2_011.nc"
CAST_012 = FIXTURES_NC / "mixsed2_012.nc"
CAST_128 = FIXTURES_NC / "mixsed2_128.nc"
CAST_129 = FIXTURES_NC / "mixsed2_129.nc"


@pytest.fixture
def ds_011():
    """Open cast 011 dataset."""
    ds = xr.open_dataset(CAST_011, engine="netcdf4")
    yield ds
    ds.close()


@pytest.fixture
def ds_128():
    """Open cast 128 dataset (deep repeat station)."""
    ds = xr.open_dataset(CAST_128, engine="netcdf4")
    yield ds
    ds.close()
