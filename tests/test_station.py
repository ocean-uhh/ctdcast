"""Structural tests for generate_station_page HTML output."""

import re
from pathlib import Path

import pytest
from conftest import CAST_011, CAST_012, FIXTURES_LADCP

from ctdreport.index import _read_cast_meta
from ctdreport.station import _cast_id_from_path, generate_station_page


@pytest.fixture
def meta_011():
    """Read metadata for cast 011."""
    m = _read_cast_meta(CAST_011)
    assert m is not None, "fixture cast 011 failed _read_cast_meta"
    return m


@pytest.fixture
def meta_012():
    """Read metadata for cast 012."""
    m = _read_cast_meta(CAST_012)
    assert m is not None, "fixture cast 012 failed _read_cast_meta"
    return m


@pytest.fixture
def station_html(tmp_path, meta_011, meta_012):
    """Generate station page for cast 011 (no LADCP) and return HTML text."""
    out = generate_station_page(
        CAST_011,
        tmp_path,
        all_meta=[meta_011, meta_012],
        prev_cast_str=None,
        next_cast_str="012",
        force=True,
    )
    assert out is not None and out.exists(), (
        "generate_station_page returned None or missing file"
    )
    return out.read_text(encoding="utf-8")


@pytest.fixture
def station_html_ladcp(tmp_path, meta_011, meta_012):
    """Generate station page for cast 011 with LADCP data."""
    out = generate_station_page(
        CAST_011,
        tmp_path,
        all_meta=[meta_011, meta_012],
        prev_cast_str=None,
        next_cast_str="012",
        force=True,
        ladcp_dir=FIXTURES_LADCP,
    )
    assert out is not None and out.exists()
    return out.read_text(encoding="utf-8")


# --- file creation -----------------------------------------------------------


def test_station_creates_file(tmp_path, meta_011):
    out = generate_station_page(CAST_011, tmp_path, all_meta=[meta_011], force=True)
    assert out is not None
    assert out.exists()
    assert out.stat().st_size > 10_000


def test_station_skips_existing(tmp_path, meta_011):
    out1 = generate_station_page(CAST_011, tmp_path, all_meta=[meta_011], force=True)
    mtime1 = out1.stat().st_mtime
    out2 = generate_station_page(CAST_011, tmp_path, all_meta=[meta_011], force=False)
    assert out2 is not None
    assert out2.stat().st_mtime == mtime1


def test_station_output_path(tmp_path, meta_011):
    out = generate_station_page(CAST_011, tmp_path, all_meta=[meta_011], force=True)
    assert out == tmp_path / "stations" / "cast_011.html"


# --- HTML structure ----------------------------------------------------------


def test_station_is_valid_html(station_html):
    assert station_html.lower().startswith("<!doctype html")
    assert "</html>" in station_html.lower()


def test_station_is_self_contained(station_html):
    # Only flag resources loaded at view time: src= and <link> href=
    # Anchor <a href="https://..."> navigation links are intentionally excluded
    external = re.findall(r'\bsrc=["\']https?://', station_html)
    external += re.findall(r'<link\b[^>]+\bhref=["\']https?://', station_html)
    assert external == [], f"External resource links found: {external}"


def test_station_has_cast_number(station_html):
    assert "011" in station_html


def test_station_has_position(station_html):
    # Cast 011 is at ~65.86°N; check for N hemisphere marker
    assert "°N" in station_html or "N" in station_html


def test_station_has_profiles_section(station_html):
    # Physics/profiles section must be present (section id s-profiles)
    assert "s-profiles" in station_html


# --- LADCP integration -------------------------------------------------------


def test_station_ladcp_creates_file(tmp_path, meta_011):
    out = generate_station_page(
        CAST_011, tmp_path, all_meta=[meta_011], force=True, ladcp_dir=FIXTURES_LADCP
    )
    assert out is not None and out.exists()


def test_station_ladcp_self_contained(station_html_ladcp):
    external = re.findall(r'\bsrc=["\']https?://', station_html_ladcp)
    external += re.findall(r'<link\b[^>]+\bhref=["\']https?://', station_html_ladcp)
    assert external == [], f"External resource links in LADCP page: {external}"


# --- cast id parsing ----------------------------------------------------------


def test_cast_id_plain():
    assert _cast_id_from_path(Path("mixsed2_042.nc")) == (42, "")


def test_cast_id_letter_suffix_no_underscore():
    assert _cast_id_from_path(Path("mixsed2_042b.nc")) == (42, "b")


def test_cast_id_letter_suffix_with_underscore():
    """Underscore-before-letter format (e.g. mixsed2_004_b.nc) normalises to same suffix."""
    assert _cast_id_from_path(Path("mixsed2_004_b.nc")) == (4, "b")
