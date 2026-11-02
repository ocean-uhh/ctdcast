"""Tests for stage-3 alignment, cell thermal mass and SBE 43 oxygen (real data only).

Native-rate input is OdB cast 011 read from the committed .hex slice (3,600 scans, 7-98 dbar,
through the thermocline) and run through stages 1 and 2.  The committed CNV fixtures for the
same casts are Sea-Bird's processing of them (binned, with CTM), the reference and the
refusal case.  Full-length casts in tests/fixtures/hex/ (git-ignored) add the acceptance check
over the whole profile.
"""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from seabirdscientific import processing as sbs_processing

from ctdcast.analysis.derive import derive_salinity
from ctdcast.processors.corrections import (
    align,
    apply_corrections,
    cell_thermal_mass,
    derive_oxygen,
    native_interval,
    native_rate_reason,
    resolve_alignment,
    resolve_cell_thermal_mass,
    resolve_oxygen_window,
    sbe43_dvdt,
    sbe43_hysteresis,
    sbe43_oxygen,
    validate_config,
)
from ctdcast.processors.stage1 import stage1
from ctdcast.processors.stage2 import run as stage2_run
from ctdcast.processors.stage3 import stage3

FIX = Path(__file__).parent / "fixtures"
CTM = {"celltm": {"default": {"alpha": 0.03, "tau": 7.0}}}


def _stage2(tmp: Path, src: Path, names: tuple[str, ...]) -> xr.Dataset:
    raw = tmp / "raw"
    raw.mkdir()
    for name in names:
        shutil.copy(src / name, raw / name)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stage1(raw, tmp / "ctd", backend="hex", pattern="*.[hH][eE][xX]")
        stage2_run(tmp / "ctd")
    path = next((tmp / "ctd" / "stage2").glob("*.nc"))
    with xr.open_dataset(path, engine="netcdf4") as ds:
        return ds.load()


@pytest.fixture(scope="module")
def slice2(tmp_path_factory) -> xr.Dataset:
    return _stage2(
        tmp_path_factory.mktemp("slice"),
        FIX / "hex_slice",
        ("MIXSED2_011.hex", "MIXSED2_011.XMLCON"),
    )


@pytest.fixture(scope="module")
def cnv011() -> xr.Dataset:
    with xr.open_dataset(FIX / "nc" / "mixsed2_011.nc", engine="netcdf4") as ds:
        return ds.load()


def _vs_cnv(ds: xr.Dataset, cnv: xr.Dataset, var: str) -> tuple[float, float]:
    """Median |CNV - hex| at 1 dbar on the downcast, in the mixed layers and the thermocline."""
    p = ds.pressure.values
    turn = int(np.nanargmax(p))
    cp = cnv.pressure.values
    down = np.arange(int(np.argmax(cp)) + 1)
    dtdz = np.gradient(cnv.ctd_temperature_1.values[down], cp[down])
    mixed, thermo = [], []
    for k, i in enumerate(down):
        sel = np.abs(p[: turn + 1] - cp[i]) <= 0.5
        if sel.sum() < 5 or cp[i] > np.nanmax(p) - 1:
            continue
        d = abs(cnv[var].values[i] - np.nanmean(ds[var].values[: turn + 1][sel]))
        (
            mixed if abs(dtdz[k]) < 0.01 else thermo if abs(dtdz[k]) > 0.05 else []
        ).append(d)
    return float(np.nanmedian(mixed)), float(np.nanmedian(thermo))


# --- input checks --------------------------------------------------------------------------


def test_native_rate_hex_passes_binned_cnv_refused(slice2, cnv011):
    assert native_rate_reason(slice2) is None
    reason = native_rate_reason(cnv011)
    assert reason is not None and "decibars" in reason


# --- configuration -------------------------------------------------------------------------


def test_alignment_resolution_specific_key_and_ranges():
    cfg = {
        "alignctd": {
            "conductivity": {"default": 0.0},
            "conductivity_2": {"ranges": [{"casts": [[30, 45]], "value": 0.021}]},
            "oxygen": {"default": 3.0},
        }
    }
    assert resolve_alignment(cfg, "conductivity_2", 31) == (
        0.021,
        "alignctd.conductivity_2 range",
    )
    assert resolve_alignment(cfg, "conductivity_2", 11) == (
        0.0,
        "alignctd.conductivity default",
    )
    assert resolve_alignment(cfg, "oxygen_raw_1", 11) == (
        3.0,
        "alignctd.oxygen default",
    )
    assert resolve_alignment({}, "conductivity_1", 11) is None


