"""Oxygen-specific preferred-sensor behaviour.

The generic mechanism (``config/preferred_sensors.py``) and the T/C pair stamp are covered
in ``tests/config/test_preferred_sensors.py`` and ``tests/test_stage3_preferred.py``.  This
file covers the pieces that need an oxygen-shaped dataset: the ``ctd_oxygen_1``/``_2``
line-plumbing assumption comment, an independent ``preferred_oxygen`` choice that
differs from ``preferred_pair`` (R.4), and the dual-oxygen stamp (the committed fixtures are
single-oxygen, so the second oxygen sensor is synthesised here).
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest
import xarray as xr
from conftest import FIXTURES_NC

from ctdcast.analysis.derive import derive_teos10
from ctdcast.config.parameters import VARIABLES
from ctdcast.config.sensors import SensorOverrides
from ctdcast.processors.stage1 import _build_cast_sensor_catalog
from ctdcast.processors.stage3 import _stamp_preferred_sensors
from ctdcast.writers.netcdf import write as write_nc

CAST = 11


def _dual_line_cast(preferred_oxygen: str) -> xr.Dataset:
    """A synthetic dual-T/C, dual-O₂ cast with distinct values per line.

    Line 1 and line 2 carry different T/S and oxygen, so the derived saturation differs
    between lines and the composite selection is observable.  ``preferred_oxygen`` is set as
    the attribute stage 3 would stamp.
    """
    n = 6
    p = np.linspace(2.0, 200.0, n)
    return xr.Dataset(
        {
            "ctd_temperature_1": ("time", np.full(n, 10.0, dtype="float32")),
            "ctd_temperature_2": ("time", np.full(n, 12.0, dtype="float32")),
            "ctd_salinity_1": ("time", np.full(n, 35.0, dtype="float32")),
            "ctd_salinity_2": ("time", np.full(n, 34.5, dtype="float32")),
            "ctd_oxygen_1": (
                "time",
                np.full(n, 250.0, dtype="float32"),
                {"units": "umol kg-1"},
            ),
            "ctd_oxygen_2": (
                "time",
                np.full(n, 200.0, dtype="float32"),
                {"units": "umol kg-1"},
            ),
            "pressure": ("time", p.astype("float32")),
            "latitude": ("time", np.full(n, 60.0, dtype="float32")),
            "longitude": ("time", np.full(n, -20.0, dtype="float32")),
        },
        attrs={"preferred_oxygen": preferred_oxygen},
    )


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


# --- ctd_oxygen_1/_2 line-plumbing assumption comment ------------------------


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


# --- oxygen_saturation per line, composite follows preferred_oxygen ----------


def test_oxygen_saturation_derived_per_line_and_selected_by_preference() -> None:
    # The two lines have distinct T/S and oxygen, so their saturations differ. The composite
    # oxygen_saturation must equal the preferred line's derivation (never a line mix).
    sec = derive_teos10(_dual_line_cast("secondary"))
    assert "oxygen_saturation_1" in sec and "oxygen_saturation_2" in sec
    # distinct lines (guards against a silent line mix hiding a bug)
    assert not np.allclose(
        sec["oxygen_saturation_1"].values, sec["oxygen_saturation_2"].values
    )
    assert np.array_equal(
        sec["oxygen_saturation"].values, sec["oxygen_saturation_2"].values
    )

    pri = derive_teos10(_dual_line_cast("primary"))
    assert np.array_equal(
        pri["oxygen_saturation"].values, pri["oxygen_saturation_1"].values
    )
    # Provenance records the T/S line each saturation was paired with.
    assert "ctd_temperature_2" in sec["oxygen_saturation_2"].attrs["oxygen_conversion"]
    assert "ctd_temperature_1" in sec["oxygen_saturation_1"].attrs["oxygen_conversion"]


def test_dual_oxygen_without_matching_line_ts_skips_not_cross_pairs() -> None:
    # Dual oxygen but only line-1 T/S present: oxygen_saturation_2 must NOT be computed from
    # line-1 T/S (silent cross-pairing) — it is skipped with a warning instead.
    ds = _dual_line_cast("primary").drop_vars(["ctd_temperature_2", "ctd_salinity_2"])
    with pytest.warns(UserWarning, match="avoid pairing it with the other line"):
        out = derive_teos10(ds)
    assert "oxygen_saturation_1" in out
    assert "oxygen_saturation_2" not in out
    # the composite falls back to the one line that was derived
    assert np.array_equal(
        out["oxygen_saturation"].values, out["oxygen_saturation_1"].values
    )


def test_undeclared_dual_oxygen_displays_primary_line() -> None:
    # oxygen_saturation is an on-the-fly report quantity (never stored), so an undeclared
    # dual cast still gets a composite for the figure — the primary line — unlike the stored
    # ctd_oxygen composite, which is absent when undeclared.
    ds = _dual_line_cast("secondary")
    del ds.attrs["preferred_oxygen"]
    out = derive_teos10(ds)
    assert "oxygen_saturation" in out
    assert np.array_equal(
        out["oxygen_saturation"].values, out["oxygen_saturation_1"].values
    )
    # The composite records which line it came from and that it was undeclared — provenance
    # the deferred report display (a follow-up rep/ branch) reads to label the figure.
    assert out["oxygen_saturation"].attrs["preferred_oxygen"] == "undeclared"
    assert out["oxygen_saturation"].attrs["oxygen_line"] == 1


def test_line_oxygen_saturation_ignores_the_pair_composite() -> None:
    # The line-2 oxygen saturation must come from line-2 T/S, independent of any pair
    # composite (ctd_temperature/ctd_salinity) — which here is deliberately set to line 1.
    base = derive_teos10(_dual_line_cast("secondary"))
    misleading = _dual_line_cast("secondary")
    misleading["ctd_temperature"] = misleading["ctd_temperature_1"]  # wrong line
    misleading["ctd_salinity"] = misleading["ctd_salinity_1"]
    out = derive_teos10(misleading)
    assert np.array_equal(
        base["oxygen_saturation_2"].values, out["oxygen_saturation_2"].values
    )
