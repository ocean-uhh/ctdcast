"""Shared paths and fixtures for the ctdcast test suite."""

from pathlib import Path

import matplotlib
import pytest
import xarray as xr

# Force non-interactive backend before any other matplotlib import.
# Without this, Windows CI fails with a TclError when matplotlib tries to
# initialise the Tk backend on a runner where Tcl/Tk is not installed.
matplotlib.use("Agg")

import ctdcast.plotters.plots as _plots

# Surface plotting failures as test errors rather than silently returning None.
_plots.RAISE_ON_PLOT_ERROR = True

_HERE = Path(__file__).parent
FIXTURES_NC = _HERE / "fixtures" / "nc"
FIXTURES_LADCP = _HERE / "fixtures" / "ladcp"
FIXTURES_CNV = _HERE / "fixtures" / "cnv"
FIXTURES_OXY = _HERE / "fixtures" / "oxy"

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
