"""The deprecated ``ctdcast.plotters.plots`` façade warns and re-exports the split modules."""

import importlib
import sys

import pytest

from ctdcast.plotters import ladcp, maps, profiles, sections, timeseries

#: The public names ``ctdcast.plotters.plots`` defined before the split (v0.4.0).
#: The façade keeps exactly these importable; functions added since are not in it.
_PRE_SPLIT_PUBLIC = {
    "draw_all_sections_map_fig",
    "draw_aux_profiles_fig",
    "draw_clock_offset_fig",
    "draw_cruise_map_fig",
    "draw_ct_sa_sigma0_fig",
    "draw_ladcp_bottomtrack_fig",
    "draw_ladcp_section_fig",
    "draw_overview_panel_fig",
    "draw_pressure_time_fig",
    "draw_qc_histogram_fig",
    "draw_section_fig",
    "draw_section_map_fig",
    "draw_section_ts_histogram_fig",
    "draw_section_ts_o2_fig",
    "draw_section_ts_profiles_fig",
    "draw_sensor_diff_fig",
    "draw_stability_fig",
    "draw_station_map_fig",
    "draw_timeseries_fig",
    "draw_ts_density_fig",
    "draw_ts_diagram_fig",
    "draw_ts_diagram_timeseries_fig",
    "draw_ts_updown_fig",
    "draw_updown_diff_fig",
    "map_panel",
    "section_figsize_and_slot",
}


def test_plots_facade_warns_and_reexports():
    sys.modules.pop("ctdcast.plotters.plots", None)
    with pytest.warns(DeprecationWarning, match="ctdcast.plotters.plots is split"):
        plots = importlib.import_module("ctdcast.plotters.plots")
    assert set(plots.__all__) == _PRE_SPLIT_PUBLIC
    split = {m.__name__: m for m in (maps, profiles, sections, timeseries, ladcp)}
    for name in _PRE_SPLIT_PUBLIC:
        obj = getattr(plots, name)
        assert obj.__module__ in split, name
        assert getattr(split[obj.__module__], name) is obj, name


def test_no_internal_caller_imports_the_facade():
    """Package code imports the subject modules, so the warning never fires in-tree."""
    from pathlib import Path

    pkg = Path(importlib.import_module("ctdcast").__file__).parent
    offenders = [
        str(p.relative_to(pkg))
        for p in pkg.rglob("*.py")
        if p.name != "plots.py"
        and "ctdcast.plotters.plots import" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_old_width_keywords_warn_and_still_work(tmp_path):
    """``fig_w=`` and ``figw=`` are deprecated aliases of ``width_in=`` until 0.7.0."""
    import xarray as xr
    from conftest import FIXTURES_NC

    from ctdcast.plotters.maps import draw_section_map_fig
    from ctdcast.plotters.timeseries import draw_timeseries_fig
    from ctdcast.processors.profiles import build_profiles

    lats, lons = [60.0, 60.2], [-30.0, -30.4]
    with pytest.warns(DeprecationWarning, match="fig_w"):
        old = draw_section_map_fig(lats, lons, [1, 2], fig_w=3.0)
    new = draw_section_map_fig(lats, lons, [1, 2], width_in=3.0)
    assert old.get_size_inches()[0] == new.get_size_inches()[0] == 3.0

    prof = tmp_path / "profiles.nc"
    build_profiles(FIXTURES_NC, prof, force=True)
    with xr.open_dataset(prof, engine="netcdf4", decode_timedelta=False) as ds:
        ds = ds.load()
    with pytest.warns(DeprecationWarning, match="figw"):
        old = draw_timeseries_fig(ds, "ctd_temperature_1", "T", figw=4.5)
    new = draw_timeseries_fig(ds, "ctd_temperature_1", "T", width_in=4.5)
    assert old.get_size_inches()[0] == new.get_size_inches()[0] == 4.5


def test_old_width_keyword_warns_even_when_nothing_is_drawn_and_conflicts_raise():
    import numpy as np

    from ctdcast.plotters.maps import draw_section_map_fig

    with pytest.warns(DeprecationWarning, match="fig_w"):
        assert draw_section_map_fig([np.nan], [np.nan], [1], fig_w=3.0) is None
    with pytest.raises(TypeError, match="width_in= only"):
        draw_section_map_fig(
            [60.0, 60.2], [-30.0, -30.4], [1, 2], width_in=4.5, fig_w=3.0
        )
