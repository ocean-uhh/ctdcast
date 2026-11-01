"""Tests for the SBE 911plus .hex/.xmlcon readers and the stage-1 hex backend.

Real data only.  The committed fixture is the first 3,600 scans (150 s, 7-98 dbar) of OdB cast
MIXSED2_011 with its acquisition .xmlcon (tests/fixtures/hex_slice/).  Full-length casts live in
tests/fixtures/hex/, which is git-ignored; tests that need them skip when it is empty.  The
committed CNV fixtures for the same casts are the Sea-Bird reference.
"""

from __future__ import annotations

import importlib.metadata
import shutil
import warnings
from datetime import datetime
from pathlib import Path

import gsw
import numpy as np
import pytest
import xarray as xr

from ctdcast.config.cnv_header import (
    header_from_raw_metadata,
    parse_sensor_block,
    parse_star_block,
)
from ctdcast.processors import StagePaths
from ctdcast.processors.stage1 import find_xmlcon, stage1
from ctdcast.readers.hex import (
    check_bottle_log,
    read_hex,
    read_hex_lines,
    time_anchor,
)
from ctdcast.readers.xmlcon import parse_xmlcon, read_xmlcon, sensor_records

FIX = Path(__file__).parent / "fixtures"
SLICE = FIX / "hex_slice"
FULL = FIX / "hex"
NC = FIX / "nc"
N_SLICE = 3600
INTERVAL = 1 / 24


def _full(name: str) -> Path:
    path = FULL / name
    if not path.exists():
        pytest.skip(f"full-length hex fixture {name} not in {FULL} (git-ignored, local only)")
    return path


@pytest.fixture(scope="module")
def slice_ds() -> xr.Dataset:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return read_hex(SLICE / "MIXSED2_011.hex", SLICE / "MIXSED2_011.XMLCON")


# --- .xmlcon ---------------------------------------------------------------------------------


def test_xmlcon_channel_layout():
    inst, _ = read_xmlcon(SLICE / "MIXSED2_011.XMLCON")
    assert inst.instrument_type == 8
    assert (inst.n_frequency, inst.n_voltage) == (5, 8)
    assert [(s.kind, s.number) for s in inst.sensors[:6]] == [
        ("frequency", 0),
        ("frequency", 1),
        ("frequency", 2),
        ("frequency", 3),
        ("frequency", 4),
        ("voltage", 0),
    ]
    assert [s.comment for s in inst.sensors[3:5]] == ["Temperature, 2", "Conductivity, 2"]
    assert inst.nmea_position_added and not inst.nmea_time_added


def test_xmlcon_size_mismatch_is_refused():
    text = (SLICE / "MIXSED2_011.XMLCON").read_text(encoding="latin-1")
    bad = text.replace(
        "<VoltageWordsSuppressed>0</VoltageWordsSuppressed>",
        "<VoltageWordsSuppressed>1</VoltageWordsSuppressed>",
    )
    with pytest.raises(ValueError, match="suppressed"):
        parse_xmlcon(bad)


def test_xmlcon_records_match_cnv_block_except_calibration_slopes():
    """The .xmlcon renders the same sensor records as the CNV header, bar the C slopes.

    The OdB CNVs were converted with a calibration .xmlcon (conductivity slopes 1.00000452 and
    0.99993682); the acquisition .xmlcon beside the .hex has 1.0.  Everything else is identical.
    """
    inst, _ = read_xmlcon(SLICE / "MIXSED2_011.XMLCON")
    with xr.open_dataset(NC / "mixsed2_011.nc", engine="netcdf4") as ds:
        cnv = parse_sensor_block(header_from_raw_metadata(ds.attrs["raw_metadata"]))
    hx = sensor_records(inst)
    assert len(cnv) == len(hx) == 13
    differing = {}
    for a, b in zip(cnv, hx, strict=True):
        keys = sorted(k for k in a if a[k] != b[k])
        if keys:
            differing[a["channel"]] = (keys, a["slope"], b["slope"])
    assert differing == {
        2: (["raw_block", "slope"], "1.00000452", "1.00000000"),
        5: (["raw_block", "slope"], "0.99993682", "1.00000000"),
    }


# --- reading the slice -----------------------------------------------------------------------


def test_slice_scans_and_time_axis(slice_ds):
    assert slice_ds.sizes["time"] == N_SLICE
    assert slice_ds.attrs["sample_interval_seconds"] == pytest.approx(INTERVAL)
    assert slice_ds.attrs["time_coordinate_source"] == "NMEA time, header"
    t = slice_ds["time"].values
    assert t[0] == np.datetime64("2026-07-12T02:40:10")  # the header's NMEA UTC (Time)
    # Built forward from the first scan, so the last scan is exactly (n - 1) intervals later.
    assert (t[-1] - t[0]) / np.timedelta64(1, "ns") == pytest.approx((N_SLICE - 1) * INTERVAL * 1e9)


