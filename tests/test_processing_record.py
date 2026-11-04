"""The per-cast processing record, its compile into profiles.nc, and the cruise processing page."""

import dataclasses
import json
import warnings

import numpy as np
import pytest
import xarray as xr

from ctdcast.analysis.processing_record import (
    ProcessingRow,
    processing_rows,
    record_json,
    rows_from_json,
)
from ctdcast.config.cnv_header import CONFORMANCE_DIFFER
from ctdcast.processors.editing import SOAK_NOT_APPLIED
from ctdcast.processors.profiles import build_profiles
from ctdcast.processors.stage3 import run as stage3_run
from ctdcast.reports.processing import (
    VARIES_AFTER,
    generate_processing_page,
    read_processing_tables,
)

#: OdB's own steps (from its CNV header), cut down to one of each kind ctdcast applies.
DP = {
    "steps": [
        {
            "wildedit": {
                "pass1_nstd": 2.0,
                "pass2_nstd": 20.0,
                "variables": ["pressure"],
            }
        },
        {"filter": {"time_constant": 0.15, "variables": ["pressure"]}},
        {"celltm": {"conductivity_1": {"alpha": 0.03, "tau": 7.0}}},
        {
            "loopedit": {
                "min_velocity": 0.25,
                "surface_soak": {"min_depth": 5.0, "max_depth": 20, "deck_pressure": 0},
            }
        },
    ],
    "products": [
        {
            "name": "1dbar_down",
            "steps": [{"split": "down"}, {"binavg": {"bin": "decibars", "size": 1}}],
        }
    ],
}


@pytest.fixture(scope="module")
def odb_root(hex_stage2, tmp_path_factory):
    """OdB cast 011 (the committed .hex slice) through stage 3 and the profiles compile."""
    root = tmp_path_factory.mktemp("prov")
    (root / "stage2").mkdir()
    hex_stage2.to_netcdf(root / "stage2" / "MIXSED2_011_stage2.nc")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stage3_run(root, force=True, cruise_cfg={"data_processing": DP})
        build_profiles(root, root / "profiles.nc", force=True)
    return root


@pytest.fixture(scope="module")
def stage3_ds(odb_root):
    path = next((odb_root / "stage3").glob("*.nc"))
    with xr.open_dataset(path, engine="netcdf4") as ds:
        return ds.load()


def test_record_lists_every_stage_in_order(stage3_ds):
    rows = processing_rows(stage3_ds)
    stages = [r.stage for r in rows]
    assert stages == sorted(
        stages, key=["stage 1", "Sea-Bird", "stage 2", "stage 3", "product"].index
    )
    steps = [r.step for r in rows if r.stage == "stage 3"]
    assert steps[:4] == ["wildedit", "filter", "celltm", "loopedit"]
    loop = next(r for r in rows if r.step == "loopedit")
    # The setting is what was configured; what it did on this cast is the outcome.
    assert loop.setting == stage3_ds["loop_edit_flag"].attrs["loop_edit"]
    assert "scans marked" in loop.outcome
    product = next(r for r in rows if r.stage == "product")
    assert product.step == "binavg (1dbar_down)"
    assert product.setting == "split down; binavg decibars 1"


def test_record_round_trips_through_json(stage3_ds):
    text = record_json(stage3_ds)
    assert isinstance(json.loads(text), list)
    assert rows_from_json(text) == processing_rows(stage3_ds)
    assert rows_from_json("") == []


def test_profiles_carry_the_record_on_both_legs(odb_root, stage3_ds):
    with xr.open_dataset(odb_root / "profiles.nc", engine="netcdf4") as prof:
        records = [str(v) for v in prof["processing_record"].values]
        directions = list(prof["cast_direction"].values.astype(str))
    assert sorted(directions) == ["down", "up"]
    assert records[0] == records[1] == record_json(stage3_ds)


