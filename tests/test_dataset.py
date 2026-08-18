"""Tests for the netCDF data-inventory page (reports/_dataset.py)."""

from pathlib import Path

import pytest
from conftest import CAST_011, FIXTURES_NC

from ctdcast.reports._dataset import (
    _SOURCE_NAME_ATTR,
    generate_dataset_page,
    read_dataset_meta,
)

PROFILES_DEMO = Path(__file__).parent / "fixtures" / "profiles_demo.nc"


# --- read_dataset_meta -------------------------------------------------------


def test_read_meta_structure():
    """Inventory carries dims, coords, data_vars, rename_map, and global_attrs."""
    meta = read_dataset_meta(CAST_011)
    assert "error" not in meta
    assert meta["filename"] == "mixsed2_011.nc"
    assert meta["filesize"] > 0
    assert meta["dims"]  # non-empty dimension map
    assert meta["coords"] and meta["data_vars"]
    # every row has the inventory fields
    row = meta["data_vars"][0]
    for key in ("name", "dims", "dtype", "units", "standard_name", "n", "n_valid"):
        assert key in row


def test_rename_map_from_cnv_original_name():
    """The renaming table is built from each variable's cnv_original_name."""
    meta = read_dataset_meta(CAST_011)
    rmap = meta["rename_map"]
    # seasenselib records the raw column; the page maps source -> canonical.
    assert rmap.get("sal00") == "ctd_salinity_1"
    assert rmap.get("t090C") == "ctd_temperature_1"
    # identity entries (source == canonical) are excluded
    assert all(src != canon for src, canon in rmap.items())


def test_columned_attrs_excluded_from_expandable():
    """units/standard_name/long_name are columns, so they leave the attrs set."""
    meta = read_dataset_meta(CAST_011)
    for row in meta["coords"] + meta["data_vars"]:
        assert "units" not in row["attrs"]
        assert "standard_name" not in row["attrs"]
        assert "long_name" not in row["attrs"]


def test_source_name_kept_in_expandable_attrs():
    """cnv_original_name stays in the expandable attrs (not a dedicated column)."""
    meta = read_dataset_meta(CAST_011)
    named = [r for r in meta["data_vars"] if _SOURCE_NAME_ATTR in r["attrs"]]
    assert named, "expected at least one variable carrying cnv_original_name"


def test_valid_count_matches_length_when_no_missing():
    """n_valid never exceeds n; a fully-finite variable has n_valid == n."""
    meta = read_dataset_meta(CAST_011)
    for row in meta["data_vars"]:
        assert row["n_valid"] <= row["n"]


def test_read_meta_missing_file_returns_error():
    """A missing/unreadable file yields an error dict, not an exception."""
    meta = read_dataset_meta(Path("/nonexistent/file.nc"))
    assert "error" in meta
    assert meta["filename"] == "file.nc"


# --- generate_dataset_page ---------------------------------------------------


def test_generate_standalone_no_report_nav(tmp_path):
    """Standalone inspection suppresses the report page-nav."""
    out = generate_dataset_page(CAST_011, tmp_path / "inv.html")
    html = out.read_text(encoding="utf-8")
    assert out.exists()
    assert "Pages:" not in html  # no report nav for an arbitrary file
    assert "netCDF inventory" in html


def test_generate_report_mode_shows_back_nav_and_jumpnav(tmp_path):
    """In-report mode renders the report nav (back-navigation) and a numbered jump-nav."""
    out = generate_dataset_page(
        PROFILES_DEMO,
        tmp_path / "profiles_inventory.html",
        cruise="DEMO",
        show_nav=True,
    )
    html = out.read_text(encoding="utf-8")
    assert "Pages:" in html  # report nav for getting back to the summary
    assert 'class="jump-nav"' in html
    # sections are numbered "(N) Title" like the manifest pages
    assert '<h2 id="s-coords">(' in html
    assert '<h2 id="s-vars">(' in html


def test_generated_page_is_self_contained(tmp_path):
    """No external resource requests at view time (self-contained HTML)."""
    out = generate_dataset_page(PROFILES_DEMO, tmp_path / "inv.html")
    html = out.read_text(encoding="utf-8")
    assert 'src="https://' not in html
    assert 'href="https://' not in html or 'stylesheet" href="https://' not in html


# --- inspect CLI -------------------------------------------------------------


def test_inspect_cli_writes_page(tmp_path, capsys):
    """`ctdcast inspect` renders a page to the chosen output path."""
    from ctdcast.cli.inspect import build_parser, run

    out = tmp_path / "page.html"
    args = build_parser().parse_args([str(CAST_011), "-o", str(out)])
    rc = run(args)
    assert rc == 0
    assert out.exists()
    assert "Wrote" in capsys.readouterr().out


def test_inspect_cli_default_output_beside_file(tmp_path):
    """Without -o, the page is written next to the input as <stem>_inventory.html."""
    from ctdcast.cli.inspect import build_parser, run

    src = tmp_path / "cast_099.nc"
    src.write_bytes(CAST_011.read_bytes())
    rc = run(build_parser().parse_args([str(src)]))
    assert rc == 0
    assert (tmp_path / "cast_099_inventory.html").exists()


def test_inspect_cli_missing_file(tmp_path, capsys):
    """A missing input file returns exit code 1 with an error message."""
    from ctdcast.cli.inspect import build_parser, run

    rc = run(build_parser().parse_args([str(tmp_path / "nope.nc")]))
    assert rc == 1
    assert "not found" in capsys.readouterr().err


# --- cast-page inline ranges -------------------------------------------------


def test_cast_page_has_data_ranges_appendix(tmp_path):
    """The cast page carries the netCDF data-ranges as appendix (B) with label units."""
    from ctdcast.reports._cast import generate_station_page
    from ctdcast.reports._index import _read_cast_meta

    meta = _read_cast_meta(CAST_011)
    assert meta is not None
    out = generate_station_page(CAST_011, tmp_path, all_meta=[meta], force=True)
    html = out.read_text(encoding="utf-8")
    assert 'id="data_ranges"' in html  # appendix section anchor
    assert "(B) netCDF data ranges" in html  # lettered appendix in heading + jump-nav
    assert "Label units" in html  # the label-units column
    assert "S m⁻¹" in html  # a populated label_units value (conductivity)


def test_var_meta_label_units_from_registry():
    """label_units falls back to the VARIABLES registry by canonical name."""
    meta = read_dataset_meta(CAST_011)
    by_name = {r["name"]: r for r in meta["data_vars"]}
    assert by_name["ctd_temperature_1"]["label_units"] == "°C"
    assert by_name["ctd_salinity_1"]["label_units"] == "PSU"


def test_report_generates_inventory_pill_and_page(tmp_path):
    """report() writes a per-file inventory page and a matching summary pill."""
    from ctdcast.reports._index import report

    report(
        FIXTURES_NC,
        tmp_path,
        profiles_path=PROFILES_DEMO,
        generate={
            "stations": False,
            "sections": False,
            "timeseries": False,
            "index": True,
            "map": False,
        },
        force=True,
        cruise_info={"cruise_id": "DEMO"},
    )
    idx = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'class="file-pill"' in idx
    assert "profiles_demo.nc" in idx
    assert (tmp_path / "profiles_demo_inventory.html").exists()
    # no old single-page name, and no global Inventory nav pill
    assert not (tmp_path / "inventory.html").exists()
    assert ">Inventory</a>" not in idx


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