def test_slice_conductivity_is_mS_per_cm_without_ctm(slice_ds):
    """No x10: conductivity and salinity are in physical ranges, with no CTM involved."""
    for line in (1, 2):
        c = slice_ds[f"conductivity_{line}"]
        assert c.attrs["units"] == "mS cm-1"
        assert 33.0 < float(c.min()) and float(c.max()) < 36.5
        sp = gsw.SP_from_C(c.values, slice_ds[f"ctd_temperature_{line}"].values, slice_ds.pressure.values)
        assert 34.0 < np.nanmin(sp) and np.nanmax(sp) < 35.2


def test_slice_calibration_attrs(slice_ds):
    c1 = slice_ds["conductivity_1"].attrs
    assert c1["xmlcon_slope"] == 1.0 and c1["xmlcon_offset"] == 0.0
    assert "S m-1" in c1["comment"]
    p = slice_ds["pressure"].attrs
    assert p["xmlcon_offset"] == pytest.approx(0.2744)
    assert "inside convert_pressure_digiquartz" in p["comment"]


def test_slice_voltage_channels_kept_raw(slice_ds):
    for n in (0, 1, 3, 4, 5, 6, 7):
        assert slice_ds[f"volt{n}_raw"].attrs["units"] == "V"
    assert "oxygen_raw_1" in slice_ds and "volt2_raw" not in slice_ds  # SBE 43 on volt 2
    for name in ("ctd_fluor", "ctd_turbidity", "ctd_altimeter", "transmissometer", "sbe_oxygen_1"):
        assert name in slice_ds


def test_slice_against_sea_bird_cnv_mixed_layer(slice_ds):
    """T, and C where dT/dz is small, agree with Sea-Bird's processing of the same cast.

    The CNV has CTM, a 10-scan median filter and the calibration .xmlcon's conductivity slopes;
    the hex has none, so C is compared only where the temperature gradient is small.
    """
    with xr.open_dataset(NC / "mixsed2_011.nc", engine="netcdf4") as cnv:
        cp = cnv.pressure.values
        down = np.arange(int(np.argmax(cp)) + 1)
        ref = {v: cnv[v].values for v in ("ctd_temperature_1", "conductivity_1", "conductivity_2")}
    p = slice_ds.pressure.values
    turn = int(np.argmax(p))
    diffs: dict[str, list[float]] = {v: [] for v in ref}
    dtdz = np.gradient(ref["ctd_temperature_1"][down], cp[down])
    for k, i in enumerate(down):
        sel = np.abs(p[: turn + 1] - cp[i]) <= 0.5
        if sel.sum() < 5 or cp[i] > p.max() - 1:
            continue
        for v in ref:
            if v.startswith("conductivity") and abs(dtdz[k]) >= 0.01:
                continue
            diffs[v].append(ref[v][i] - float(slice_ds[v].values[: turn + 1][sel].mean()))
    assert abs(np.median(diffs["ctd_temperature_1"])) < 0.001
    assert abs(np.median(diffs["conductivity_1"])) < 0.002
    assert abs(np.median(diffs["conductivity_2"])) < 0.005  # includes the 0.99993682 slope (~-0.0022)


def test_layout_mismatch_is_refused(tmp_path):
    text = (SLICE / "MIXSED2_011.hex").read_bytes()
    bad = text.replace(b"Number of Bytes Per Scan = 37", b"Number of Bytes Per Scan = 36")
    (tmp_path / "MIXSED2_011.hex").write_bytes(bad)
    with pytest.raises(ValueError, match="bytes per scan"):
        read_hex(tmp_path / "MIXSED2_011.hex", SLICE / "MIXSED2_011.XMLCON")


# --- time anchor -----------------------------------------------------------------------------


def _header() -> str:
    return read_hex_lines(SLICE / "MIXSED2_011.hex").header


def test_time_anchor_falls_back_to_pc_clock_without_nmea():
    header = "\n".join(ln for ln in _header().split("\n") if "NMEA UTC" not in ln)
    with pytest.warns(UserWarning, match="PC clock"):
        anchor = time_anchor(header)
    assert anchor.t0 == datetime(2026, 7, 12, 2, 40, 13)
    assert anchor.source == "System UTC, first data scan"


def test_time_anchor_distrusts_an_undated_gps():
    header = _header().replace("Jul 12 2026  02:40:10", "Jan 01 2000  12:26:20")
    with pytest.warns(UserWarning, match="beyond"):
        anchor = time_anchor(header)
    assert anchor.t0 == datetime(2026, 7, 12, 2, 40, 13)


