"""Oxygen-specific preferred-sensor behaviour.

The generic mechanism (``config/preferred_sensors.py``) and the T/C pair stamp are covered
in ``tests/config/test_preferred_sensors.py`` and ``tests/test_stage3_preferred.py``.  This
file covers the pieces that need an oxygen-shaped dataset: the ``ctd_oxygen_1``/``_2``
line-plumbing assumption comment (R.6), an independent ``preferred_oxygen`` choice that
differs from ``preferred_pair`` (R.4), and the dual-oxygen stamp (the committed fixtures are
single-oxygen, so the second oxygen sensor is synthesised here).
"""

from __future__ import annotations

import warnings

import numpy as np
import xarray as xr
from conftest import FIXTURES_NC

from ctdcast.config.parameters import VARIABLES
from ctdcast.config.sensors import SensorOverrides
from ctdcast.processors.stage1 import _build_cast_sensor_catalog
from ctdcast.processors.stage3 import _stamp_preferred_sensors
from ctdcast.writers.netcdf import write as write_nc

CAST = 11


def _dual_oxygen_ds() -> xr.Dataset:
    """The mixsed2_011 catalog (dual T/C, single O₂) augmented with a secondary oxygen."""
    ds = _build_cast_sensor_catalog(
        xr.open_dataset(FIXTURES_NC / "mixsed2_011.nc", engine="netcdf4"),
        SensorOverrides(),
    )
    ds["SENSOR_OXYGEN_B"] = xr.DataArray(
        np.int32(0), attrs={"sensor_role": "oxygen_2", "sensor_channel": 9}
    )
    return ds


# --- R.6: ctd_oxygen_1/_2 line-plumbing assumption comment -------------------


def test_oxygen_line_assumption_comment_round_trips(tmp_path) -> None:
    """ctd_oxygen_1/_2 carry the line-plumbing assumption comment through the writer."""
    n = 4
    ds = xr.Dataset(
        {
            "ctd_oxygen_1": ("time", np.arange(n, dtype="float32")),
            "ctd_oxygen_2": ("time", np.arange(n, dtype="float32")),
        },
        coords={"time": np.arange(n)},
    )
    out = tmp_path / "cast.nc"
    write_nc(ds, out)
    got = xr.open_dataset(out, engine="netcdf4")
    try:
        c1 = got["ctd_oxygen_1"].attrs["comment"]
        c2 = got["ctd_oxygen_2"].attrs["comment"]
        assert "primary" in c1 and "sbox0" in c1
        assert "secondary" in c2 and "sbox1" in c2
    finally:
        got.close()


def test_line_assumption_lives_in_variables() -> None:
    """The assumption is declared in VARIABLES (one source), not hard-coded in the writer."""
    assert "sbox0" in VARIABLES["ctd_oxygen_1"]["comment"]
    assert "sbox1" in VARIABLES["ctd_oxygen_2"]["comment"]


# --- R.4: preferred_oxygen is independent of preferred_pair -------------------


def test_oxygen_and_pair_choices_independent_both_stamped() -> None:
    """preferred_oxygen != preferred_pair is valid: both stamp, neither warns."""
    ds = _dual_oxygen_ds()
    cfg = {
        "preferred_pair": {"default": "primary"},
        "preferred_oxygen": {"default": "secondary"},
    }
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # the stamp must emit no warning here
        _stamp_preferred_sensors(ds, cfg, CAST)
    assert ds.attrs["preferred_pair"] == "primary"
    assert ds.attrs["preferred_oxygen"] == "secondary"
    assert ds.attrs["sensor_temperature_preferred"] == "SENSOR_TEMPERATURE_6435"
    assert ds.attrs["sensor_oxygen_preferred"] == "SENSOR_OXYGEN_B"


def test_dual_oxygen_primary_stamp_selects_the_primary_sensor() -> None:
    ds = _dual_oxygen_ds()
    _stamp_preferred_sensors(ds, {"preferred_oxygen": {"default": "primary"}}, CAST)
    assert ds.attrs["preferred_oxygen"] == "primary"
    assert ds.attrs["sensor_oxygen_preferred"] == "SENSOR_OXYGEN_0707"
