"""Tests for :mod:`ctdcast.processors.stage_layout`.

These exercise filename and path logic only — the files are empty ``touch``ed
placeholders, never opened — so no instrument data is involved.
"""

from __future__ import annotations

import pytest

import ctdcast.processors as processors
from ctdcast.processors.stage_layout import (
    STAGE_DIRS,
    STAGE_SUFFIXES,
    STAGES,
    best_available,
    group_by_cast,
    parse_stage,
    stage_dir,
    stage_path,
)


def _touch(root, stage, stem):
    """Create an empty stage file for *stem* and return its path."""
    path = stage_path(root, stem, stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


# --- single source of truth ------------------------------------------------


def test_suffixes_and_tuple_derive_from_dirs():
    # Suffix is the dir name with a leading underscore; the tuple is its keys.
    assert STAGE_SUFFIXES == {n: f"_{d}" for n, d in STAGE_DIRS.items()}
    assert STAGES == tuple(sorted(STAGE_DIRS))


def test_cast_stages_match_the_pipeline_registry():
    # The cast-scope registry stages and this module's stage tuple encode the
    # same fact in two modules (deriving would be an import cycle: the registry
    # imports the stage modules that import this one).  This ties them so adding
    # a stage to one without the other fails loudly -- e.g. a future hex→CNV
    # stage 0.
    registry_cast_stages = {s.number for s in processors.STAGES if s.scope == "cast"}
    assert registry_cast_stages == set(STAGES)


# --- stage_dir / stage_path ------------------------------------------------


def test_stage_dir_returns_subdirectory(tmp_path):
    assert stage_dir(tmp_path, 2) == tmp_path / "stage2"


def test_stage_dir_create_makes_it(tmp_path):
    d = stage_dir(tmp_path, 1, create=True)
    assert d.is_dir()


def test_stage_dir_default_does_not_create(tmp_path):
    d = stage_dir(tmp_path, 3)
    assert not d.exists()


def test_stage_path_carries_suffix_and_dir(tmp_path):
    p = stage_path(tmp_path, "mixsed2_017", 2)
    assert p == tmp_path / "stage2" / "mixsed2_017_stage2.nc"


@pytest.mark.parametrize("bad", [0, 4, "1"])
def test_unknown_stage_raises(tmp_path, bad):
    with pytest.raises(ValueError, match="unknown stage"):
        stage_dir(tmp_path, bad)
    with pytest.raises(ValueError, match="unknown stage"):
        stage_path(tmp_path, "mixsed2_017", bad)


# --- parse_stage -----------------------------------------------------------


def test_parse_stage_reads_base_and_stage(tmp_path):
    p = stage_path(tmp_path, "mixsed2_017", 3)
    assert parse_stage(p) == ("mixsed2_017", 3)


def test_parse_stage_on_name_without_suffix():
    assert parse_stage("mixsed2_017.nc") is None


def test_parse_stage_filename_wins_over_parent_dir(tmp_path):
    # A stage-2 file sitting in the stage1/ directory: filename wins, with a warning.
    misplaced = tmp_path / STAGE_DIRS[1] / "mixsed2_005_stage2.nc"
    misplaced.parent.mkdir(parents=True)
    misplaced.touch()
    with pytest.warns(UserWarning, match="trusting the filename"):
        base, stage = parse_stage(misplaced)
    assert (base, stage) == ("mixsed2_005", 2)


def test_parse_stage_no_warning_when_dir_agrees(tmp_path, recwarn):
    p = _touch(tmp_path, 2, "mixsed2_005")
    assert parse_stage(p) == ("mixsed2_005", 2)
    assert len(recwarn) == 0


def test_parse_stage_outside_any_stage_dir_no_warning(tmp_path, recwarn):
    # Copied to a desktop: no stage-named parent, so no disagreement to warn about.
    loose = tmp_path / "mixsed2_005_stage1.nc"
    loose.touch()
    assert parse_stage(loose) == ("mixsed2_005", 1)
    assert len(recwarn) == 0


# --- best_available --------------------------------------------------------


def test_best_available_prefers_highest_stage(tmp_path):
    _touch(tmp_path, 1, "mixsed2_017")
    _touch(tmp_path, 2, "mixsed2_017")
    _touch(tmp_path, 3, "mixsed2_017")
    assert best_available(tmp_path, "mixsed2_017") == stage_path(
        tmp_path, "mixsed2_017", 3
    )


def test_best_available_falls_back_to_only_stage_present(tmp_path):
    _touch(tmp_path, 1, "mixsed2_017")
    assert best_available(tmp_path, "mixsed2_017") == stage_path(
        tmp_path, "mixsed2_017", 1
    )


def test_best_available_skips_missing_intermediate(tmp_path):
    _touch(tmp_path, 1, "mixsed2_017")
    _touch(tmp_path, 3, "mixsed2_017")  # stage 2 absent
    assert best_available(tmp_path, "mixsed2_017") == stage_path(
        tmp_path, "mixsed2_017", 3
    )


def test_best_available_none_when_no_files(tmp_path):
    assert best_available(tmp_path, "mixsed2_017") is None


# --- flat / suffix-less shim (old nc_dir layout, committed fixtures) --------


def test_best_available_flat_suffixless_file_is_stage1(tmp_path):
    flat = tmp_path / "mixsed2_017.nc"  # no stage dir, no suffix
    flat.touch()
    assert best_available(tmp_path, "mixsed2_017") == flat


def test_best_available_nested_wins_over_flat(tmp_path):
    (tmp_path / "mixsed2_017.nc").touch()  # flat stage-1 shim
    nested = _touch(tmp_path, 1, "mixsed2_017")  # real nested stage 1
    assert best_available(tmp_path, "mixsed2_017") == nested


def test_group_by_cast_folds_in_flat_files_as_stage1(tmp_path):
    (tmp_path / "mixsed2_017.nc").touch()
    (tmp_path / "mixsed2_018.nc").touch()
    groups = group_by_cast(tmp_path)
    assert set(groups) == {(17, ""), (18, "")}
    assert groups[(17, "")] == {1: tmp_path / "mixsed2_017.nc"}


def test_group_by_cast_flat_stage1_plus_nested_stage2(tmp_path):
    flat = tmp_path / "mixsed2_017.nc"
    flat.touch()
    nested2 = _touch(tmp_path, 2, "mixsed2_017")
    groups = group_by_cast(tmp_path)
    assert groups[(17, "")] == {1: flat, 2: nested2}


def test_group_by_cast_nested_stage1_wins_over_flat(tmp_path):
    (tmp_path / "mixsed2_017.nc").touch()  # flat
    nested1 = _touch(tmp_path, 1, "mixsed2_017")  # nested — should win
    groups = group_by_cast(tmp_path)
    assert groups[(17, "")][1] == nested1


def test_group_by_cast_skips_compiled_products_at_root(tmp_path):
    (tmp_path / "mixsed2_017.nc").touch()
    (tmp_path / "profiles.nc").touch()  # compiled product, no cast number
    (tmp_path / "ladcp_profiles.nc").touch()
    groups = group_by_cast(tmp_path)
    assert set(groups) == {(17, "")}


def test_group_by_cast_ignores_loose_suffixed_file_at_root(tmp_path):
    # A stage-suffixed file loose at the root (not in its stage dir) is not a
    # flat stage 1 and is not in a stage dir, so it is not grouped.
    (tmp_path / "mixsed2_017_stage2.nc").touch()
    assert group_by_cast(tmp_path) == {}


# --- group_by_cast ---------------------------------------------------------


def test_group_by_cast_collects_stages_per_cast(tmp_path):
    _touch(tmp_path, 1, "mixsed2_017")
    _touch(tmp_path, 2, "mixsed2_017")
    _touch(tmp_path, 1, "mixsed2_018")
    groups = group_by_cast(tmp_path)
    assert set(groups) == {(17, ""), (18, "")}
    assert set(groups[(17, "")]) == {1, 2}
    assert set(groups[(18, "")]) == {1}
    assert groups[(17, "")][2] == stage_path(tmp_path, "mixsed2_017", 2)


def test_group_by_cast_distinguishes_lettered_sibling(tmp_path):
    _touch(tmp_path, 1, "mixsed2_004")
    _touch(tmp_path, 1, "mixsed2_004b")
    groups = group_by_cast(tmp_path)
    assert (4, "") in groups
    assert (4, "b") in groups


def test_group_by_cast_skips_file_without_cast_number(tmp_path):
    _touch(tmp_path, 1, "mixsed2_017")
    (tmp_path / STAGE_DIRS[1] / "notes_stage1.nc").touch()  # no 3+-digit group
    groups = group_by_cast(tmp_path)
    assert set(groups) == {(17, "")}


def test_group_by_cast_tolerates_missing_stage_dirs(tmp_path):
    # Only stage1/ exists; stage2/ and stage3/ never created.
    _touch(tmp_path, 1, "mixsed2_017")
    groups = group_by_cast(tmp_path)
    assert set(groups) == {(17, "")}


def test_group_by_cast_empty_root(tmp_path):
    assert group_by_cast(tmp_path) == {}
