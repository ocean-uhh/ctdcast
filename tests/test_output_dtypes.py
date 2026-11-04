"""Storage dtypes: float32 science on disk, float64 time and position, float64 arithmetic."""

import warnings
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ctdcast.writers.dtypes import cast_output_dtypes, find_best_dtype, widen_floats
from ctdcast.writers.netcdf import write

NC = Path(__file__).parent / "fixtures" / "nc"

SCIENCE = (
    "pressure",
    "ctd_temperature_1",
    "ctd_temperature_2",
    "conductivity_1",
    "conductivity_2",
    "ctd_salinity_1",
    "ctd_salinity_2",
)


@pytest.fixture
def cast011():
    with xr.open_dataset(NC / "mixsed2_011.nc", engine="netcdf4") as ds:
        return widen_floats(ds.load())


def _written(ds, tmp_path):
    path = tmp_path / "c.nc"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        write(ds, path)
    with xr.open_dataset(path, engine="netcdf4") as back:
        return back.load()


def test_science_is_float32_time_and_position_float64(cast011, tmp_path):
    back = _written(cast011, tmp_path)
    for v in SCIENCE:
        if v in cast011:
            assert back[v].dtype == np.float32, v
    assert back["latitude"].dtype == np.float64
    assert back["longitude"].dtype == np.float64
    assert np.issubdtype(back["time"].dtype, np.datetime64)
    assert all(back[v].dtype == np.int8 for v in back.data_vars if v.endswith("_qc"))


def test_round_trip_error_is_below_the_sensors(cast011, tmp_path):
    """float32 storage loses about 10^-7 relative: far below the SBE 911plus resolution."""
    back = _written(cast011, tmp_path)
    bounds = {"pressure": 5e-4, "ctd_temperature_1": 1e-6, "ctd_salinity_1": 1e-5}
    for v, bound in bounds.items():
        err = np.nanmax(np.abs(back[v].values.astype(float) - cast011[v].values))
        assert err < bound, (v, err)


def test_position_stays_float64_as_data_or_coordinate():
    lat = np.array([60.123456789, 60.123456791])
    as_data = xr.Dataset({"latitude": ("N_PROF", lat)})
    as_coord = xr.Dataset(coords={"latitude": ("N_PROF", lat)})
    for ds in (as_data, as_coord):
        out = cast_output_dtypes(ds)
        assert out["latitude"].dtype == np.float64
        np.testing.assert_array_equal(out["latitude"].values, lat)


def test_float_coordinate_is_narrowed_too():
    ds = xr.Dataset(
        {"ctd_temperature": (("N_PROF", "pressure"), np.ones((2, 3)))},
        coords={"pressure": np.array([1.0, 2.0, 3.0])},
    )
    out = cast_output_dtypes(ds)
    assert out["pressure"].dtype == np.float32
    assert out["ctd_temperature"].dtype == np.float32
    assert ds["pressure"].dtype == np.float64  # input untouched


def test_timedelta_is_left_alone():
    da = xr.DataArray(np.array([1, 2], dtype="timedelta64[s]"))
    assert find_best_dtype("soak_duration", da) == np.timedelta64


def test_widen_floats_restores_float64_without_touching_the_input(cast011, tmp_path):
    back = _written(cast011, tmp_path)
    wide = widen_floats(back)
    assert wide["ctd_temperature_1"].dtype == np.float64
    assert back["ctd_temperature_1"].dtype == np.float32
    again = widen_floats(wide)
    assert again is not wide  # always a new dataset, so a caller may change it freely


def test_name_rules_do_not_misfire():
    """``altimeter`` is not a time; Sea-Bird's own flag column is not a QARTOD flag."""
    f64 = xr.DataArray(np.zeros(2))
    assert find_best_dtype("ctd_altimeter", f64) == np.float32
    for name in ("time", "timeJ", "time_start", "sbe_timeS"):
        assert find_best_dtype(name, f64) == np.float64, name
    assert find_best_dtype("sbe_flag", f64) == np.float32
    assert find_best_dtype("loop_edit_flag", f64) == np.int8
    assert find_best_dtype("ctd_temperature_1_qc", f64) == np.int8


def test_sea_bird_loop_edit_marks_survive_read_and_write(tmp_path):
    """A real Loop-Edited CNV: its -9.99e-29 marks are kept through stage 1's read and a write."""
    from ctdcast.readers.cnv import read

    pytest.importorskip("seasenselib")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = read(
            Path(__file__).parent / "fixtures" / "cnv" / "mixsed2_050_24Hz_slice.cnv"
        )
    marked = ds["sbe_flag"].values != 0
    assert marked.sum() == 1076  # counted in the CNV text: 1076 of 1150 scans
    back = _written(ds, tmp_path)
    np.testing.assert_array_equal(back["sbe_flag"].values != 0, marked)
    assert back["ctd_altimeter"].dtype == np.float32


def test_stage3_leaves_an_all_float64_input_untouched(cast011):
    from ctdcast.processors.stage3 import stage3

    before = dict(cast011.attrs)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stage3(cast011, {"data_processing": {"steps": []}}, cast_number=11)
    assert cast011.attrs == before


def test_stage3_computes_in_float64_on_a_float32_file(cast011, tmp_path):
    from ctdcast.processors.stage3 import stage3

    back = _written(cast011, tmp_path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = stage3(back, {}, cast_number=11)
    assert out["ctd_temperature_1"].dtype == np.float64


def test_profiles_do_not_bin_the_loop_edit_flag(hex_stage2, tmp_path):
    """A bin mean of Loop Edit's 0/1 flag is not a flag (and int8 storage would truncate it)."""
    from ctdcast.processors.profiles import build_profiles
    from ctdcast.processors.stage3 import stage3

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s3 = stage3(
            hex_stage2,
            {"data_processing": {"steps": [{"loopedit": {}}]}},
            cast_number=11,
        )
        assert s3["loop_edit_flag"].values.any()
        (tmp_path / "stage3").mkdir()
        write(s3, tmp_path / "stage3" / "MIXSED2_011_stage3.nc")
        build_profiles(tmp_path, tmp_path / "profiles.nc", force=True)
    with xr.open_dataset(tmp_path / "profiles.nc", engine="netcdf4") as prof:
        assert "loop_edit_flag" not in prof
        assert "ctd_temperature_1" in prof
