"""The ``to_canonical_units`` boundary pass.

Covers the pass's spelling rewrite, value conversion, idempotence, fill-from-registry for a
unit-less derived variable, and loud failure on an unknown spelling.  Per the branch ruling a
factor != 1 is logged, not stamped — no per-variable conversion provenance attributes are
written.  The registry-canonical pin lives in :mod:`tests.config.test_units`.
"""

import numpy as np
import pytest
import xarray as xr
from conftest import CAST_011

from ctdcast.processors.units import UnitsError, to_canonical_units


def test_real_fixture_units_unchanged():
    """Every fixture variable is already canonical, so the pass rewrites no units string."""
    with xr.open_dataset(CAST_011, engine="netcdf4", decode_timedelta=False) as ds:
        ds = ds.load()
    before = {v: ds[v].attrs.get("units") for v in ds.variables}
    out = to_canonical_units(ds, stage=1)
    after = {v: out[v].attrs.get("units") for v in out.variables}
    assert after == before


def test_unknown_spelling_raises_naming_variable_and_stage():
    ds = xr.Dataset(
        {
            "ctd_temperature_1": (
                "t",
                np.array([1.0, 2.0]),
                {"units": "nonsense", "standard_name": "sea_water_temperature"},
            )
        }
    )
    with pytest.raises(UnitsError, match=r"ctd_temperature_1.*stage 1.*nonsense"):
        to_canonical_units(ds, stage=1)


def test_missing_units_on_registered_variable_is_filled_from_registry():
    """A registered variable with no units gets its canonical filled (ctdcast writer source)."""
    ds = xr.Dataset({"ctd_temperature_1": ("t", np.array([1.0, 2.0]))})
    out = to_canonical_units(ds)
    assert out["ctd_temperature_1"].attrs["units"] == "degree_Celsius"


def test_unregistered_variable_is_untouched():
    ds = xr.Dataset(
        {"density00": ("t", np.array([1.0, 2.0]), {"units": "density, kg/m^3"})}
    )
    out = to_canonical_units(ds)
    assert out["density00"].attrs["units"] == "density, kg/m^3"


def test_temperature_gets_units_metadata():
    ds = xr.Dataset(
        {"ctd_temperature_1": ("t", np.array([1.0, 2.0]), {"units": "degree_Celsius"})}
    )
    out = to_canonical_units(ds)
    assert out["ctd_temperature_1"].attrs["units_metadata"] == "temperature: on_scale"


def test_s_per_m_converts_times_ten_and_warns_without_provenance_attrs():
    """The seeded `S/m` alias converts conductivity ×10, warns, but stamps no provenance.

    Evidence: cnv/mixsed2_004.cnv `c0S/m: Conductivity [S/m]`. 1 S/m = 10 mS/cm.  A value-scaling
    conversion is announced loudly (never silent) but not stamped on the variable (branch ruling).
    """
    ds = xr.Dataset({"conductivity_1": ("t", np.array([0.4, 0.5]), {"units": "S/m"})})
    with pytest.warns(UserWarning, match=r"conductivity_1.*scaled x10.*S/m.*mS cm-1"):
        out = to_canonical_units(ds)
    assert out["conductivity_1"].attrs["units"] == "mS cm-1"
    np.testing.assert_allclose(out["conductivity_1"].values, [4.0, 5.0])
    assert "units_converted_from" not in out["conductivity_1"].attrs
    assert "units_conversion_factor" not in out["conductivity_1"].attrs


def test_pass_is_idempotent_under_conversion():
    ds = xr.Dataset({"conductivity_1": ("t", np.array([0.4]), {"units": "S/m"})})
    with pytest.warns(UserWarning, match="scaled x10"):
        out = to_canonical_units(ds)  # first pass converts and warns
    out2 = to_canonical_units(out.copy(deep=True))  # second pass is a no-op, no warning
    np.testing.assert_allclose(
        out2["conductivity_1"].values, [4.0]
    )  # not multiplied twice


def test_seeded_cnv_header_spellings_canonicalise():
    """The spellings seeded from the raw CNV headers rewrite to their canonical form.

    seasenselib normalises these upstream, so this exercises the path a non-normalising
    backend (the future .hex/.xmlcon reader) will take.
    """
    ds = xr.Dataset(
        {
            "ctd_temperature_1": ("t", np.array([10.0]), {"units": "ITS-90, deg C"}),
            "conductivity_1": ("t", np.array([40.0]), {"units": "mS/cm"}),
            "pressure": ("t", np.array([5.0]), {"units": "db"}),
            "ctd_fluor": ("t", np.array([1.0]), {"units": "mg/m^3"}),
            "ctd_oxygen_1": ("t", np.array([250.0]), {"units": "umol/kg"}),
            "sbe_oxygen_saturation_1": (
                "t",
                np.array([95.0]),
                {"units": "% saturation"},
            ),
        }
    )
    out = to_canonical_units(ds)
    assert out["ctd_temperature_1"].attrs["units"] == "degree_Celsius"
    assert out["conductivity_1"].attrs["units"] == "mS cm-1"
    assert out["pressure"].attrs["units"] == "dbar"
    assert out["ctd_fluor"].attrs["units"] == "mg m-3"
    assert out["ctd_oxygen_1"].attrs["units"] == "umol kg-1"
    assert out["sbe_oxygen_saturation_1"].attrs["units"] == "percent"


def test_variable_scoped_psu_ntu_and_deg():
    """PSU/NTU/deg resolve per variable; deg is north on latitude, east on longitude."""
    ds = xr.Dataset(
        {
            "ctd_salinity_1": ("t", np.array([35.0]), {"units": "PSU"}),
            "ctd_turbidity": ("t", np.array([1.0]), {"units": "NTU"}),
            "latitude": ("t", np.array([60.0]), {"units": "deg"}),
            "longitude": ("t", np.array([-5.0]), {"units": "deg"}),
        }
    )
    out = to_canonical_units(ds)
    assert out["ctd_salinity_1"].attrs["units"] == "1"
    assert out["ctd_turbidity"].attrs["units"] == "1"
    assert out["latitude"].attrs["units"] == "degrees_north"
    assert out["longitude"].attrs["units"] == "degrees_east"


def test_cf_latitude_longitude_spellings_canonicalise():
    """The CF §4.1 acceptable lat/lon spellings rewrite to degrees_north / degrees_east."""
    for spelling in ("degree_north", "degree_N", "degrees_N", "degreeN", "degreesN"):
        ds = xr.Dataset({"latitude": ("x", np.array([60.0]), {"units": spelling})})
        assert to_canonical_units(ds)["latitude"].attrs["units"] == "degrees_north"
    for spelling in ("degree_east", "degree_E", "degrees_E", "degreeE", "degreesE"):
        ds = xr.Dataset({"longitude": ("x", np.array([-5.0]), {"units": spelling})})
        assert to_canonical_units(ds)["longitude"].attrs["units"] == "degrees_east"


def test_variable_scoped_spelling_refused_on_wrong_variable():
    """PSU is salinity-only; a `1`-canonical flag variable carrying PSU must raise."""
    ds = xr.Dataset({"sbe_flag": ("t", np.array([0.0]), {"units": "PSU"})})
    with pytest.raises(UnitsError, match="PSU"):
        to_canonical_units(ds)
