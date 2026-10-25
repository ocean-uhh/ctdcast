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