@pytest.mark.parametrize(
    ("cfg", "match"),
    [
        ({"alignctd": {"temperature": {"default": 0.1}}}, "unknown channel"),
        ({"alignctd": {"oxygen": {"default": 3.0, "value": 1}}}, "unknown key"),
        (
            {
                "alignctd": {
                    "oxygen": {
                        "ranges": [
                            {"casts": [[1, 20]], "value": 3},
                            {"casts": [[10, 30]], "value": 4},
                        ]
                    }
                }
            },
            "different values",
        ),
    ],
)
def test_alignment_config_errors(cfg, match):
    with pytest.raises(ValueError, match=match):
        resolve_alignment(cfg, "oxygen_raw_1", 11)


def test_ctm_resolution_and_errors():
    cfg = {
        "celltm": {
            "default": {"alpha": 0.03, "tau": 7.0},
            "conductivity_2": {"default": {"alpha": 0.04, "tau": 8.0}},
        }
    }
    assert resolve_cell_thermal_mass(cfg, "conductivity_1", 11) == (
        0.03,
        7.0,
        "celltm default",
    )
    assert resolve_cell_thermal_mass(cfg, "conductivity_2", 11) == (
        0.04,
        8.0,
        "celltm.conductivity_2 default",
    )
    with pytest.raises(ValueError, match="alpha and tau"):
        resolve_cell_thermal_mass(
            {"celltm": {"default": {"alpha": 0.03}}}, "conductivity_1", 11
        )


# --- appliers ------------------------------------------------------------------------------


def test_align_whole_scans_and_edges(slice2):
    c = slice2.conductivity_1.values
    out, mask = align(c, 3 / 24, 1 / 24)  # exactly three scans
    np.testing.assert_allclose(out[:-3], c[3:])
    assert mask.sum() == 3 and mask[-3:].all() and np.isnan(out[-3:]).all()
    back, mask_back = align(c, -2 / 24, 1 / 24)
    assert mask_back[:2].all() and mask_back.sum() == 2


def test_ctm_works_in_s_per_m(slice2):
    c, t = slice2.conductivity_1.values, slice2.ctd_temperature_1.values
    ours = cell_thermal_mass(c, t, 0.03, 7.0, 1 / 24)
    theirs = (
        sbs_processing.cell_thermal_mass(t.astype(float), c / 10.0, 0.03, 7.0, 1 / 24)
        * 10.0
    )
    np.testing.assert_allclose(ours, theirs)
    t_gap = t.astype(float).copy()
    t_gap[100] = np.nan
    with pytest.raises(ValueError, match="gaps"):
        cell_thermal_mass(c, t_gap, 0.03, 7.0, 1 / 24)


# --- orchestration and provenance -----------------------------------------------------------


def test_apply_corrections_records_everything(slice2):
    cfg = {**CTM, "alignctd": {"oxygen": {"default": 0.5}}}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds, rec = apply_corrections(slice2, cfg, 11, cast_label="011")
    assert rec.skipped == []
    assert set(rec.changed) == {"oxygen_raw_1", "conductivity_1", "conductivity_2"}
    c1 = ds.conductivity_1.attrs
    assert (c1["cell_thermal_mass_alpha"], c1["cell_thermal_mass_tau_seconds"]) == (
        0.03,
        7.0,
    )
    assert c1["cell_thermal_mass_temperature"] == "ctd_temperature_1"
    assert "seabirdscientific" in c1["cell_thermal_mass_method"]
    o = ds.oxygen_raw_1.attrs
    assert (
        o["alignment_offset_seconds"] == 0.5
        and o["alignment_config"] == "alignctd.oxygen default"
    )
    assert (ds.oxygen_raw_1_qc.values[-12:] == 9).all() and np.isnan(
        ds.oxygen_raw_1.values[-12:]
    ).all()
    assert ds.sizes["time"] == slice2.sizes["time"]  # never shortened
    assert "celltm: conductivity_1 alpha=0.03 tau=7 s" in ds.attrs["history"]
    assert "alignctd: oxygen_raw_1 +0.500 s" in ds.attrs["history"]


