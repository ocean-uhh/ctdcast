from pathlib import Path

import yaml

from ctdcast.config.sbe_chain import chain_steps, chain_yaml, header_text_of

FIX = Path(__file__).parent / "fixtures"


def _modules(steps):
    return [next(iter(s)) for s in steps]


def test_odb_chain_in_run_order():
    out = chain_steps(header_text_of(FIX / "cnv" / "mixsed2_004.cnv"))
    assert _modules(out["steps"]) == [
        "wildedit",
        "window_filter",
        "filter",
        "filter",
        "celltm",
        "binavg",
    ]
    assert [s["module"] for s in out["skipped"]] == ["datcnv", "Derive"]


def test_wildedit_parameters_and_names():
    we = chain_steps(header_text_of(FIX / "cnv" / "mixsed2_004.cnv"))["steps"][0][
        "wildedit"
    ]
    assert we["pass1_nstd"] == 2.0 and we["pass2_nstd"] == 20.0
    assert we["scans_per_block"] == 100 and we["exclude_flagged"] is True
    assert {"pressure", "conductivity_1", "ctd_temperature_2"} <= set(we["variables"])


def test_window_filter_grouped_by_type_and_width():
    wf = chain_steps(header_text_of(FIX / "cnv" / "mixsed2_004.cnv"))["steps"][1][
        "window_filter"
    ]
    assert wf["type"] == "median" and wf["width"] == 10
    assert wf["variables"][:3] == ["pressure", "ctd_temperature_1", "conductivity_1"]


def test_filter_a_and_b_are_two_steps():
    steps = chain_steps(header_text_of(FIX / "cnv" / "mixsed2_004.cnv"))["steps"]
    a, b = steps[2]["filter"], steps[3]["filter"]
    assert a["time_constant"] == 0.03 and "ctd_fluor" in a["variables"]
    assert b == {"time_constant": 0.15, "variables": ["pressure"]}


def test_celltm_per_sensor_and_binavg():
    steps = chain_steps(header_text_of(FIX / "cnv" / "mixsed2_004.cnv"))["steps"]
    assert steps[4]["celltm"] == {
        "conductivity_1": {"alpha": 0.03, "tau": 7.0},
        "conductivity_2": {"alpha": 0.03, "tau": 7.0},
    }
    bavg = steps[5]["binavg"]
    assert bavg["bin"] == "decibars" and bavg["size"] == 1
    assert bavg["surface_bin"] is None


def test_other_order_alignctd_and_loopedit():
    out = chain_steps(header_text_of(FIX / "cnv_headers" / "MSM121_054_1db.cnv"))
    mods = _modules(out["steps"])
    assert mods == [
        "filter",
        "filter",
        "alignctd",
        "celltm",
        "loopedit",
        "wildedit",
        "binavg",
    ]
    le = out["steps"][4]["loopedit"]
    assert le["min_velocity"] == 0.1
    assert le["surface_soak"] == {
        "min_depth": 7.0,
        "max_depth": 24,
        "deck_pressure": True,
    }
    assert set(out["steps"][2]["alignctd"].values()) == {4.0}


def test_yaml_round_trips():
    text = header_text_of(FIX / "cnv" / "mixsed2_004.cnv")
    loaded = yaml.safe_load(chain_yaml(text))
    assert loaded["data_processing"]["steps"] == chain_steps(text)["steps"]
    assert "# not a step: datcnv" in chain_yaml(text)


def test_rename_map_wins():
    text = header_text_of(FIX / "cnv" / "mixsed2_004.cnv")
    we = chain_steps(text, {"prdm": "my_pressure"})["steps"][0]["wildedit"]
    assert we["variables"][0] == "my_pressure"