# --- stage 1 ---------------------------------------------------------------------------------


def test_stage1_hex_backend(tmp_path):
    raw = tmp_path / "raw"
    shutil.copytree(SLICE, raw)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        n = stage1(raw, tmp_path / "ctd", backend="hex", pattern="*.[hH][eE][xX]")
    assert n == 1
    out = next((tmp_path / "ctd").rglob("*.nc"))
    with xr.open_dataset(out, engine="netcdf4") as ds:
        assert ds.attrs["source_hex"] == "MIXSED2_011.hex"
        assert ds.attrs["source_xmlcon"] == "MIXSED2_011.XMLCON"
        assert ds.attrs["input_format"] == "hex"
        assert ds.attrs["cast_id"] == "011"
        assert ds.attrs["sbe_processing_order"] == "align(deck)"
        assert "seabirdscientific" in ds.attrs["history"]
        assert ds["oxygen_raw_1"].attrs["sensor"] == "SENSOR_OXYGEN_0707"
        assert ds["conductivity_2"].attrs["sensor"] == "SENSOR_CONDUCTIVITY_3120"
        assert "ctd_salinity_1" in ds and "ctd_salinity_2" in ds


def test_find_xmlcon_ignores_case(tmp_path):
    (tmp_path / "MIXSED2_004_b.hex").write_text("")
    (tmp_path / "MIXSED2_004_B.XMLCON").write_text("")
    assert find_xmlcon(tmp_path / "MIXSED2_004_b.hex").name == "MIXSED2_004_B.XMLCON"
    (tmp_path / "MIXSED2_005.hex").write_text("")
    with pytest.raises(FileNotFoundError, match="found none"):
        find_xmlcon(tmp_path / "MIXSED2_005.hex")


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"cnv_dir": "a"}, "cnv"),
        ({"hex_dir": "b"}, "hex"),
        ({"cnv_dir": "a", "hex_dir": "b", "ctd_raw_format": "hex"}, "hex"),
        ({"cnv_dir": "a", "hex_dir": "b", "ctd_raw_format": "CNV"}, "cnv"),
    ],
)
def test_raw_format_resolution(data, expected):
    paths = StagePaths.from_config(data)
    assert paths.ctd_raw_format == expected
    assert str(paths.ctd_raw_dir) == data[f"{expected}_dir"]


@pytest.mark.parametrize(
    ("data", "match"),
    [
        ({"cnv_dir": "a", "hex_dir": "b"}, "both set"),
        ({"cnv_dir": "a", "ctd_raw_format": "hex"}, "hex_dir is not set"),
        ({"cnv_dir": "a", "ctd_raw_format": "seabird"}, "must be"),
    ],
)
def test_raw_format_errors(data, match):
    with pytest.raises(ValueError, match=match):
        StagePaths.from_config(data)


def test_seabirdscientific_major_version():
    """A major-version change of seabirdscientific is found here, deliberately."""
    assert importlib.metadata.version("seabirdscientific").split(".")[0] == "3"


# --- full-length casts (local only) ----------------------------------------------------------


@pytest.mark.parametrize(("cast", "n_scans"), [("011", 29620), ("012", None)])
def test_full_cast_time_and_bottle_log(cast, n_scans):
    hex_path = _full(f"MIXSED2_{cast}.hex")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = read_hex(hex_path, _full(f"MIXSED2_{cast}.XMLCON"))
    if n_scans is not None:
        assert ds.sizes["time"] == n_scans
        assert ds["time"].values[-1] == np.datetime64("2026-07-12T03:00:44.125")
    upload = parse_star_block(read_hex_lines(hex_path).header).clocks.system_upload_dt
    check = check_bottle_log(_full(f"MIXSED2_{cast}.bl"), upload, INTERVAL)
    assert check.n_bottles > 0 and check.passed


def test_bottle_log_catches_a_wrong_anchor():
    hex_path = _full("MIXSED2_011.hex")
    upload = parse_star_block(read_hex_lines(hex_path).header).clocks.system_upload_dt
    shifted = upload.replace(second=upload.second - 5)
    assert not check_bottle_log(_full("MIXSED2_011.bl"), shifted, INTERVAL).passed


def test_full_cast_000_other_xmlcon_version():
    """Cast 000's .xmlcon puts the altimeter on volt 4 and the C-Star on volt 5 (011: swapped)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = read_hex(_full("MIXSED2_000.hex"), _full("MIXSED2_000.XMLCON"))
    assert ds["volt4_raw"].attrs["sbe_sensor_element"] == "AltimeterSensor"
    assert ds["volt5_raw"].attrs["sbe_sensor_element"] == "WET_LabsCStar"
    assert ds["conductivity_1"].attrs["sensor_serial_number"] == "3345"