def test_deck_advance_recorded_as_residual_base(slice2):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds, _ = apply_corrections(
            slice2, {"alignctd": {"conductivity": {"default": 0.0}}}, 11
        )
    assert ds.conductivity_1.attrs[
        "alignment_deck_unit_advance_seconds"
    ] == pytest.approx(0.073)
    assert "residual on the deck-unit advance +0.073 s" in ds.attrs["history"]


def test_corrections_reconstruct_from_the_file_alone(slice2):
    """Re-applying the corrections from only the output's attrs to stage 2 reproduces it."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out, _ = apply_corrections(
            slice2, {**CTM, "alignctd": {"conductivity": {"default": 0.042}}}, 11
        )
    interval = float(out.attrs["sample_interval_seconds"])
    for var in ("conductivity_1", "conductivity_2"):
        a = out[var].attrs
        redo, _ = align(slice2[var].values, a["alignment_offset_seconds"], interval)
        redo = cell_thermal_mass(
            redo,
            slice2[a["cell_thermal_mass_temperature"]].values,
            a["cell_thermal_mass_alpha"],
            a["cell_thermal_mass_tau_seconds"],
            interval,
        )
        np.testing.assert_array_equal(np.isnan(redo), np.isnan(out[var].values))
        np.testing.assert_allclose(
            redo, out[var].values, equal_nan=True, rtol=0, atol=1e-6
        )


def test_binned_cnv_is_refused_and_still_qcd(cnv011):
    with pytest.warns(UserWarning, match="skipped: sampled by decibars"):
        ds = stage3(
            cnv011,
            {**CTM, "alignctd": {"oxygen": {"default": 3.0}}},
            cast_number=11,
            cast_label="011",
        )
    np.testing.assert_array_equal(
        ds.conductivity_1.values, cnv011.conductivity_1.values
    )
    assert "cell_thermal_mass_alpha" not in ds.conductivity_1.attrs
    assert "alignctd/celltm skipped" in ds.attrs["history"]
    assert "conductivity_1_qc" in ds  # QC still ran


def test_qc_judges_slope_corrected_values(cnv011):
    """QC runs after the slope: a fail bound between max(C) and max(C)*slope fails scans."""
    slope = 1.01
    c = cnv011.conductivity_1.values
    cmax = float(np.nanmax(c))
    bound = cmax * (1 + slope) / 2  # above every raw value, below the corrected maximum
    cfg = {
        "calibration": {"conductivity_slope": slope},
        "qc": {"gross_range": {"fail": {"conductivity_1": (0.0, bound)}}},
    }
    ds = stage3(cnv011, cfg, cast_number=11)
    expected = np.isfinite(c) & (c * slope > bound)
    assert expected.any() and not (np.isfinite(c) & (c > bound)).any()
    np.testing.assert_array_equal(ds.conductivity_1_qc.values == 4, expected)


# --- acceptance against Sea-Bird's processing ---------------------------------------------------


def test_ctm_brings_thermocline_salinity_to_the_cnv(slice2, cnv011):
    before = _vs_cnv(slice2, cnv011, "ctd_salinity_1")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds, _ = apply_corrections(slice2, CTM, 11)
    after = _vs_cnv(derive_salinity(ds), cnv011, "ctd_salinity_1")
    assert before[1] > 0.004  # Sea-Bird's CTM is in the CNV, not in the raw hex
    assert after[1] < 0.0015 and after[0] < 0.001


def test_oxygen_from_voltage_matches_sea_bird(slice2, cnv011):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = stage3(slice2, CTM, cast_number=11, cast_label="011")
    o = ds.ctd_oxygen
    assert (
        o.attrs["oxygen_tau_correction"] == "yes"
        and o.attrs["oxygen_hysteresis_correction"] == "yes"
    )
    assert "ctd_oxygen_qc" in ds
    mixed, _ = _vs_cnv(ds, cnv011, "ctd_oxygen")
    assert mixed < 0.2  # µmol/kg; measured 0.06-0.08 on 011/012


def test_cnv_oxygen_is_never_rederived(cnv011):
    ds, written = derive_oxygen(cnv011)
    assert written == []


def test_full_casts_acceptance():
    full = FIX / "hex"
    names = ("MIXSED2_012.hex", "MIXSED2_012.XMLCON")
    if not all((full / n).exists() for n in names):
        pytest.skip(
            "full-length hex casts not in tests/fixtures/hex (git-ignored, local only)"
        )
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        s2 = _stage2(Path(tmp), full, names)
    with xr.open_dataset(FIX / "nc" / "mixsed2_012.nc", engine="netcdf4") as cnv:
        cnv = cnv.load()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds, _ = apply_corrections(s2, CTM, 12)
    before = _vs_cnv(s2, cnv, "ctd_salinity_1")
    after = _vs_cnv(derive_salinity(ds), cnv, "ctd_salinity_1")
    assert before[1] > 0.01 and after[1] < 0.001


# --- compiled product and report --------------------------------------------------------------


def test_profiles_carries_parameters_per_profile_when_casts_differ(tmp_path):
    """Constant parameters stay attributes; one that changes between casts becomes N_PROF data."""
    from ctdcast.processors.profiles import build_profiles

    src = FIX / "hex_slice"
    for cast in (
        "011",
        "021",
    ):  # the slice twice, as two casts, different oxygen advance
        root = tmp_path / f"c{cast}"
        raw = root / "raw"
        raw.mkdir(parents=True)
        for ext in ("hex", "XMLCON"):
            shutil.copy(src / f"MIXSED2_011.{ext}", raw / f"MIXSED2_{cast}.{ext}")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            stage1(raw, tmp_path / "ctd", backend="hex", pattern="*.[hH][eE][xX]")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stage2_run(tmp_path / "ctd")
        from ctdcast.processors.stage3 import run as stage3_run

        cfg = {
            **CTM,
            "alignctd": {
                "oxygen": {
                    "default": 0.0,
                    "ranges": [{"casts": [[21, 21]], "value": 1.0}],
                }
            },
        }
        stage3_run(tmp_path / "ctd", cruise_cfg=cfg)
        build_profiles(tmp_path / "ctd", tmp_path / "profiles.nc", force=True)
    with xr.open_dataset(tmp_path / "profiles.nc", engine="netcdf4") as p:
        assert p.conductivity_1.attrs["cell_thermal_mass_alpha"] == 0.03
        assert "varies by cast" in p.oxygen_raw_1.attrs["alignment_offset_seconds"]
        np.testing.assert_array_equal(
            p.oxygen_raw_1_alignment_offset_seconds.values, [0, 0, 1, 1]
        )


def test_cast_page_lists_ctdcast_corrections(slice2):
    from ctdcast.reports.cast import _ctdcast_correction_rows

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = stage3(
            slice2, {**CTM, "alignctd": {"oxygen": {"default": 1.0}}}, cast_number=11
        )
    rows = _ctdcast_correction_rows(ds)
    assert [(r.label, t.variables) for r, t in rows] == [
        ("alignctd", "oxygen_raw_1"),
        ("celltm", "conductivity_1"),
        ("celltm", "conductivity_2"),
        ("SBE 43 oxygen", "ctd_oxygen"),
    ]
    # Same columns and references as the Sea-Bird table: OdB's celltm matches SBE's (0.03, 7);
    # oxygen has no reference; versions come from the file.
    states = [t.state for _r, t in rows]
    assert states == ["no_reference", "match", "match", "no_reference"]
    assert rows[1][0].version.startswith("ctdcast ") and "seabirdscientific 3.1" in (
        rows[1][0].version
    )
    assert rows[1][1].source == "SBE manual p.92 (TC duct, 3000-rpm pump)"


def test_cast_page_conductivity_alignment_judged_by_total_advance(slice2):
    from ctdcast.reports.cast import _ctdcast_correction_rows

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds0 = stage3(
            slice2, {"alignctd": {"conductivity": {"default": 0.0}}}, cast_number=11
        )
        ds1 = stage3(
            slice2, {"alignctd": {"conductivity": {"default": 0.02}}}, cast_number=11
        )
    (r0, t0), _ = _ctdcast_correction_rows(ds0)[:2]
    (_r1, t1), _ = _ctdcast_correction_rows(ds1)[:2]
    assert (
        t0.state == "match" and "deck unit's +0.073 s" in r0.parameters
    )  # 0.073 total
    assert t1.state == "differ"  # 0.093 total


# --- what Sea-Bird already did, from real headers ---------------------------------------------


def _header(name: str) -> str:
    return (FIX / name).read_text(encoding="latin-1")


def _header_ds(text: str, **attrs) -> xr.Dataset:
    import json

    raw = json.dumps(
        {"schema": "test", "raw_format": "sbe-cnv", "blocks": {"header": text}}
    )
    return xr.Dataset(attrs={"raw_metadata": raw, **attrs})


def test_applied_sbe_corrections_reads_alignctd_channels():
    from ctdcast.config.cnv_header import applied_sbe_corrections

    msm121 = applied_sbe_corrections(_header("cnv_headers/MSM121_054_1db.cnv"))
    assert {"alignctd", "celltm", "loopedit", "binavg"} <= msm121["modules"]
    assert msm121["aligned"] == {"oxygen_1": 4.0, "oxygen_2": 4.0}
    assert msm121["align_unparsed"] == []
    odb = applied_sbe_corrections(_header("cnv/mixsed2_004.cnv"))
    assert odb["aligned"] == {} and odb["deck_advance"][
        "primary conductivity"
    ] == pytest.approx(0.073)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("cnv/mixsed2_004.cnv", ("decibars", 1.0)),
        ("cnv/msm_142_1_017_1sec.cnv", ("seconds", 1.0)),
    ],
)
def test_parse_sample_interval_real_headers(name, expected):
    from ctdcast.config.cnv_header import parse_sample_interval

    assert parse_sample_interval(_header(name)) == expected


def test_native_rate_reasons_on_real_headers():
    msm142 = _header("cnv/msm_142_1_017_1sec.cnv")
    assert "not the SBE 9's native" in native_rate_reason(_header_ds(msm142))
    msm121 = _header("cnv_headers/MSM121_054_1db.cnv")
    # Claimed native rate but bin-averaged in the chain: still refused.
    assert "binavg" in native_rate_reason(
        _header_ds(msm121, sample_interval_seconds=1 / 24)
    )
    assert native_rate_reason(xr.Dataset()) == "no sample interval recorded"


def test_sea_bird_alignment_blocks_ctdcast_alignment(slice2):
    """A channel Sea-Bird's alignctd already advanced is not advanced again."""
    import json

    msm121 = _header("cnv_headers/MSM121_054_1db.cnv")
    hexhead = json.loads(slice2.attrs["raw_metadata"])["blocks"]["header"]
    raw = json.loads(slice2.attrs["raw_metadata"])
    # The slice's own header plus MSM121's processing chain minus its binavg: a native-rate
    # cast that Sea-Bird aligned (oxygen 4 s) and CTM-corrected.
    chain = "\n".join(
        ln for ln in msm121.splitlines() if ln.startswith("# ") and "binavg" not in ln
    )
    raw["blocks"]["header"] = hexhead.replace("*END*", chain + "\n*END*")
    ds = slice2.assign_attrs(raw_metadata=json.dumps(raw))
    with pytest.warns(UserWarning) as caught:
        out, rec = apply_corrections(
            ds, {**CTM, "alignctd": {"oxygen": {"default": 3.0}}}, 11
        )
    messages = " ".join(str(w.message) for w in caught)
    assert "already advanced it +4 s" in messages and "celltm already ran" in messages
    assert (
        rec.changed == [] and "alignment_offset_seconds" not in out.oxygen_raw_1.attrs
    )


