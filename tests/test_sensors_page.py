"""The SBE sensors page: preferred-sensor table, calibration columns, cast-page line.

Real data only: the mixsed2 fixtures (dual T/C, single oxygen, no declaration) and the
msm_142 cast 056 CNV (dual T/C and dual oxygen), run through stages 1–3 under different
``preferred_pair`` / ``preferred_oxygen`` declarations.
"""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from conftest import FIXTURES_NC

from ctdcast.analysis.derive import fill_oxygen_composite
from ctdcast.config.parameters import color_limit_override, resolve_sensor_var
from ctdcast.plotters.profiles import _oxygen_label
from ctdcast.processors.profiles import build_profiles
from ctdcast.reports._sensors import generate_sensors_page, read_sensor_tables
from ctdcast.reports.cast import _preferred_str

_OXY_CNV = Path(__file__).parent / "fixtures" / "oxy" / "msm_142_1_056_1sec.cnv"


@pytest.fixture(scope="module")
def fixture_profiles(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("fix") / "profiles.nc"
    build_profiles(FIXTURES_NC, out, force=True)
    return out


def _run_cast_056(root: Path, cruise_cfg: dict) -> tuple[Path, Path]:
    """Cast 056 through stages 1–3 and profiles under *cruise_cfg*; (stage3, profiles)."""
    import ctdcast

    (root / "cnv").mkdir()
    shutil.copy(_OXY_CNV, root / "cnv")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ctdcast.process(
            [1, 2, 3, "profiles"],
            cnv_dir=root / "cnv",
            ctd_root=root / "ctd",
            force=True,
            cruise_cfg=cruise_cfg,
        )
    return next((root / "ctd" / "stage3").glob("*.nc")), root / "ctd" / "profiles.nc"


@pytest.fixture(scope="module")
def oxygen_declared(tmp_path_factory) -> tuple[Path, Path]:
    return _run_cast_056(
        tmp_path_factory.mktemp("oxy"), {"preferred_oxygen": {"default": "secondary"}}
    )


@pytest.fixture(scope="module")
def all_undeclared(tmp_path_factory) -> tuple[Path, Path]:
    return _run_cast_056(tmp_path_factory.mktemp("undecl"), {})


@pytest.fixture(scope="module")
def all_declared(tmp_path_factory) -> tuple[Path, Path]:
    return _run_cast_056(
        tmp_path_factory.mktemp("decl"),
        {
            "preferred_pair": {"default": "primary"},
            "preferred_oxygen": {"default": "secondary"},
        },
    )


def test_undeclared_dual_pair_reads_not_declared(fixture_profiles):
    runs = read_sensor_tables(fixture_profiles)["preferred"]
    assert len(runs) == 1  # all four casts share one configuration
    (run,) = runs
    assert run["range"] == "011–129"
    assert run["pair"] == "not declared" and run["pair_serials"] == ""
    assert run["oxygen"] == "single sensor" and run["oxygen_serial"] == "0707"
    assert run["undeclared"]


def test_inventory_carries_slope_and_offset(fixture_profiles):
    meta = read_sensor_tables(fixture_profiles)
    by_serial = {r["serial"]: r for r in meta["catalog"]}
    c2, p, t1 = by_serial["3120"], by_serial["0814"], by_serial["6435"]
    assert (c2["slope"], c2["slope_nondefault"]) == ("0.99993682", True)
    assert (p["offset"], p["offset_nondefault"]) == ("0.27440", True)
    assert not (t1["slope_nondefault"] or t1["offset_nondefault"])
    assert by_serial["0707"]["slope"] == ""  # oxygen: no datcnv drift knob
    assert meta["any_calibrated"]


def test_sensors_page_renders_preferred_and_calibration(fixture_profiles, tmp_path):
    html = generate_sensors_page(fixture_profiles, tmp_path / "s.html").read_text(
        encoding="utf-8"
    )
    assert 'id="s-preferred"' in html and "not declared" in html
    assert "Amber row: a cast with two T/C pairs" in html
    assert 'style="background:var(--warn-bg)"' in html
    assert "<strong>0.99993682</strong>" in html
    assert "Amber row: a calibration was applied" in html


@pytest.mark.slow
def test_declared_dual_oxygen_shows_on_both_pages(oxygen_declared):
    stage3, profiles = oxygen_declared
    (run,) = read_sensor_tables(profiles)["preferred"]
    assert run["oxygen"] == "secondary" and run["oxygen_serial"] == "1451"
    assert run["pair"] == "not declared"
    with xr.open_dataset(stage3, engine="netcdf4") as ds:
        assert _preferred_str(ds) == "T/C not declared, O₂ secondary (s/n 1451)"


@pytest.mark.slow
def test_undeclared_dual_oxygen_shows_line_1(all_undeclared):
    stage3, profiles = all_undeclared
    (run,) = read_sensor_tables(profiles)["preferred"]
    assert run["oxygen"] == "line 1 shown (not declared)"
    assert run["oxygen_serial"] == "2415"  # the line-1 sensor
    assert run["undeclared"]
    with xr.open_dataset(stage3, engine="netcdf4") as ds:
        assert _preferred_str(ds) == "T/C not declared, O₂ line 1 shown (not declared)"


@pytest.mark.slow
def test_fully_declared_cast_has_no_amber_and_no_caption(all_declared, tmp_path):
    stage3, profiles = all_declared
    (run,) = read_sensor_tables(profiles)["preferred"]
    assert run["pair"] == "primary" and run["pair_serials"] == "4823 / 3425"
    assert not run["undeclared"]
    html = generate_sensors_page(profiles, tmp_path / "s.html").read_text(
        encoding="utf-8"
    )
    preferred = html[html.index('id="s-preferred"') : html.index('id="s-inventory"')]
    assert "Amber row" not in preferred and "--warn-bg" not in preferred
    with xr.open_dataset(stage3, engine="netcdf4") as ds:
        assert _preferred_str(ds) == (
            "T/C primary (s/n 4823 / 3425), O₂ secondary (s/n 1451)"
        )


@pytest.mark.slow
def test_mixed_cruise_draws_every_cast_and_splits_runs(all_undeclared, tmp_path):
    """Single-oxygen casts carry a plain ``ctd_oxygen``; an undeclared dual cast does not.

    Compiled together, ``profiles.nc`` holds ``ctd_oxygen`` (blank for cast 056) and the
    pages draw that name, so the fill must put line 1 into cast 056's profiles.
    """
    stage3, _ = all_undeclared
    nc = tmp_path / "nc"
    nc.mkdir()
    for f in FIXTURES_NC.glob("*.nc"):
        shutil.copy(f, nc)
    shutil.copy(stage3, nc / "mixsed2_056.nc")
    out = tmp_path / "profiles.nc"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        build_profiles(nc, out, force=True)
    with xr.open_dataset(out, engine="netcdf4") as ds:
        ds = ds.load()
    assert resolve_sensor_var(ds, "ctd_oxygen") == "ctd_oxygen"
    k56 = int(np.flatnonzero(ds["cast_number"].values == 56)[0])
    k11 = int(np.flatnonzero(ds["cast_number"].values == 11)[0])
    assert not np.isfinite(ds["ctd_oxygen"][k56]).any()
    filled = fill_oxygen_composite(ds)
    np.testing.assert_array_equal(
        filled["ctd_oxygen"][k56].values, ds["ctd_oxygen_1"][k56].values
    )
    np.testing.assert_array_equal(
        filled["ctd_oxygen"][k11].values, ds["ctd_oxygen"][k11].values
    )
    assert filled["ctd_oxygen"].attrs["filled_from_ctd_oxygen_1"] == "056"

    runs = read_sensor_tables(out)["preferred"]
    assert [r["range"] for r in runs] == ["011–012", "056", "128–129"]
    assert runs[1]["oxygen"] == "line 1 shown (not declared)"


def test_fill_leaves_a_dataset_without_line_1_alone(fixture_profiles):
    with xr.open_dataset(fixture_profiles, engine="netcdf4") as ds:
        assert fill_oxygen_composite(ds) is ds


def test_stage1_cast_reads_not_resolved_yet():
    with xr.open_dataset(FIXTURES_NC / "mixsed2_011.nc", engine="netcdf4") as ds:
        # Dual T/C, single oxygen; a stage-1 file, so the choice is not stamped yet.
        assert int(ds.attrs["processing_stage"]) == 1
        assert _preferred_str(ds) == "T/C not resolved yet (stage 1 file)"


def test_oxygen_label_follows_the_line_drawn():
    plain = _oxygen_label({})
    assert _oxygen_label({"preferred_oxygen": "secondary", "oxygen_line": 2}) == (
        f"{plain} · secondary"
    )
    assert _oxygen_label({"preferred_oxygen": "undeclared", "oxygen_line": 1}) == (
        f"{plain} · line 1, not declared"
    )
    # Declared secondary that could not be derived: the figure fell back to line 1.
    assert _oxygen_label({"preferred_oxygen": "secondary", "oxygen_line": 1}) == (
        f"{plain} · line 1 (secondary not available)"
    )


def test_color_limit_override_never_puts_a_composite_override_on_line_2():
    assert (
        color_limit_override({"ctd_oxygen": 40.0}, "ctd_oxygen_2", "ctd_oxygen_2")
        is None
    )
    assert (
        color_limit_override({"ctd_oxygen_2": 45.0}, "ctd_oxygen_2", "ctd_oxygen_2")
        == 45.0
    )


def test_report_inventory_points_to_sensors_page(fixture_profiles, tmp_path):
    from ctdcast.reports.dataset import generate_dataset_page

    html = generate_dataset_page(
        fixture_profiles, tmp_path / "inv.html", sensors_href="sbe_sensors.html"
    ).read_text(encoding="utf-8")
    assert 'id="s-sensors"' in html
    assert 'href="sbe_sensors.html#s-variables"' in html
    assert "sensor_channel_&lt;role&gt;" in html  # the three families are explained
    assert 'id="s-sensor-catalog"' not in html  # the tables live on the sensors page


def test_standalone_inventory_keeps_sensor_tables(fixture_profiles, tmp_path):
    from ctdcast.reports.dataset import generate_dataset_page

    html = generate_dataset_page(fixture_profiles, tmp_path / "inv.html").read_text(
        encoding="utf-8"
    )
    for sid in (
        "s-sensors",
        "s-sensor-catalog",
        "s-sensor-linkage",
        "s-sensor-channel",
    ):
        assert f'id="{sid}"' in html
    assert "sbe_sensors.html" not in html


def test_sensors_page_ends_with_the_sensor_variables(fixture_profiles, tmp_path):
    html = generate_sensors_page(
        fixture_profiles, tmp_path / "s.html", inventory_href="profiles_inventory.html"
    ).read_text(encoding="utf-8")
    assert 'id="s-variables"' in html and 'href="profiles_inventory.html"' in html
    for sid in ("s-sensor-catalog", "s-sensor-linkage", "s-sensor-channel"):
        assert f'id="{sid}"' in html
    assert "SENSOR_CONDUCTIVITY_3120" in html
