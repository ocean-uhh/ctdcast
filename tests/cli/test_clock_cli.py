"""Tests for the ``ctdcast clock`` subcommand."""

import argparse
import datetime as dt
import json
from pathlib import Path

import xarray as xr

from ctdcast.cli import clock as clock_cli


def _write_cruise(
    root: Path,
    offsets: list[float],
    *,
    coordinate: str | None = "System UTC, first data scan.",
) -> None:
    """Write stage-1 files under ``root/stage1`` whose headers carry the given System/NMEA offsets.

    ``coordinate`` is the ``start_time`` bracket text; ``None`` omits the ``start_time`` line so the
    coordinate source is undetermined.
    """
    stage1 = root / "stage1"
    stage1.mkdir(parents=True)
    base = dt.datetime(2026, 3, 29, 20, 0, 0)
    for i, off in enumerate(offsets):
        system = base + dt.timedelta(hours=i)
        nmea = system + dt.timedelta(seconds=off)
        header = (
            f"* System UTC = {system:%b %d %Y %H:%M:%S}\n"
            f"* NMEA UTC (Time) = {nmea:%b %d %Y %H:%M:%S}"
        )
        if coordinate is not None:
            header += f"\n# start_time = {system:%b %d %Y %H:%M:%S} [{coordinate}]"
        envelope = {
            "schema": "test",
            "raw_format": "sbe-cnv",
            "blocks": {"header": header},
        }
        ds = xr.Dataset(attrs={"raw_metadata": json.dumps(envelope)})
        ds.to_netcdf(stage1 / f"cast_{i + 1:03d}_stage1.nc", engine="netcdf4")


def _config(tmp_path: Path, root: Path | None) -> Path:
    """Write a minimal config.yaml, optionally with a ctd_root, and return its path."""
    lines = ["data:"]
    if root is not None:
        lines.append(f"  ctd_root: {root}")
    lines.append("output:")
    lines.append(f"  dir: {tmp_path / 'report'}")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("\n".join(lines) + "\n")
    return cfg


def _ns(config: Path, figure: Path | None = None) -> argparse.Namespace:
    return argparse.Namespace(config=config, figure=figure)


def test_build_parser_standalone_parses_args() -> None:
    """The parser builds and reads the config positional and --figure option."""
    ns = clock_cli.build_parser(None).parse_args(["config.yaml", "--figure", "c.png"])
    assert ns.config == Path("config.yaml")
    assert ns.figure == Path("c.png")


def test_missing_config_returns_1(tmp_path: Path) -> None:
    """A non-existent config path is a clean error, not a traceback."""
    assert clock_cli.run(_ns(tmp_path / "nope.yaml")) == 1


def test_nonexistent_ctd_root_returns_1(tmp_path: Path, capsys) -> None:
    """A configured but missing ctd_root is reported as such, not as an empty cruise."""
    cfg = _config(tmp_path, root=tmp_path / "gone")
    assert clock_cli.run(_ns(cfg)) == 1
    assert "does not exist" in capsys.readouterr().err


def test_figure_requested_but_nothing_to_plot(tmp_path: Path, capsys) -> None:
    """--figure on a verdict with no segments writes nothing and says why."""
    root = tmp_path / "ctd"
    _write_cruise(root, [5, 5])  # too few -> insufficient, no segments
    cfg = _config(tmp_path, root=root)
    fig_path = tmp_path / "clock.png"
    assert clock_cli.run(_ns(cfg, figure=fig_path)) == 0
    assert not fig_path.exists()
    assert "nothing to plot" in capsys.readouterr().err


def test_unset_ctd_root_fails_loudly(tmp_path: Path, capsys) -> None:
    """An unset ctd_root fails like other config commands — not reported as 'no clock pairs'."""
    cfg = _config(tmp_path, root=None)
    assert clock_cli.run(_ns(cfg)) == 1
    err = capsys.readouterr().err
    assert "ctd_root is required" in err


def test_reports_step_and_suggests_config(tmp_path: Path, capsys) -> None:
    """A real cruise-shaped tree prints the verdict, segment table and paste-ready block."""
    root = tmp_path / "ctd"
    _write_cruise(root, [2, 2, 3, 2, 2] + [9, 8, 9, 9, 8])
    cfg = _config(tmp_path, root=root)
    assert clock_cli.run(_ns(cfg)) == 0
    out = capsys.readouterr().out
    assert "Verdict: step" in out
    assert "Coordinate: System (PC clock) on 10/10" in out  # printed on every run
    assert "Current processing.clock" in out
    assert "clock_offset_seconds" in out


def test_no_block_when_coordinate_already_on_gps(tmp_path: Path, capsys) -> None:
    """A GPS-anchored coordinate suppresses the paste-ready block — the offset is not applied."""
    root = tmp_path / "ctd"
    _write_cruise(
        root, [2, 2, 3, 2, 2] + [9, 8, 9, 9, 8], coordinate="NMEA time, header"
    )
    cfg = _config(tmp_path, root=root)
    assert clock_cli.run(_ns(cfg)) == 0
    out = capsys.readouterr().out
    assert "NMEA (GPS)" in out and "already correct" in out
    assert "No correction suggested" in out
    assert "clock_offset_seconds" not in out  # block suppressed


def test_noisy_constant_prints_caveat(tmp_path: Path, capsys) -> None:
    """A constant with sd above the quantisation surfaces its resolution caveat in the CLI."""
    root = tmp_path / "ctd"
    _write_cruise(
        root, [-5, -1, -3, -4, -2, -5, -1, -3, -2, -4, -3, -5, -2, -1, -4, -3]
    )
    cfg = _config(tmp_path, root=root)
    assert clock_cli.run(_ns(cfg)) == 0
    out = capsys.readouterr().out
    assert "Verdict: constant" in out
    assert "Caveat:" in out


def test_undetermined_coordinate_is_not_reported_as_gps(tmp_path: Path, capsys) -> None:
    """With no start_time bracket, the source is undetermined — never asserted to be GPS."""
    root = tmp_path / "ctd"
    _write_cruise(root, [2, 2, 3, 2, 2] + [9, 8, 9, 9, 8], coordinate=None)
    cfg = _config(tmp_path, root=root)
    assert clock_cli.run(_ns(cfg)) == 0
    out = capsys.readouterr().out
    assert "could not be determined" in out
    assert "already on GPS" not in out  # must NOT claim a source it never measured
    assert "clock_offset_seconds" not in out  # block suppressed


def test_figure_written_when_requested(tmp_path: Path) -> None:
    """--figure writes the offset-vs-cast PNG for a plottable verdict."""
    root = tmp_path / "ctd"
    _write_cruise(root, [2, 2, 3, 2, 2] + [9, 8, 9, 9, 8])
    cfg = _config(tmp_path, root=root)
    fig_path = tmp_path / "clock.png"
    assert clock_cli.run(_ns(cfg, figure=fig_path)) == 0
    assert fig_path.exists()