def test_alignctd_channels_ctdcast_cannot_name_are_reported():
    """An alignctd entry ctdcast can't map to a variable is listed, so alignment is refused.

    No header in the corpus has one, so this edits MSM121's real alignctd line: an unknown
    channel name, and a known one with an unreadable advance.
    """
    from ctdcast.config.cnv_header import applied_sbe_corrections

    text = _header("cnv_headers/MSM121_054_1db.cnv").replace(
        "# alignctd_adv = sbeox0ML/L 4.000, sbeox1ML/L 4.000",
        "# alignctd_adv = sbeox0ML/L 4.000, par 1.000, c0S/m n/a",
    )
    applied = applied_sbe_corrections(text)
    assert applied["aligned"] == {"oxygen_1": 4.0}
    assert applied["align_unparsed"] == ["par 1.000", "c0S/m n/a"]


def test_ctm_skips_a_line_without_temperature(slice2):
    ds = slice2.drop_vars(
        ["ctd_temperature_2", "ctd_temperature_2_qc"], errors="ignore"
    )
    with pytest.warns(UserWarning, match="no temperature for line 2"):
        out, rec = apply_corrections(ds, CTM, 11)
    assert set(rec.cell_thermal_mass) == {"conductivity_1"}
    assert "cell_thermal_mass_alpha" not in out.conductivity_2.attrs


