"""Tests for ctdcast.processors registry (STAGES, resolve_stage, process API)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from conftest import FIXTURES_LADCP, FIXTURES_NC

from ctdcast.processors import (
    STAGES,
    Stage,
    StagePaths,
    process,
    resolve_stage,
    stages_for,
)
from ctdcast.processors.profiles import run as profiles_run
from ctdcast.processors.stage1 import run as stage1_run
from ctdcast.processors.stage2 import run as stage2_run
from ctdcast.processors.stage3 import run as stage3_run
from ctdcast.processors.stage_layout import stage_path


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


def test_resolve_stage_numeric_string() -> None:
    """The CLI passes stage numbers as strings; '1' must resolve to stage1.

    Regression: ``--stage 1`` forwarded the string ``"1"``, which only matched the
    integer ``1`` and raised "unknown stage '1'" while listing 1 as valid.
    """
    assert resolve_stage("1").name == "stage1"
    assert resolve_stage("2").name == "stage2"
    assert resolve_stage("3").name == "stage3"


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
    """stage2.run dry_run returns 0 and writes no stage-2 file."""
    root = tmp_path / "CTD"
    src = stage_path(root, "mixsed2_011", 1)
    src.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES_NC / "mixsed2_011.nc", src)
    result = stage2_run(root, dry_run=True)
    assert result == 0
    assert not stage_path(root, "mixsed2_011", 2).exists()


def test_run_stage3_dry_run(tmp_path: Path) -> None:
    """stage3.run dry_run returns 0 and writes no stage-3 file."""
    root = tmp_path / "CTD"
    src = stage_path(root, "mixsed2_011", 2)
    src.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES_NC / "mixsed2_011.nc", src)
    result = stage3_run(root, dry_run=True)
    assert result == 0
    assert not stage_path(root, "mixsed2_011", 3).exists()


def test_run_stage2_root_not_found(tmp_path: Path) -> None:
    """stage2.run raises FileNotFoundError when the stage root does not exist."""
    with pytest.raises(FileNotFoundError):
        stage2_run(tmp_path / "missing", dry_run=True)


def test_run_stage3_root_not_found(tmp_path: Path) -> None:
    """stage3.run raises FileNotFoundError when the stage root does not exist."""
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


def _place(root: Path, name: str, stem: str, stage: int) -> Path:
    """Copy fixture *name* into *root* as *stem* at *stage*; return the path."""
    dst = stage_path(root, stem, stage)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES_NC / name, dst)
    return dst


def test_run_stage2_cast_tags(tmp_path: Path) -> None:
    """stage2.run with cast_tags processes only the matching cast."""
    root = tmp_path / "CTD"
    _place(root, "mixsed2_011.nc", "mixsed2_011", 1)
    _place(root, "mixsed2_012.nc", "mixsed2_012", 1)

    stage2_run(root, cast_tags={"011"})

    assert stage_path(root, "mixsed2_011", 2).exists(), "011 should be processed"
    assert not stage_path(root, "mixsed2_012", 2).exists(), "012 should be filtered out"


def test_run_stage3_cast_tags(tmp_path: Path) -> None:
    """stage3.run with cast_tags processes only the matching cast."""
    root = tmp_path / "CTD"
    _place(root, "mixsed2_011.nc", "mixsed2_011", 2)
    _place(root, "mixsed2_012.nc", "mixsed2_012", 2)

    stage3_run(root, cast_tags={"011"})

    assert stage_path(root, "mixsed2_011", 3).exists(), "011 should be processed"
    assert not stage_path(root, "mixsed2_012", 3).exists(), "012 should be filtered out"


def test_stage3_declared_delayed_mode_without_calibration_warns(tmp_path: Path) -> None:
    """A declared data_mode 'D' with no calibration block stamps 'D' but warns naming
    the cast and records the unsupported claim in history — the file states its own gap."""
    import xarray as xr

    root = tmp_path / "CTD"
    _place(root, "mixsed2_011.nc", "mixsed2_011", 2)

    with pytest.warns(UserWarning, match="data_mode 'D'"):
        stage3_run(root, cruise_info={"data_mode": "D"})

    ds = xr.open_dataset(stage_path(root, "mixsed2_011", 3), engine="netcdf4")
    try:
        assert ds.attrs["data_mode"] == "D"
        assert ds.attrs["data_mode_meaning"] == "delayed-mode"
        assert "unsupported" in ds.attrs.get("history", "")
    finally:
        ds.close()


def test_compiled_profiles_processing_level_agrees_or_marks_mixed(
    tmp_path: Path,
) -> None:
    """profiles.nc carries per-variable processing_level so the archive is interpretable on
    its own: the casts' agreed value when they match, an explicit mixed marker when they
    differ — never a union of the sentences (which would claim a procedure on a cast that
    never had it)."""
    import warnings

    import xarray as xr

    from ctdcast.processors.profiles import build_profiles

    cal = {"calibration": {"conductivity_slope": 1.0002}}

    # Agreement: both casts processed identically to stage 3.
    agree = tmp_path / "agree"
    _place(agree, "mixsed2_011.nc", "mixsed2_011", 1)
    _place(agree, "mixsed2_012.nc", "mixsed2_012", 1)
    stage2_run(agree)
    stage3_run(agree, cruise_cfg=cal)
    out_a = tmp_path / "agree.nc"
    build_profiles(agree, out_a, force=True)
    da = xr.open_dataset(out_a, engine="netcdf4")
    try:
        tvar = "ctd_temperature_1" if "ctd_temperature_1" in da else "ctd_temperature"
        # Both casts agree, so the compiled value is theirs verbatim: the stage-1 conversion
        # value (fixtures now carry it) plus the stage-2/3 range flag.
        assert "Ranges applied, bad data flagged" in da[tvar].attrs["processing_level"]
        assert "converted to geophysical values" in da[tvar].attrs["processing_level"]
        assert (
            "Post-recovery calibrations have been applied"
            in da["conductivity_1"].attrs["processing_level"]
        )
    finally:
        da.close()

    # Disagreement: one cast at stage 3, one left at stage 1 -> explicit mixed marker.
    mixed = tmp_path / "mixed"
    _place(mixed, "mixsed2_011.nc", "mixsed2_011", 1)
    stage2_run(mixed)
    stage3_run(mixed, cruise_cfg=cal)
    _place(mixed, "mixsed2_012.nc", "mixsed2_012", 1)  # stays stage 1
    out_m = tmp_path / "mixed.nc"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # mixed-stage warning is expected here
        build_profiles(mixed, out_m, force=True)
    dm = xr.open_dataset(out_m, engine="netcdf4")
    try:
        tvar = "ctd_temperature_1" if "ctd_temperature_1" in dm else "ctd_temperature"
        assert "mixed across casts" in dm[tvar].attrs["processing_level"]
    finally:
        dm.close()


def test_processing_level_accumulates_idempotently_across_stages(
    tmp_path: Path,
) -> None:
    """stage 2 soak/deck and stage 3 gross-range both flag a measured var, yet the range
    value is listed once; calibration adds its own value and propagates to re-derived
    salinity, which — computed, never instrument data — carries no conversion value; the
    SENSOR_* catalog scalars carry no processing_level at all."""
    import xarray as xr

    ranges = "Ranges applied, bad data flagged"
    cal = "Post-recovery calibrations have been applied"

    root = tmp_path / "CTD"
    _place(root, "mixsed2_011.nc", "mixsed2_011", 1)
    stage2_run(root)
    stage3_run(root, cruise_cfg={"calibration": {"conductivity_slope": 1.0002}})

    ds = xr.open_dataset(stage_path(root, "mixsed2_011", 3), engine="netcdf4")
    try:
        tvar = "ctd_temperature_1" if "ctd_temperature_1" in ds else "ctd_temperature"
        assert ds[tvar].attrs["processing_level"].count(ranges) == 1  # idempotent
        assert cal in ds["conductivity_1"].attrs["processing_level"]
        sal = "ctd_salinity_1" if "ctd_salinity_1" in ds else "ctd_salinity"
        assert cal in ds[sal].attrs["processing_level"]  # calibration propagates
        assert "converted to geophysical values" not in ds[sal].attrs.get(
            "processing_level", ""
        )
        sensors = [v for v in ds.data_vars if str(v).startswith("SENSOR_")]
        assert sensors and all("processing_level" not in ds[v].attrs for v in sensors)
    finally:
        ds.close()


def test_stage3_declared_delayed_mode_with_empty_calibration_block_warns(
    tmp_path: Path,
) -> None:
    """A calibration block that applies no slope does not back a 'D' claim: the warning
    fires on whether calibration was *applied*, not on the mere presence of the block."""
    import xarray as xr

    root = tmp_path / "CTD"
    _place(root, "mixsed2_011.nc", "mixsed2_011", 2)

    with pytest.warns(UserWarning, match="data_mode 'D'"):
        stage3_run(
            root,
            cruise_info={"data_mode": "D"},
            cruise_cfg={"calibration": {"conductivity_slope": None}},
        )

    ds = xr.open_dataset(stage_path(root, "mixsed2_011", 3), engine="netcdf4")
    try:
        assert ds.attrs["data_mode"] == "D"
        assert "unsupported" in ds.attrs.get("history", "")
    finally:
        ds.close()


def test_stage3_declared_delayed_mode_with_calibration_is_silent(
    tmp_path: Path,
) -> None:
    """When a calibration block backs the 'D' claim, stamp 'D' and raise no warning."""
    import warnings

    import xarray as xr

    root = tmp_path / "CTD"
    _place(root, "mixsed2_011.nc", "mixsed2_011", 2)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        stage3_run(
            root,
            cruise_info={"data_mode": "D"},
            cruise_cfg={"calibration": {"conductivity_slope": 1.0002}},
        )
    assert not [w for w in caught if "data_mode 'D'" in str(w.message)]

    ds = xr.open_dataset(stage_path(root, "mixsed2_011", 3), engine="netcdf4")
    try:
        assert ds.attrs["data_mode"] == "D"
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# Non-destructive stage lineage — new files, frozen predecessors, strict reads
# ---------------------------------------------------------------------------


def test_stage2_is_non_destructive(tmp_path: Path) -> None:
    """stage 2 writes a new stage-2 file and leaves the stage-1 file byte-frozen."""
    root = tmp_path / "CTD"
    s1 = _place(root, "mixsed2_011.nc", "mixsed2_011", 1)
    before = s1.read_bytes()

    assert stage2_run(root) == 1
    s2 = stage_path(root, "mixsed2_011", 2)
    assert s2.exists()
    assert s1.read_bytes() == before, "stage 1 must be frozen"

    import xarray as xr

    ds = xr.open_dataset(s2, engine="netcdf4")
    assert any(v.endswith("_qc") for v in ds.data_vars), "stage 2 should add _qc flags"
    ds.close()


def test_stage2_skips_when_target_exists(tmp_path: Path) -> None:
    """A second stage-2 run skips the cast whose target already exists."""
    root = tmp_path / "CTD"
    _place(root, "mixsed2_011.nc", "mixsed2_011", 1)
    assert stage2_run(root) == 1
    assert stage2_run(root) == 0  # target exists → skipped


def test_stage2_force_rewrites_target(tmp_path: Path) -> None:
    """--force reprocesses a cast even when its stage-2 file already exists."""
    root = tmp_path / "CTD"
    _place(root, "mixsed2_011.nc", "mixsed2_011", 1)
    assert stage2_run(root) == 1
    assert stage2_run(root, force=True) == 1  # rewritten despite existing target


def test_stage2_skips_cast_missing_stage1(tmp_path: Path) -> None:
    """A cast present only at stage 2 has no stage-1 input, so stage 2 skips it."""
    root = tmp_path / "CTD"
    _place(root, "mixsed2_011.nc", "mixsed2_011", 2)  # only stage 2 present
    assert stage2_run(root) == 0


def test_stage3_reads_stage2_strictly(tmp_path: Path) -> None:
    """stage 3 requires a stage-2 file; a stage-1-only cast is skipped (not promoted)."""
    root = tmp_path / "CTD"
    _place(root, "mixsed2_011.nc", "mixsed2_011", 1)  # only stage 1 present
    assert stage3_run(root) == 0
    assert not stage_path(root, "mixsed2_011", 3).exists()


def test_stage_pipeline_lineage(tmp_path: Path) -> None:
    """stage 2 then 3 leave all files, with earlier stages frozen by later ones."""
    root = tmp_path / "CTD"
    s1 = _place(root, "mixsed2_011.nc", "mixsed2_011", 1)
    assert stage2_run(root) == 1
    s2 = stage_path(root, "mixsed2_011", 2)
    s1_bytes, s2_bytes = s1.read_bytes(), s2.read_bytes()

    assert stage3_run(root) == 1
    s3 = stage_path(root, "mixsed2_011", 3)
    assert s1.exists() and s2.exists() and s3.exists()
    assert s1.read_bytes() == s1_bytes, "stage 1 frozen by stage 3"
    assert s2.read_bytes() == s2_bytes, "stage 2 frozen by stage 3"


# ---------------------------------------------------------------------------
# Stage registry — single source of truth, one token per stage, source fan-out
# ---------------------------------------------------------------------------


def test_stages_are_the_four_pipeline_tokens() -> None:
    """STAGES holds exactly stage1/2/3/profiles — LADCP is a source, not a token."""
    assert [s.name for s in STAGES] == ["stage1", "stage2", "stage3", "profiles"]


def test_retired_ladcp_tokens_do_not_resolve() -> None:
    """The old per-source tokens are gone; LADCP runs under stage1/profiles now."""
    for token in ("ladcp", "ladcp-profiles"):
        with pytest.raises(ValueError, match="unknown stage"):
            resolve_stage(token)


def test_stages_for_orders_and_dedups() -> None:
    """A requested subset always runs in STAGES order, deduplicated."""
    got = [s.name for s in stages_for(["profiles", 1, "1"])]
    assert got == ["stage1", "profiles"]
    assert [s.name for s in stages_for(None)] == [s.name for s in STAGES]


def test_stage1_fans_out_to_ladcp(tmp_path: Path) -> None:
    """process(stage1) with only LADCP paths converts the .mat files (CTD skipped)."""
    ladcp_nc = tmp_path / "ladcp_nc"
    process(
        "stage1",
        ladcp_dir=FIXTURES_LADCP,
        ladcp_nc_dir=ladcp_nc,
        force=True,
    )
    assert len(list((ladcp_nc / "stage1").glob("ladcp_*.nc"))) == 4


def test_profiles_fans_out_to_both_sources(tmp_path: Path) -> None:
    """process(profiles) compiles profiles.nc (CTD) and ladcp_profiles.nc (LADCP)."""
    ladcp_nc = tmp_path / "ladcp_nc"
    process("stage1", ladcp_dir=FIXTURES_LADCP, ladcp_nc_dir=ladcp_nc, force=True)
    profiles_path = tmp_path / "profiles.nc"
    ladcp_profiles = tmp_path / "ladcp_profiles.nc"
    process(
        "profiles",
        nc_dir=FIXTURES_NC,
        profiles_path=profiles_path,
        ladcp_nc_dir=ladcp_nc,
        ladcp_profiles_path=ladcp_profiles,
        force=True,
    )
    assert profiles_path.exists()
    assert ladcp_profiles.exists()


def test_stagepaths_unconfigured_source_is_skipped(tmp_path: Path) -> None:
    """A stage with no configured source for it does nothing, without error."""
    # profiles with neither ctd_root nor ladcp_root configured — both products
    # are unconfigured, so nothing is written.  (With a root set, profiles_path
    # now derives as <root>/profiles.nc, so passing a read dir alone would write.)
    result = process("profiles")
    assert result is False  # nothing written
    assert isinstance(StagePaths(), StagePaths)


def test_process_stage1_ctd_branch_with_no_cnv_files(tmp_path: Path) -> None:
    """stage 1 enters the CTD source branch even when the CNV dir is empty."""
    # stage1() loads the CTD backend before globbing, so this needs seasenselib.
    pytest.importorskip("seasenselib")
    cnv = tmp_path / "cnv"
    cnv.mkdir()
    assert process("stage1", cnv_dir=cnv, ctd_root=tmp_path / "CTD") == 0


def test_process_stage2_without_ctd_root_is_noop() -> None:
    """stage 2 with no ctd_root configured does nothing, without error."""
    assert process("stage2") == 0


def test_process_stage3_without_ctd_root_is_noop() -> None:
    """stage 3 with no ctd_root configured does nothing, without error."""
    assert process("stage3") == 0


def test_stage2_rebuilds_when_stage1_is_newer(tmp_path: Path) -> None:
    """A stage-1 rewrite makes stage 2 re-run without --force (source-mtime skip)."""
    import os

    root = tmp_path / "CTD"
    s1 = _place(root, "mixsed2_011.nc", "mixsed2_011", 1)
    assert stage2_run(root) == 1
    s2 = stage_path(root, "mixsed2_011", 2)
    assert stage2_run(root) == 0  # unchanged stage 1 → skipped (up to date)
    # Make stage 1 newer than stage 2: the stale stage-2 file must be rebuilt.
    os.utime(s1, (s2.stat().st_atime, s2.stat().st_mtime + 10))
    assert stage2_run(root) == 1
