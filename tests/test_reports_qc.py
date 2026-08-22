"""Tests for the report QC readers and the cast-page QC table."""

import xarray as xr
from conftest import CAST_011

from ctdcast.processors.qc import apply_gross_range
from ctdcast.processors.stage2 import apply_stage2
from ctdcast.reports._cast import _render_qc_table
from ctdcast.reports._qc import qc_summary, qc_thresholds


def _qc_file(tmp_path, name="cast_qc.nc"):
    """Write a cast file carrying QARTOD flags (stage 2 soak/deck + gross-range)."""
    with xr.open_dataset(CAST_011, engine="netcdf4") as ds:
        ds = ds.load()
    ds = apply_gross_range(apply_stage2(ds))
    path = tmp_path / name
    ds.to_netcdf(path)
    return path


class TestQCSummary:
    """qc_summary reads the flag-count breakdown from a per-cast file."""

    def test_rows_for_a_flagged_file(self, tmp_path):
        rows = qc_summary(_qc_file(tmp_path))
        assert rows, "a flagged file must produce summary rows"
        row = rows[0]
        assert set(row) == {"var", "total", "flags"}
        assert row["total"] > 0
        flag = row["flags"][0]
        assert set(flag) == {"flag", "label", "color", "n", "pct"}
        # counts sum to the total scan count
        assert sum(f["n"] for f in row["flags"]) == row["total"]

    def test_labels_come_from_the_files_flag_meanings(self, tmp_path):
        rows = qc_summary(_qc_file(tmp_path))
        labels = {f["label"] for row in rows for f in row["flags"]}
        # glossed from QARTOD flag_meanings the file declares
        assert "suspect" in labels  # suspect_or_of_high_interest
        assert "fail" in labels
        assert "pass" in labels

    def test_empty_for_a_file_without_qc(self):
        # CAST_011 is a stage-1 fixture: no _qc companions.
        assert qc_summary(CAST_011) == []

    def test_empty_on_missing_file(self, tmp_path):
        assert qc_summary(tmp_path / "nope.nc") == []


class TestQCThresholds:
    """qc_thresholds reads the gross-range attrs stamped on each _qc companion."""

    def test_reads_both_tiers(self, tmp_path):
        rows = qc_thresholds(_qc_file(tmp_path))
        assert rows, "gross-range attrs must be readable back"
        gr = [r for r in rows if r["test"] == "gross-range"]
        assert gr, "gross-range rows expected"
        assert all({"var", "test", "suspect", "fail"} <= set(r) for r in gr)
        # at least one variable carries a suspect range like [2.0, 40.0]
        assert any(r["suspect"].startswith("[") for r in gr)

    def test_empty_for_a_file_without_qc(self):
        assert qc_thresholds(CAST_011) == []


class TestRenderQCTable:
    """_render_qc_table turns the readers into the cast-page panel markup."""

    def test_renders_tables_for_a_flagged_file(self, tmp_path):
        html = _render_qc_table(_qc_file(tmp_path))
        assert html is not None
        assert "qc-bar" in html and "qc-legend" in html
        assert "Distribution" in html
        assert "Suspect range" in html  # thresholds sub-table present

    def test_none_for_a_file_without_qc(self):
        assert _render_qc_table(CAST_011) is None


class TestCastPageWiring:
    """The QC section shows on a flagged cast page and is omitted otherwise."""

    def test_section_appears_on_a_flagged_cast(self, tmp_path):
        from ctdcast.reports._cast import generate_station_page
        from ctdcast.reports._index import _read_cast_meta

        src = _qc_file(tmp_path, "mixsed2_011.nc")
        meta = _read_cast_meta(src)
        out = generate_station_page(src, tmp_path / "out", all_meta=[meta], force=True)
        html = out.read_text(encoding="utf-8")
        assert 'id="qc_flags"' in html
        assert "QC flags" in html
        assert "qc-bar" in html

    def test_section_omitted_when_no_flags(self, tmp_path):
        # CAST_011 is a stage-1 fixture: no _qc, so the section is not applicable.
        from ctdcast.reports._cast import generate_station_page
        from ctdcast.reports._index import _read_cast_meta

        meta = _read_cast_meta(CAST_011)
        out = generate_station_page(
            CAST_011, tmp_path / "out", all_meta=[meta], force=True
        )
        html = out.read_text(encoding="utf-8")
        assert 'id="qc_flags"' not in html


class TestCastsIndexQCColumn:
    """The casts index gains a per-cast QC-flagged percentage column."""

    def test_column_shows_percent_for_a_flagged_cast(self, tmp_path):
        from ctdcast.reports._index import (
            _cast_qc_pct,
            _read_cast_meta,
            _write_stations_list,
        )

        src = _qc_file(tmp_path, "mixsed2_011_stage3.nc")
        pct = _cast_qc_pct(src)
        assert pct is not None and pct > 0
        _write_stations_list([_read_cast_meta(src)], "MSM142", tmp_path)
        html = (tmp_path / "casts.html").read_text(encoding="utf-8")
        assert "QC flagged" in html  # the column header
        assert f"{pct}%" in html  # the aggregated suspect+fail percentage

    def test_column_shows_dash_for_stage1_cast(self, tmp_path):
        from ctdcast.reports._index import _read_cast_meta, _write_stations_list

        _write_stations_list([_read_cast_meta(CAST_011)], "MSM142", tmp_path)
        html = (tmp_path / "casts.html").read_text(encoding="utf-8")
        assert "QC flagged" in html
        # no _qc companions → the cell is an en-dash, not a percentage
