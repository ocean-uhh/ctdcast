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

from ctdreport.cli import draft as _draft
from ctdreport.cli import init as _init
from ctdreport.cli import main as cli_main
from ctdreport.cli import report as _report
from ctdreport.cli import run as _run
from ctdreport.cli import validate as _validate

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
    defaults = {
        "stations": False,
        "sections": False,
        "timeseries": False,
        "index": False,
        "map": False,
        "cast": None,
        "force": False,
        "skip_existing": False,
        "dry_run": False,
        "sal": None,
        "trim_soak": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _validate_ns(**kwargs) -> argparse.Namespace:
    defaults = {"strict": False}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _init_ns(**kwargs) -> argparse.Namespace:
    defaults = {
        "dest": Path("."),
        "sections": False,
        "force": False,
        "interactive": False,
        "dx_timeseries": 5.0,
        "dx_section": 50.0,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _run_ns(**kwargs) -> argparse.Namespace:
    """Build a Namespace for run.run() with safe defaults."""
    defaults = {
        "ctd": False,
        "cast": None,
        "force": False,
        "skip_existing": False,
        "dry_run": False,
        "trim_soak": False,
    }
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
# _detect_groups / _cast_range / _format_sections_yaml unit tests
# ---------------------------------------------------------------------------


def _make_profiles_nc(path: Path, cast_nums, lats, lons) -> None:
    """Write a minimal profiles.nc with the given per-cast metadata."""
    import numpy as np
    import xarray as xr

    n = len(cast_nums)
    # Each cast appears twice: once as "down", once as "up".
    all_cast_nums = np.concatenate([cast_nums, cast_nums])
    all_types = np.array(["down"] * n + ["up"] * n)
    all_lats = np.concatenate([lats, lats])
    all_lons = np.concatenate([lons, lons])
    p_grid = np.arange(1, 11, dtype=np.float32)

    ds = xr.Dataset(
        {
            "cast_number": ("N_PROF", all_cast_nums.astype(np.int32)),
            "cast_type": ("N_PROF", all_types),
            "latitude": ("N_PROF", all_lats.astype(np.float32)),
            "longitude": ("N_PROF", all_lons.astype(np.float32)),
            "temperature_1": (
                ["N_PROF", "pressure"],
                np.zeros((2 * n, len(p_grid)), dtype=np.float32),
            ),
        },
        coords={"pressure": p_grid},
    )
    ds.to_netcdf(path, engine="netcdf4")


class TestDetectGroups:
    """Tests for _detect_groups, _cast_range, and _format_sections_yaml."""

    def _profiles(self, tmp_path, cast_nums, lats, lons) -> Path:
        import numpy as np

        p = tmp_path / "profiles.nc"
        _make_profiles_nc(p, np.array(cast_nums), np.array(lats), np.array(lons))
        return p

    def test_single_cast_yields_no_groups(self, tmp_path):
        # One cast: too small for any run (min_run_casts >= 3) → no groups.
        p = self._profiles(tmp_path, [1], [60.0], [-25.0])
        sections, ts = _init._detect_groups(p, dx_timeseries_km=5.0, dx_section_km=50.0)
        assert sections == []
        assert ts == []

    def test_two_close_casts_yield_no_groups(self, tmp_path):
        # Two casts: below minimum run length → no groups.
        p = self._profiles(tmp_path, [1, 2], [60.0, 60.009], [-25.0, -25.0])
        sections, ts = _init._detect_groups(p, dx_timeseries_km=5.0, dx_section_km=50.0)
        assert sections == []
        assert ts == []

    def test_two_distant_casts_yield_no_groups(self, tmp_path):
        # Two casts ~28 km apart: below minimum run length → no groups.
        p = self._profiles(tmp_path, [1, 2], [60.0, 60.0], [-25.0, -24.5])
        sections, ts = _init._detect_groups(p, dx_timeseries_km=5.0, dx_section_km=50.0)
        assert sections == []
        assert ts == []

    def test_transit_splits_into_two_groups(self, tmp_path):
        # Casts 1-3 clustered going N, then a 200 km transit, then casts 4-6 clustered going N.
        # min_run_casts=3 used so 3-cast groups are kept.
        import numpy as np

        lats = np.array([60.0, 60.01, 60.02, 62.0, 62.01, 62.02])
        lons = np.array([-25.0, -25.0, -25.0, -25.0, -25.0, -25.0])
        p = self._profiles(tmp_path, [1, 2, 3, 4, 5, 6], lats, lons)
        sections, ts = _init._detect_groups(
            p, dx_timeseries_km=5.0, dx_section_km=50.0, min_run_casts=3
        )
        assert len(sections) == 0
        assert len(ts) == 2

    def test_section_and_timeseries_mixed(self, tmp_path):
        # Casts 1-5: lon transect at 57°N, 0.4° steps ≈ 22 km → section.
        # Casts 6-8: clustered at 60°N (large transit → gap split) → timeseries.
        # min_run_casts=3 so the 3-cast cluster is kept.
        import numpy as np

        lats = np.array([57.0, 57.0, 57.0, 57.0, 57.0, 60.0, 60.01, 60.02])
        lons = np.array([-25.0, -24.6, -24.2, -23.8, -23.4, -25.0, -25.0, -25.0])
        p = self._profiles(tmp_path, list(range(1, 9)), lats, lons)
        sections, ts = _init._detect_groups(
            p, dx_timeseries_km=5.0, dx_section_km=50.0, min_run_casts=3
        )
        assert len(sections) == 1
        assert len(ts) == 1

    def test_section_name_is_sequential(self, tmp_path):
        # 6 casts along a lon transect at 57°N, 0.4° steps ≈ 22 km each.
        import numpy as np

        lats = np.full(6, 57.0)
        lons = np.arange(6) * 0.4 - 25.0
        p = self._profiles(tmp_path, list(range(1, 7)), lats, lons)
        sections, _ = _init._detect_groups(p, dx_timeseries_km=5.0, dx_section_km=50.0)
        assert len(sections) >= 1
        assert sections[0]["name"] == "Section_001"

    def test_timeseries_name_is_sequential(self, tmp_path):
        # 3 casts clustered near the same point → timeseries (min_run_casts=3).
        import numpy as np

        lats = np.array([60.0, 60.009, 60.018])
        lons = np.array([-25.0, -25.0, -25.0])
        p = self._profiles(tmp_path, [1, 2, 3], lats, lons)
        _, ts = _init._detect_groups(
            p, dx_timeseries_km=5.0, dx_section_km=50.0, min_run_casts=3
        )
        assert ts[0]["name"] == "Station_001"


class TestCastRange:
    def test_consecutive_range(self):
        import numpy as np

        result = _init._cast_range(np.array([1, 2, 3, 4, 5]))
        assert result == [[1, 5]]

    def test_non_consecutive_individual(self):
        import numpy as np

        result = _init._cast_range(np.array([1, 3, 5]))
        assert result == [1, 3, 5]

    def test_single_element(self):
        import numpy as np

        result = _init._cast_range(np.array([7]))
        assert result == [[7, 7]]

    def test_empty(self):
        import numpy as np

        result = _init._cast_range(np.array([], dtype=int))
        assert result == []


class TestFormatSectionsYaml:
    def test_output_is_valid_yaml(self):
        sections = [
            {
                "name": "Section_001",
                "description": "Test",
                "cast_numbers": [[1, 5]],
                "color": "#1f77b4",
            }
        ]
        ts = [
            {
                "name": "Station_001",
                "description": "Rep",
                "cast_numbers": [[6, 8]],
                "color": "#ff7f0e",
            }
        ]
        text = _init._format_sections_yaml(sections, ts, 5.0, 50.0)
        parsed = yaml.safe_load(text)
        assert "sections" in parsed
        assert "timeseries" in parsed

    def test_empty_sections_still_valid(self):
        text = _init._format_sections_yaml([], [], 5.0, 50.0)
        parsed = yaml.safe_load(text)
        assert parsed is not None

    def test_range_notation_used(self):
        sections = [
            {
                "name": "Section_001",
                "description": "T",
                "cast_numbers": [[1, 10]],
                "color": "#1f77b4",
            }
        ]
        text = _init._format_sections_yaml(sections, [], 5.0, 50.0)
        assert "[1, 10]" in text


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

    def test_run_parser_skip_existing_flag(self):
        parser = _run.build_parser()
        args = parser.parse_args(["config.yaml", "--skip-existing"])
        assert args.skip_existing is True

    def test_run_skip_existing_does_not_overwrite(self, tmp_path):
        """--skip-existing leaves existing station pages untouched."""
        cfg = self._write_cfg(tmp_path)
        _run.run(_run_ns(config=cfg, force=True))
        page = tmp_path / "out" / "stations" / "cast_011.html"
        mtime_before = page.stat().st_mtime
        _run.run(_run_ns(config=cfg, skip_existing=True))
        assert page.stat().st_mtime == mtime_before


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


# ---------------------------------------------------------------------------
# ctdreport draft
# ---------------------------------------------------------------------------


def _draft_ns(**kwargs) -> argparse.Namespace:
    """Build a Namespace for draft.run() with safe defaults."""
    defaults = {
        "cruise": None,
        "ship": None,
        "keep_nc": None,
        "force": False,
        "dry_run": False,
        "pattern": "*.cnv",
        "trim_soak": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestDraft:
    def test_missing_cnv_dir_returns_error(self, tmp_path):
        ns = _draft_ns(cnv_dir=tmp_path / "nonexistent", out_dir=tmp_path / "out")
        rc = _draft.run(ns)
        assert rc == 1

    def test_empty_cnv_dir_returns_error(self, tmp_path):
        cnv_dir = tmp_path / "cnv"
        cnv_dir.mkdir()
        ns = _draft_ns(cnv_dir=cnv_dir, out_dir=tmp_path / "out")
        rc = _draft.run(ns)
        assert rc == 1

    def test_dry_run_returns_zero(self, tmp_path):
        cnv_dir = tmp_path / "cnv"
        cnv_dir.mkdir()
        (cnv_dir / "cast_001.cnv").write_text("dummy")
        ns = _draft_ns(cnv_dir=cnv_dir, out_dir=tmp_path / "out", dry_run=True)
        rc = _draft.run(ns)
        assert rc == 0

    def test_dry_run_writes_no_files(self, tmp_path):
        cnv_dir = tmp_path / "cnv"
        cnv_dir.mkdir()
        (cnv_dir / "cast_001.cnv").write_text("dummy")
        out_dir = tmp_path / "out"
        ns = _draft_ns(cnv_dir=cnv_dir, out_dir=out_dir, dry_run=True)
        _draft.run(ns)
        assert not out_dir.exists()

    def test_draft_parser_standalone(self):
        parser = _draft.build_parser()
        args = parser.parse_args(["cnv/", "--force", "--cruise", "M200"])
        assert args.force is True
        assert args.cruise == "M200"
        assert args.cnv_dir == Path("cnv/")

    def test_draft_parser_default_out_dir(self):
        parser = _draft.build_parser()
        args = parser.parse_args(["cnv/"])
        assert args.out_dir == Path("ctd_draft/")

    def test_keep_nc_flag(self):
        parser = _draft.build_parser()
        args = parser.parse_args(["cnv/", "--keep-nc", "nc_out/"])
        assert args.keep_nc == Path("nc_out/")
