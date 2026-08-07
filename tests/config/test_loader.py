"""Tests for ctdcast.config.loader."""

from __future__ import annotations

from pathlib import Path

from ctdcast.config.loader import SectionsConfig


def test_from_yaml_roundtrip(tmp_path: Path) -> None:
    """SectionsConfig.from_yaml round-trips a minimal sections YAML."""
    yaml_content = """\
sections:
  KO:
    description: "Kögur Outer"
    cast_numbers: [[1, 5]]
    color: "#e41a1c"
timeseries:
  FDYY:
    description: "Fardwo yoyo"
    cast_numbers: [[50, 60]]
cruise_info:
  cruise_id: msm142
  ship: "Maria S. Merian"
"""
    p = tmp_path / "ctd_sections.yaml"
    p.write_text(yaml_content)
    cfg = SectionsConfig.from_yaml(p)
    assert list(cfg.sections.keys()) == ["KO"]
    assert cfg.sections["KO"]["description"] == "Kögur Outer"
    assert list(cfg.timeseries.keys()) == ["FDYY"]
    assert cfg.cruise_info["cruise_id"] == "msm142"
    assert cfg.cruise_info["ship"] == "Maria S. Merian"


def test_from_yaml_missing_file() -> None:
    """SectionsConfig.from_yaml returns empty config when file does not exist."""
    cfg = SectionsConfig.from_yaml(Path("/nonexistent/path.yaml"))
    assert cfg.sections == {}
    assert cfg.timeseries == {}
    assert cfg.cruise_info == {}


def test_from_yaml_empty_file(tmp_path: Path) -> None:
    """SectionsConfig.from_yaml returns empty config for an empty YAML file."""
    p = tmp_path / "empty.yaml"
    p.write_text("")
    cfg = SectionsConfig.from_yaml(p)
    assert cfg.sections == {}
    assert cfg.timeseries == {}
    assert cfg.cruise_info == {}


def test_from_yaml_partial(tmp_path: Path) -> None:
    """SectionsConfig.from_yaml handles YAML with only some top-level keys."""
    p = tmp_path / "partial.yaml"
    p.write_text("sections:\n  KO:\n    cast_numbers: [1, 2]\n")
    cfg = SectionsConfig.from_yaml(p)
    assert list(cfg.sections.keys()) == ["KO"]
    assert cfg.timeseries == {}
    assert cfg.cruise_info == {}


def test_empty() -> None:
    """SectionsConfig() with no args returns an all-empty config."""
    cfg = SectionsConfig()
    assert cfg.sections == {}
    assert cfg.timeseries == {}
    assert cfg.cruise_info == {}


def test_from_yaml_cast_notes(tmp_path: Path) -> None:
    """SectionsConfig preserves cast_notes entries within section configs."""
    yaml_content = """\
sections:
  KO:
    cast_numbers: [1, 2]
    cast_notes:
      1: "Soak aborted early"
"""
    p = tmp_path / "ctd_sections.yaml"
    p.write_text(yaml_content)
    cfg = SectionsConfig.from_yaml(p)
    assert cfg.sections["KO"]["cast_notes"][1] == "Soak aborted early"
