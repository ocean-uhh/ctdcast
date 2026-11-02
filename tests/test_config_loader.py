import pytest

from ctdcast.config.loader import ConfigError, load_config, load_yaml


def _write(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_step_written_twice_in_one_item_is_refused(tmp_path):
    path = _write(
        tmp_path,
        "data_processing:\n"
        "  steps:\n"
        "    - filter: {time_constant: 0.03, variables: [ctd_fluor]}\n"
        "      filter: {time_constant: 0.15, variables: [pressure]}\n",
    )
    with pytest.raises(
        ConfigError,
        match=r"'filter' appears twice .* lines 3 and 4.*start each with '- '",
    ):
        load_config(path)


def test_two_steps_as_list_items_are_fine(tmp_path):
    path = _write(
        tmp_path,
        "data_processing:\n"
        "  steps:\n"
        "    - filter: {time_constant: 0.03, variables: [ctd_fluor]}\n"
        "    - filter: {time_constant: 0.15, variables: [pressure]}\n",
    )
    steps = load_config(path)["data_processing"]["steps"]
    assert [s["filter"]["time_constant"] for s in steps] == [0.03, 0.15]


def test_a_block_given_twice_is_refused(tmp_path):
    path = _write(
        tmp_path,
        "data_processing:\n  steps: []\nqc: {}\ndata_processing:\n  steps: []\n",
    )
    with pytest.raises(
        ConfigError, match=r"'data_processing' appears twice .* lines 1 and 4.*merge"
    ):
        load_config(path)


def test_bad_yaml_names_the_line(tmp_path):
    path = _write(tmp_path, "data:\n  ctd_root: [x\n")
    with pytest.raises(ConfigError, match=r"not valid YAML at line 3"):
        load_yaml(path)


def test_top_level_must_be_blocks(tmp_path):
    with pytest.raises(ConfigError, match="expected blocks"):
        load_config(_write(tmp_path, "- a\n- b\n"))
    assert load_config(_write(tmp_path, "")) == {}


def test_command_line_reports_a_config_error(tmp_path, monkeypatch, capsys):
    import sys

    from ctdcast.cli import main

    path = _write(tmp_path, "data: {}\ndata: {}\n")
    monkeypatch.setattr(sys, "argv", ["ctdcast", "process", str(path), "--stage", "3"])
    with pytest.raises(SystemExit) as exit_:
        main()
    assert exit_.value.code == 1
    assert "Config error:" in capsys.readouterr().err
