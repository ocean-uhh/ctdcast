"""Vendored netCDF inventory builders — reports/_vendored/nc_tables.

Real committed casts for the shape-on-real-data checks; small synthetic datasets for the
QC-companion fold and the datetime decode (pure-logic edges not present in the fixtures); and
an AST import-purity guard that the vendored module stays package-neutral.
"""

import ast
import sys
from pathlib import Path

import numpy as np
import xarray as xr
from conftest import CAST_011

from ctdcast.reports._vendored import nc_tables as nt


def _is_qc(name, ds):
    return name.endswith("_qc")


def _is_sensor(name):
    return name.startswith("SENSOR_")


def _synthetic():
    """A tiny dataset with a QC companion, a datetime coord, a string and a scalar."""
    return xr.Dataset(
        {
            "temperature": ("time", np.array([1.0, 2.0, np.nan])),
            "temperature_qc": ("time", np.array([1, 1, 4])),
            "label": ("time", np.array(["a", "b", "c"])),
            "deployment": ((), np.int64(7)),
        },
        coords={
            "time": np.array(
                ["2020-01-01", "2020-01-02", "2020-01-03"], dtype="datetime64[ns]"
            )
        },
    )


def test_each_builder_returns_rows_and_a_source():
    """Every builder returns ``(rows, source)`` and names itself in the source string."""
    with xr.open_dataset(CAST_011, engine="netcdf4") as ds:
        for fn, suffix in [
            (lambda: nt.coords_rows(ds), ":coords_rows"),
            (
                lambda: nt.variables_rows(ds, is_qc=_is_qc, is_sensor=_is_sensor),
                ":variables_rows",
            ),
            (lambda: nt.scalars_rows(ds, exclude=_is_sensor), ":scalars_rows"),
            (lambda: nt.globals_rows(ds), ":globals_rows"),
            (lambda: nt.sensor_rows(ds), ":sensor_rows"),
        ]:
            rows, source = fn()
            assert isinstance(rows, list)
            assert source.endswith(suffix)
            assert source.endswith(".py" + suffix)


def test_variables_grouped_by_dims_with_sample_count():
    """Variables group by dimension tuple and the title carries the sample count."""
    ds = _synthetic()
    groups, _ = nt.variables_rows(ds, is_qc=_is_qc)
    titles = [t for t, _ in groups]
    assert titles == ["time (3 samples)"]


def test_qc_companions_folded_not_listed():
    """A ``_qc`` variable is not a row; its parent carries ``has_qc``."""
    ds = _synthetic()
    (_title, rows) = nt.variables_rows(ds, is_qc=_is_qc)[0][0]
    names = [r["name"] for r in rows]
    assert "temperature" in names
    assert "temperature_qc" not in names
    assert next(r for r in rows if r["name"] == "temperature")["has_qc"] is True


def test_valid_count_and_percent():
    """Valid counts the finite values; the percent is of the total."""
    ds = _synthetic()
    (_t, rows) = nt.variables_rows(ds, is_qc=_is_qc)[0][0]
    temp = next(r for r in rows if r["name"] == "temperature")
    assert temp["n"] == 3
    assert temp["n_valid"] == 2
    assert temp["valid_pct"] == round(100 * 2 / 3, 1)


def test_dtype_readable_float_string_datetime():
    """float64 keeps its precision; strings read ``string``; times read ``datetime``."""
    ds = _synthetic()
    (_t, rows) = nt.variables_rows(ds, is_qc=_is_qc)[0][0]
    by = {r["name"]: r["dtype"] for r in rows}
    assert by["temperature"] == "float64"
    assert by["label"] == "string"
    coords, _ = nt.coords_rows(ds)
    assert next(c for c in coords if c["name"] == "time")["dtype"] == "datetime"


def test_datetime_minmax_decoded_through_xarray():
    """A datetime coordinate's min/max render as readable dates, not raw integers."""
    coords, _ = nt.coords_rows(_synthetic())
    time = next(c for c in coords if c["name"] == "time")
    assert time["v_min"].startswith("2020-01-01")
    assert time["v_max"].startswith("2020-01-03")
    assert time["length"] == 3


