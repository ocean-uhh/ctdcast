"""Tests for the vendored QC builders and the cast-page QC table."""

import xarray as xr
from conftest import CAST_011

from ctdcast.processors.qc import apply_gross_range
from ctdcast.processors.stage2 import apply_stage2
from ctdcast.reports import design
from ctdcast.reports._vendored.nc_tables import qc_flag_rows, qc_threshold_rows
from ctdcast.reports.cast import _render_qc_table
from ctdcast.reports.qc_tables import collapse_sibling_rows


def _qc_ds():
    """A cast dataset carrying QARTOD flags (stage 2 soak/deck + gross-range)."""
    with xr.open_dataset(CAST_011, engine="netcdf4") as ds:
        ds = ds.load()
    return apply_gross_range(apply_stage2(ds))


def _qc_file(tmp_path, name="cast_qc.nc"):
    """Write the flagged cast dataset to a file (for the path-taking report functions)."""
    path = tmp_path / name
    _qc_ds().to_netcdf(path)
    return path


class TestQCFlagRows:
    """qc_flag_rows reads the flag-count breakdown from each _qc companion."""

    def test_rows_for_a_flagged_file(self):
        rows, _ = qc_flag_rows(_qc_ds(), is_qc=design.is_qc)
        assert rows, "a flagged file must produce rows"
        row = rows[0]
        assert set(row) == {"var", "total", "undeclared", "flags"}
        assert row["total"] > 0
        assert row["undeclared"] is False
        flag = row["flags"][0]
        assert set(flag) == {"flag", "token", "label", "color", "n", "pct"}
        # counts sum to the total scan count
        assert sum(f["n"] for f in row["flags"]) == row["total"]

    def test_labels_come_from_the_files_flag_meanings(self):
        rows, _ = qc_flag_rows(_qc_ds(), is_qc=design.is_qc)
        labels = {f["label"] for row in rows for f in row["flags"]}
        assert {"suspect", "fail", "pass"} <= labels

    def test_every_declared_flag_is_a_column_in_declared_order(self):
        """All declared flags get an entry, in declared order, even zero-count ones."""
        rows, _ = qc_flag_rows(_qc_ds(), is_qc=design.is_qc)
        assert [f["flag"] for f in rows[0]["flags"]] == [1, 2, 3, 4, 9]

    def test_empty_for_a_dataset_without_qc(self):
        # CAST_011 is a stage-1 fixture: no _qc companions.
        with xr.open_dataset(CAST_011, engine="netcdf4") as ds:
            rows, _ = qc_flag_rows(ds.load(), is_qc=design.is_qc)
        assert rows == []


class TestQCThresholdRows:
    """qc_threshold_rows reads the gross-range / spike attrs on each _qc companion."""

    def test_reads_both_tiers(self):
        rows, _ = qc_threshold_rows(_qc_ds(), is_qc=design.is_qc)
        gr = [r for r in rows if r["test"] == "gross-range"]
        assert gr, "gross-range rows expected"
        assert all({"var", "test", "suspect", "fail"} <= set(r) for r in gr)
        # at least one variable carries a suspect range like [2.0, 40.0]
        assert any(r["suspect"].startswith("[") for r in gr)

    def test_empty_for_a_dataset_without_qc(self):
        with xr.open_dataset(CAST_011, engine="netcdf4") as ds:
            rows, _ = qc_threshold_rows(ds.load(), is_qc=design.is_qc)
        assert rows == []

    def test_dual_sensors_collapse_when_thresholds_match(self):
        """conductivity_1 and _2 share thresholds → one 'conductivity_*' row (owned collapse)."""
        rows, _ = qc_threshold_rows(_qc_ds(), is_qc=design.is_qc)
        names = {r["var"] for r in collapse_sibling_rows(rows)}
        assert "conductivity_*" in names
        assert "conductivity_1" not in names and "conductivity_2" not in names


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
        from ctdcast.reports.cast import generate_station_page
        from ctdcast.reports.index import _read_cast_meta

        src = _qc_file(tmp_path, "mixsed2_011.nc")
        meta = _read_cast_meta(src)
        out = generate_station_page(src, tmp_path / "out", all_meta=[meta], force=True)
        html = out.read_text(encoding="utf-8")
        assert 'id="qc_flags"' in html
        assert "QC flags" in html
        assert "qc-bar" in html

    def test_section_omitted_when_no_flags(self, tmp_path):
        # CAST_011 is a stage-1 fixture: no _qc, so the section is not applicable.
        from ctdcast.reports.cast import generate_station_page
        from ctdcast.reports.index import _read_cast_meta

        meta = _read_cast_meta(CAST_011)
        out = generate_station_page(
            CAST_011, tmp_path / "out", all_meta=[meta], force=True
        )
        html = out.read_text(encoding="utf-8")
        assert 'id="qc_flags"' not in html


class TestCastsIndexQCColumn:
    """The casts index gains a per-cast QC-flagged percentage column."""

    def test_column_shows_percent_for_a_flagged_cast(self, tmp_path):
        from ctdcast.reports.index import (
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
        from ctdcast.reports.index import _read_cast_meta, _write_stations_list

        _write_stations_list([_read_cast_meta(CAST_011)], "MSM142", tmp_path)
        html = (tmp_path / "casts.html").read_text(encoding="utf-8")
        assert "QC flagged" in html
        # no _qc companions → the cell is an en-dash, not a percentage
