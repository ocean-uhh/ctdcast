"""The SBE sensors page: preferred-sensor table, calibration drift figure, cast-page line.

Two real data sets: the mixsed2 fixtures (dual T/C, single oxygen, no declaration) and
the msm_142 cast 056 CNV (dual T/C and dual oxygen), run through stages 1–3 with
``preferred_oxygen`` declared.
"""

from __future__ import annotations

import re
import shutil
import warnings
from pathlib import Path

import pytest
import xarray as xr
from conftest import FIXTURES_NC

from ctdcast.plotters.profiles import _oxygen_label
from ctdcast.processors.profiles import build_profiles
from ctdcast.reports._sensors import generate_sensors_page, read_sensor_tables
from ctdcast.reports.cast import _preferred_str

_OXY_CNV = Path(__file__).parent / "fixtures" / "oxy" / "msm_142_1_056_1sec.cnv"
_TEMPLATES = Path(__file__).parents[1] / "ctdcast" / "reports" / "templates"


@pytest.fixture(scope="module")
def fixture_profiles(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("fix") / "profiles.nc"
    build_profiles(FIXTURES_NC, out, force=True)
    return out


@pytest.fixture(scope="module")
def dual_oxygen(tmp_path_factory) -> tuple[Path, Path]:
    """Cast 056 through stages 1–3 and profiles, ``preferred_oxygen: secondary``."""
    import ctdcast

    root = tmp_path_factory.mktemp("oxy")
    (root / "cnv").mkdir()
    shutil.copy(_OXY_CNV, root / "cnv")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ctdcast.process(
            [1, 2, 3, "profiles"],
            cnv_dir=root / "cnv",
            ctd_root=root / "ctd",
            force=True,
            cruise_cfg={"preferred_oxygen": {"default": "secondary"}},
        )
    stage3 = next((root / "ctd" / "stage3").glob("*.nc"))
    return stage3, root / "ctd" / "profiles.nc"


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
    html = generate_sensors_page(fixture_profiles, tmp_path / "s.html").read_text()
    assert 'id="s-preferred"' in html and "not declared" in html
    assert "Amber row: a cast with two T/C pairs" in html
    assert "<strong>0.99993682</strong>" in html
    assert "Amber row: a calibration was applied" in html


@pytest.mark.slow
def test_declared_dual_oxygen_shows_on_both_pages(dual_oxygen, tmp_path):
    stage3, profiles = dual_oxygen
    (run,) = read_sensor_tables(profiles)["preferred"]
    assert run["oxygen"] == "secondary" and run["oxygen_serial"] == "1451"
    assert run["pair"] == "not declared"
    with xr.open_dataset(stage3, engine="netcdf4") as ds:
        assert _preferred_str(ds) == "T/C not declared, O₂ secondary (s/n 1451)"


def test_single_sensor_cast_has_no_preferred_line():
    with xr.open_dataset(FIXTURES_NC / "mixsed2_011.nc", engine="netcdf4") as ds:
        # Dual T/C, single oxygen, undeclared: only the pair has a choice to report.
        assert _preferred_str(ds) == "T/C not declared"


def test_oxygen_label_names_the_line():
    plain = _oxygen_label({})
    assert _oxygen_label({"preferred_oxygen": "secondary", "oxygen_line": 2}) == (
        f"{plain} · secondary"
    )
    assert _oxygen_label({"preferred_oxygen": "undeclared", "oxygen_line": 1}) == (
        f"{plain} · line 1, not declared"
    )


#: Owned templates still writing their own ``<th>``, with the reason each is exempt.
_TH_EXEMPT = {
    # Column classes (``num``) and a ``title`` tooltip that the vendored ``thead`` macro
    # cannot express yet.
    "casts.html",
}


def test_owned_templates_use_the_vendored_thead():
    offenders = sorted(
        p.name
        for p in _TEMPLATES.glob("*.html")
        if p.name not in _TH_EXEMPT and re.search(r"<th[\s>]", p.read_text())
    )
    assert offenders == []


def test_report_inventory_points_to_sensors_page(fixture_profiles, tmp_path):
    from ctdcast.reports.dataset import generate_dataset_page

    html = generate_dataset_page(
        fixture_profiles, tmp_path / "inv.html", sensors_href="sbe_sensors.html"
    ).read_text()
    assert 'id="s-sensors"' in html
    assert 'href="sbe_sensors.html#s-variables"' in html
    assert "sensor_channel_&lt;role&gt;" in html  # the three families are explained
    assert 'id="s-sensor-catalog"' not in html  # the tables live on the sensors page


def test_standalone_inventory_keeps_sensor_tables(fixture_profiles, tmp_path):
    from ctdcast.reports.dataset import generate_dataset_page

    html = generate_dataset_page(fixture_profiles, tmp_path / "inv.html").read_text()
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
    ).read_text()
    assert 'id="s-variables"' in html and 'href="profiles_inventory.html"' in html
    for sid in ("s-sensor-catalog", "s-sensor-linkage", "s-sensor-channel"):
        assert f'id="{sid}"' in html
    assert "SENSOR_CONDUCTIVITY_3120" in html