def test_scalars_excluded_by_predicate():
    """Scalars honour the exclude predicate; a plain scalar still appears."""
    ds = _synthetic()
    rows, _ = nt.scalars_rows(ds)
    assert [r["name"] for r in rows] == ["deployment"]
    rows_excl, _ = nt.scalars_rows(ds, exclude=lambda n: n == "deployment")
    assert rows_excl == []


def test_sensor_rows_read_the_catalog():
    """The default reader pulls model/serial/calibration from SENSOR_* variables."""
    with xr.open_dataset(CAST_011, engine="netcdf4") as ds:
        rows, source = nt.sensor_rows(ds)
        assert rows, "fixture cast carries a sensor catalog"
        assert all(n.startswith("SENSOR_") for n in (r["name"] for r in rows))
        r0 = rows[0]
        assert {"model", "serial", "calibration", "model_assumed"} <= set(r0)
        assert isinstance(r0["model_assumed"], bool)
        assert source.endswith(":sensor_rows")


def test_globals_grouped_into_canonical_titles():
    """Global attributes land in the canonical groups plus a trailing Other."""
    with xr.open_dataset(CAST_011, engine="netcdf4") as ds:
        groups, _ = nt.globals_rows(ds)
        titles = [t for t, _ in groups]
        allowed = {t for t, _ in nt.ATTR_GROUPS} | {nt.OTHER_GROUP}
        assert set(titles) <= allowed
        assert all(rows for _t, rows in groups), "empty groups are omitted"


def test_globals_extras_merge_into_a_title():
    """A package's extra names join the named group rather than falling to Other."""
    ds = xr.Dataset(attrs={"my_custom_attr": "x", "title": "t"})
    groups, _ = nt.globals_rows(
        ds, extras={"Identity & discovery": ("my_custom_attr",)}
    )
    by = dict(groups)
    # rows are (attribute, type, value) triples; the type is the one shared vocabulary
    # (_readable_dtype), so text reads "string", never "str"
    assert ("my_custom_attr", "string", "x") in by["Identity & discovery"]
    assert nt.OTHER_GROUP not in by


def test_template_renders_sortable_tables_with_source():
    """The vendored macros render sortable tables and the builder source line."""
    from ctdcast.reports._env import _env

    ds = _synthetic()
    groups, vsrc = nt.variables_rows(ds, is_qc=_is_qc)
    coords, csrc = nt.coords_rows(ds)
    tmpl = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}"
        "{{ nc.coords_table(coords, source=csrc) }}"
        "{{ nc.variables_tables(groups, source=vsrc) }}"
    )
    html = tmpl.render(
        coords=coords, groups=groups, csrc=csrc, vsrc=vsrc, show_source=True
    )
    assert 'class="sortable' in html
    assert f"source: {vsrc}" in html
    assert "Variables on time" in html
    assert "<strong><code>float64" in html  # the float64 flag
    assert "data-nosort" in html  # the Attributes column / sub-tables
    # show_source off → no source line emitted.
    off = tmpl.render(
        coords=coords, groups=groups, csrc=csrc, vsrc=vsrc, show_source=False
    )
    assert "source:" not in off


def test_summary_counts_exclude_keeps_data_count_honest():
    """exclude() names leave data_variables for their own 'excluded' count, no double-count."""
    ds = xr.Dataset(
        {
            "ctd_temperature": ("time", np.array([1.0, 2.0])),
            "sensor_temperature_1": ("time", np.array(["s", "s"])),  # linkage
            "SENSOR_t": ((), np.int64(0)),  # catalog, already a sensor
        },
        coords={"time": np.array([0, 1])},
    )
    counts = nt.summary_counts(
        ds,
        is_qc=_is_qc,
        is_sensor=_is_sensor,
        exclude=lambda n: n.startswith(("sensor_", "SENSOR_")),
    )
    assert counts["data_variables"] == 1  # only ctd_temperature
    assert counts["sensors"] == 1  # SENSOR_t
    assert (
        counts["excluded"] == 1
    )  # sensor_temperature_1, not double-counted with sensors


