import re
from pathlib import Path

import pytest
import yaml

from ctdcast.config.sbe_steps import header_text_of, processing_steps, processing_yaml

FIX = Path(__file__).parent / "fixtures"


def _modules(steps):
    return [next(iter(s)) for s in steps]


def test_odb_steps_in_run_order():
    out = processing_steps(header_text_of(FIX / "cnv" / "mixsed2_004.cnv"))
    assert _modules(out["steps"]) == [
        "wildedit",
        "window_filter",
        "filter",
        "filter",
        "celltm",
    ]
    # Bin Average changes which scans there are, so it opens a product.
    assert out["products"] == [
        {
            "name": "1dbar",
            "steps": [{"binavg": out["products"][0]["steps"][0]["binavg"]}],
        }
    ]
    assert [s["module"] for s in out["skipped"]] == ["datcnv", "Derive"]


def test_wildedit_parameters_and_names():
    we = processing_steps(header_text_of(FIX / "cnv" / "mixsed2_004.cnv"))["steps"][0][
        "wildedit"
    ]
    assert we["pass1_nstd"] == 2.0 and we["pass2_nstd"] == 20.0
    assert we["scans_per_block"] == 100 and we["exclude_flagged"] is True
    assert {"pressure", "conductivity_1", "ctd_temperature_2"} <= set(we["variables"])


def test_window_filter_grouped_by_type_and_width():
    wf = processing_steps(header_text_of(FIX / "cnv" / "mixsed2_004.cnv"))["steps"][1][
        "window_filter"
    ]
    assert wf["type"] == "median" and wf["width"] == 10
    assert wf["variables"][:3] == ["pressure", "ctd_temperature_1", "conductivity_1"]


def test_filter_a_and_b_are_two_steps():
    steps = processing_steps(header_text_of(FIX / "cnv" / "mixsed2_004.cnv"))["steps"]
    a, b = steps[2]["filter"], steps[3]["filter"]
    assert a["time_constant"] == 0.03 and "ctd_fluor" in a["variables"]
    assert b == {"time_constant": 0.15, "variables": ["pressure"]}


def test_celltm_per_sensor_and_binavg():
    out = processing_steps(header_text_of(FIX / "cnv" / "mixsed2_004.cnv"))
    steps = out["steps"]
    assert steps[4]["celltm"] == {
        "conductivity_1": {"alpha": 0.03, "tau": 7.0},
        "conductivity_2": {"alpha": 0.03, "tau": 7.0},
    }
    bavg = out["products"][0]["steps"][0]["binavg"]
    assert bavg["bin"] == "decibars" and bavg["size"] == 1
    assert bavg["surface_bin"] is None


def test_other_order_alignctd_and_loopedit():
    out = processing_steps(header_text_of(FIX / "cnv_headers" / "MSM121_054_1db.cnv"))
    mods = _modules(out["steps"])
    assert mods == [
        "filter",
        "filter",
        "alignctd",
        "celltm",
        "loopedit",
        "wildedit",
    ]
    assert out["products"][0]["steps"][0]["binavg"]["surface_bin"] == {
        "min": 0.0,
        "max": 0.0,
        "value": 0.0,
    }
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
    loaded = yaml.safe_load(processing_yaml(text))
    assert loaded["data_processing"]["steps"] == processing_steps(text)["steps"]
    assert loaded["data_processing"]["products"] == processing_steps(text)["products"]
    assert "# not a step: datcnv" in processing_yaml(text)


def test_rename_map_wins():
    text = header_text_of(FIX / "cnv" / "mixsed2_004.cnv")
    we = processing_steps(text, {"prdm": "my_pressure"})["steps"][0]["wildedit"]
    assert we["variables"][0] == "my_pressure"


def test_yaml_style_one_step_per_line():
    text = processing_yaml(header_text_of(FIX / "cnv" / "mixsed2_004.cnv"))
    assert "  - wildedit:\n" in text
    assert "conductivity_1: {alpha: 0.03, tau: 7.0}" in text
    assert "variables: [pressure]" in text


