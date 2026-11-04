"""Shared paths and fixtures for the ctdcast test suite."""

from pathlib import Path

import matplotlib
import pytest
import xarray as xr

# Force non-interactive backend before any other matplotlib import.
# Without this, Windows CI fails with a TclError when matplotlib tries to
# initialise the Tk backend on a runner where Tcl/Tk is not installed.
matplotlib.use("Agg")

import ctdcast.reports._vendored.design_tokens as _report_tokens

# Surface plotting failures as test errors rather than silently returning None.
# The flag lives in report_tokens (a leaf both plotters and the encoder read
# live); setting it here governs both.
_report_tokens.RAISE_ON_PLOT_ERROR = True

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


@pytest.fixture(scope="session")
def hex_stage2(tmp_path_factory):
    """The committed OdB .hex slice (cast 011, 24 Hz), through stages 1 and 2."""
    import shutil
    import warnings

    from ctdcast.processors.stage1 import stage1
    from ctdcast.processors.stage2 import run as stage2_run

    fix = Path(__file__).parent / "fixtures"
    tmp = tmp_path_factory.mktemp("hex_stage2")
    raw = tmp / "raw"
    raw.mkdir()
    for name in ("MIXSED2_011.hex", "MIXSED2_011.XMLCON"):
        shutil.copy(fix / "hex_slice" / name, raw / name)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stage1(raw, tmp / "ctd", backend="hex", pattern="*.[hH][eE][xX]")
        stage2_run(tmp / "ctd")
    path = next((tmp / "ctd" / "stage2").glob("*.nc"))
    with xr.open_dataset(path, engine="netcdf4") as ds:
        return ds.load()