def test_oxygen_needs_the_xmlcon(slice2):
    import json

    raw = json.loads(slice2.attrs["raw_metadata"])
    del raw["blocks"]["xmlcon"]
    ds = derive_salinity(slice2.assign_attrs(raw_metadata=json.dumps(raw)))
    with pytest.warns(UserWarning, match="no .xmlcon"):
        _out, written = derive_oxygen(ds)
    assert written == []


def test_ctm_alpha_zero_is_no_correction(slice2):
    c, t = slice2.conductivity_1.values, slice2.ctd_temperature_1.values
    np.testing.assert_array_equal(
        cell_thermal_mass(c, t, 0.0, 7.0, 1 / 24), c.astype(float)
    )
    with pytest.raises(ValueError, match="tau > 0"):
        cell_thermal_mass(c, t, 0.03, 0.0, 1 / 24)


# --- review fixes -------------------------------------------------------------------------------


def test_rounded_cnv_interval_uses_the_exact_native_interval(slice2):
    """A CNV writes 1/24 s as 0.0416667; corrections use the exact native interval."""
    ds = slice2.copy()
    ds.attrs["sample_interval_seconds"] = 0.0416667
    interval, reason = native_interval(ds)
    assert reason is None and interval == 1 / 24
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out, rec = apply_corrections(
            ds, {"alignctd": {"conductivity": {"default": 0.073}}}, 11
        )
    assert rec.skipped == [] and len(out.conductivity_1) == len(ds.conductivity_1)


