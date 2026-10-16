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
    assert ("my_custom_attr", "x") in by["Identity & discovery"]
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
