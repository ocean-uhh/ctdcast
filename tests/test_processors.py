"""Tests for ctdcast.processors registry (STAGES, resolve_stage, process API)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from conftest import FIXTURES_NC
from ctdcast.processors import STAGES, Stage, resolve_stage
from ctdcast.processors.profiles import run as profiles_run
from ctdcast.processors.stage1 import run as stage1_run
from ctdcast.processors.stage2 import run as stage2_run
from ctdcast.processors.stage3 import run as stage3_run


def test_stages_is_nonempty_tuple_of_stage() -> None:
    """STAGES is a non-empty tuple of Stage dataclasses."""
    assert isinstance(STAGES, tuple)
    assert len(STAGES) > 0
    for s in STAGES:
        assert isinstance(s, Stage)


def test_stages_numbered_stages_have_unique_numbers() -> None:
    """Numbered stages each have a distinct positive integer."""
    numbers = [s.number for s in STAGES if s.number is not None]
    assert len(numbers) == len(set(numbers)), "Duplicate stage numbers in STAGES"
    assert all(n > 0 for n in numbers)


def test_resolve_stage_by_number() -> None:
    """resolve_stage(1) returns the stage with number 1."""
    s = resolve_stage(1)
    assert s.number == 1
    assert s.name == "stage1"


def test_resolve_stage_by_name() -> None:
    """resolve_stage('profiles') returns the profiles stage."""
    s = resolve_stage("profiles")
    assert s.name == "profiles"
    assert s.number is None


def test_resolve_stage_name_case_insensitive() -> None:
    """Stage names are matched case-insensitively."""
    assert resolve_stage("STAGE1") == resolve_stage("stage1")


def test_resolve_stage_none_raises() -> None:
    """resolve_stage(None) must raise ValueError, not silently match 'profiles'.

    Stage('profiles', None, ...) has number=None, so without an explicit guard
    None==None would match it via the number comparison.
    """
    with pytest.raises(ValueError, match="None"):
        resolve_stage(None)  # type: ignore[arg-type]


def test_resolve_stage_unknown_raises() -> None:
    """resolve_stage with an unknown value raises ValueError listing valid choices."""
    with pytest.raises(ValueError, match="unknown stage"):
        resolve_stage(99)


def test_resolve_stage_invalid_name_raises() -> None:
    """resolve_stage with an unrecognised name raises ValueError."""
    with pytest.raises(ValueError, match="unknown stage"):
        resolve_stage("bogus")


def test_profiles_stage_has_no_number() -> None:
    """The profiles stage is named-only (number=None) — stage=4 must not match it."""
    profiles = resolve_stage("profiles")
    assert profiles.number is None
    with pytest.raises(ValueError):
        resolve_stage(4)


def test_resolve_stage_bool_raises() -> None:
    """True == 1 in Python, so resolve_stage(True/False) must raise, not match stage1.

    Without the isinstance(stage, bool) guard, resolve_stage(True) silently returned
    the stage-1 Stage object because True == 1.
    """
    with pytest.raises(ValueError):
        resolve_stage(True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        resolve_stage(False)  # type: ignore[arg-type]


def test_resolve_stage_float_resolves() -> None:
    """1.0 == 1 in Python; resolve_stage(1.0) resolves to stage1 (not a defect)."""
    s = resolve_stage(1.0)  # type: ignore[arg-type]
    assert s.number == 1


# ---------------------------------------------------------------------------
# run() dry_run — no files written, return value is 0 / False
# ---------------------------------------------------------------------------


def test_run_stage1_dry_run(tmp_path: Path) -> None:
    """stage1.run dry_run returns 0 and writes nothing."""
    cnv_dir = tmp_path / "cnv"
    cnv_dir.mkdir()
    nc_dir = tmp_path / "nc"
    result = stage1_run(cnv_dir, nc_dir, dry_run=True)
    assert result == 0
    assert not nc_dir.exists()


def test_run_stage2_dry_run(tmp_path: Path) -> None:
    """stage2.run dry_run returns 0 and writes nothing."""
    nc_dir = tmp_path / "nc"
    nc_dir.mkdir()
    shutil.copy(FIXTURES_NC / "mixsed2_011.nc", nc_dir / "mixsed2_011.nc")
    mtime_before = (nc_dir / "mixsed2_011.nc").stat().st_mtime
    result = stage2_run(nc_dir, dry_run=True)
    assert result == 0
    assert (nc_dir / "mixsed2_011.nc").stat().st_mtime == mtime_before


def test_run_stage3_dry_run(tmp_path: Path) -> None:
    """stage3.run dry_run returns 0 and writes nothing."""
    nc_dir = tmp_path / "nc"
    nc_dir.mkdir()
    shutil.copy(FIXTURES_NC / "mixsed2_011.nc", nc_dir / "mixsed2_011.nc")
    mtime_before = (nc_dir / "mixsed2_011.nc").stat().st_mtime
    result = stage3_run(nc_dir, dry_run=True)
    assert result == 0
    assert (nc_dir / "mixsed2_011.nc").stat().st_mtime == mtime_before


def test_run_stage2_nc_dir_not_found(tmp_path: Path) -> None:
    """stage2.run raises FileNotFoundError when nc_dir does not exist."""
    with pytest.raises(FileNotFoundError):
        stage2_run(tmp_path / "missing", dry_run=True)


def test_run_stage3_nc_dir_not_found(tmp_path: Path) -> None:
    """stage3.run raises FileNotFoundError when nc_dir does not exist."""
    with pytest.raises(FileNotFoundError):
        stage3_run(tmp_path / "missing", dry_run=True)


def test_run_profiles_dry_run(tmp_path: Path) -> None:
    """profiles.run dry_run returns False and writes nothing."""
    nc_dir = tmp_path / "nc"
    nc_dir.mkdir()
    profiles_path = tmp_path / "profiles.nc"
    result = profiles_run(nc_dir, profiles_path, dry_run=True)
    assert result is False
    assert not profiles_path.exists()


# ---------------------------------------------------------------------------
# run() cast_tags — only matching files processed
# ---------------------------------------------------------------------------


def test_run_stage2_cast_tags(tmp_path: Path) -> None:
    """stage2.run with cast_tags processes only the matching file."""
    nc_dir = tmp_path / "nc"
    nc_dir.mkdir()
    for name in ("mixsed2_011.nc", "mixsed2_012.nc"):
        shutil.copy(FIXTURES_NC / name, nc_dir / name)

    stage2_run(nc_dir, cast_tags={"011"}, force=True)

    # 011 was processed — it will have _qc variables; 012 was skipped — it won't
    import xarray as xr

    ds_011 = xr.open_dataset(nc_dir / "mixsed2_011.nc", engine="netcdf4")
    ds_012 = xr.open_dataset(nc_dir / "mixsed2_012.nc", engine="netcdf4")
    assert any(v.endswith("_qc") for v in ds_011.data_vars), "011 should be flagged"
    assert not any(v.endswith("_qc") for v in ds_012.data_vars), (
        "012 should be untouched"
    )
    ds_011.close()
    ds_012.close()


def test_run_stage3_cast_tags(tmp_path: Path) -> None:
    """stage3.run with cast_tags processes only the matching file."""
    nc_dir = tmp_path / "nc"
    nc_dir.mkdir()
    for name in ("mixsed2_011.nc", "mixsed2_012.nc"):
        shutil.copy(FIXTURES_NC / name, nc_dir / name)

    mtime_012_before = (nc_dir / "mixsed2_012.nc").stat().st_mtime
    stage3_run(nc_dir, cast_tags={"011"}, force=True)

    assert (nc_dir / "mixsed2_012.nc").stat().st_mtime == mtime_012_before, (
        "012 should not be touched"
    )