def test_inspect_cnv_prints_block_and_writes_page(tmp_path, capsys):
    from ctdcast.cli import inspect as cli_inspect

    out = tmp_path / "processing.html"
    args = cli_inspect.build_parser().parse_args(
        [str(FIX / "cnv" / "mixsed2_004.cnv"), "-o", str(out)]
    )
    assert cli_inspect.run(args) == 0
    assert "data_processing:" in capsys.readouterr().out
    html = out.read_text()
    assert "sbe-processing-config" in html and "wildedit" in html
    assert 'src="http' not in html


def test_inspect_cnv_without_out_writes_nothing(tmp_path, capsys):
    import shutil

    from ctdcast.cli import inspect as cli_inspect

    cnv = shutil.copy(FIX / "cnv" / "mixsed2_004.cnv", tmp_path / "x.cnv")
    args = cli_inspect.build_parser().parse_args([str(cnv)])
    assert cli_inspect.run(args) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.cnv"]


def test_stacked_advance_found_and_flagged_everywhere(tmp_path):
    from ctdcast.config.cnv_header import (
        CONFORMANCE_DIFFER,
        conformance_ticks,
        provenance_advisories,
        stacked_advances,
    )
    from ctdcast.reports.sbe_processing import generate_sbe_processing_page

    path = FIX / "cnv_headers" / "mixsed2_017_cnv24Hz.cnv"
    text = header_text_of(path)
    (s,) = stacked_advances(text)
    assert (s.channel, s.deck, s.software) == ("c0S/m", 0.073, 0.073)
    assert s.total == pytest.approx(0.146)
    assert "+0.146 s in all" in processing_yaml(text)
    assert any("+0.146 s in all" in a for a in provenance_advisories(text))
    (tick,) = [t for t in conformance_ticks(text) if t.key == "alignctd"]
    assert tick.state == CONFORMANCE_DIFFER and tick.variables == "conductivity_1"
    html = generate_sbe_processing_page(path, tmp_path / "p.html").read_text()
    assert "var(--warn-bg)" in html and "Amber: an Align CTD step" in html


def test_no_stacked_advance_without_a_conductivity_alignctd():
    from ctdcast.config.cnv_header import stacked_advances

    for path in (
        FIX / "cnv" / "mixsed2_004.cnv",
        FIX / "cnv_headers" / "MSM121_054_1db.cnv",  # aligns oxygen only
    ):
        text = header_text_of(path)
        assert stacked_advances(text) == []
        assert "# check:" not in processing_yaml(text)


def test_a_split_becomes_one_product_per_leg():
    from ctdcast.config.sbe_steps import _as_products

    trunk, products = _as_products(
        [
            {"wildedit": {}},
            {"split": {"exclude_flagged": True}},
            {"loopedit": {"min_velocity": 0.25}},
            {"binavg": {"bin": "decibars", "size": 1}},
        ]
    )
    assert trunk == [{"wildedit": {}}]
    assert [p["name"] for p in products] == ["1dbar_down", "1dbar_up"]
    assert products[1]["steps"][0] == {"split": "up"}
    assert next(iter(products[0]["steps"][1])) == "loopedit"


def test_bin_average_that_kept_bad_scans_becomes_a_check_line():
    from ctdcast.config.sbe_steps import header_text_of, processing_yaml
    from ctdcast.processors.steps import validate_data_processing

    header = header_text_of(FIX / "cnv" / "mixsed2_004.cnv")
    assert "binavg_excl_bad_scans" in header
    kept = re.sub(r"(binavg_excl_bad_scans\s*=\s*)\w+", r"\1no", header)
    block = processing_yaml(kept)
    assert "# check: this file's Bin Average kept scans marked bad" in block
    dp = yaml.safe_load(block)["data_processing"]
    assert "exclude_flagged" not in dp["products"][0]["steps"][-1]["binavg"]
    validate_data_processing(dp)
