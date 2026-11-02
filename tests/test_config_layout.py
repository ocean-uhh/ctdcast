import re
import warnings

import pytest
import yaml

from ctdcast.config.layout import processing_view
from ctdcast.processors.corrections import resolve_slope_offset
from ctdcast.processors.steps import iter_steps
from ctdcast.processors.steps import validate_data_processing as validate_config

NEW = {
    "preferred_sensor": {
        "tc": {
            "default": "primary",
            "ranges": [{"casts": [[5, 9]], "value": "secondary"}],
        },
        "oxygen": "secondary",
    },
    "clock": {"segments": [{"casts": [[1, 3]], "clock_offset_seconds": 4.0}]},
    "qc": {"spike": {"fail": {"pressure": 50.0}}},
    "fit": {"ctm_pmin": 300},
    "data_processing": {
        "slope_offset": {"conductivity_1": {"slope": 1.0001}},
        "steps": [
            {"wildedit": {"pass2_nstd": 5.0}},
            {"celltm": {"conductivity": {"alpha": 0.03, "tau": 7}}},
        ],
    },
    "processing": {"profiles_dbar": 2, "trim": {"near_surface_dbar": 8}},
}


def test_new_layout_reads_without_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        view = processing_view(NEW)
    assert view["preferred_pair"]["ranges"] == [{"casts": [[5, 9]], "use": "secondary"}]
    assert view["preferred_oxygen"] == "secondary"
    assert view["clock"] == NEW["clock"] and view["qc"] == NEW["qc"]
    assert view["fit"] == {"ctm_pmin": 300}
    assert view["profiles_dbar"] == 2 and view["trim"] == {"near_surface_dbar": 8}
    assert view["data_processing"] == NEW["data_processing"]
    assert NEW["preferred_sensor"]["tc"]["ranges"][0] == {
        "casts": [[5, 9]],
        "value": "secondary",
    }


def test_released_old_layout_is_read_with_one_warning_per_key():
    old = {
        "processing": {
            "preferred_pair": {
                "default": "primary",
                "ranges": [{"casts": [[5, 9]], "use": "secondary"}],
            },
            "preferred_oxygen": {"default": "primary"},
            "clock": {"segments": []},
            "qc": {"spike": {}},
            "calibration": {"conductivity_slope": 1.0002},
            "profiles_dbar": 1,
        }
    }
    with pytest.warns(DeprecationWarning) as rec:
        view = processing_view(old)
    moved = sorted(
        re.search(r"`([^`]+)` is deprecated", str(w.message)).group(1) for w in rec
    )
    assert moved == [
        "processing.calibration.conductivity_slope",
        "processing.clock",
        "processing.preferred_oxygen",
        "processing.preferred_pair",
        "processing.qc",
    ]
    assert view["preferred_pair"]["ranges"][0]["use"] == "secondary"
    assert view["data_processing"]["slope_offset"] == {
        "conductivity_1": {"slope": 1.0002, "offset": 0.0},
        "conductivity_2": {"slope": 1.0002, "offset": 0.0},
    }
    assert "calibration" not in view


@pytest.mark.parametrize("key", ["alignctd", "celltm", "oxygen", "fit", "wildedit"])
def test_unreleased_processing_keys_are_refused_with_their_new_place(key):
    with pytest.raises(ValueError, match=rf"processing\.{key} -> "):
        processing_view({"processing": {key: {}}})


def test_both_layouts_at_once_is_refused():
    with pytest.raises(ValueError, match="keep one"):
        processing_view({"qc": {}, "processing": {"qc": {}}})
    with pytest.raises(ValueError, match="keep one"):
        processing_view(
            {
                "preferred_sensor": {"tc": "primary"},
                "processing": {"preferred_pair": "primary"},
            }
        )


def test_use_in_a_new_preferred_range_warns():
    with pytest.warns(DeprecationWarning, match=r"ranges\[\]\.use"):
        processing_view(
            {
                "preferred_sensor": {
                    "tc": {"ranges": [{"casts": [[1, 2]], "use": "secondary"}]}
                }
            }
        )


def test_slope_offset_per_sensor_with_a_swap():
    block = {
        "conductivity_1": {"slope": 1.0001, "offset": -0.002},
        "conductivity_2": {
            "default": {"slope": 0.9999},
            "ranges": [{"casts": [[1, 6]], "value": {"slope": 1.00002}}],
        },
    }
    assert resolve_slope_offset(block, "conductivity_1", 40)[:2] == (1.0001, -0.002)
    assert resolve_slope_offset(block, "conductivity_2", 3)[:2] == (1.00002, 0.0)
    assert resolve_slope_offset(block, "conductivity_2", 40)[:2] == (0.9999, 0.0)
    assert (
        resolve_slope_offset({"conductivity_1": {"slope": 1.0}}, "conductivity_2", 1)
        is None
    )
    for bad, match in (
        ({"conductivity_3": {"slope": 1}}, "unknown key"),
        ({"conductivity_1": {"slope": 1, "drift": 2}}, "slope:, offset:"),
        ({"conductivity_1": {"slope": 0}}, "must be positive"),
    ):
        with pytest.raises(ValueError, match=match):
            resolve_slope_offset(bad, "conductivity_1", 1)