def test_valid_cell_macro():
    """valid_cell shows a bare count when all valid, else 'n / total' flagged cell-bad."""
    from ctdcast.reports._env import _env

    tmpl = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}"
        "<table><tbody><tr>{{ nc.valid_cell(n_valid, n) }}</tr></tbody></table>"
    )
    full = tmpl.render(n_valid=390, n=390)
    assert ">390<" in full
    assert "cell-bad" not in full
    assert 'data-sort="390"' in full
    short = tmpl.render(n_valid=370, n=390)
    assert "370 / 390" in short
    assert "cell-bad" in short


def test_minmax_cell_sort_keys():
    """minmax_cell: numeric→raw data-sort, datetime→no data-sort (ISO text), missing→sentinel."""
    from ctdcast.reports._env import _env

    tmpl = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}"
        "N{{ nc.minmax_cell(num) }}|D{{ nc.minmax_cell(dt) }}|M{{ nc.minmax_cell(miss) }}"
    )
    html = tmpl.render(
        num={"v_min_raw": 5.0, "v_min": "5", "v_max": "10"},
        dt={
            "v_min_raw": None,
            "v_min": "2026-07-09 10:00",
            "v_max": "2026-07-09 18:00",
        },
        miss={"v_min_raw": None, "v_min": "—", "v_max": "—"},
    )
    assert 'data-sort="5.0"' in html  # numeric sorts on the raw min
    assert html.count("-1e308") == 1  # only the all-missing row gets the sentinel
    # the datetime cell carries NO data-sort, so the JS text-sorts its ISO string chronologically
    dt_cell = html.split("|D", 1)[1].split("|M", 1)[0]
    assert "2026-07-09 10:00" in dt_cell and "data-sort" not in dt_cell


def test_units_cell_flags_float_missing_units():
    """units_cell: float w/o units is amber, string w/o units is plain, present units shows."""
    from ctdcast.reports._env import _env

    tmpl = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}"
        "{{ nc.units_cell(fl) }}|{{ nc.units_cell(st) }}|{{ nc.units_cell(ok) }}"
    )
    html = tmpl.render(
        fl={"units": "", "is_numeric": True},  # float: CF expects a unit
        st={"units": "", "is_numeric": False},  # string/int: a unit does not apply
        ok={"units": "degree_Celsius", "is_numeric": True},
    )
    assert 'class="cell-bad">—' in html  # float, no units -> file defect
    assert html.count("cell-bad") == 1  # the non-numeric missing unit is not a defect
    assert "degree_Celsius" in html


def test_variables_tables_optional_drops_all_empty_columns():
    """A declared-optional column vanishes when no row in the group carries a value."""
    from ctdcast.reports._env import _env

    ds = xr.Dataset(
        {"sensor_x": ("N_PROF", np.array(["a", "b"]))}
    )  # string, no units/range
    groups, src = nt.variables_rows(ds, is_qc=_is_qc)
    nc = (
        "{% import '_nc_tables.html' as nc with context %}"
        "{{ nc.variables_tables(groups, optional=('units', 'minmax'), source=src) }}"
    )
    dropped = _env.from_string(nc).render(groups=groups, src=src, show_source=False)
    assert "Units</th>" not in dropped
    assert "Min / Max</th>" not in dropped
    # without the opt-out the same group keeps the columns
    kept = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}"
        "{{ nc.variables_tables(groups, source=src) }}"
    ).render(groups=groups, src=src, show_source=False)
    assert "Units</th>" in kept and "Min / Max</th>" in kept


def test_coords_and_scalars_tables_take_optional():
    """coords_table and scalars_table honour the same optional column-drop (symmetry)."""
    from ctdcast.reports._env import _env

    ds = xr.Dataset(
        {"flag": ((), np.int8(1))},  # a scalar with no units
        coords={
            "label": ("label", np.array(["a", "b"]))
        },  # string coord, no units/range
    )
    coord_rows, csrc = nt.coords_rows(ds)
    scalar_rows, ssrc = nt.scalars_rows(ds)
    html = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}"
        "{{ nc.coords_table(coords, optional=('units', 'minmax'), source=csrc) }}"
        "{{ nc.scalars_table(scalars, optional=('units',), source=ssrc) }}"
    ).render(
        coords=coord_rows, scalars=scalar_rows, csrc=csrc, ssrc=ssrc, show_source=False
    )
    assert "Units</th>" not in html
    assert "Min / Max</th>" not in html


