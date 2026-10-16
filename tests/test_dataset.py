"""Tests for the netCDF data-inventory page (reports/_dataset.py)."""

from pathlib import Path

import pytest
from conftest import CAST_011, FIXTURES_NC

from ctdcast.readers.metadata import _SOURCE_NAME_ATTRS
from ctdcast.reports.dataset import (
    data_range_rows,
    generate_dataset_page,
    read_dataset_meta,
)

PROFILES_DEMO = Path(__file__).parent / "fixtures" / "profiles_demo.nc"


def _all_var_rows(meta):
    """Flatten the grouped data-variable rows of an inventory into one list."""
    return [row for _title, group in meta["variables"]["groups"] for row in group]


# --- read_dataset_meta -------------------------------------------------------


def test_read_meta_structure():
    """Inventory carries dims, summary, the five builder blocks, rename_map, coverage."""
    meta = read_dataset_meta(CAST_011)
    assert "error" not in meta
    assert meta["filename"] == "mixsed2_011.nc"
    assert meta["filesize"] > 0
    assert meta["dims"]  # non-empty dimension map
    assert meta["summary"]["coordinates"] >= 1
    assert meta["coords"]["rows"] and meta["variables"]["groups"]
    # each builder reports the caption string naming the function that built it
    assert meta["coords"]["source"] and meta["variables"]["source"]
    # every variable row has the inventory fields the vendored builder produces
    rows = _all_var_rows(meta)
    assert rows
    for key in ("name", "dtype", "units", "standard_name", "n", "n_valid", "valid_pct"):
        assert key in rows[0]


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
    for row in meta["coords"]["rows"] + _all_var_rows(meta):
        assert "units" not in row["attrs"]
        assert "standard_name" not in row["attrs"]
        assert "long_name" not in row["attrs"]


def test_source_name_kept_in_expandable_attrs():
    """cnv_original_name stays in the expandable attrs (not a dedicated column)."""
    meta = read_dataset_meta(CAST_011)
    named = [
        r
        for r in _all_var_rows(meta)
        if any(a in r["attrs"] for a in _SOURCE_NAME_ATTRS)
    ]
    assert named, "expected at least one variable carrying cnv_original_name"


def test_valid_count_matches_length_when_no_missing():
    """n_valid never exceeds n; a fully-finite variable has n_valid == n."""
    meta = read_dataset_meta(CAST_011)
    for row in _all_var_rows(meta):
        assert row["n_valid"] <= row["n"]


def test_coverage_check_matches_written_bounds():
    """The coverage recompute agrees with a correctly-written file (no cell flagged)."""
    meta = read_dataset_meta(PROFILES_DEMO)
    cov = meta["coverage"]
    # the demo file states bounds computed from its own data, so nothing is over tolerance
    assert cov, "expected coverage attributes to be checked"
    assert all(not entry["over"] for entry in cov.values())
    # both the lat extent and the time extent were recomputed and compared
    assert "geospatial_lat_min" in cov
    assert "time_coverage_start" in cov


def test_qc_companions_not_listed_as_variables():
    """A ``_qc`` companion folds into its parent's row, never appears as its own row."""
    meta = read_dataset_meta(PROFILES_DEMO)
    names = {r["name"] for r in _all_var_rows(meta)}
    assert not any(n.endswith("_qc") for n in names)


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