def test_steps_keep_order_and_repeats_and_refuse_unknowns():
    dp = {
        "steps": [
            {"filter": {"time_constant": 0.03}},
            {"wildedit": {}},
            {"filter": {"time_constant": 0.15}},
        ]
    }
    assert [n for n, _ in iter_steps(dp)] == ["filter", "wildedit", "filter"]
    with pytest.raises(ValueError, match="unknown step 'derive'"):
        iter_steps({"steps": [{"derive": {}}]})
    with pytest.raises(ValueError, match="one step name"):
        iter_steps({"steps": [{"wildedit": {}, "celltm": {}}]})


def test_validate_config_reaches_into_steps():
    with pytest.raises(ValueError, match="expected a number"):
        validate_config({"steps": [{"alignctd": {"oxygen": {"default": "3"}}}]})
    with pytest.raises(ValueError, match="wildedit: unknown key"):
        validate_config({"steps": [{"wildedit": {"npoint": 100}}]})
    with pytest.raises(ValueError, match="must be positive"):
        validate_config({"slope_offset": {"conductivity_1": {"slope": -1}}})


def test_inspect_block_and_init_template_validate():
    from pathlib import Path

    from ctdcast.cli.init import _CONFIG_TEMPLATE
    from ctdcast.config.sbe_steps import header_text_of, processing_yaml

    fix = Path(__file__).parent / "fixtures" / "cnv" / "mixsed2_004.cnv"
    block_dp = yaml.safe_load(processing_yaml(header_text_of(fix)))["data_processing"]
    with pytest.raises(ValueError, match="does not apply yet"):
        validate_config(block_dp)
    validate_config({**block_dp, "allow_unapplied": True})
    # The init template's data_processing block, uncommented, is valid.
    lines = _CONFIG_TEMPLATE.splitlines()
    start = lines.index("# data_processing:")
    block = []
    for line in lines[start:]:
        if not line.startswith("#"):
            break
        block.append(line[2:] if line.startswith("# ") else line[1:])
    validate_config(yaml.safe_load("\n".join(block))["data_processing"])
    processing_view(yaml.safe_load(_CONFIG_TEMPLATE.split("_SECTIONS")[0]))


def test_unapplied_steps_refused_unless_allowed_and_recorded(tmp_path):
    dp = {
        "steps": [
            {"wildedit": {}},
            {"filter": {"time_constant": 0.03}},
            {"celltm": {"conductivity": {"alpha": 0.03, "tau": 7}}},
        ]
    }
    with pytest.raises(
        ValueError, match="lists filter, which stage 3 does not apply yet"
    ):
        validate_config(dp)
    validate_config({**dp, "allow_unapplied": True})
    with pytest.raises(ValueError, match="unknown key"):
        validate_config({**dp, "allow_unaplied": True})


def test_step_registry_is_the_one_list():
    from ctdcast.config.sbe_steps import _TRANSLATORS
    from ctdcast.processors.steps import STEPS

    # Every step `ctdcast inspect` can write is one stage 3 knows.
    translated = {
        "wildedit",
        "window_filter",
        "filter",
        "alignctd",
        "celltm",
        "loopedit",
        "binavg",
        "split",
    }
    assert translated <= set(STEPS)
    assert {"wfilter"} <= set(_TRANSLATORS)
    assert {n for n, s in STEPS.items() if s.apply} == {
        "wildedit",
        "alignctd",
        "celltm",
    }


def test_celltm_header_with_mismatched_lists_is_refused():
    from ctdcast.config.sbe_steps import _celltm

    with pytest.raises(ValueError, match="2 alpha value"):
        _celltm({"alpha": "0.03, 0.04", "tau": "7.0"}, None)


@pytest.mark.parametrize(
    ("params", "match"),
    [
        ({"pass1_nstd": True}, "expected a number"),
        ({"pass2_nstd": float("inf")}, "finite"),
        ({"scans_per_block": 100.0}, "whole number"),
        ({"exclude_flagged": "yes"}, "true or false"),
    ],
)
def test_wildedit_numbers_checked_like_every_other_step(params, match):
    with pytest.raises(ValueError, match=match):
        validate_config({"steps": [{"wildedit": params}]})