def test_optional_stdname_drops_empty_standard_long_name_column():
    """The Standard / long name column drops when `stdname` is optional and all rows lack it."""
    from ctdcast.reports._env import _env

    ds = xr.Dataset({"sensor_x": ("N_PROF", np.array(["a", "b"]))})  # no std/long name
    groups, src = nt.variables_rows(ds, is_qc=_is_qc)
    dropped = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}"
        "{{ nc.variables_tables(groups, optional=('stdname',), source=src) }}"
    ).render(groups=groups, src=src, show_source=False)
    assert "Standard / long name</th>" not in dropped

    # a populated long_name keeps the column even when stdname is opted-in
    ds2 = xr.Dataset({"temp": ("N_PROF", np.array([1.0, 2.0]))})
    ds2["temp"].attrs["long_name"] = "temperature"
    groups2, src2 = nt.variables_rows(ds2, is_qc=_is_qc)
    kept = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}"
        "{{ nc.variables_tables(groups, optional=('stdname',), source=src) }}"
    ).render(groups=groups2, src=src2, show_source=False)
    assert "Standard / long name</th>" in kept


def test_value_and_names_cells_are_wrappable():
    """The scalar Value cell and the standard/long-name cell carry the wrap class.

    A long unbroken token (a ``tracking_id``, a dotted ``standard_name``) must break inside
    the cell instead of widening the whole table.
    """
    from ctdcast.reports._env import _env

    ds = xr.Dataset({"tracking_id": ((), "x" * 60)})  # a long unbroken scalar value
    rows, src = nt.scalars_rows(ds)
    html = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}"
        "{{ nc.scalars_table(rows, source=src) }}"
    ).render(rows=rows, src=src, show_source=False)
    assert html.count('class="cell-wrap"') >= 1


def test_numbered_adds_a_sortable_index_column():
    """`numbered=True` prepends a `#` column; the default omits it."""
    from ctdcast.reports._env import _env

    ds = xr.Dataset(
        {"a": ("x", np.array([1.0, 2.0])), "b": ("x", np.array([3.0, 4.0]))}
    )
    groups, src = nt.variables_rows(ds, is_qc=_is_qc)
    numbered = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}"
        "{{ nc.variables_tables(groups, source=src, numbered=True) }}"
    ).render(groups=groups, src=src, show_source=False)
    assert ">#</th>" in numbered
    plain = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}"
        "{{ nc.variables_tables(groups, source=src) }}"
    ).render(groups=groups, src=src, show_source=False)
    assert ">#</th>" not in plain


def test_globals_requirement_column_is_opt_in():
    """globals_rows(requirement=...) emits 4-tuples and globals_tables adds a Requirement column."""
    from ctdcast.reports._env import _env

    ds = xr.Dataset(attrs={"title": "t", "Conventions": "CF-1.13"})
    groups, _ = nt.globals_rows(ds, requirement={"title": "required"})
    rows = [r for _title, grp in groups for r in grp]
    title_row = next(r for r in rows if r[0] == "title")
    assert title_row[3] == "required"  # mapped attr carries its label
    conv_row = next(r for r in rows if r[0] == "Conventions")
    assert conv_row[3] == ""  # unmapped attr gets an empty label, not dropped
    html = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}{{ nc.globals_tables(groups) }}"
    ).render(groups=groups, show_source=False)
    assert ">Requirement</th>" in html and "required" in html

    # default (no requirement) stays (attr, type, value) triples with no column
    groups_plain, _ = nt.globals_rows(ds)
    assert all(len(r) == 3 for _t, grp in groups_plain for r in grp)
    plain = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}{{ nc.globals_tables(groups) }}"
    ).render(groups=groups_plain, show_source=False)
    assert ">Requirement</th>" not in plain


def test_name_cell_puts_original_on_its_own_muted_line():
    """A renamed variable shows `<orig> →` on its own `.var-orig` line above the canonical name."""
    from ctdcast.reports._env import _env

    html = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}{{ nc.name_cell(row) }}"
    ).render(
        row={"name": "ctd_temperature_1", "original_name": "t090C", "has_qc": False},
        show_source=False,
    )
    assert 'class="var-orig"' in html
    assert "t090C" in html and "ctd_temperature_1" in html
    assert "<br>" in html  # original and canonical name are on separate lines