def test_stage_file_without_interval_attrs_skips_with_the_reason(slice2):
    """No recorded interval and no header ``# interval``: skip and say why, never KeyError."""
    ds = slice2.copy()
    for key in ("sample_interval_seconds", "sample_interval_kind"):
        ds.attrs.pop(key, None)
    assert native_interval(ds) == (None, "no sample interval recorded")
    with pytest.warns(UserWarning, match="no sample interval recorded"):
        _, rec = apply_corrections(ds, CTM, 11)
    assert rec.changed == []
    with pytest.warns(
        UserWarning, match="oxygen not derived: no sample interval recorded"
    ):
        derive_oxygen(derive_salinity(ds), None, cast_label="011")


@pytest.mark.parametrize(
    ("cfg", "match"),
    [
        ({"alignctd": {"conductivity": {"default": None}}}, "expected a number"),
        ({"alignctd": {"oxygen": {"default": "3"}}}, "expected a number"),
        (
            {"alignctd": {"oxygen": {"ranges": [{"casts": [[5, 9]], "value": "x"}]}}},
            "expected a number",
        ),
        ({"celltm": {"default": {"alpha": 0.03, "tau": 0}}}, "tau > 0"),
        ({"celltm": {"default": {"alpha": "a", "tau": 7}}}, "expected a number"),
        ({"oxygen": {"tau_window_seconds": 0.05}}, "more than two scans"),
        ({"oxygen": {"window": 2}}, "unknown key"),
    ],
)
def test_validate_config_rejects_bad_values(cfg, match):
    with pytest.raises(ValueError, match=match):
        validate_config(cfg)


def test_validate_config_accepts_the_documented_grammar():
    validate_config(
        {
            **CTM,
            "alignctd": {
                "conductivity": {"default": 0.0},
                "oxygen": {
                    "default": 3,
                    "ranges": [{"casts": [[30, 45]], "value": 2.5}],
                },
            },
            "oxygen": {"tau_window_seconds": 4},
        }
    )
    assert resolve_oxygen_window(None) == 2.0


def test_stage3_run_validates_config_before_any_cast(tmp_path):
    from ctdcast.processors.stage3 import run as stage3_run

    (tmp_path / "stage2").mkdir()
    with pytest.raises(ValueError, match="expected a number"):
        stage3_run(tmp_path, cruise_cfg={"alignctd": {"oxygen": {"default": None}}})


