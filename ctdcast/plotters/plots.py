"""Deprecated: the figure builders now live in subject modules.

:mod:`ctdcast.plotters.maps`, :mod:`ctdcast.plotters.profiles`,
:mod:`ctdcast.plotters.sections`, :mod:`ctdcast.plotters.timeseries` and
:mod:`ctdcast.plotters.ladcp`. This module re-exports their public names until
it is removed in 0.7.0.
"""

from __future__ import annotations

import warnings

from ctdcast.plotters.ladcp import (
    draw_ladcp_bottomtrack_fig,
    draw_ladcp_section_fig,
)
from ctdcast.plotters.maps import (
    draw_all_sections_map_fig,
    draw_cruise_map_fig,
    draw_section_map_fig,
    draw_station_map_fig,
    map_panel,
)
from ctdcast.plotters.profiles import (
    draw_aux_profiles_fig,
    draw_ct_sa_sigma0_fig,
    draw_qc_histogram_fig,
    draw_stability_fig,
    draw_ts_density_fig,
    draw_ts_diagram_fig,
    draw_ts_updown_fig,
)
from ctdcast.plotters.sections import (
    draw_overview_panel_fig,
    draw_section_fig,
    draw_section_ts_histogram_fig,
    draw_section_ts_o2_fig,
    draw_section_ts_profiles_fig,
    draw_ts_diagram_timeseries_fig,
    section_figsize_and_slot,
)
from ctdcast.plotters.timeseries import (
    draw_clock_offset_fig,
    draw_pressure_time_fig,
    draw_sensor_diff_fig,
    draw_timeseries_fig,
    draw_updown_diff_fig,
)

warnings.warn(
    "ctdcast.plotters.plots is split into ctdcast.plotters.maps, profiles, sections, "
    "timeseries and ladcp; import from those. This module is removed in 0.7.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
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
]
