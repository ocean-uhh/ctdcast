"""Tests for the CLI layer: argument wiring, config parsing, error paths.

These tests call run() directly with an argparse.Namespace rather than
subprocess, so they are fast.  Full end-to-end generation is covered by
tests/integration/; here we test the thin CLI layer only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
import yaml

from ctd_report.cli import init as _init
from ctd_report.cli import main as cli_main
from ctd_report.cli import report as _report
from ctd_report.cli import run as _run
from ctd_report.cli import validate as _validate

_HERE = Path(__file__).parent
_FIXTURES_NC = _HERE.parent / "fixtures" / "nc"
_FIXTURES_LADCP = _HERE.parent / "fixtures" / "ladcp"

_SECTION_YAML_TEXT = """\
sections:
  KO:
    description: KO fixture
    cast_numbers: [[11, 12]]
    color: "#1f77b4"
timeseries:
  Triangle:
    description: Triangle fixture
    cast_numbers: [[128, 129]]
    color: "#d62728"
"""


def _report_ns(**kwargs) -> argparse.Namespace:
    """Build a Namespace for report.run() with safe defaults."""
    defaults = dict(
        stations=False,
        sections=False,
        timeseries=False,
        index=False,
        map=False,
        cast=None,
        force=False,
        skip_existing=False,
        dry_run=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _validate_ns(**kwargs) -> argparse.Namespace:
    defaults = dict(strict=False)
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _init_ns(**kwargs) -> argparse.Namespace:
    defaults = dict(dest=Path("."), sections=False, force=False)
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _run_ns(**kwargs) -> argparse.Namespace:
    """Build a Namespace for run.run() with safe defaults."""
    defaults = {"ctd": False, "cast": None, "force": False, "dry_run": False}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# oceancast init
# ---------------------------------------------------------------------------


class TestInit:
    def test_writes_config_to_directory(self, tmp_path):
        rc = _init.run(_init_ns(dest=tmp_path))
        assert rc == 0
        cfg = tmp_path / "config.yaml"
        assert cfg.exists()

    def test_writes_to_explicit_yaml_path(self, tmp_path):
        dest = tmp_path / "myconfig.yaml"
        rc = _init.run(_init_ns(dest=dest))
        assert rc == 0
        assert dest.exists()

    def test_output_is_valid_yaml(self, tmp_path):
        _init.run(_init_ns(dest=tmp_path))
        parsed = yaml.safe_load((tmp_path / "config.yaml").read_text())
        assert isinstance(parsed, dict)
        assert "data" in parsed
        assert "output" in parsed

    def test_fails_if_exists_without_force(self, tmp_path):
        _init.run(_init_ns(dest=tmp_path))
        rc = _init.run(_init_ns(dest=tmp_path))
        assert rc == 1

    def test_force_overwrites(self, tmp_path):
        _init.run(_init_ns(dest=tmp_path))
        rc = _init.run(_init_ns(dest=tmp_path, force=True))
        assert rc == 0

    def test_sections_flag_writes_sections_yaml(self, tmp_path):
        rc = _init.run(_init_ns(dest=tmp_path, sections=True))
        assert rc == 0
        assert (tmp_path / "ctd_sections.yaml").exists()

    def test_sections_yaml_is_valid_yaml(self, tmp_path):
        _init.run(_init_ns(dest=tmp_path, sections=True))
        parsed = yaml.safe_load((tmp_path / "ctd_sections.yaml").read_text())
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# oceancast validate
# ---------------------------------------------------------------------------


class TestValidate:
    def _write_cfg(self, tmp_path, **overrides) -> Path:
        cfg = {
            "data": {"nc_dir": str(_FIXTURES_NC)},
            "output": {"dir": str(tmp_path / "out")},
        }
        cfg["data"].update(overrides.pop("data", {}))
        cfg.update(overrides)
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump(cfg))
        return p

    def test_missing_config_file(self, tmp_path):
        ns = _validate_ns(config=tmp_path / "nonexistent.yaml")
        rc = _validate.run(ns)
        assert rc == 1

    def test_valid_config_returns_zero(self, tmp_path):
        cfg_path = self._write_cfg(tmp_path)
        rc = _validate.run(_validate_ns(config=cfg_path))
        assert rc == 0

    def test_missing_nc_dir_returns_error(self, tmp_path):
        cfg_path = self._write_cfg(tmp_path, data={"nc_dir": str(tmp_path / "missing")})
        rc = _validate.run(_validate_ns(config=cfg_path))
        assert rc == 1

    def test_missing_nc_dir_key_returns_error(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"data": {}, "output": {"dir": str(tmp_path / "out")}}))
        rc = _validate.run(_validate_ns(config=p))
        assert rc == 1

    def test_empty_nc_dir_returns_error(self, tmp_path):
        empty = tmp_path / "empty_nc"
        empty.mkdir()
        cfg_path = self._write_cfg(tmp_path, data={"nc_dir": str(empty)})
        rc = _validate.run(_validate_ns(config=cfg_path))
        assert rc == 1

    def test_bad_yaml_returns_error(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("key: [unclosed bracket\n")
        rc = _validate.run(_validate_ns(config=p))
        assert rc == 1

    def test_strict_all_casts_present(self, tmp_path):
        sec_yaml = tmp_path / "sections.yaml"
        sec_yaml.write_text(_SECTION_YAML_TEXT)
        cfg_path = self._write_cfg(
            tmp_path,
            data={"nc_dir": str(_FIXTURES_NC), "section_yaml": str(sec_yaml)},
        )
        rc = _validate.run(_validate_ns(config=cfg_path, strict=True))
        assert rc == 0

    def test_strict_missing_cast_returns_error(self, tmp_path):
        sec_yaml = tmp_path / "sections.yaml"
        sec_yaml.write_text(
            "sections:\n  BAD:\n    cast_numbers: [[999, 1000]]\n    color: '#f00'\n"
        )
        cfg_path = self._write_cfg(
            tmp_path,
            data={"nc_dir": str(_FIXTURES_NC), "section_yaml": str(sec_yaml)},
        )
        rc = _validate.run(_validate_ns(config=cfg_path, strict=True))
        assert rc == 1


# ---------------------------------------------------------------------------
# oceancast report
# ---------------------------------------------------------------------------


class TestReport:
    def _write_cfg(self, tmp_path, **extras) -> Path:
        cfg: dict = {
            "data": {"nc_dir": str(_FIXTURES_NC)},
            "output": {"dir": str(tmp_path / "out")},
        }
        for k, v in extras.items():
            cfg["data"][k] = v
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump(cfg))
        return p

    def test_missing_config_returns_error(self, tmp_path):
        ns = _report_ns(config=tmp_path / "nonexistent.yaml")
        rc = _report.run(ns)
        assert rc == 1

    def test_dry_run_returns_zero(self, tmp_path):
        cfg = self._write_cfg(tmp_path)
        rc = _report.run(_report_ns(config=cfg, dry_run=True))
        assert rc == 0

    def test_dry_run_writes_no_files(self, tmp_path):
        cfg = self._write_cfg(tmp_path)
        _report.run(_report_ns(config=cfg, dry_run=True))
        assert not (tmp_path / "out").exists()

    def test_dry_run_with_cast_returns_zero(self, tmp_path):
        cfg = self._write_cfg(tmp_path)
        rc = _report.run(_report_ns(config=cfg, dry_run=True, cast=11))
        assert rc == 0

    def test_missing_nc_dir_exits_zero_no_files(self, tmp_path):
        # report doesn't validate paths — it just prints "No cast files found"
        # and exits 0.  Use `oceancast validate` to catch missing paths upfront.
        p = tmp_path / "config.yaml"
        p.write_text(
            yaml.dump(
                {
                    "data": {"nc_dir": str(tmp_path / "missing")},
                    "output": {"dir": str(tmp_path / "out")},
                }
            )
        )
        rc = _report.run(_report_ns(config=p))
        assert rc == 0
        assert not list((tmp_path / "out").glob("stations/*.html"))

    def test_stations_only_generates_pages(self, tmp_path):
        """Confirm the CLI drives generate_ctd_report correctly for stations."""
        cfg = self._write_cfg(tmp_path)
        rc = _report.run(
            _report_ns(
                config=cfg,
                stations=True,
                force=True,
            )
        )
        assert rc == 0
        for cast_num in (11, 12, 128, 129):
            assert (
                tmp_path / "out" / "stations" / f"cast_{cast_num:03d}.html"
            ).exists()

    def test_cast_flag_generates_single_station(self, tmp_path):
        cfg = self._write_cfg(tmp_path)
        rc = _report.run(_report_ns(config=cfg, cast=11, force=True))
        assert rc == 0
        assert (tmp_path / "out" / "stations" / "cast_011.html").exists()
        assert not (tmp_path / "out" / "stations" / "cast_012.html").exists()


# ---------------------------------------------------------------------------
# oceancast run
# ---------------------------------------------------------------------------


class TestRun:
    def _write_cfg(self, tmp_path, **extras) -> Path:
        cfg: dict = {
            "data": {"nc_dir": str(_FIXTURES_NC)},
            "output": {"dir": str(tmp_path / "out")},
        }
        for k, v in extras.items():
            cfg["data"][k] = v
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump(cfg))
        return p

    def test_missing_config_returns_error(self, tmp_path):
        rc = _run.run(_run_ns(config=tmp_path / "nonexistent.yaml"))
        assert rc == 1

    def test_dry_run_returns_zero(self, tmp_path):
        cfg = self._write_cfg(tmp_path)
        rc = _run.run(_run_ns(config=cfg, dry_run=True))
        assert rc == 0

    def test_dry_run_writes_no_files(self, tmp_path):
        cfg = self._write_cfg(tmp_path)
        _run.run(_run_ns(config=cfg, dry_run=True))
        assert not (tmp_path / "out").exists()

    def test_run_generates_station_pages(self, tmp_path):
        """run with no profiles_nc → skips convert profiles, generates station pages."""
        cfg = self._write_cfg(tmp_path)
        rc = _run.run(_run_ns(config=cfg, force=True))
        assert rc == 0
        for cast_num in (11, 12, 128, 129):
            assert (
                tmp_path / "out" / "stations" / f"cast_{cast_num:03d}.html"
            ).exists()

    def test_run_with_cast_skips_profiles_but_generates_page(self, tmp_path):
        """--cast N skips convert entirely; generates only the one station page."""
        cfg = self._write_cfg(tmp_path)
        rc = _run.run(_run_ns(config=cfg, cast=11, force=True))
        assert rc == 0
        assert (tmp_path / "out" / "stations" / "cast_011.html").exists()
        assert not (tmp_path / "out" / "stations" / "cast_012.html").exists()

    def test_run_parser_standalone(self):
        parser = _run.build_parser()
        args = parser.parse_args(["config.yaml", "--force", "--cast", "42"])
        assert args.force is True
        assert args.cast == 42
        assert args.config == Path("config.yaml")
        assert args.ctd is False

    def test_run_parser_ctd_flag(self):
        parser = _run.build_parser()
        args = parser.parse_args(["config.yaml", "--ctd"])
        assert args.ctd is True


# ---------------------------------------------------------------------------
# Entry point: argument parser wiring
# ---------------------------------------------------------------------------


class TestEntryPoint:
    def test_main_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc:
            cli_main()  # no args → subparsers.required triggers SystemExit(2)
        # Exit 2 means "usage error" — expected since no subcommand provided
        assert exc.value.code == 2

    def test_report_parser_standalone(self):
        parser = _report.build_parser()
        args = parser.parse_args(["config.yaml", "--force", "--cast", "42"])
        assert args.force is True
        assert args.cast == 42
        assert args.config == Path("config.yaml")

    def test_validate_parser_standalone(self):
        parser = _validate.build_parser()
        args = parser.parse_args(["config.yaml", "--strict"])
        assert args.strict is True

    def test_init_parser_standalone(self):
        parser = _init.build_parser()
        args = parser.parse_args(["mydir/", "--sections", "--force"])
        assert args.sections is True
        assert args.force is True
