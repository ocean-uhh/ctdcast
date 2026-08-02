"""Smoke tests for Tier-1 _make_*_b64 plot functions.

Each test asserts only that the function returns a str or None — not
that the image is pixel-perfect.  A returned str must start with the
PNG base64 magic bytes ("iVBOR").
"""

import pytest
import xarray as xr

import ctd_report._plots as plots
from ctd_report._plots import (
    _make_aux_profiles_b64,
    _make_ct_sa_sigma0_b64,
    _make_ladcp_bottomtrack_b64,
    _make_pressure_time_b64,
    _make_sensor_diff_b64,
    _make_stability_b64,
    _make_station_map_b64,
    _make_ts_density_b64,
    _make_ts_density_ladcp_b64,
    _make_ts_diagram_b64,
    _make_ts_updown_b64,
    _make_updown_diff_b64,
    _make_profile_b64,
)

from conftest import CAST_011, CAST_128, FIXTURES_LADCP

_LADCP_011 = FIXTURES_LADCP / "011.mat"
_LADCP_128 = FIXTURES_LADCP / "128.mat"


def _is_valid(result):
    """Return True if result is None or a PNG base64 string."""
    if result is None:
        return True
    return isinstance(result, str) and result.startswith("iVBOR")


# --- profile plots -----------------------------------------------------------

def test_profile_temperature(ds_011):
    assert _is_valid(_make_profile_b64(ds_011, "temperature_1", "Temperature (°C)"))


def test_profile_salinity(ds_011):
    assert _is_valid(_make_profile_b64(ds_011, "salinity_1", "Salinity (PSU)"))


def test_profile_missing_var(ds_011):
    # Missing variable must return None, not raise
    assert _make_profile_b64(ds_011, "nonexistent_var", "units") is None


# --- station-page plot functions ---------------------------------------------

def test_ts_density_b64(ds_011):
    assert _is_valid(_make_ts_density_b64(ds_011))


def test_ts_diagram_b64(ds_011):
    assert _is_valid(_make_ts_diagram_b64(ds_011))


def test_stability_b64(ds_011):
    assert _is_valid(_make_stability_b64(ds_011))


def test_aux_profiles_b64(ds_011):
    assert _is_valid(_make_aux_profiles_b64(ds_011))


def test_ct_sa_sigma0_b64(ds_011):
    assert _is_valid(_make_ct_sa_sigma0_b64(ds_011))


def test_ts_updown_b64(ds_011):
    assert _is_valid(_make_ts_updown_b64(ds_011))


def test_pressure_time_b64(ds_011):
    assert _is_valid(_make_pressure_time_b64(ds_011))


def test_sensor_diff_b64(ds_011):
    assert _is_valid(_make_sensor_diff_b64(ds_011))


def test_updown_diff_b64(ds_011):
    assert _is_valid(_make_updown_diff_b64(ds_011))


# --- LADCP plot functions ----------------------------------------------------

def test_ts_density_ladcp_b64(ds_011):
    assert _is_valid(_make_ts_density_ladcp_b64(ds_011, _LADCP_011))


def test_ts_density_ladcp_missing_file(ds_011):
    # Missing LADCP file must return None or a plain density plot — not raise
    result = _make_ts_density_ladcp_b64(ds_011, None)
    assert _is_valid(result)


def test_ladcp_bottomtrack_b64():
    assert _is_valid(_make_ladcp_bottomtrack_b64(_LADCP_011))


def test_ladcp_bottomtrack_none():
    assert _make_ladcp_bottomtrack_b64(None) is None


# --- station map (no GEBCO) --------------------------------------------------

def test_station_map_no_gebco(ds_011, monkeypatch):
    monkeypatch.setattr(plots, "GEBCO_PATH", None)
    import xarray as xr
    import numpy as np
    ds = xr.open_dataset(CAST_011, engine="netcdf4")
    lat = float(np.nanmedian(ds["latitude"].values))
    lon = float(np.nanmedian(ds["longitude"].values))
    ds.close()
    all_meta = [{"lat": lat, "lon": lon}]
    assert _is_valid(_make_station_map_b64(lat, lon, all_meta))


# --- deep cast (cast 128) ----------------------------------------------------

def test_ts_density_deep_cast(ds_128):
    assert _is_valid(_make_ts_density_b64(ds_128))


def test_ts_density_ladcp_deep(ds_128):
    assert _is_valid(_make_ts_density_ladcp_b64(ds_128, _LADCP_128))
