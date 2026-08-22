"""Tests for :class:`ctdcast.processors.StagePaths` — root resolution and shim."""

from __future__ import annotations

from pathlib import Path

from ctdcast.processors import StagePaths


def test_roots_are_read_straight_through():
    paths = StagePaths.from_config(
        {"cnv_dir": "/d/cnv", "ctd_root": "/d/CTD", "ladcp_root": "/d/LADCP"}
    )
    assert paths.ctd_root == Path("/d/CTD")
    assert paths.ladcp_root == Path("/d/LADCP")
    assert paths.cnv_dir == Path("/d/cnv")


def test_products_derive_from_their_root():
    paths = StagePaths.from_config({"ctd_root": "/d/CTD", "ladcp_root": "/d/LADCP"})
    assert paths.profiles_path == Path("/d/CTD/profiles.nc")
    assert paths.ladcp_profiles_path == Path("/d/LADCP/ladcp_profiles.nc")


def test_explicit_product_paths_override_the_derived_ones():
    """An existing config pointing the product elsewhere keeps working."""
    paths = StagePaths.from_config(
        {"ctd_root": "/d/CTD", "profiles_nc": "/elsewhere/p.nc"}
    )
    assert paths.profiles_path == Path("/elsewhere/p.nc")


def test_legacy_nc_dir_becomes_the_root():
    """The flat-layout shim: a pre-stage-layout config still resolves.

    Flatness itself is NOT carried here — it is a naming variant, detected in the
    module that owns naming, so nothing downstream branches on layout.
    """
    paths = StagePaths.from_config({"nc_dir": "/d/nc", "ladcp_nc": "/d/lnc"})
    assert paths.ctd_root == Path("/d/nc")
    assert paths.ladcp_root == Path("/d/lnc")


def test_a_root_wins_over_the_legacy_key():
    paths = StagePaths.from_config({"ctd_root": "/d/CTD", "nc_dir": "/d/old"})
    assert paths.ctd_root == Path("/d/CTD")


def test_absent_sources_stay_none_rather_than_becoming_paths():
    """A `None` path means the source is not configured and is skipped, so an
    empty string must not resolve to Path('.')."""
    paths = StagePaths.from_config({"ctd_root": "", "ladcp_root": None})
    assert paths.ctd_root is None
    assert paths.ladcp_root is None
    assert paths.profiles_path is None
    assert paths.ladcp_profiles_path is None


def test_process_kwargs_and_config_agree():
    """Both entry points route through one precedence rule."""
    from_cfg = StagePaths.from_config({"nc_dir": "/d/nc", "profiles_nc": "/d/p.nc"})
    assert from_cfg.ctd_root == Path("/d/nc")
    assert from_cfg.profiles_path == Path("/d/p.nc")