def test_coverage_caption_only_when_a_cell_ambers():
    """globals_tables shows the coverage criterion caption only when a coverage cell is over."""
    from ctdcast.reports._env import _env

    groups = [("Spatiotemporal coverage", [("geospatial_lat_max", "float64", "60.0")])]
    tmpl = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}"
        "{{ nc.globals_tables(groups, computed=computed, coverage_note='CRITERION') }}"
    )
    over = tmpl.render(
        groups=groups,
        computed={"geospatial_lat_max": {"value": "59.0", "diff": "+1", "over": True}},
        show_source=False,
    )
    assert "CRITERION" in over  # a cell ambers -> the rule is stated
    clean = tmpl.render(
        groups=groups,
        computed={"geospatial_lat_max": {"value": "60.0", "diff": "0", "over": False}},
        show_source=False,
    )
    assert "CRITERION" not in clean  # no highlight -> no caption


def test_attributes_column_is_not_sortable():
    """The Attributes heading carries data-nosort and no tabindex, so the JS leaves it inert."""
    from ctdcast.reports._env import _env

    ds = _synthetic()
    groups, vsrc = nt.variables_rows(ds, is_qc=_is_qc)
    html = _env.from_string(
        "{% import '_nc_tables.html' as nc with context %}"
        "{{ nc.variables_tables(groups, source=vsrc) }}"
    ).render(groups=groups, vsrc=vsrc, show_source=False)
    assert "<th data-nosort>Attributes</th>" in html
    assert '<th tabindex="0">Attributes</th>' not in html