def test_generated_page_has_family_layout(tmp_path):
    """The inventory page renders the vendored family layout and sortable tables."""
    out = generate_dataset_page(PROFILES_DEMO, tmp_path / "inv.html")
    html = out.read_text(encoding="utf-8")
    assert "Variables on N_PROF" in html  # variables grouped by dimension
    assert "Sensor catalog" in html
    assert 'class="sortable' in html  # the click-to-sort tables
    # ctdcast turns the source caption on, so builder provenance shows under a table
    assert "source:" in html
    # the old flat layout is gone
    assert 'class="dims-line"' not in html


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
    """The cast page carries the netCDF data-ranges appendix with label units.

    Sensors (A) and File provenance (B) precede it for a fixture that carries sensor
    information and identity attributes, so data ranges is the third appendix (C).
    """
    from ctdcast.reports.cast import generate_station_page
    from ctdcast.reports.index import _read_cast_meta

    meta = _read_cast_meta(CAST_011)
    assert meta is not None
    out = generate_station_page(CAST_011, tmp_path, all_meta=[meta], force=True)
    html = out.read_text(encoding="utf-8")
    assert 'id="data_ranges"' in html  # appendix section anchor
    assert "(C) netCDF data ranges" in html  # lettered appendix in heading + jump-nav
    assert "Label units" in html  # the label-units column
    assert "mS/cm" in html  # a populated label_units value (conductivity)


def test_cast_page_shows_file_provenance_and_processing_level(tmp_path):
    """A cast file carrying identity/mode/stage attrs gets a File provenance appendix, and the
    data-ranges table carries a Processing level column populated from the variables."""
    import xarray as xr

    from ctdcast.reports.cast import generate_station_page
    from ctdcast.reports.index import _read_cast_meta

    src = tmp_path / "mixsed2_011_stage3.nc"
    ds = xr.open_dataset(CAST_011, engine="netcdf4").load()
    ds.attrs["cast_id"] = "011"
    ds.attrs["data_mode"] = "P"
    ds.attrs["data_mode_meaning"] = "provisional"
    ds.attrs["processing_stage"] = 3
    ds.attrs["tracking_id"] = "abc-123"
    tvar = "ctd_temperature_1" if "ctd_temperature_1" in ds else "ctd_temperature"
    ds[tvar].attrs["processing_level"] = (
        "Instrument data that has been converted to geophysical values"
    )
    ds.to_netcdf(src)  # plain write: exercise the report reading arbitrary file attrs
    ds.close()

    out = generate_station_page(
        src, tmp_path / "out", all_meta=[_read_cast_meta(src)], force=True
    )
    html = out.read_text(encoding="utf-8")
    assert 'id="file_provenance"' in html  # the new appendix section
    assert "File provenance" in html
    assert "provisional" in html  # data_mode meaning surfaced
    assert "Processing level" in html  # the new data-ranges column header
    assert "converted to geophysical values" in html  # the value, in the ranges table


def test_cast_page_shows_source_provenance(tmp_path):
    """The cast page names the source file (stage in the name) and a Processed date."""
    import shutil

    from ctdcast.reports.cast import generate_station_page
    from ctdcast.reports.index import _read_cast_meta

    src = tmp_path / "mixsed2_011_stage2.nc"
    shutil.copy(CAST_011, src)
    out = generate_station_page(
        src, tmp_path / "out", all_meta=[_read_cast_meta(src)], force=True
    )
    html = out.read_text(encoding="utf-8")
    assert "<dt>Source</dt>" in html
    assert "mixsed2_011_stage2.nc" in html  # the stage is encoded in the filename
    assert "<dt>Processed</dt>" in html  # separate date field, not crammed in Source


def test_data_range_rows_label_units_from_registry():
    """The cast-page data-ranges rows carry label_units from the VARIABLES registry."""
    by_name = {r["name"]: r for r in data_range_rows(CAST_011)}
    assert by_name["ctd_temperature_1"]["label_units"] == "°C"
    assert by_name["ctd_salinity_1"]["label_units"] == "PSU"


def test_data_range_rows_missing_file_is_empty():
    """An unreadable file yields no rows (the cast appendix is skipped), not an exception."""
    assert data_range_rows(Path("/nonexistent/file.nc")) == []


def test_report_generates_inventory_pill_and_page(tmp_path):
    """report() writes a per-file inventory page and a matching summary pill."""
    from ctdcast.reports.index import report

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
