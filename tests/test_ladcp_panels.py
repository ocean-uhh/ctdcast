"""LADCP panels: the shared grids and the U and V panels drawn from them."""

import numpy as np
import pytest
import xarray as xr
from conftest import FIXTURES_LADCP

from ctdcast.plotters.ladcp import ladcp_overview_grid
from ctdcast.processors.ladcp import build_ladcp_profiles, convert_ladcp_cast
from ctdcast.reports._plots import _make_ladcp_overview_b64
from ctdcast.reports._vendored import figure_png


@pytest.fixture(scope="module")
def ds_ladcp(tmp_path_factory):
    """Compiled ladcp_profiles.nc from the four fixture LADCP casts."""
    d = tmp_path_factory.mktemp("ladcp")
    for m in ("011", "012", "128", "129"):
        convert_ladcp_cast(
            FIXTURES_LADCP / f"{m}.mat", d / f"ladcp_{m}.nc", cast_num=int(m)
        )
    build_ladcp_profiles(d, d / "ladcp_profiles.nc", force=True)
    with xr.open_dataset(
        d / "ladcp_profiles.nc", engine="netcdf4", decode_timedelta=False
    ) as ds:
        yield ds.load()


def test_grid_is_sorted_trimmed_and_shared(ds_ladcp):
    grid = ladcp_overview_grid(ds_ladcp)
    assert list(grid.cast_nums) == [11, 12, 128, 129]
    assert grid.u.shape == grid.v.shape == (4, len(grid.depth))
    # The depth axis ends at the deepest level where any velocity is finite.
    last = np.isfinite(grid.u[:, -1]) | np.isfinite(grid.v[:, -1])
    assert last.any()
    # One symmetric scale serves both components.
    assert grid.bounds[0] == pytest.approx(-grid.bounds[-1])


def test_overview_returns_u_and_v_captioned_by_the_draw_function(ds_ladcp):
    panels = _make_ladcp_overview_b64(ds_ladcp, cast_groups={"#1f77b4": [11, 12]})
    assert [p.short for p in panels] == ["U", "V"]
    for p in panels:
        assert p.b64.startswith("iVBOR")
        assert (
            figure_png.source_of(p.b64)
            == "ctdcast/plotters/ladcp.py:draw_ladcp_overview_fig"
        )


def test_overview_needs_two_casts(ds_ladcp):
    assert _make_ladcp_overview_b64(ds_ladcp.isel(N_PROF=[0])) == []
    assert _make_ladcp_overview_b64(ds_ladcp.drop_vars("u")) == []


def test_section_reads_each_mat_file_once(monkeypatch):
    """U and V share one grid, so each cast's .mat file is read once, not twice."""
    import ctdcast.plotters.ladcp as ladcp_mod
    from ctdcast.reports._plots import _make_ladcp_section_b64

    reads = []
    real = ladcp_mod.read_ladcp
    monkeypatch.setattr(ladcp_mod, "read_ladcp", lambda p: reads.append(p) or real(p))
    panels = _make_ladcp_section_b64(
        [128, 129], np.array([0.0, 5.0]), "Distance (km)", FIXTURES_LADCP
    )
    assert [p.short for p in panels] == ["U", "V"]
    assert len(reads) == 2


def test_section_panel_is_the_same_with_and_without_a_prebuilt_grid():
    from ctdcast.plotters.ladcp import draw_ladcp_section_fig, ladcp_section_grid
    from ctdcast.reports._vendored.figure_png import render_b64

    args = ([128, 129], np.array([0.0, 5.0]), "Distance (km)", FIXTURES_LADCP)
    grid = ladcp_section_grid(args[0], args[1], args[3])
    for component in ("U", "V"):
        built_here = render_b64(draw_ladcp_section_fig, *args, component=component)
        shared = render_b64(
            draw_ladcp_section_fig, *args, component=component, grid=grid
        )
        assert built_here == shared, component


def test_section_grid_failure_warning_names_the_cause(monkeypatch):
    from ctdcast.reports._plots import _make_ladcp_section_b64
    from ctdcast.reports._vendored import design_tokens

    # The suite raises on plot errors; the report itself warns and omits the panels.
    monkeypatch.setattr(design_tokens, "RAISE_ON_PLOT_ERROR", False)

    with pytest.warns(RuntimeWarning, match="ladcp_section_grid failed.*ValueError"):
        panels = _make_ladcp_section_b64(
            [128, 129],
            np.array([0.0, 5.0]),
            "Distance (km)",
            FIXTURES_LADCP,
            lats=[60.0],  # wrong length
            lons=[-30.0, -30.1],
        )
    assert panels == []