def test_import_purity_package_neutral():
    """nc_tables imports only stdlib, numpy, xarray and vendored siblings (relative)."""
    src = Path(nt.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    allowed_top = set(sys.stdlib_module_names) | {"numpy", "xarray"}
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in allowed_top:
                    offenders.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                continue  # relative sibling import — allowed
            top = (node.module or "").split(".")[0]
            if top not in allowed_top:
                offenders.append(node.module)
    assert offenders == [], f"non-neutral imports: {offenders}"


def test_variables_rows_include_and_original_name():
    """include= keeps only accepted names; original_name_attrs surfaces the source name."""
    ds = xr.Dataset(
        {
            "keep_me": ("x", np.arange(3.0), {"cnv_original_name": "raw0"}),
            "drop_me": ("x", np.arange(3.0)),
        }
    )
    groups, _ = nt.variables_rows(
        ds,
        is_qc=lambda _n, _d: False,
        include=lambda n: n == "keep_me",
        original_name_attrs=("cnv_original_name",),
    )
    rows = [r for _t, g in groups for r in g]
    assert [r["name"] for r in rows] == ["keep_me"]
    assert rows[0]["original_name"] == "raw0"


def test_fmt_datetime_whole_ms_and_nat():
    """fmt_datetime renders whole seconds, keeps ms when non-zero, and NaT → em-dash."""
    assert (
        nt.fmt_datetime(np.datetime64("2020-01-19T20:30:00")) == "2020-01-19 20:30:00"
    )
    assert (
        nt.fmt_datetime(np.datetime64("2020-01-19T20:30:00.123"))
        == "2020-01-19 20:30:00.123"
    )
    assert nt.fmt_datetime(np.datetime64("NaT")) == "—"


def test_sensor_rows_reads_og1_serial_with_legacy_fallback():
    """sensor_rows reads the OG1 ``sensor_serial_number``, falling back to legacy ``serial_number``."""
    og1 = xr.Dataset(
        {
            "SENSOR_ctd_temperature": (
                (),
                np.int8(0),
                {"sensor_model": "SBE3", "sensor_serial_number": "SN-OG1"},
            )
        }
    )
    rows, _ = nt.sensor_rows(og1)
    assert rows[0]["serial"] == "SN-OG1"
    legacy = xr.Dataset(
        {
            "SENSOR_ctd_temperature": (
                (),
                np.int8(0),
                {"sensor_model": "SBE3", "serial_number": "SN-LEGACY"},
            )
        }
    )
    rows2, _ = nt.sensor_rows(legacy)
    assert rows2[0]["serial"] == "SN-LEGACY"


def test_qc_marker_shows_the_files_own_suffix():
    """The (_QC) marker carries the companion's actual name, so its suffix matches the file.

    ctdcast writes ``{var}_qc`` (lowercase); an OG1 file writes ``{var}_QC``. The row carries
    ``qc_name`` and the template renders the suffix verbatim, never a hard-coded spelling.
    """
    ds = xr.Dataset(
        {
            "temp": ("x", np.arange(3.0)),
            "temp_qc": ("x", np.array([1, 1, 3], np.int8)),  # ctdcast lowercase
            "sal": ("x", np.arange(3.0)),
            "sal_QC": ("x", np.array([1, 1, 1], np.int8)),  # OG1 uppercase
        }
    )
    groups, _ = nt.variables_rows(ds, is_qc=lambda n, _d: n.lower().endswith("_qc"))
    by = {r["name"]: r for _t, g in groups for r in g}
    assert by["temp"]["qc_name"] == "temp_qc"
    assert by["sal"]["qc_name"] == "sal_QC"


def test_qc_flag_label_and_value_token_sets_match():
    """QC_FLAG_LABELS and _QC_FLAG_VALUE cover the same tokens, so the two cannot drift."""
    from ctdcast.reports._vendored import design_tokens as dt

    assert set(dt.QC_FLAG_LABELS) == set(dt._QC_FLAG_VALUE)


def _qc_dataset(flag_values, flag_meanings):
    """A one-variable dataset with a QC companion carrying the given flag attrs."""
    attrs = {}
    if flag_values is not None:
        attrs["flag_values"] = np.array(flag_values, dtype=np.int8)
    if flag_meanings is not None:
        attrs["flag_meanings"] = flag_meanings
    return xr.Dataset(
        {
            "temp": ("t", np.arange(4.0)),
            "temp_qc": ("t", np.array([1, 1, 3, 4], dtype=np.int8), attrs),
        }
    )


def test_qc_flag_rows_declared_when_values_and_meanings_match():
    """A well-formed companion (values + matching meanings) is declared, not amber."""
    ds = _qc_dataset([1, 3, 4], "pass suspect_or_of_high_interest fail")
    rows, _ = nt.qc_flag_rows(ds, is_qc=lambda n, _d: n.endswith("_qc"))
    assert rows[0]["undeclared"] is False
    assert [f["flag"] for f in rows[0]["flags"]] == [1, 3, 4]


def test_qc_flag_rows_malformed_declaration_is_undeclared():
    """flag_values with no / short flag_meanings → undeclared (raw-integer columns, amber)."""
    no_meanings = _qc_dataset([1, 3, 4], None)
    rows, _ = nt.qc_flag_rows(no_meanings, is_qc=lambda n, _d: n.endswith("_qc"))
    assert rows[0]["undeclared"] is True  # no flag_meanings
    short = _qc_dataset([1, 3, 4], "pass suspect")  # 2 meanings for 3 values
    rows2, _ = nt.qc_flag_rows(short, is_qc=lambda n, _d: n.endswith("_qc"))
    assert rows2[0]["undeclared"] is True  # length mismatch
    # raw integer codes observed in the data become the columns
    assert [f["flag"] for f in rows2[0]["flags"]] == [1, 3, 4]


def test_qc_flag_rows_non_numeric_flag_values_is_undeclared():
    """A non-numeric flag_values entry is malformed — undeclared, not a crash."""
    ds = xr.Dataset(
        {
            "temp": ("t", np.arange(4.0)),
            "temp_qc": (
                "t",
                np.array([1, 1, 3, 4], dtype=np.int8),
                {"flag_values": np.array(["x", "y"]), "flag_meanings": "pass fail"},
            ),
        }
    )
    rows, _ = nt.qc_flag_rows(ds, is_qc=lambda n, _d: n.endswith("_qc"))
    assert rows[0]["undeclared"] is True
    assert [f["flag"] for f in rows[0]["flags"]] == [1, 3, 4]


def test_original_name_identity_is_none():
    """A source name equal to the current name shows no arrow (original_name is None)."""
    ds = xr.Dataset({"v": ("x", np.arange(2.0), {"cnv_original_name": "v"})})
    groups, _ = nt.variables_rows(
        ds, is_qc=lambda _n, _d: False, original_name_attrs=("cnv_original_name",)
    )
    assert groups[0][1][0]["original_name"] is None