def test_oxygen_alignment_refused_when_sea_bird_converted_oxygen(slice2):
    ds = slice2.copy()
    ds["ctd_oxygen_1"] = ds.oxygen_raw_1 * 0 + 200.0
    with pytest.warns(UserWarning, match="Sea-Bird already converted oxygen"):
        out, rec = apply_corrections(ds, {"alignctd": {"oxygen": {"default": 3.0}}}, 11)
    np.testing.assert_array_equal(out.oxygen_raw_1.values, ds.oxygen_raw_1.values)
    assert "oxygen_raw_1" not in rec.changed


def test_conductivity_alignment_refused_when_sea_bird_aligned_temperature(slice2):
    ds = slice2.copy()
    header = "# alignctd_adv = t090C 0.500\n# datcnv_date = Jan 01 2026\n"
    from ctdcast.config.cnv_header import applied_sbe_corrections

    assert applied_sbe_corrections(header)["aligned"] == {"temperature_1": 0.5}
    import ctdcast.processors.corrections as corr

    real = corr.applied_sbe_corrections
    corr.applied_sbe_corrections = lambda _h: {
        **real(""),
        "aligned": {"temperature_1": 0.5},
    }
    try:
        with pytest.warns(UserWarning, match="advanced temperature_1"):
            out, rec = apply_corrections(
                ds, {"alignctd": {"conductivity": {"default": 0.02}}}, 11
            )
    finally:
        corr.applied_sbe_corrections = real
    assert "conductivity_1" not in rec.changed and "conductivity_2" in rec.changed


def test_empty_alignctd_adv_is_unparsed():
    from ctdcast.config.cnv_header import applied_sbe_corrections

    header = "# alignctd_adv = \n"
    got = applied_sbe_corrections(header)
    if "alignctd" in got["modules"]:
        assert got["align_unparsed"] == ["(no adv recorded)"]


def test_oxygen_converts_each_finite_run(slice2):
    """An interior gap leaves NaN only there; each side matches converting it alone."""
    ds = slice2.copy()
    v = ds.oxygen_raw_1.values.astype(float).copy()
    v[1800:1810] = np.nan
    ds["oxygen_raw_1"] = (ds.oxygen_raw_1.dims, v, dict(ds.oxygen_raw_1.attrs))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        full, _ = derive_oxygen(derive_salinity(ds), None, cast_label="011")
        left, _ = derive_oxygen(
            derive_salinity(ds.isel(time=slice(0, 1800))), None, cast_label="011"
        )
    o = full.ctd_oxygen.values
    assert np.isnan(o[1800:1810]).all()
    assert np.isfinite(o[:1800]).all() and np.isfinite(o[1810:]).all()
    np.testing.assert_allclose(o[:1800], left.ctd_oxygen.values)


def _o2_inputs(ds):
    from ctdcast.config.cnv_header import raw_metadata_block
    from ctdcast.readers.xmlcon import oxygen43_coefficients, parse_xmlcon

    ds = derive_salinity(ds)
    sensor = parse_xmlcon(
        raw_metadata_block(ds.attrs["raw_metadata"], "xmlcon")
    ).by_element("OxygenSensor")[0]
    arrays = [
        ds[v].values.astype(float)
        for v in ("oxygen_raw_1", "ctd_temperature_1", "pressure", "ctd_salinity_1")
    ]
    good = np.logical_and.reduce([np.isfinite(a) for a in arrays])
    return [a[good] for a in arrays], oxygen43_coefficients(sensor), sensor


def test_sbe43_dvdt_matches_seabirdscientific(slice2):
    """Remerge guard: the convolution is seabirdscientific's per-scan regression."""
    from seabirdscientific import conversion as sbs_conversion

    (v, t, p, s), coefs, _ = _o2_inputs(slice2)
    v, t, p, s = (a[:600] for a in (v, t, p, s))
    theirs = sbs_conversion.convert_sbe43_oxygen(
        v, t, p, s, coefs, apply_tau_correction=True, window_size=2.0,
        sample_interval=1 / 24, units="dov/dt",
    )  # fmt: skip
    np.testing.assert_allclose(sbe43_dvdt(v, 2.0, 1 / 24), theirs, rtol=0, atol=1e-10)