def _cruise(tmp_path, records):
    """A profiles.nc holding only what the processing page reads: one record per cast, both legs."""
    n = len(records)
    ds = xr.Dataset(
        {
            "cast_number": ("N_PROF", np.repeat(np.arange(1, n + 1), 2)),
            "cast_suffix": ("N_PROF", np.array([""] * 2 * n, dtype=object)),
            "cast_direction": ("N_PROF", np.array(["down", "up"] * n, dtype=object)),
            "processing_record": (
                "N_PROF",
                np.repeat(
                    np.array(
                        [
                            json.dumps([dataclasses.asdict(r) for r in rows])
                            for rows in records
                        ],
                        dtype=object,
                    ),
                    2,
                ),
            ),
        }
    )
    path = tmp_path / "profiles.nc"
    ds.to_netcdf(path)
    return path


def _with(rows, step, **changes):
    return [dataclasses.replace(r, **changes) if r.step == step else r for r in rows]


def test_page_collapses_runs_and_marks_exceptions(stage3_ds, tmp_path):
    base = processing_rows(stage3_ds)
    loop = next(r for r in base if r.step == "loopedit")
    deep = _with(
        base,
        "loopedit",
        outcome=f"{loop.outcome}; {SOAK_NOT_APPLIED}: the recording starts below the soak window (at 200.0 dbar)",
    )
    tighter = _with(base, "wildedit", setting="pass1_nstd=3 pass2_nstd=20")
    # Casts 1–3 as set, 4–5 a different Wild Edit, 6 starts at depth, 7 as set.
    path = _cruise(tmp_path, [base, base, base, tighter, tighter, deep, base])
    meta = read_processing_tables(path)
    steps = {s.step: s for _, _, ss in meta["stages"] for s in ss}
    assert [r.casts for r in steps["wildedit"].runs] == [
        "001–003",
        "004–005",
        "006–007",
    ]
    # The skipped soak test leaves the setting alone (one run) and gets its own amber row.
    assert [r.casts for r in steps["loopedit"].runs] == ["001–007"]
    assert (
        steps["loopedit"].exception_casts == "006"
        and steps["loopedit"].exception_count == 1
    )
    assert meta["any_exception"]

    out = generate_processing_page(path, tmp_path / "processing.html", cruise="test")
    html = out.read_text()
    assert "did not run as its setting says" in html
    assert "006" in html and "soak test not applied" in html


def test_page_draws_a_setting_that_varies_cast_to_cast(stage3_ds, tmp_path):
    base = processing_rows(stage3_ds)
    records = [
        _with(
            base,
            "celltm",
            setting=f"alpha={0.02 + 0.002 * i:g} tau=7 s, with ctd_temperature_1",
        )
        for i in range(VARIES_AFTER + 2)
    ]
    meta = read_processing_tables(_cruise(tmp_path, records))
    celltm = next(s for _, _, ss in meta["stages"] for s in ss if s.step == "celltm")
    assert celltm.varies is not None
    assert (
        celltm.varies["setting"] == "alpha=0.02–0.032 tau=7 s, with ctd_temperature_1"
    )
    assert celltm.figure  # one number varies, so it is drawn against cast number


def test_amber_caption_states_the_reference_criterion(stage3_ds, tmp_path):
    base = processing_rows(stage3_ds)
    differ = _with(
        base,
        "celltm",
        state=CONFORMANCE_DIFFER,
        reference="(α,τ)=(0.03,7)",
        source="SBE manual",
    )
    path = _cruise(tmp_path, [differ, differ])
    html = generate_processing_page(path, tmp_path / "p.html").read_text()
    assert "differs from the value SBE documents" in html
    assert "var(--warn-bg)" in html


def test_page_without_a_record_says_how_to_rebuild(tmp_path):
    path = tmp_path / "old.nc"
    xr.Dataset({"cast_number": ("N_PROF", [1, 1])}).to_netcdf(path)
    html = generate_processing_page(path, tmp_path / "p.html").read_text()
    assert "No processing record" in html and "--stage profiles --force" in html


def test_processing_row_defaults_are_json_safe():
    row = ProcessingRow("stage 3", "filter", "ctdcast", "0", "low-pass 0.15 s")
    assert rows_from_json(json.dumps([dataclasses.asdict(row)])) == [row]