def test_sbe43_oxygen_differs_from_seabirdscientific_only_in_the_hysteresis(slice2):
    """Remerge guard: with seabirdscientific's recursion swapped in, the result is theirs."""
    from seabirdscientific import conversion as sbs_conversion

    import ctdcast.processors.corrections as corr

    (v, t, p, s), coefs, _ = _o2_inputs(slice2)
    v, t, p, s = (a[:600] for a in (v, t, p, s))
    theirs = sbs_conversion.convert_sbe43_oxygen(
        v, t, p, s, coefs, apply_tau_correction=True, apply_hysteresis_correction=True,
        window_size=2.0, sample_interval=1 / 24, units="umol/kg",
    )  # fmt: skip

    def sbs_recursion(volts, pressure, c, interval):
        out = np.asarray(volts, dtype=float).copy()
        cc = np.exp(-interval / c.h3)
        for i in range(1, out.size):
            d = 1 + c.h1 * (np.exp(pressure[i] / c.h2) - 1)
            x, prev = out[i] + c.v_offset, out[i - 1] + c.v_offset
            out[i] = ((x + prev * cc * d) - prev * cc) / d - c.v_offset
        return out

    real = corr.sbe43_hysteresis
    corr.sbe43_hysteresis = sbs_recursion
    try:
        ours_sbs_form = corr.sbe43_oxygen(v, t, p, s, coefs, 2.0, 1 / 24)
    finally:
        corr.sbe43_hysteresis = real
    np.testing.assert_allclose(ours_sbs_form, theirs, rtol=0, atol=1e-9)


def test_sbe43_hysteresis_is_application_note_64_3(slice2):
    """The filter is AN 64-3's recursion, with the uncorrected previous value."""
    (v, _, p, _), coefs, _ = _o2_inputs(slice2)
    v, p = v[:500], p[:500] + 3000.0  # deep, where the hysteresis term matters
    ox = v + coefs.v_offset
    expected = ox.copy()
    c = np.exp(-(1 / 24) / coefs.h3)
    for i in range(1, ox.size):
        d = 1 + coefs.h1 * (np.exp(p[i] / coefs.h2) - 1)
        expected[i] = (ox[i] + expected[i - 1] * c * d - ox[i - 1] * c) / d
    np.testing.assert_allclose(
        sbe43_hysteresis(v, p, coefs, 1 / 24),
        expected - coefs.v_offset,
        rtol=0,
        atol=1e-12,
    )


def test_oxygen_reconstructs_from_the_file_alone(slice2):
    from ctdcast.config.cnv_header import raw_metadata_block
    from ctdcast.readers.xmlcon import oxygen43_coefficients, parse_xmlcon

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out, _ = derive_oxygen(derive_salinity(slice2), None, cast_label="011")
    a = out.ctd_oxygen.attrs
    assert "64-3" in a["oxygen_hysteresis_method"]
    raw, temp, sal, pres = (x.strip() for x in a["derived_from"].split(","))
    sensor = parse_xmlcon(
        raw_metadata_block(out.attrs["raw_metadata"], "xmlcon")
    ).by_element("OxygenSensor")[int(raw[-1]) - 1]
    assert sensor.serial == a["sensor_serial_number"]
    arrays = [out[v].values.astype(float) for v in (raw, temp, pres, sal)]
    good = np.logical_and.reduce([np.isfinite(x) for x in arrays])
    v, t, p, s = (x[good] for x in arrays)
    redo = sbe43_oxygen(
        v,
        t,
        p,
        s,
        oxygen43_coefficients(sensor),
        a["oxygen_tau_window_seconds"],
        1 / 24,
    )
    np.testing.assert_allclose(redo, out.ctd_oxygen.values[good])


def test_cast_page_skips_preferred_composites(slice2):
    from ctdcast.reports.cast import _ctdcast_correction_rows

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds, _ = apply_corrections(slice2, CTM, 11)
    ds["conductivity"] = ds.conductivity_1.copy()
    ds["conductivity"].attrs["comment"] = "preferred primary channel; copied from x"
    rows = _ctdcast_correction_rows(ds)
    assert [t.variables for r, t in rows if r.label == "celltm"] == [
        "conductivity_1",
        "conductivity_2",
    ]
